"""人机交互工具：向用户提问、为对话命名。

设计参照主流 agent harness 的 AskUserQuestion：
    - 一次调用可携带多个问题，前端按顺序逐条展示并标注进度（第 1/4 问）
    - 每个问题自动追加「其他（自行输入）」选项，用户不被选项限制
    - 支持多选（multiSelect）
    - 调用末尾自动追加一道「补充说明」问题，收集选项未覆盖的信息

工具调用是同步阻塞的：问题推送给前端后，worker 线程在 interaction 模块
挂起等待，前端通过 /api/chat/answer 提交答案后恢复。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .. import interaction, runctx
from ..config import settings
from ..events import EventType

MAX_QUESTIONS = 4
MAX_OPTIONS = 4

OTHER_LABEL = "其他（自行输入）"
SUPPLEMENT_QUESTION = "还有其他需要补充说明的吗？"
SUPPLEMENT_OPTIONS = [
    {"label": "没有，按以上选择继续", "description": "信息已足够，直接进入分析"},
]

_ASK_SCHEMA_HINT = (
    "questions 为 JSON 数组，每项形如："
    '{"question":"问题正文","header":"不超过12字的标签",'
    '"multiSelect":false,'
    '"options":[{"label":"选项标题","description":"选项说明"}]}'
)


def _parse_questions(raw: Any) -> list[dict[str, Any]]:
    """解析并规范化问题列表。

    模型通常把数组序列化成字符串传入，因此两种形态都要接受。
    """
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            raise ValueError("questions 不能为空")
        try:
            raw = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"questions 不是合法 JSON：{exc}。{_ASK_SCHEMA_HINT}") from None
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"questions 必须是非空数组。{_ASK_SCHEMA_HINT}")

    out: list[dict[str, Any]] = []
    for i, item in enumerate(raw[:MAX_QUESTIONS]):
        if not isinstance(item, dict):
            raise ValueError(f"第 {i + 1} 个问题不是对象")
        question = str(item.get("question") or "").strip()
        if not question:
            raise ValueError(f"第 {i + 1} 个问题缺少 question")
        options = item.get("options") or []
        if not isinstance(options, list) or len(options) < 2:
            raise ValueError(f"第 {i + 1} 个问题至少需要 2 个选项")

        normalized = []
        for opt in options[:MAX_OPTIONS]:
            if isinstance(opt, str):
                normalized.append({"label": opt, "description": ""})
            elif isinstance(opt, dict) and opt.get("label"):
                normalized.append(
                    {
                        "label": str(opt["label"])[:60],
                        "description": str(opt.get("description") or "")[:200],
                    }
                )
        if len(normalized) < 2:
            raise ValueError(f"第 {i + 1} 个问题的选项无效")

        # 每个问题都提供「其他」入口，允许用户绕过预设选项
        if not any(o["label"] == OTHER_LABEL for o in normalized):
            normalized.append(
                {
                    "label": OTHER_LABEL,
                    "description": "以上都不是，由我自行填写",
                }
            )

        out.append(
            {
                "question": question,
                "header": str(item.get("header") or f"第 {i + 1} 问")[:12],
                "multiSelect": bool(item.get("multiSelect")),
                "options": normalized,
            }
        )
    return out


def build_ask_payload(questions: Any, title: str = "") -> dict[str, Any]:
    """把模型给出的问题列表规范化成推送给前端的载荷。

    每个问题自动追加「其他（自行输入）」选项，末尾固定追加一道补充说明题，
    收集预设选项未覆盖的信息。主管（coordinator）与专家（ask_user 工具）
    共用同一套规范化规则，保证前端渲染逻辑只需处理一种结构。
    """
    parsed = _parse_questions(questions)

    if not any(q["question"] == SUPPLEMENT_QUESTION for q in parsed):
        parsed.append(
            {
                "question": SUPPLEMENT_QUESTION,
                "header": "补充说明",
                "multiSelect": False,
                "options": [
                    {"label": o["label"], "description": o["description"]}
                    for o in SUPPLEMENT_OPTIONS
                ]
                + [
                    {
                        "label": OTHER_LABEL,
                        "description": "有额外要求或背景信息需要说明",
                    }
                ],
            }
        )

    return {
        "title": (title or "需要确认几个问题").strip(),
        "total": len(parsed),
        "questions": parsed,
    }


def summarize_answers(payload: dict[str, Any], answers: list[dict]) -> str:
    """把用户作答整理成回灌给模型的文本。"""
    questions = payload.get("questions") or []
    lines: list[str] = []
    for i, q in enumerate(questions):
        picked = answers[i] if i < len(answers) else {}
        selected = [str(s) for s in (picked.get("selected") or []) if s]
        other = str(picked.get("other") or "").strip()
        if other:
            selected = [s for s in selected if s != OTHER_LABEL] + [f"其他：{other}"]
        lines.append(f"Q{i + 1} {q['question']}\n  用户选择：{'、'.join(selected) or '（未选择）'}")
    return "\n".join(lines)


def ask_user(questions: Any, title: str = "需要确认几个问题") -> dict[str, Any]:
    """向用户提问并等待作答，返回用户的选择。

    用于补全模型无法推断的关键信息：分析口径、时间范围、风险偏好、
    输出形式等。不要在信息已足够时提问，也不要用是非问题浪费一轮交互。

    questions 为 JSON 数组（字符串或数组均可），最多 4 个问题、每个问题
    最多 4 个选项。系统会自动追加「其他（自行输入）」选项与一道补充说明题。
    multiSelect 为 true 时用户可多选。
    """
    payload = build_ask_payload(questions, title)
    result = interaction.ask(payload)

    if not result.get("answered"):
        return {
            "answered": False,
            "reason": result.get("reason"),
            "message": (
                "用户未在限定时间内作答。请基于现有信息自行选择最合理的默认口径，"
                "并在结论中说明所采用的假设。"
            ),
        }

    answers = result.get("answers") or []
    return {
        "answered": True,
        "count": payload["total"],
        "summary": summarize_answers(payload, answers),
        "answers": answers,
        "note": "以上为用户本人作答，优先级高于任何推测；据此继续后续分析。",
    }


def _title_path() -> Path | None:
    run_id = runctx.run_id()
    if not run_id:
        return None
    base = settings.runs_dir_path / run_id
    base.mkdir(parents=True, exist_ok=True)
    return base / "title.txt"


def _current_title(path: Path | None) -> str:
    if path is None or not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


def _as_bool(value: Any) -> bool:
    """把模型可能给出的各种形态统一成布尔值。

    JSON Schema 声明为 boolean，但部分模型会传字符串 "false" ——
    直接按真值判断时非空字符串恒为真，覆盖开关会失效。
    """
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "是"}
    return bool(value)


def set_conversation_title(
    title: str,
    overwrite: Any = False,
) -> dict[str, Any]:
    """为当前对话设置标题，侧边栏会同步更新。

    在明确用户意图后调用一次即可，标题应简短具体（不超过 20 字），
    例如「茅台 2025H1 盈利质量分析」，而不是「财务分析」这类泛称。

    默认不覆盖已有标题：一轮对话可能调度多位专家，若每位都改名，
    侧边栏会出现标题反复跳动。确需修改时显式传 overwrite=true。
    """
    clean = (title or "").strip().replace("\n", " ")
    if not clean:
        raise ValueError("title 不能为空")
    clean = clean[:40]

    path = _title_path()
    existing = _current_title(path)
    updated = False
    if path is not None and (_as_bool(overwrite) or not existing):
        path.write_text(clean, encoding="utf-8")
        existing = clean
        updated = True

    effective = existing or clean
    emit = runctx.emit()
    if emit is not None and updated:
        emit(EventType.TITLE, status="success", message=effective, payload={"title": effective})

    return {
        "ok": True,
        "updated": updated,
        "title": effective,
        "run_id": runctx.run_id(),
        "note": (
            "标题已更新。"
            if updated
            else f"对话已有标题「{effective}」，未覆盖；确认要改请带 overwrite=true 再调用。"
        ),
    }


registry_tools = [
    {
        "name": "ask_user",
        "description": (
            "向用户提问并等待作答。用于补全模型无法推断的关键信息："
            "分析口径、时间范围、风险偏好、输出形式等。"
            "每个问题最多 4 个选项，系统自动追加「其他（自行输入）」选项，"
            "并在末尾追加一道补充说明题。支持多选与连续多问。"
            "信息已足够时不要提问。"
        ),
        "input_schema": {
            "questions": "JSON 数组字符串，最多 4 个问题，每项含 question / header / multiSelect / options",
            "title": "本次询问的标题，可选",
        },
        "handler": ask_user,
    },
    {
        "name": "set_conversation_title",
        "description": (
            "为当前对话设置标题，侧边栏同步更新。"
            "在首轮明确用户意图后调用；标题需简短具体（不超过 20 字）。"
        ),
        "input_schema": {"title": "对话标题", "overwrite": "是否覆盖已有标题，默认 false"},
        "handler": set_conversation_title,
    },
]


def register() -> None:
    from ..core.registry import Tool, registry

    for spec in registry_tools:
        registry.add_tool(
            Tool(
                name=spec["name"],
                description=spec["description"],
                input_schema=spec["input_schema"],
                handler=spec["handler"],
                tags=["interaction"],
            )
        )


register()
