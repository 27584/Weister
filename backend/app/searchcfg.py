"""搜索源配置的运行时覆盖。

优先级：
    1. 请求头（前端设置面板里填的，X-Search-*）
    2. profiles.json 里保存的配置（storage.load_profiles()["search"]）
    3. backend/.env（settings.tavily_api_key / bocha_api_key / searxng_url）

为什么用 contextvars 而不是全局字典：
    /api/chat 的 worker 跑在 asyncio.to_thread 里，to_thread 会复制当前
    context 进子线程，天然按请求隔离；并发请求不会互相覆盖 Key。
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any

_KEYS = ("tavily_api_key", "bocha_api_key", "searxng_url")

_ctx: ContextVar[dict[str, str] | None] = ContextVar("weister_search_cfg", default=None)


def bind(cfg: dict[str, Any] | None) -> None:
    """把本次请求生效的搜索配置绑定到当前 context。"""
    _ctx.set({k: str((cfg or {}).get(k) or "").strip() for k in _KEYS})


def get() -> dict[str, str]:
    return _ctx.get() or {k: "" for k in _KEYS}
