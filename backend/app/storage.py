"""文件存储层。

统一管理 data 目录下的持久化数据：
    profiles.json       模型配置档案
    samples/*.txt       演示财报样例
    checkpoints/*.json  运行检查点
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
PROFILES_FILE = DATA_DIR / "profiles.json"
SAMPLES_DIR = DATA_DIR / "samples"
CHECKPOINT_DIR = DATA_DIR / "checkpoints"

for _d in (DATA_DIR, SAMPLES_DIR, CHECKPOINT_DIR):
    _d.mkdir(parents=True, exist_ok=True)


def _read_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def _write_json(path: Path, payload: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


DEFAULT_PROFILE = {
    "id": "default",
    "name": "DeepSeek",
    "provider": "deepseek",
    "model": "deepseek-chat",
    "fallbackModels": [],
    "apiKey": "",
    "baseUrl": "",
}


DEFAULT_SEARCH = {
    "tavilyApiKey": "",
    "bochaApiKey": "",
    "searxngUrl": "",
}


def _clean_search(raw: Any) -> dict[str, str]:
    """搜索源配置（前端设置面板写入），字段缺失一律补空串。"""
    src = raw if isinstance(raw, dict) else {}
    return {k: str(src.get(k) or "") for k in DEFAULT_SEARCH}


def load_profiles() -> dict[str, Any]:
    data = _read_json(PROFILES_FILE, None)
    if not isinstance(data, dict) or not data.get("profiles"):
        seed = {
            "profiles": [dict(DEFAULT_PROFILE)],
            "activeId": DEFAULT_PROFILE["id"],
            "search": dict(DEFAULT_SEARCH),
        }
        _write_json(PROFILES_FILE, seed)
        return seed

    profiles = []
    for p in data.get("profiles", []):
        if not isinstance(p, dict):
            continue
        profiles.append(
            {
                "id": p.get("id") or f"p{len(profiles) + 1}",
                "name": p.get("name") or "未命名",
                "provider": p.get("provider") or "deepseek",
                "model": p.get("model") or "",
                "fallbackModels": p.get("fallbackModels")
                if isinstance(p.get("fallbackModels"), list)
                else [],
                "apiKey": p.get("apiKey") or "",
                "baseUrl": p.get("baseUrl") or "",
            }
        )

    if not profiles:
        profiles = [dict(DEFAULT_PROFILE)]

    active = data.get("activeId")
    if active not in {p["id"] for p in profiles}:
        active = profiles[0]["id"]

    return {
        "profiles": profiles,
        "activeId": active,
        "search": _clean_search(data.get("search")),
    }


def save_profiles(payload: dict[str, Any]) -> dict[str, Any]:
    profiles = payload.get("profiles") or []
    active = payload.get("activeId") or (profiles[0]["id"] if profiles else "default")
    cleaned = {
        "profiles": profiles,
        "activeId": active,
        "search": _clean_search(payload.get("search")),
        "updatedAt": time.time(),
    }
    _write_json(PROFILES_FILE, cleaned)
    return cleaned


def list_samples() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for path in sorted(SAMPLES_DIR.glob("*.txt")):
        stat = path.stat()
        out.append(
            {
                "name": path.stem,
                "filename": path.name,
                "size": stat.st_size,
                "updatedAt": stat.st_mtime,
            }
        )
    return out


def read_sample(name: str) -> str | None:
    safe = Path(name).name
    candidates = [SAMPLES_DIR / safe]
    if not safe.endswith(".txt"):
        candidates.append(SAMPLES_DIR / (safe + ".txt"))
    else:
        candidates.append(SAMPLES_DIR / safe[: -len(".txt")])

    for path in candidates:
        if path.is_file():
            return path.read_text(encoding="utf-8")
    return None


def write_sample(name: str, text: str) -> Path:
    safe = Path(name).name
    if not safe.endswith(".txt"):
        safe += ".txt"
    path = SAMPLES_DIR / safe
    path.write_text(text, encoding="utf-8")
    return path
