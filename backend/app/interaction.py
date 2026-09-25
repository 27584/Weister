"""人机交互桥：让 worker 线程里的同步工具向用户提问并等待回答。

SSE 是单向通道（后端 → 前端），而工具调用是同步阻塞的，
因此用「注册表 + threading.Event」在两者之间搭桥：

    工具 ask()   → 注册待答问题 → 经 emit 推送 ask_user 事件 → 阻塞等待
    前端         → 收到事件后渲染选项 → 用户作答
    前端         → POST /api/chat/answer → answer() 写入并唤醒
    工具         → 被唤醒，拿到答案继续 ReAct 循环

超时与中断：
    - 超时后工具收到 answered=False，据此告知模型「用户未作答」
    - run 被中断（客户端断开或主动 abort）时调用 cancel_run() 唤醒全部等待，
      避免 worker 线程悬挂到超时
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from typing import Any

from . import runctx
from .events import EventType

# 等待上限：超过后视为用户未作答，工具返回给模型自行决断
ASK_TIMEOUT_SECONDS = 900


@dataclass
class PendingQuestion:
    qid: str
    run_id: str
    event: threading.Event = field(default_factory=threading.Event)
    answer: dict[str, Any] | None = None


_PENDING: dict[str, PendingQuestion] = {}
_LOCK = threading.Lock()


def ask(
    payload: dict[str, Any],
    timeout: float = ASK_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """注册问题、推送事件并阻塞等待答案。

    payload 由调用方给出（问题列表、进度、是否多选等），
    原样透传给前端，仅额外附加 qid。
    """
    emit = runctx.emit()
    if emit is None:
        return {"answered": False, "reason": "no_event_channel"}

    qid = uuid.uuid4().hex[:12]
    pending = PendingQuestion(qid=qid, run_id=runctx.run_id())
    with _LOCK:
        _PENDING[qid] = pending

    emit(
        EventType.ASK_USER,
        status="running",
        message=str(payload.get("title") or "等待用户选择"),
        payload={"qid": qid, **payload},
    )

    answered = pending.event.wait(timeout)
    with _LOCK:
        _PENDING.pop(qid, None)

    if not answered or pending.answer is None:
        return {"answered": False, "qid": qid, "reason": "timeout"}
    return {"answered": True, "qid": qid, **pending.answer}


def answer(qid: str, payload: dict[str, Any]) -> bool:
    """写入答案并唤醒等待中的工具。问题不存在时返回 False。"""
    with _LOCK:
        pending = _PENDING.get(qid)
    if pending is None:
        return False
    pending.answer = payload
    pending.event.set()
    return True


def cancel_run(run_id: str) -> int:
    """唤醒某个运行下所有等待中的提问，返回被唤醒的数量。"""
    woke = 0
    with _LOCK:
        targets = [p for p in _PENDING.values() if p.run_id == run_id]
        for p in targets:
            _PENDING.pop(p.qid, None)
    for p in targets:
        p.answer = None
        p.event.set()
        woke += 1
    return woke


def pending_count() -> int:
    with _LOCK:
        return len(_PENDING)
