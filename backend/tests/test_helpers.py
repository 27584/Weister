"""技能命令解析与用户消息构造。"""

from __future__ import annotations

from app.api.helpers import build_user_message, skill_command_context, split_skill_command
from app.core.registry import registry


def test_split_known_skill():
    known = {"financial_analysis"}
    name, rest = split_skill_command("/financial_analysis 看这份财报", known)
    assert name == "financial_analysis"
    assert rest == "看这份财报"


def test_split_unknown_keeps_text():
    name, rest = split_skill_command("/nope 你好", {"financial_analysis"})
    assert name is None
    assert rest == "/nope 你好"


def test_user_message_no_body_in_content():
    doc = {
        "filename": "x.pdf",
        "kind": "text",
        "mime": "application/pdf",
        "document_text": "A" * 5000,
        "pages": [],
        "diagnostics": {"chars": 5000, "page_count": 12},
        "readable": True,
    }
    msg = build_user_message("帮我分析", [], [doc])
    assert "AAAA" not in msg["content"]
    assert "12 页" in msg["content"]
    assert msg["display_text"] == "帮我分析"


def test_skill_context_has_action_requirement():
    name = min(registry.skills)
    bare = skill_command_context(name, has_body=False)
    assert "禁止只回答" in bare
