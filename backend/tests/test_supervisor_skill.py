"""主管调度协议 skill 加载与热更新。"""

from __future__ import annotations

from pathlib import Path

from app.chat_supervisor import (
    _FALLBACK_SUPERVISOR_PROMPT,
    _load_supervisor_prompt,
    delegateable_agents,
)


def test_skill_prompt_loads_and_formats():
    body = _load_supervisor_prompt()
    assert "action" in body
    s = body.format(agents=", ".join(delegateable_agents()))
    assert "financial_analyst" in s
    assert "JSON" in s


def test_skill_file_exists():
    from app.core.registry import SKILLS_DIR

    assert (Path(SKILLS_DIR) / "supervisor_coordination.md").exists()


def test_fallback_formats():
    s = _FALLBACK_SUPERVISOR_PROMPT.format(agents="a, b")
    assert "a, b" in s
