"""回归测试：_chat_stream 必须把事件流落盘（供刷新后重建协作面板）。

用假 run_chat 产生若干 agent 事件，断言 _save_chat_events 被以该 run_id 调用，
且收集到的事件包含 agent_start / thinking / token / agent_end。
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.api import ChatRequest, Credentials, _chat_stream
from app.api import chat as chat_mod
from app.events import EventType, NodeStatus


def fake_run_chat(state, documents, emit):
    emit(EventType.LOG, status=NodeStatus.RUNNING, message="第 1/6 轮调度")
    emit(
        EventType.AGENT_START,
        status=NodeStatus.RUNNING,
        message="财务分析师 开始工作",
        payload={"agent": "financial_analyst", "name": "财务分析师"},
    )
    emit(
        EventType.THINKING,
        status=NodeStatus.RUNNING,
        message="推理片段",
        payload={"agent": "financial_analyst"},
    )
    emit(
        EventType.TOKEN,
        status=NodeStatus.RUNNING,
        message="分析内容",
        payload={"agent": "financial_analyst"},
    )
    emit(
        EventType.AGENT_END,
        status=NodeStatus.SUCCESS,
        message="财务分析师 完成",
        payload={"agent": "financial_analyst"},
    )
    return {
        "reply": "ok",
        "messages": [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "ok"}],
        "iterations": 1,
        "truncated": False,
        "specialists_called": ["financial_analyst"],
    }


async def drive(req):
    async for _chunk in _chat_stream(
        req,
        {},
        Credentials(provider="deepseek", model="ds", api_key="x"),
    ):
        pass


def main():
    saved: dict[str, list] = {}
    chat_mod.run_chat = fake_run_chat
    chat_mod.save_chat_history = lambda *a, **k: None
    chat_mod.load_chat_history = lambda run_id: []
    chat_mod.save_chat_events = lambda run_id, events: saved.__setitem__(run_id, list(events))

    asyncio.run(drive(ChatRequest(run_id="evt-test", message="hi", attachments=[])))

    events = saved.get("evt-test")
    assert events, "_save_chat_events 未被调用"
    # 事件 dict 里的 type 可能是 EventType 枚举（str 子类），统一取 .value
    types = [getattr(e.get("type"), "value", e.get("type")) for e in events]
    # run_end（及 result）必须落盘，否则重放时 agent 相位停在「进行中」
    need = {"agent_start", "thinking", "token", "agent_end", "run_end", "result"}
    got = set(types)
    print("落盘事件数:", len(events))
    print("事件类型:", sorted(got))
    missing = need - got
    assert not missing, f"缺少事件类型: {missing}"
    assert all(e.get("run_id") == "evt-test" for e in events), "事件 run_id 不一致"
    # 落盘版 result 不应携带完整 messages（避免事件文件翻倍）
    result_ev = next(
        e for e in events if getattr(e.get("type"), "value", e.get("type")) == "result"
    )
    assert "messages" not in (result_ev.get("payload") or {}), "落盘 result 不应含 messages"
    print("\nALL PASS: 事件流（含 run_end）已正确落盘，可完整重建协作面板")
    raise SystemExit(0)


if __name__ == "__main__":
    main()
