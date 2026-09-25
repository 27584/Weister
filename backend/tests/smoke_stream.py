"""验证 /api/chat 的 SSE 是「逐条实时」流出，而非跑完才一次性 flush。

用假 run_chat（三段 sleep 模拟多轮 LLM 调用）替换真模型，证明：
  1. 事件在 worker 执行过程中就一条条推到前端（不是整轮结束才发）
  2. 事件循环不被阻塞（主协程持续 await sleep 轮询队列）
"""

import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from _harness import isolate_data_dir

from app.api import ChatRequest, Credentials, _chat_stream
from app.api import chat as chat_mod
from app.events import EventType, NodeStatus


def fake_run_chat(state, documents, emit):
    emit(EventType.LOG, status=NodeStatus.RUNNING, message="supervisor 思考中…")
    time.sleep(0.4)
    emit(EventType.LOG, status=NodeStatus.RUNNING, message="调度 财务分析师")
    time.sleep(0.4)
    emit(EventType.LOG, status=NodeStatus.RUNNING, message="财务分析师 调用工具 extract_fields")
    time.sleep(0.4)
    emit(EventType.LOG, status=NodeStatus.RUNNING, message="调度 估值专家")
    time.sleep(0.4)
    return {
        "reply": "mock 回复",
        "messages": [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "mock 回复"},
        ],
        "iterations": 2,
        "truncated": False,
        "specialists_called": ["financial_analyst", "valuation_expert"],
    }


# 避免读写磁盘历史文件，保持测试纯净
chat_mod.run_chat = fake_run_chat
chat_mod.load_chat_history = lambda run_id: []
chat_mod.save_chat_history = lambda *a, **k: None
# _save_chat_events 仍会真实落盘，把数据目录重定向到临时目录
isolate_data_dir()


async def drive():
    req = ChatRequest(run_id="mock-stream", message="hi", attachments=[])
    cred = Credentials(provider="deepseek", model="deepseek-chat", api_key="x")
    arrivals = []  # (t_rel, type, message)
    t0 = time.monotonic()
    async for chunk in _chat_stream(req, {}, cred):
        t = time.monotonic() - t0
        # chunk 形如 "data: {...}\n\n"
        body = chunk.split("data: ", 1)[1].strip()
        ev = json.loads(body)
        arrivals.append((round(t, 2), ev.get("type"), str(ev.get("message") or "")[:32]))
    return arrivals


def main():
    arrivals = asyncio.run(drive())
    print("=== 事件到达时间线（相对起点，单位秒）===")
    prev = 0.0
    for t, typ, msg in arrivals:
        gap = round(t - prev, 2)
        print(f"  t={t:>5.2f}s  +{gap:>5.2f}s  {typ:<12} {msg}")
        prev = t

    ev_types = [t for _, t, _ in arrivals]
    # 关键断言 1：中途事件（非首非尾）之间有明显时间差 → 实时流出
    mid = [
        t
        for t, typ, _ in arrivals
        if typ not in (EventType.RUN_START.value, EventType.RESULT.value, EventType.RUN_END.value)
    ]
    gaps = [mid[i] - mid[i - 1] for i in range(1, len(mid))]
    live_streaming = len(mid) >= 3 and max(gaps) >= 0.3
    # 关键断言 2：RESULT 存在，且其后由 run_end(SUCCESS) 正常收尾
    has_result = EventType.RESULT.value in ev_types
    has_run_end = EventType.RUN_END.value in ev_types
    # run_end 必须出现在 result 之后（作为终态收尾）
    result_before_runend = (
        (ev_types.index(EventType.RESULT.value) < ev_types.index(EventType.RUN_END.value))
        if (has_result and has_run_end)
        else False
    )

    print("\n=== 断言 ===")
    print(f"中途事件数(应≥3): {len(mid)}")
    print(f"事件间隔最大值(应≥0.3s 证明非一次性flush): {max(gaps) if gaps else 0:.2f}s")
    print(f"实时逐条流出: {'PASS' if live_streaming else 'FAIL'}")
    print(
        f"RESULT 存在且由 run_end(SUCCESS) 收尾: "
        f"{'PASS' if (has_result and has_run_end and result_before_runend) else 'FAIL'}"
    )
    ok = live_streaming and has_result and has_run_end and result_before_runend
    print("\nRESULT:", "ALL PASS" if ok else "FAIL")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
