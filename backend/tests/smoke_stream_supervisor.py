"""回归测试：supervisor 的事件必须实时 emit，不能攒到整轮结束再 flush。

用一个「逐条吐 delta 且每条之间 sleep」的假 LLM 客户端替换真模型，
调用 run_chat 并记录每个事件到达时间。若实现退回到「本地队列缓冲 + 结束才 drain」，
thinking/token 会在同一时刻集中到达，本测试即失败。
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app.api  # noqa: F401  —— 触发 bootstrap_agents()
from app import chat_supervisor
from app.events import EventType
from app.llm import Delta


class FakeClient:
    """reasoning 5 片 + content 逐字符，每片之间 sleep，模拟真实流式。"""

    def stream_messages(self, messages, **kwargs):
        for i in range(5):
            time.sleep(0.15)
            yield Delta(reasoning=f"推理片段{i} ")
        decision = json.dumps(
            {"action": "reply", "content": "这是最终回复。"},
            ensure_ascii=False,
        )
        for ch in decision:
            time.sleep(0.01)
            yield Delta(content=ch)


def main():
    chat_supervisor.build_chat_client = lambda state, emit: FakeClient()

    arrivals = []

    def emit(type_, *, status=None, message=None, payload=None, node_override=None):
        arrivals.append((time.monotonic(), type_, message or ""))

    state = {
        "run_id": "test-rt",
        "messages": [{"role": "user", "content": "你好"}],
        "model": "fake",
        "api_key": "x",
    }
    result = chat_supervisor.run_chat(state, [], emit)

    t0 = arrivals[0][0]
    print("=== 事件时间线 ===")
    for t, ty, m in arrivals:
        print(f"  +{t - t0:5.2f}s  {ty.value:<11} {m[:40]}")

    think = [t for t, ty, _ in arrivals if ty == EventType.THINKING]
    tok = [t for t, ty, _ in arrivals if ty == EventType.TOKEN]
    types = [ty for _, ty, _ in arrivals]

    think_spread = (think[-1] - think[0]) if len(think) > 1 else 0
    tok_spread = (tok[-1] - tok[0]) if len(tok) > 1 else 0

    print("\n=== 断言 ===")
    print(f"thinking 条数: {len(think)}，首末跨度 {think_spread:.2f}s（应 ≥0.4s）")
    print(f"token 条数: {len(tok)}，首末跨度 {tok_spread:.2f}s（应 ≥0.3s）")
    ok_spread = think_spread >= 0.4 and tok_spread >= 0.3
    # 顺序：AGENT_START → (thinking/token) → AGENT_END → LOG(最终回复)
    idx_start = types.index(EventType.AGENT_START)
    idx_end = types.index(EventType.AGENT_END)
    last_log = types[-1] == EventType.LOG
    ok_order = idx_start < idx_end and last_log and result["reply"] == "这是最终回复。"
    print(f"事件顺序正确（start<end，最后是 LOG）: {ok_order}")
    print(f"回复正确: {result['reply']!r}")
    ok = ok_spread and ok_order
    print("\nRESULT:", "ALL PASS（实时流式）" if ok else "FAIL")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
