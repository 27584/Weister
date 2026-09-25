"""结构化抽取。

从财报文本提取标准化财务字段与原文证据。
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from ..core.registry import Tool, registry
from ..llm import LLMClient

DeltaHandler = Callable[[Any], None]

EXTRACT_SYSTEM = """从文本抽取字段并输出 JSON。

严格要求：
- 直接输出 JSON，不要写任何分析、解释或思考过程
- 不要讨论字段含义、单位换算或数字格式
- 找不到的字段填 null
- 数值保持原文精度，不做换算
- evidence 最多 3 条，quote 直接抄原文"""

EXTRACT_SCHEMA_HINT = """输出结构（严格照抄键名，只输出这一行 JSON）：
{"company":null,"period":null,"currency":"CNY","unit":"元","fields":{"revenue":null,"net_profit":null,"gross_margin":null,"operating_cash_flow":null,"total_assets":null,"total_liabilities":null,"eps":null,"shares_outstanding":null},"evidence":[]}"""


def _scan(text: str) -> tuple[list[str], bool]:
    """扫描字符串，返回未闭合的括号栈与是否停在字符串中。"""
    stack: list[str] = []
    in_string = False
    escape = False

    for ch in text:
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch in "{[":
            stack.append(ch)
        elif (ch == "}" and stack and stack[-1] == "{") or (
            ch == "]" and stack and stack[-1] == "["
        ):
            stack.pop()

    return stack, in_string


def _find_last_separator(text: str) -> int:
    """找到不在字符串内的最后一个逗号位置，找不到返回 -1。"""
    in_string = False
    escape = False
    last = -1

    for i, ch in enumerate(text):
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == ",":
            last = i

    return last


def _close_brackets(text: str) -> str:
    """补齐未闭合的括号。"""
    s = text.rstrip()
    s = re.sub(r",\s*$", "", s)

    stack, in_string = _scan(s)
    if in_string:
        s += '"'
        s = re.sub(r",\s*$", "", s)
        stack, _ = _scan(s)

    while stack:
        opener = stack.pop()
        s = re.sub(r",\s*$", "", s.rstrip())
        s += "}" if opener == "{" else "]"

    return s


def _repair_json(text: str) -> str:
    """修补被截断的 JSON。

    策略：先尝试闭合未完成的字符串与括号；若仍不合法，
    则从尾部逐层截断到上一个逗号再闭合，直到可以解析。
    """
    s = text.strip()
    s = re.sub(r",\s*$", "", s)

    # 快速路径：仅缺括号或引号
    candidate = _close_brackets(s)
    try:
        json.loads(candidate)
        return candidate
    except json.JSONDecodeError:
        pass

    # 慢路径：逐层截断到上一个逗号
    working = s
    for _ in range(20):
        cut = _find_last_separator(working)
        if cut < 0:
            break

        working = working[:cut]
        candidate = _close_brackets(working)
        try:
            json.loads(candidate)
            return candidate
        except json.JSONDecodeError:
            continue

    # 末级回退：仅保留最外层键值对
    return _close_brackets(s)


def _parse_json_safe(raw: str) -> Any:
    """解析 JSON，失败时尝试修补。"""
    text = raw.strip()

    fence = chr(96) * 3
    if text.startswith(fence):
        parts = text.split(fence)
        if len(parts) >= 2:
            text = parts[1]
            text = text.removeprefix("json")
            text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    repaired = _repair_json(text)
    try:
        return json.loads(repaired)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"JSON 解析失败：{exc}\n原始片段：{text[:200]}\n修补后：{repaired[:200]}"
        ) from exc


def _chat_json_streamed(
    client: LLMClient,
    system: str,
    user: str,
    on_delta: DeltaHandler | None,
) -> Any:
    prompt_system = system + "\n只输出 JSON，不要任何解释或 Markdown 代码块围栏。"

    if on_delta is None:
        raw = client.chat(prompt_system, user)
        return _parse_json_safe(raw)

    parts: list[str] = []
    reasoning_chars = 0
    for delta in client.stream_messages(
        [
            {"role": "system", "content": prompt_system},
            {"role": "user", "content": user},
        ],
    ):
        on_delta(delta)
        if delta.reasoning:
            reasoning_chars += len(delta.reasoning)
        if delta.content:
            parts.append(delta.content)

    raw = "".join(parts).strip()
    if not raw:
        raise RuntimeError(
            f"模型未返回正文 JSON（推理 {reasoning_chars} 字，正文 0 字）。"
            f"该端点可能对推理模型的输出有硬限制。"
        )

    return _parse_json_safe(raw)


def extract_fields(
    text: str,
    client: LLMClient,
    *,
    max_chars: int = 6000,
    on_delta: DeltaHandler | None = None,
) -> dict[str, Any]:
    client.require_configured()
    return _chat_json_streamed(
        client,
        EXTRACT_SYSTEM,
        f"{EXTRACT_SCHEMA_HINT}\n\n财务文本：\n{text[:max_chars]}",
        on_delta,
    )


registry.add_tool(
    Tool(
        name="extract_fields",
        description="从财报文本中结构化抽取关键财务字段与原文证据",
        input_schema={"text": "str", "max_chars": "int（可选）"},
        handler=extract_fields,
        tags=["extraction", "llm"],
        inject=["client", "on_delta"],
    )
)
