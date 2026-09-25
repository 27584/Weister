"""聊天落盘与事件压缩的单测。"""

from __future__ import annotations

from app.api.store import (
    compact_stream_events,
    load_chat_documents,
    load_chat_events,
    load_chat_history,
    save_chat_documents,
    save_chat_events,
    save_chat_history,
)


def test_compact_merges_same_agent_stream():
    events = [
        {"type": "thinking", "message": "A", "payload": {"agent": "x"}},
        {"type": "thinking", "message": "B", "payload": {"agent": "x"}},
        {"type": "thinking", "message": "C", "payload": {"agent": "y"}},
        {"type": "token", "message": "D", "payload": {"agent": "x"}},
    ]
    out = compact_stream_events(events)
    assert len(out) == 3
    assert out[0]["message"] == "AB"
    assert out[1]["payload"]["agent"] == "y"


def test_events_append(temp_data_dir):
    save_chat_events("r1", [{"type": "run_start", "message": "a"}])
    save_chat_events("r1", [{"type": "token", "message": "b"}])
    evs = load_chat_events("r1")
    assert [e["message"] for e in evs] == ["a", "b"]


def test_events_empty_noop(temp_data_dir):
    save_chat_events("r2", [{"type": "run_start", "message": "x"}])
    save_chat_events("r2", [])
    assert len(load_chat_events("r2")) == 1


def test_history_roundtrip(temp_data_dir):
    msgs = [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "在的"},
    ]
    save_chat_history("h1", msgs)
    assert load_chat_history("h1") == msgs


def test_documents_roundtrip(temp_data_dir):
    docs = [{"filename": "a.pdf", "document_text": "hello", "kind": "text"}]
    save_chat_documents("d1", docs)
    assert load_chat_documents("d1") == docs
