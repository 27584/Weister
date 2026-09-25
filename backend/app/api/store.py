"""聊天对话落盘：messages / events / documents / title。"""

from __future__ import annotations

import json
from pathlib import Path

from ..chat_supervisor import deserialize_messages, serialize_messages
from ..config import settings


def save_chat_history(run_id: str, messages: list[dict]) -> None:
    """把 messages 数组落盘到 data/runs/{run_id}/messages.jsonl。"""
    base = Path(settings.runs_dir) / run_id
    base.mkdir(parents=True, exist_ok=True)
    (base / "messages.jsonl").write_text(
        serialize_messages(messages),
        encoding="utf-8",
    )


def load_chat_history(run_id: str) -> list[dict]:
    base = Path(settings.runs_dir) / run_id
    path = base / "messages.jsonl"
    if not path.exists():
        return []
    return deserialize_messages(path.read_text(encoding="utf-8"))


def compact_stream_events(events: list[dict]) -> list[dict]:
    """把连续的流式碎片合并成一条再落盘。

    thinking / token 是逐字吐出的，一个字一条 JSONL 记录，而单条记录的
    外壳（type / status / payload / seq / run_id / node）约 177 字节，
    内容本身平均只有几个字节 —— 某次对话的 thinking 内容仅 25KB，
    落盘却占 853KB，97% 是外壳。

    前端回放时本来就会把连续的同类型项拼回同一个显示块，因此合并后
    展示效果完全一致，只是少读几千条记录。
    """
    out: list[dict] = []
    for ev in events:
        etype = ev.get("type")
        prev = out[-1] if out else None
        if (
            etype in ("thinking", "token")
            and prev is not None
            and prev.get("type") == etype
            # 同一位 agent 的连续流才合并；换了人必须断开，否则归属会错
            and (prev.get("payload") or {}).get("agent") == (ev.get("payload") or {}).get("agent")
        ):
            merged = dict(prev)
            merged["message"] = (prev.get("message") or "") + (ev.get("message") or "")
            out[-1] = merged
            continue
        out.append(ev)
    return out


def save_chat_events(run_id: str, events: list[dict]) -> None:
    """把本次运行的事件**追加**到 data/runs/{run_id}/events.jsonl。

    用于刷新/切换对话后重建「协作面板」（messages.jsonl 里没有 agent 过程事件）。

    追加而非覆盖：一个对话通常包含多轮，覆盖会让协作面板只剩最后一轮，
    无法完整还原。重放时按文件顺序累积，多轮记录自然叠加。
    """
    if not events:
        return
    events = compact_stream_events(events)
    base = Path(settings.runs_dir) / run_id
    base.mkdir(parents=True, exist_ok=True)
    lines = "\n".join(json.dumps(ev, ensure_ascii=False) for ev in events)
    with (base / "events.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(lines + "\n")


def load_chat_events(run_id: str) -> list[dict]:
    path = Path(settings.runs_dir) / run_id / "events.jsonl"
    if not path.exists():
        return []
    out: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def save_chat_documents(run_id: str, documents: list[dict]) -> None:
    """把已解析的文档存到 data/runs/{run_id}/documents.json。

    这样后续轮次（用户追问）仍能拿到完整文档正文 —— 因为正文不再写进
    messages，否则对话记录里会变成一大段截断文本。
    """
    base = Path(settings.runs_dir) / run_id
    base.mkdir(parents=True, exist_ok=True)
    (base / "documents.json").write_text(
        json.dumps(documents, ensure_ascii=False),
        encoding="utf-8",
    )


def load_chat_documents(run_id: str) -> list[dict]:
    path = Path(settings.runs_dir) / run_id / "documents.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def load_chat_title(run_id: str) -> str:
    """读取模型显式设置的对话标题，未设置时返回空串。

    标题由 set_conversation_title 工具写入 data/runs/{run_id}/title.txt，
    优先级高于从首条消息截取的默认标题。
    """
    path = Path(settings.runs_dir) / run_id / "title.txt"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


def conversation_title(
    messages: list[dict],
    run_id: str = "",
) -> str:
    """取对话标题：优先模型显式设置的，否则用第一条用户消息。

    优先用 display_text（用户实际输入），避免标题里出现附件标记「📎 xxx」。
    """
    if run_id:
        explicit = load_chat_title(run_id)
        if explicit:
            return explicit
    for m in messages:
        if m.get("role") != "user":
            continue
        content = m.get("display_text")
        if content is None:
            content = m.get("content") or ""
        if isinstance(content, list):
            texts = [p.get("text", "") for p in content if p.get("type") == "text"]
            content = " ".join(texts)
        title = str(content).strip().replace("\n", " ")[:40]
        if title:
            return title
    return "新对话"


__all__ = [
    "compact_stream_events",
    "conversation_title",
    "load_chat_documents",
    "load_chat_events",
    "load_chat_history",
    "load_chat_title",
    "save_chat_documents",
    "save_chat_events",
    "save_chat_history",
]
