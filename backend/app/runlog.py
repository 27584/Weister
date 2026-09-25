"""运行日志记录。

把执行过程中的每个事件持久化到文件，用于事后审计与复现验证。

输出位置：
    data/runs/{run_id}/events.jsonl   逐行 JSON，每个事件一行
    data/runs/{run_id}/summary.json   运行摘要（起止时间、耗时、状态）

设计目标：
    - 可追溯：每个工具调用与模型输出都有时间戳与序列号
    - 可复现：记录足够的上下文，便于复现问题
    - 可审计：不记录 API Key 等敏感信息
"""

from __future__ import annotations

import json
import time
from typing import Any

from .storage import DATA_DIR

RUNS_DIR = DATA_DIR / "runs"

SENSITIVE_KEYS = {"api_key", "apikey", "authorization", "token", "secret"}


def _sanitize(value: Any) -> Any:
    """递归移除敏感字段。"""
    if isinstance(value, dict):
        return {
            k: ("***" if k.lower() in SENSITIVE_KEYS else _sanitize(v)) for k, v in value.items()
        }
    if isinstance(value, list):
        return [_sanitize(v) for v in value]
    return value


class RunLogger:
    """单次运行的日志记录器。

    用法：
        logger = RunLogger(run_id)
        logger.start(filename, provider, model)
        logger.event(event_dict)
        logger.finish(status)
    """

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self.dir = RUNS_DIR / run_id
        self.dir.mkdir(parents=True, exist_ok=True)
        self.events_path = self.dir / "events.jsonl"
        self.summary_path = self.dir / "summary.json"
        self._seq = 0
        self._started_at = time.time()
        self._event_count = 0
        self._tool_calls: dict[str, int] = {}
        self._errors: list[str] = []

    def start(
        self,
        filename: str,
        provider: str,
        model: str,
        question: str = "",
    ) -> None:
        """记录运行开始。"""
        self._write(
            {
                "kind": "run_start",
                "filename": filename,
                "provider": provider,
                "model": model,
                "question": question,
            }
        )

    def event(self, event: dict[str, Any]) -> None:
        """记录一条 SSE 事件。"""
        payload = event.get("payload") or {}
        sanitized = _sanitize(payload)

        record: dict[str, Any] = {
            "kind": "event",
            "type": event.get("type"),
            "node": event.get("node"),
            "status": event.get("status"),
        }

        # 消息可能很长，截断存储
        message = event.get("message")
        if isinstance(message, str):
            record["message"] = message[:2000]

        if sanitized:
            record["payload"] = sanitized

        self._write(record)

        if event.get("type") == "tool_call":
            tool = payload.get("tool") or ""
            if tool:
                self._tool_calls[tool] = self._tool_calls.get(tool, 0) + 1

        if event.get("type") == "error":
            msg = event.get("message") or ""
            if msg:
                self._errors.append(msg[:500])

    def finish(self, status: str = "success") -> None:
        """记录运行结束并写入摘要。"""
        ended_at = time.time()
        self._write({"kind": "run_end", "status": status})

        summary = {
            "run_id": self.run_id,
            "status": status,
            "started_at": self._started_at,
            "ended_at": ended_at,
            "duration_ms": int((ended_at - self._started_at) * 1000),
            "event_count": self._event_count,
            "tool_calls": self._tool_calls,
            "errors": self._errors,
        }
        self.summary_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _write(self, record: dict[str, Any]) -> None:
        self._seq += 1
        record["seq"] = self._seq
        record["ts"] = time.time()
        with self.events_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        self._event_count += 1


def list_run_logs(limit: int = 50) -> list[dict[str, Any]]:
    """列出所有运行日志的摘要。"""
    if not RUNS_DIR.is_dir():
        return []

    out: list[dict[str, Any]] = []
    for path in sorted(RUNS_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not path.is_dir():
            continue
        summary_file = path / "summary.json"
        if summary_file.is_file():
            try:
                out.append(json.loads(summary_file.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, OSError):
                continue
        if len(out) >= limit:
            break
    return out


def read_run_events(run_id: str, limit: int = 500) -> list[dict[str, Any]]:
    """读取指定运行的原始事件流。"""
    path = RUNS_DIR / run_id / "events.jsonl"
    if not path.is_file():
        return []

    out: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
            if len(out) >= limit:
                break
    return out


def clear_run_log(run_id: str) -> None:
    """删除指定运行的日志目录。"""
    import shutil

    path = RUNS_DIR / run_id
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
