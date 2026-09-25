"""运行时上下文：让同步工具能够拿到当前运行的标识与事件出口。

工具 handler 的签名由模型给出的参数决定（AgentRunner 只注入 client 与
on_delta），拿不到 run_id 与 emit。而人机交互工具必须往当前 SSE 流推事件，
因此用 ContextVar 在 worker 线程入口绑定一次，工具内部直接读取。

与搜索配置同理：/api/chat 的 worker 跑在 asyncio.to_thread 里，
线程内的 context 是入口 context 的副本，绑定后对整个 worker 生命周期可见。
"""

from __future__ import annotations

from collections.abc import Callable
from contextvars import ContextVar
from typing import Any

_run_id: ContextVar[str] = ContextVar("weister_run_id", default="")
_emit: ContextVar[Callable[..., Any] | None] = ContextVar("weister_emit", default=None)


def bind(run_id: str, emit: Callable[..., Any] | None) -> None:
    """在 worker 线程入口绑定当前运行上下文。"""
    _run_id.set(run_id)
    _emit.set(emit)


def run_id() -> str:
    return _run_id.get()


def emit() -> Callable[..., Any] | None:
    return _emit.get()
