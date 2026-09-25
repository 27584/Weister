"""聊天形态的智能体编排。

采用 supervisor loop 而非固定节点流水线：
    用户消息 → coordinator(LLM) → 决定 delegate 到哪个 specialist 或直接 reply
                                       │
                                       ▼
                                   specialist 跑（用 AgentRunner）
                                       │
                                       ▼
                                结果回灌 messages → 下一轮 coordinator
                                       │
                                       ▼
                              coordinator 输出 reply → 写入 messages → 返回前端

为什么不用 LangGraph supervisor 模板：
    1. 当前 messages 数组本身就是 OpenAI 原生格式，supervisor 与 specialist
       共享同一份 history 不需要再过一层状态图
    2. 决策走 JSON 输出（不是 function calling），对参数量较小的模型更稳定
    3. checkpoint / 续跑全部走 messages.jsonl 落盘，不依赖 LangGraph 持久化

与流水线形态（orchestrator.py）并行存在的原因：
    现有 /api/analyze 接口依赖该实现。chat_supervisor 为独立实现，
    不影响既有调用方。
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from . import interaction
from .agents import AgentRunner, registry
from .core.registry import AgentSpec
from .decision import normalize_decision as _normalize_decision
from .decision import parse_decision as _parse_decision
from .events import EventType, NodeStatus
from .llm import LLMClient
from .state import InvestState
from .tokens import (
    OUTPUT_RESERVE_TOKENS,
    context_limit_for_model,
    count_text_tokens,
)
from .tools.interact import build_ask_payload, summarize_answers

EmitFn = Callable[..., None]

# 主管 prompt 里除历史以外的固定开销：系统提示 + 已调度专家清单 +
# 文档摘要 + 本轮指令。这块每个模型都要占，从窗口里先扣掉，
# 剩下的才归历史。取保守值，宁可少给历史也不要让请求超窗。
SUPERVISOR_OVERHEAD_TOKENS = 6_000

# 历史预算的下限。小窗模型（如 gpt-4 的 8K）扣完开销可能为负，
# 此时仍然保证主管能看到最近几轮对话，否则它连用户问什么都不知道。
MIN_HISTORY_TOKENS = 8_000

# 终止以「是否还有进展」为准，不设调度轮数预算。
#
# 固定轮数上限（原先为 6）会在任务做到一半时把结论截断 —— 用户问一个需要
# 财务、估值、风险、撰写四步的问题，恰好被卡在第 6 轮，拿到的就是半成品，
# 而它本可以再跑一轮收尾。轮数是手段不是目标，因此这里改为：只要每轮都
# 有实质产出（调度了新专家、拿到了用户作答），就一直跑下去。
MAX_IDLE_ROUNDS = 3

# 防失控水位：正常任务由上面的进展检测终止，永远触不到这里。
# 保留它是为了保证「模型陷入决策死循环」这类异常下进程一定返回，
# 而不是把请求挂到超时。它不是一个调度预算。
ABSOLUTE_ROUND_LIMIT = 50

# 纯确认话术。按「更具体者优先」排列，命中后取第一个
_ACK_WORDS = (
    "已收到技能指令",
    "技能指令",
    "收到指令",
    "已收到",
    "已激活",
    "已切换",
    "已就绪",
    "已启用",
    "明白",
    "好的",
    "收到",
    "okay",
    "ok",
)

# 出现这些信号说明回复里确实有信息：提问、数据、编号等
_SUBSTANTIVE_HINTS = ("请问", "？", "?", "请提供", "请告诉", "请说明", "\n")


def _is_empty_ack(content: str) -> bool:
    """判断回复是否只是一句没有信息量的确认。

    判定要同时满足三点，避免把「好的，我这就查」这类回复也拦掉：
        1. 短（不超过 30 字）—— 长回复几乎不可能没有内容
        2. 命中确认话术
        3. 去掉话术与标点后几乎不剩实质内容，且没有向用户提问
    """
    text = (content or "").strip()
    if not text or len(text) > 30:
        return False
    if any(h in text for h in _SUBSTANTIVE_HINTS):
        return False

    low = text.lower()
    hit = next((w for w in _ACK_WORDS if w in low), None)
    if not hit:
        return False

    rest = low.replace(hit, "")
    rest = re.sub(r"[，。、！!~～\s]+", "", rest)
    rest = re.sub(r"^(的|了|你|我|请|稍等|马上|立即|现在|会|就)+", "", rest)
    return len(rest) <= 4


# 允许调度的专家白名单：除主管自身外的所有已注册智能体。
# 直接由 registry.agents 推导，避免与注册表定义漂移 ——
# 新增/改名专家时只改 specialists.py 与 coordinator.py，这里自动同步。
def delegateable_agents() -> tuple[str, ...]:
    return tuple(k for k in registry.agents if k != "coordinator")


# 传给 specialist 的文档正文预算（字符）。
# focus_text 由解析器挑出「财务关键页」拼接，上限 30000 字符，
# 足以覆盖长报告的正文而不触发截断。
DOC_CONTEXT_PER_DOC = 30000
DOC_CONTEXT_TOTAL = 60000


_SUPERVISOR_SKILL = "supervisor_coordination"


def _load_supervisor_prompt() -> str:
    """从 skill 文件加载主管调度协议；缺失时用内置兜底。

    改 backend/app/skills/supervisor_coordination.md 即可热更新主管路由
    提示词，无需改 Python 代码。
    """
    from pathlib import Path as _P

    from .core.registry import SKILLS_DIR

    path = _P(SKILLS_DIR) / f"{_SUPERVISOR_SKILL}.md"
    if path.exists():
        text = path.read_text(encoding="utf-8")
        if text.startswith("---"):
            parts = text.split("---", 2)
            if len(parts) >= 3:
                return parts[2].lstrip("\n")
        return text.strip() + "\n"
    return _FALLBACK_SUPERVISOR_PROMPT


_FALLBACK_SUPERVISOR_PROMPT = """你是投研团队的主管。你**只输出一个 JSON 对象**，禁止输出分析正文。

可用动作（字段名必须是 action）：
1) {{"action":"reply","reason":"一句话","content":"回复"}}
2) {{"action":"delegate","reason":"一句话","agent":"<expert_key>","task":"任务"}}
   agent 必须是：{agents}
3) {{"action":"ask","reason":"一句话","title":"标题","questions":[{{"question":"问题","header":"标签","multiSelect":false,"options":[{{"label":"选项","description":"说明"}}]}}]}}

- 财报/估值/风险 → delegate；新闻/非A股 → research_assistant；闲聊 → reply；缺信息 → ask
- 禁止说「我无法联网」，应 delegate research_assistant
- action 只能是 reply / delegate / ask

现在只输出 JSON：
"""

SUPERVISOR_PROMPT = _load_supervisor_prompt()



def _format_history(
    messages: list[dict[str, Any]],
    max_tokens: int = 20_000,
    model: str = "",
) -> str:
    """把 messages 序列化成 supervisor 看得懂的纯文本。

    从**末尾（最近）**开始保留，超预算才丢弃更早的消息 —— 保证最新一轮
    用户问题与最近的专家结论始终在上下文内；若从开头累积，长对话会挤掉
    最新的用户消息，主管将看不到本轮的实际提问。

    预算按 **token** 计而不是字符：中文 1 字 ≈ 0.6~1 token，用字符估会
    显著低估占用。预算本身由 `history_token_budget()` 按模型窗口算出，
    调用方必须传入，否则 1M 窗口的模型也会被 20K 的死数卡住。

    多模态图片字段会被丢掉（视觉信息需要 LLM 直传，不能塞进 supervisor 文本）。
    上传的文档会作为 system context 单独注入，不走 history。
    """
    kept: list[str] = []
    total = 0
    truncated = False
    for m in reversed(messages):
        role = m.get("role", "user")
        content = m.get("content")
        if isinstance(content, list):
            text_parts = [
                p.get("text", "")
                for p in content
                if isinstance(p, dict) and p.get("type") == "text"
            ]
            content = "\n".join(text_parts).strip()
        content = (content or "").strip()
        if not content:
            continue
        block = f"[{role}] {content}"
        cost = count_text_tokens(block, model)
        if total + cost > max_tokens:
            truncated = True
            break
        kept.append(block)
        total += cost
    kept.reverse()
    if truncated:
        kept.insert(0, "（更早的对话历史已省略）")
    return "\n\n".join(kept) or "（暂无对话历史）"


def history_token_budget(state: InvestState) -> int:
    """主管历史可用的 token 预算，按模型**实际上下文窗口**计算。

    原先硬编码 20000 字符，与模型能力完全脱钩：用户换用 1M 窗口的模型时，
    主管看到的上下文仍然只有那一点点，等于白扔掉 98% 的窗口；而小窗模型
    又可能超窗报错。这里改为从窗口反推可用额度。
    """
    model = str(state.get("model") or "")
    limit = context_limit_for_model(model)
    # 扣掉三块固定开销：模型输出、系统提示与工具声明、文档摘要与已调度专家清单
    usable = limit - OUTPUT_RESERVE_TOKENS - SUPERVISOR_OVERHEAD_TOKENS
    return max(usable, MIN_HISTORY_TOKENS)


def _build_supervisor_messages(
    messages: list[dict[str, Any]],
    documents_summary: str,
    called: list[str] | None = None,
    max_history_tokens: int = 20_000,
    model: str = "",
) -> list[dict[str, str]]:
    """构造 supervisor 调用 LLM 的 messages 数组。

    系统提示 + 文档 context + 已调用专家 + 历史 + 最后一条用户消息。

    `messages` 必须是 run_chat 里**实时累积**的那一份，不能从 state 里取快照：
    state["messages"] 在本轮循环中不会更新，若用它构造历史，主管每一轮看到的
    都是同一份旧历史，看不到刚跑完的专家结论，于是会反复调度同一位专家。

    `called` 是本轮已经调度过的 specialist key 列表。必须显式告知 supervisor：
    仅依赖历史文本推断时，参数量较小的模型容易反复调度同一位专家，
    绕着圈子不产出最终回复。
    """
    agents_str = "、".join(delegateable_agents())
    # 每次构造时重新读 skill，便于不重启进程热改主管协议
    system = _load_supervisor_prompt().format(agents=agents_str)

    history_text = _format_history(messages, max_history_tokens, model)

    context_block = f"当前已上传的文档：\n{documents_summary}\n\n" if documents_summary else ""

    called_block = ""
    if called:
        uniq: list[str] = []
        for k in called:
            if k not in uniq:
                uniq.append(k)
        names = "、".join(uniq)
        remaining = [a for a in delegateable_agents() if a not in uniq]
        called_block = (
            f"本轮已经调度过的专家：{names}\n"
            f"**绝对不要再次调度上面列出的专家**，除非用户明确要求重新评估。\n"
            f"{'尚未调度的专家：' + '、'.join(remaining) if remaining else '（所有专家都已调度过）'}\n"
            f"如果已有专家的结论足以回答用户，请直接输出 action=reply 给出最终答复。\n\n"
        )

    user_block = (
        f"{context_block}{called_block}对话历史：\n{history_text}\n\n请只输出下一步动作的 JSON。"
    )

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user_block},
    ]


def _summarize_documents(documents: list[dict[str, Any]]) -> str:
    """把已解析的文档压缩成一段 supervisor 看得懂的文本。

    文本来源包括：document_text（前若干 KB）+ 文件名 + 页数 + 关键提示。
    """
    if not documents:
        return ""

    parts: list[str] = []
    for doc in documents:
        name = doc.get("filename", "未知文件")
        kind = doc.get("kind", "text")
        diag = doc.get("diagnostics") or {}
        pages = diag.get("page_count") or len(doc.get("pages") or [])
        chars = diag.get("chars") or 0
        text = (doc.get("document_text") or "").strip()
        if not text:
            parts.append(
                f"- {name}（{kind}，{pages} 页）：无可读文本，"
                "可能是扫描件（无文字层），不要基于它下结论"
            )
            continue
        snippet = text[:1500].strip()
        suffix = "（已截断）" if len(text) > 1500 else ""
        warn = f"，共 {chars} 字" if chars else ""
        parts.append(f"- {name}（{kind}，{pages} 页{warn}）：\n{snippet}{suffix}")
    return "\n\n".join(parts)


def build_chat_client(state: InvestState, emit: EmitFn) -> LLMClient:
    """与 orchestrator.build_client 同样的构造逻辑，但独立写在这里方便测试。"""

    def on_retry(attempt: int, wait: float, reason: str) -> None:
        emit(
            EventType.LOG,
            status=NodeStatus.RUNNING,
            message=f"第 {attempt} 次重试（{reason}），{wait:.1f}s 后重发",
            payload={"attempt": attempt, "wait": wait, "reason": reason},
        )

    def on_switch(old: str, new: str) -> None:
        emit(
            EventType.LOG,
            status=NodeStatus.RUNNING,
            message=f"模型持续失败，切换至备用模型：{new}",
            payload={"from": old, "to": new},
        )

    return LLMClient(
        base_url=state.get("base_url") or None,
        api_key=state.get("api_key") or None,
        model=state.get("model") or None,
        fallback_models=list(state.get("fallback_models") or []),
        on_retry=on_retry,
        on_switch=on_switch,
    )


def _specialist_summary_text(result: dict[str, Any]) -> str:
    """把 specialist 输出格式化成回灌给 supervisor 的简短摘要。"""
    name = result.get("name") or result.get("agent") or "专家"
    output = (result.get("output") or "").strip()
    truncated = result.get("truncated", False)
    truncated_note = "（已触顶截断，结论可能不完整）" if truncated else ""
    if not output:
        return f"【{name}】未产出有效内容{truncated_note}"
    # 上限 6000 字符与 AgentRunner 内部一致，避免下一轮上下文超出预算
    body = output[:6000]
    return f"【{name}】\n{body}{truncated_note}"


def _run_supervisor_iteration(
    messages: list[dict[str, Any]],
    documents_summary: str,
    emit: EmitFn,
    client: LLMClient,
    called: list[str] | None = None,
    max_history_tokens: int = 20_000,
    model: str = "",
) -> dict[str, Any] | None:
    """跑一次 coordinator 决策，返回 decision dict 或 None（解析失败）。

    事件**直接 emit，不经本地队列缓冲**。若先攒进队列、等整轮 LLM 调用结束后
    再一次性 flush，调用期间前端收不到任何事件，思考过程与流式 token 只会在
    最后集中抵达，表现为流式输出不连续。

    `documents_summary` 与 `client` 由 run_chat 预先构建一次后传入 —— 文档摘要
    在整轮对话中不变，重复汇总既浪费又在长对话里反复占用 token；client 同理。
    """
    messages = _build_supervisor_messages(
        messages, documents_summary, called, max_history_tokens, model
    )

    spec = registry.agents["coordinator"]
    emit(
        EventType.AGENT_START,
        status=NodeStatus.RUNNING,
        message=f"{spec.name} 评估下一步",
        payload={"agent": "coordinator", "name": spec.name, "role": spec.role},
        node_override="supervisor",
    )

    parts: list[str] = []
    for delta in client.stream_messages(messages):
        if delta.content:
            parts.append(delta.content)
            emit(
                EventType.TOKEN,
                status=NodeStatus.RUNNING,
                message=delta.content,
                payload={"agent": "coordinator"},
                node_override="supervisor",
            )
        if delta.reasoning:
            emit(
                EventType.THINKING,
                status=NodeStatus.RUNNING,
                message=delta.reasoning,
                payload={"agent": "coordinator"},
                node_override="supervisor",
            )

    raw = "".join(parts).strip()
    decision = _normalize_decision(_parse_decision(raw))

    # 解析失败时纠偏重试一次：部分模型会忽略「只输出 JSON」直接写分析正文。
    # 把上次输出回灌并强制要 schema，比直接判死更有用。
    if decision is None and raw:
        emit(
            EventType.LOG,
            status=NodeStatus.RUNNING,
            message="主管输出不是决策 JSON，正在纠偏重试",
            payload={"preview": raw[:200]},
            node_override="supervisor",
        )
        repair_messages = messages + [
            {"role": "assistant", "content": raw[:2000]},
            {
                "role": "user",
                "content": (
                    "你刚才输出的是分析正文，不是决策 JSON。"
                    "请立刻只输出一个 JSON 对象，不要再输出任何分析内容。\n"
                    '格式必须是：{"action":"reply|delegate|ask", ...}\n'
                    "delegate 时必须包含 agent 与 task；"
                    "reply 时必须包含 content；"
                    "ask 时必须包含 questions 数组。"
                ),
            },
        ]
        repair_parts: list[str] = []
        for delta in client.stream_messages(repair_messages):
            if delta.content:
                repair_parts.append(delta.content)
        repair_raw = "".join(repair_parts).strip()
        decision = _normalize_decision(_parse_decision(repair_raw))
        if decision:
            raw = repair_raw
            emit(
                EventType.LOG,
                status=NodeStatus.RUNNING,
                message="纠偏成功，已解析为决策 JSON",
                node_override="supervisor",
            )

    # 决策依据单独发一条日志：模型输出的 JSON 里带 reason，但它混在
    # 一整段 token 流里，用户看不出主管「为什么派这位专家」。抽出来单独展示，
    # 协作面板才能回答「它到底在想什么」。
    if decision:
        reason = str(decision.get("reason") or "").strip()
        if reason:
            emit(
                EventType.LOG,
                status=NodeStatus.RUNNING,
                message=f"决策依据：{reason}",
                payload={
                    "agent": "coordinator",
                    "reason": reason,
                    "action": decision.get("action"),
                },
                node_override="supervisor",
            )

    emit(
        EventType.AGENT_END,
        status=NodeStatus.SUCCESS if decision else NodeStatus.FAILED,
        message=f"{spec.name} 完成决策" if decision else f"{spec.name} 输出无法解析",
        payload={
            "agent": "coordinator",
            "name": spec.name,
            "role": spec.role,
            "decision": decision,
            "raw_preview": raw[:400],
        },
        node_override="supervisor",
    )

    return decision


def _run_specialist(
    spec: AgentSpec,
    task: str,
    state: InvestState,
    documents: list[dict[str, Any]],
    emit: EmitFn,
    client: LLMClient,
) -> dict[str, Any]:
    """跑一个 specialist agent，结果作为 dict 返回。

    事件直接 emit（不缓冲），保证 ReAct 每步、每个 token 都实时到达前端。
    `client` 由 run_chat 预先构建一次后传入，避免每个专家各自新建。
    """
    node = f"specialist:{spec.key}"

    def put(
        type_: EventType,
        *,
        status: NodeStatus | None = None,
        message: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        emit(type_, status=status, message=message, payload=payload, node_override=node)

    put(
        EventType.AGENT_START,
        status=NodeStatus.RUNNING,
        message=f"{spec.name} 开始工作",
        payload={"agent": spec.key, "name": spec.name, "role": spec.role},
    )

    runner = AgentRunner(spec)

    # 把已上传文档的关键内容作为 task 的一部分注入。
    # specialist 的 system_prompt 已经指引它使用工具；
    # 上传文档会作为补充上下文，让它不必再调 parse_document。
    doc_block = ""
    budget = DOC_CONTEXT_TOTAL
    for doc in documents:
        if budget <= 0:
            break
        focus = (doc.get("focus_text") or doc.get("document_text") or "").strip()
        if not focus:
            continue
        take = focus[: min(DOC_CONTEXT_PER_DOC, budget)]
        budget -= len(take)
        note = "（节选，已截断）" if len(focus) > len(take) else ""
        diag = doc.get("diagnostics") or {}
        pages = diag.get("page_count") or len(doc.get("pages") or [])
        doc_block += (
            f"\n\n【附件 {doc.get('filename', '')}（{doc.get('kind', 'text')}，"
            f"{pages} 页，共 {diag.get('chars', 0)} 字）{note}】\n{take}\n"
        )
    full_task = task + doc_block if doc_block else task

    result = runner.run(full_task, client, put, node, shared={})
    payload = {
        "agent": spec.key,
        "name": spec.name,
        "role": spec.role,
        "opinion": result.get("output", ""),
        "steps": result.get("steps", 0),
        "tools_used": result.get("tools_used", []),
        "elapsed_ms": result.get("elapsed_ms", 0),
        "loaded_skills": list(spec.skills),
        "truncated": result.get("truncated", False),
    }

    put(
        EventType.AGENT_END, status=NodeStatus.SUCCESS, message=f"{spec.name} 完成", payload=payload
    )

    return {**result, **payload}


def run_chat(
    state: InvestState,
    documents: list[dict[str, Any]],
    emit: EmitFn,
) -> dict[str, Any]:
    """主入口：跑 supervisor loop，返回最终的 assistant 消息内容 + 元数据。

    终止以「是否还有进展」为准，不设调度轮数预算：只要每轮都有实质产出
    （调度了新专家、拿到了用户作答），就一直跑下去，直到主管给出最终回复。

    返回：
        {
            "reply": "<最终给用户的回复文本>",
            "messages": [<完整 messages 数组（含 specialist 结果与最终 assistant）>],
            "iterations": <实际执行轮数>,
            "truncated": <是否因无进展收尾>,
            "specialists_called": [<被调度的 specialist key>],
        }
    """
    messages: list[dict[str, Any]] = list(state.get("messages") or [])
    specialists_called: list[str] = []
    asked_signatures: set[str] = set()
    # 本轮是否已经因为「只回了一句确认」要求过重决策。
    # 再次空确认就接受它，不再耗一轮 —— 说明该模型确实只能给到这个程度。
    ack_retried = False
    idle_rounds = 0
    actual_iterations = 0

    # 整轮对话里文档与 client 都不变：只构建一次，向下传给每一轮 supervisor
    # 与每一位 specialist，避免每轮重复汇总文档 / 重复 new 一个 LLMClient。
    client = build_chat_client(state, emit)
    documents_summary = _summarize_documents(documents)

    # 历史预算按模型窗口算一次即可：窗口在整轮里不变，
    # 每轮重算只是重复查表。
    model = str(state.get("model") or "")
    max_history_tokens = history_token_budget(state)

    def idle(reason: str, iteration: int, **payload: Any) -> None:
        """记一次「本轮没有实质产出」，连续多次即收尾。"""
        nonlocal idle_rounds
        idle_rounds += 1
        emit(
            EventType.LOG,
            status=NodeStatus.FAILED,
            message=reason,
            payload={"iteration": iteration, "idle": idle_rounds, **payload},
        )

    while True:
        actual_iterations += 1
        # 进展检测是正常终止路径；水位只用于拦住决策死循环
        if idle_rounds >= MAX_IDLE_ROUNDS or actual_iterations > ABSOLUTE_ROUND_LIMIT:
            break

        iteration = actual_iterations
        emit(
            EventType.LOG,
            status=NodeStatus.RUNNING,
            message=f"第 {iteration} 轮调度",
            payload={"iteration": iteration},
        )

        decision = _run_supervisor_iteration(
            messages,
            documents_summary,
            emit,
            client,
            specialists_called,
            max_history_tokens,
            model,
        )

        if decision is None:
            idle("主管输出无法解析为 JSON", iteration)
            continue

        action = str(decision.get("action") or "").strip().lower()
        decision = _normalize_decision(decision) or {}
        action = str(decision.get("action") or "").strip().lower()

        if action == "reply":
            content = (decision.get("content") or "").strip() or "（主管未提供具体回复）"

            # 空确认防线：用户发来技能命令或实质请求时，参数量较小的模型常只回
            # 一句「已收到技能指令」，整轮就此空转。首次拦下并要求重新决策。
            if not specialists_called and not ack_retried and _is_empty_ack(content):
                ack_retried = True
                emit(
                    EventType.LOG,
                    status=NodeStatus.FAILED,
                    message=f"回复没有实质内容（{content[:20]}），要求重新决策",
                    payload={"iteration": iteration},
                )
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "（你刚才的回复只是一句确认，没有任何实质内容。）\n"
                            "请重新决策：需要专业分析就 delegate 给对应专家，"
                            "信息不足就 ask 向用户提问，"
                            "能直接回答就给出有实质内容的 reply。"
                        ),
                        "internal": True,
                    }
                )
                continue

            messages.append({"role": "assistant", "content": content})
            emit(
                EventType.LOG,
                status=NodeStatus.RUNNING,
                message=f"主管给出最终回复（{len(content)} 字）",
                payload={"iteration": iteration},
            )
            return {
                "reply": content,
                "messages": messages,
                "iterations": iteration,
                "truncated": False,
                "specialists_called": specialists_called,
            }

        if action == "ask":
            try:
                payload = build_ask_payload(
                    decision.get("questions"),
                    decision.get("title") or "",
                )
            except ValueError as exc:
                idle(f"询问参数无效：{exc}", iteration)
                continue

            signature = json.dumps(payload["questions"], sort_keys=True, ensure_ascii=False)
            if signature in asked_signatures:
                idle("重复提问同一批问题，已跳过", iteration)
                continue

            asked_signatures.add(signature)
            result = interaction.ask(payload)
            answers = result.get("answers") or []
            if result.get("answered"):
                user_reply = summarize_answers(payload, answers)
                tail = "以上为用户本人作答，优先级高于任何推测；据此继续后续分析。"
            else:
                user_reply = (
                    "（用户未在限定时间内作答。请基于现有信息自行选择最合理的"
                    "默认口径，并在结论中说明所采用的假设。）"
                )
                tail = ""
                idle("用户未在限定时间内作答", iteration)

            full = f"{user_reply}\n\n{tail}".strip()
            messages.append({"role": "user", "content": full})
            emit(
                EventType.LOG,
                status=NodeStatus.RUNNING,
                message=f"用户已作答（{len(answers)} 项）",
                payload={"iteration": iteration, "asked": len(asked_signatures)},
            )
            if result.get("answered"):
                idle_rounds = 0
            continue

        if action == "delegate":
            agent_key = decision.get("agent")
            task = (decision.get("task") or "").strip()

            if agent_key not in delegateable_agents():
                idle(f"主管请求调用未注册的专家：{agent_key}", iteration, agent=agent_key)
                messages.append(
                    {
                        "role": "assistant",
                        "content": f"（主管请求调度的专家 {agent_key} 未注册，已忽略）",
                    }
                )
                continue

            if not task:
                idle(f"主管调用 {agent_key} 但未给出任务说明", iteration, agent=agent_key)
                continue

            if agent_key in specialists_called:
                idle(f"主管重复调度 {agent_key}（本轮已调用过）", iteration, agent=agent_key)
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            f"（{registry.agents[agent_key].name} 本轮已经给过结论，"
                            "见上方历史，不要再调度他。）\n"
                            "请二选一：\n"
                            "1. 若已有结论足以回答用户，输出 action=reply 给出最终答复；\n"
                            "2. 若确实还缺别的视角，改为调度尚未用过的专家。"
                        ),
                        "internal": True,
                    }
                )
                continue

            spec = registry.agents[agent_key]
            emit(
                EventType.LOG,
                status=NodeStatus.RUNNING,
                message=f"主管调度：{spec.name}",
                payload={"agent": agent_key, "task": task[:200]},
            )

            result = _run_specialist(spec, task, state, documents, emit, client)

            specialists_called.append(agent_key)
            messages.append(
                {
                    "role": "assistant",
                    "name": spec.name,
                    "content": _specialist_summary_text(result),
                }
            )
            idle_rounds = 0
            ack_retried = False
            continue

        idle(
            f"主管输出未知动作：{decision.get('action')}", iteration, action=decision.get("action")
        )

    # 收尾：连续多轮没有实质产出，用最近一次专家结论作答
    fallback = ""
    for m in reversed(messages):
        if m.get("role") == "assistant" and (m.get("content") or "").strip():
            fallback = m["content"]
            break
    if not fallback:
        fallback = (
            "本轮未能完成有效调度。可以：\n"
            "1. 换个说法重试；\n"
            "2. 上传/粘贴财报原文；\n"
            "3. 在设置中更换更遵循指令的模型（如 dots / deepseek-v4-pro）。"
        )
    emit(
        EventType.LOG,
        status=NodeStatus.RUNNING,
        message="对话未能自然结束，已使用最近一次专家结论收尾，结论可能不完整",
        payload={"iterations": actual_iterations, "idle": idle_rounds},
    )
    return {
        "reply": fallback,
        "messages": messages,
        "iterations": actual_iterations,
        "truncated": True,
        "specialists_called": specialists_called,
    }


def serialize_messages(messages: list[dict[str, Any]]) -> str:
    """把 messages 数组落盘为 JSONL。

    JSONL 而不是单个 JSON，便于以后追加与流式读取。
    视觉字段（image_url）也一并保留，续跑时可还原。
    """
    lines: list[str] = []
    for m in messages:
        lines.append(json.dumps(m, ensure_ascii=False))
    return "\n".join(lines)


def deserialize_messages(text: str) -> list[dict[str, Any]]:
    """从 JSONL 反序列化 messages。空文本返回空数组。"""
    out: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out
