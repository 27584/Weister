"""事件协议：后端 EventType / NodeStatus 与前端 types.ts 必须一致。"""

from __future__ import annotations

import re
from pathlib import Path

from app.events import EventType, NodeStatus

FRONTEND_TYPES = (
    Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "types.ts"
)


def _ts_union_literals(src: str, type_name: str) -> set[str]:
    m = re.search(rf"export type {type_name}\s*=\s*(.+?);", src, re.DOTALL)
    assert m, f"types.ts 中找不到 {type_name}"
    return set(re.findall(r'"([a-z_]+)"', m.group(1)))


def test_event_types_match_frontend():
    src = FRONTEND_TYPES.read_text(encoding="utf-8")
    fe = _ts_union_literals(src, "EventType")
    be = {e.value for e in EventType}
    assert be == fe, f"事件类型不一致 backend-only={be - fe} frontend-only={fe - be}"


def test_node_status_match_frontend():
    src = FRONTEND_TYPES.read_text(encoding="utf-8")
    fe = _ts_union_literals(src, "NodeStatus")
    be = {s.value for s in NodeStatus}
    assert be == fe


def test_agent_event_shape_docs():
    """AgentEvent 字段名前后端一致（文档级断言）。"""
    src = FRONTEND_TYPES.read_text(encoding="utf-8")
    for field in ("type", "run_id", "seq", "node", "status", "message", "payload"):
        assert field in src
