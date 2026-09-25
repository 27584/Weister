"""主管决策字段规范化：兼容非标准模型输出。"""

from __future__ import annotations

from app.agents import bootstrap
from app.decision import normalize_decision
from app.tools.interact import build_ask_payload

bootstrap()

_normalize_decision = normalize_decision


def test_ask_flat_question_options_string_list():
    d = _normalize_decision(
        {
            "action": "ask",
            "question": "您希望分析什么？",
            "options": ["A 选项", "B 选项"],
        }
    )
    assert d is not None
    qs = d["questions"]
    assert len(qs) == 1
    assert qs[0]["question"] == "您希望分析什么？"
    payload = build_ask_payload(d["questions"])
    assert payload["questions"]


def test_ask_already_normalized_passthrough():
    src = {
        "action": "ask",
        "questions": [
            {
                "question": "q",
                "header": "h",
                "multiSelect": False,
                "options": [{"label": "a", "description": ""}, {"label": "b", "description": ""}],
            }
        ],
    }
    d = _normalize_decision(src)
    assert d["questions"] == src["questions"]


def test_reply_field_alias():
    d = _normalize_decision({"action": "reply", "reply": "你好"})
    assert d["content"] == "你好"


def test_delegate_role_alias():
    d = _normalize_decision({"action": "delegate", "role": "财务分析师", "task": "分析财报"})
    assert d["agent"] == "financial_analyst"
    assert d["task"] == "分析财报"


def test_next_action_and_expert_alias():
    d = _normalize_decision(
        {
            "next_action": "delegate",
            "expert": "财务分析师",
            "task": "分析苹果财报",
        }
    )
    assert d["action"] == "delegate"
    assert d["agent"] == "financial_analyst"
    assert d["task"] == "分析苹果财报"


def test_next_action_target_alias():
    d = _normalize_decision(
        {
            "next_action": "delegate",
            "target": "financial_analyst",
            "task": "抽取字段",
        }
    )
    assert d["action"] == "delegate"
    assert d["agent"] == "financial_analyst"


def test_delegate_delegates_array():
    d = _normalize_decision(
        {
            "action": "delegate",
            "delegates": [
                {"role": "风险审查员", "task": "找风险"},
                {"role": "反方质疑者", "task": "质疑"},
            ],
        }
    )
    assert d["agent"] == "risk_reviewer"
    assert d["task"] == "找风险"


def test_request_user_input_becomes_ask():
    d = _normalize_decision(
        {
            "action": "request_user_input",
            "message": "请提供 Apple 10-K 关键科目",
        }
    )
    assert d["action"] == "ask"
    assert d["questions"][0]["question"].startswith("请提供")
    assert len(d["questions"][0]["options"]) >= 2


def test_request_user_input_with_options():
    d = _normalize_decision(
        {
            "action": "request_user_input",
            "question": "选一种口径",
            "options": ["A", "B"],
        }
    )
    assert d["action"] == "ask"
    assert d["questions"][0]["options"][0] in ("A", {"label": "A", "description": ""})
