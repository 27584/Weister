"""运行检查点。

每个节点执行后写入状态，支持中断后从上次完成的位置续跑，
避免重复调用 LLM。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .storage import CHECKPOINT_DIR

CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)


def _path(run_id: str) -> Path:
    return CHECKPOINT_DIR / f"{run_id}.json"


def save(run_id: str, payload: dict[str, Any]) -> None:
    payload["updated_at"] = time.time()
    tmp = _path(run_id).with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, default=str), encoding="utf-8")
    tmp.replace(_path(run_id))


def load(run_id: str) -> dict[str, Any] | None:
    path = _path(run_id)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def latest() -> dict[str, Any] | None:
    files = sorted(CHECKPOINT_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if not data.get("finished"):
            return data
    return None


def mark_finished(run_id: str) -> None:
    data = load(run_id)
    if data is None:
        return
    data["finished"] = True
    save(run_id, data)


def clear(run_id: str) -> None:
    path = _path(run_id)
    if path.is_file():
        path.unlink()


def list_runs(limit: int = 20) -> list[dict[str, Any]]:
    files = sorted(CHECKPOINT_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    out: list[dict[str, Any]] = []
    for path in files[:limit]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        out.append(
            {
                "run_id": data.get("run_id"),
                "filename": data.get("filename"),
                "finished": data.get("finished", False),
                "stage": data.get("stage"),
                "completed_nodes": data.get("completed_nodes", []),
                "updated_at": data.get("updated_at"),
            }
        )
    return out
