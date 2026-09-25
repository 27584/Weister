"""主管决策解析与字段规范化。

不同模型对 JSON 协议的服从程度差异很大：dots 会按 schema 输出，
deepseek-v4.1-flash 等会自创 next_action / expert / 顶层 question 等字段，
甚至直接输出分析正文。本模块负责：
    1. 从流式文本中提取 JSON 决策
    2. 把非标准字段映射为 run_chat 期望的 action / agent / task / questions
"""

from __future__ import annotations

import json
from typing import Any

from .agents import registry

# 显示名 / 角色名 → agent key
_AGENT_ALIASES: dict[str, str] = {
    "财务分析师": "financial_analyst",
    "financial analyst": "financial_analyst",
    "估值专家": "valuation_expert",
    "valuation expert": "valuation_expert",
    "风险审查员": "risk_reviewer",
    "risk reviewer": "risk_reviewer",
    "反方质疑者": "devils_advocate",
    "devils advocate": "devils_advocate",
    "报告撰写人": "report_writer",
    "report writer": "report_writer",
    "市场数据研究员": "market_analyst",
    "market analyst": "market_analyst",
    "信息研究员": "research_assistant",
    "research assistant": "research_assistant",
}

_ACTION_ALIASES: dict[str, str] = {
    "回复": "reply",
    "回答": "reply",
    "直接回复": "reply",
    "respond": "reply",
    "answer": "reply",
    "final": "reply",
    "final_reply": "reply",
    "respond_to_user": "reply",
    "提问": "ask",
    "询问": "ask",
    "ask_user": "ask",
    "ask_user_input": "ask",
    "request_user_input": "ask",
    "request_input": "ask",
    "clarify": "ask",
    "clarification": "ask",
    "confirm": "ask",
    "user_input": "ask",
    "need_input": "ask",
    "调度": "delegate",
    "委派": "delegate",
    "分派": "delegate",
    "调用专家": "delegate",
    "dispatch": "delegate",
    "delegate_to_agent": "delegate",
    "call_expert": "delegate",
    "use_agent": "delegate",
}

_ACTION_FIELD_ALIASES = ("next_action", "nextAction", "type", "operation", "intent")


def parse_decision(raw: str) -> dict[str, Any] | None:
    """从 LLM 输出中提取 JSON 决策。

    容忍完整 JSON、markdown 围栏、以及前后夹说明文字三种形态。
    """
    text = (raw or "").strip()
    if not text:
        return None

    fence = chr(96) * 3
    if text.startswith(fence):
        body = text[len(fence) :]
        body = body.removeprefix("json")
        if fence in body:
            body = body.split(fence)[0]
        text = body.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    first = text.find("{")
    last = text.rfind("}")
    if first >= 0 and last > first:
        try:
            return json.loads(text[first : last + 1])
        except json.JSONDecodeError:
            return None
    return None


def resolve_agent_key(raw: Any) -> str | None:
    if not raw:
        return None
    key = str(raw).strip()
    if key in registry.agents:
        return key
    return _AGENT_ALIASES.get(key.lower()) or _AGENT_ALIASES.get(key)


def _normalize_ask_options(options: Any) -> list[Any]:
    if not isinstance(options, list):
        return []
    out: list[Any] = []
    for opt in options[:6]:
        if isinstance(opt, str) and opt.strip():
            out.append(opt.strip())
        elif isinstance(opt, dict) and (opt.get("label") or opt.get("text")):
            out.append(
                {
                    "label": str(opt.get("label") or opt.get("text"))[:80],
                    "description": str(opt.get("description") or "")[:200],
                }
            )
    return out


def normalize_decision(decision: dict[str, Any] | None) -> dict[str, Any] | None:
    """把不同模型输出的决策字段，统一成 run_chat 期望的形态。"""
    if not decision or not isinstance(decision, dict):
        return decision

    out = dict(decision)
    if not out.get("action"):
        for key in _ACTION_FIELD_ALIASES:
            val = out.get(key)
            if isinstance(val, str) and val.strip():
                out["action"] = val.strip()
                break

    action = str(out.get("action") or "").strip().lower()
    action = _ACTION_ALIASES.get(action, action)
    out["action"] = action

    if action == "reply":
        if not (out.get("content") or "").strip():
            alt = out.get("reply") or out.get("text") or out.get("message") or ""
            if alt:
                out["content"] = str(alt)
        return out

    if action == "ask":
        questions = out.get("questions")
        if isinstance(questions, list) and questions:
            return out

        q_text = (
            out.get("question")
            or out.get("title")
            or out.get("message")
            or out.get("prompt")
            or out.get("content")
            or out.get("reason")
            or ""
        )
        options = _normalize_ask_options(out.get("options") or out.get("choices"))
        if q_text and len(options) >= 1:
            out["questions"] = [
                {
                    "question": str(q_text)[:500],
                    "header": str(out.get("header") or "确认")[:12],
                    "multiSelect": bool(out.get("multiSelect")),
                    "options": options
                    if len(options) >= 2
                    else options + [{"label": "继续", "description": "按默认口径继续"}],
                }
            ]
            return out

        if q_text:
            out["questions"] = [
                {
                    "question": str(q_text)[:500],
                    "header": "需要确认",
                    "multiSelect": False,
                    "options": [
                        {"label": "按你的建议继续", "description": "采用模型提出的默认口径"},
                        {"label": "我补充信息", "description": "自行填写标的、期间或数据"},
                    ],
                }
            ]
            return out

        if isinstance(questions, dict) and questions.get("question"):
            out["questions"] = [questions]
        return out

    if action == "delegate":
        agent = resolve_agent_key(
            out.get("agent")
            or out.get("expert")
            or out.get("target")
            or out.get("delegate_to")
            or out.get("assignee")
            or out.get("role")
            or out.get("specialist")
        )
        if agent:
            out["agent"] = agent

        delegates = out.get("delegates") or out.get("experts") or out.get("agents")
        if isinstance(delegates, list) and delegates:
            for item in delegates:
                if not isinstance(item, dict):
                    continue
                key = resolve_agent_key(
                    item.get("agent")
                    or item.get("expert")
                    or item.get("role")
                    or item.get("key")
                    or item.get("name")
                    or item.get("target")
                )
                if key:
                    out["agent"] = key
                    if not (out.get("task") or "").strip():
                        out["task"] = str(item.get("task") or item.get("instruction") or "")
                    break

        if not (out.get("task") or "").strip():
            payload = out.get("input") or out.get("payload") or {}
            if isinstance(payload, dict):
                out["task"] = str(payload.get("task") or payload.get("request") or "")
            if not (out.get("task") or "").strip():
                out["task"] = str(out.get("instruction") or out.get("prompt") or "")
        return out

    return out


# 兼容旧内部名
_parse_decision = parse_decision
_normalize_decision = normalize_decision
_resolve_agent_key = resolve_agent_key

__all__ = [
    "_normalize_decision",
    "_parse_decision",
    "normalize_decision",
    "parse_decision",
    "resolve_agent_key",
]
