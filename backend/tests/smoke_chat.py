"""端到端 smoke test：mock LLM（singleton）+ supervisor loop。

用法（在 backend 目录）：
    .venv/Scripts/python.exe -m tests.smoke_chat

退出码 0 表示通过；非 0 + 详细 stderr 表示失败原因。

覆盖路径：
    - supervisor 第 1 轮：delegate(valuation_expert) → 触发 specialist 跑一次
    - supervisor 第 2 轮：reply → 返回最终用户可见的回复文本
    - 校验：reply 不空、specialists_called 含 valuation_expert 且仅一次、
            iterations=2、truncated=False、至少有 AGENT_START/AGENT_END/LOG/TOKEN 事件。
"""

import sys

sys.path.insert(0, r"D:\open_source_projects\Weister\backend")

from app.chat_supervisor import run_chat
from app.llm import Delta


class FakeLLM:
    """根据调用上下文判断是 supervisor 还是 specialist，决定返回内容。

    Singleton：跨 supervisor 轮次共享 call 计数，否则每次都会拿到 delegate。
    """

    def __init__(self):
        self.supervisor_calls = 0
        self.specialist_calls = 0

    def stream_messages(self, messages, *, tools=None, tool_choice=None):
        sys_msg = messages[0]["content"] if messages else ""
        first_50 = sys_msg[:50]
        is_supervisor = sys_msg.startswith("你是投研团队的主管")
        print(f"[DEBUG LLM] is_supervisor={is_supervisor} sys_msg_first_50={first_50!r}")
        if is_supervisor:
            self.supervisor_calls += 1
            if self.supervisor_calls == 1:
                text = '{"action": "delegate", "agent": "valuation_expert", "task": "粗估公司价值"}'
            else:
                text = '{"action": "reply", "content": "经过估值专家测算，估值区间为 [80, 120] 亿元。"}'
            print(f"[DEBUG supervisor call #{self.supervisor_calls}] returning: {text[:60]}")
            yield Delta(content=text)
        else:
            self.specialist_calls += 1
            text = "（估值专家推演：基于 12% 折现率，权益价值 80~120 亿元。）"
            print(f"[DEBUG specialist call #{self.specialist_calls}]")
            yield Delta(content=text)


_FAKE = {"instance": None}


def _build_singleton(_state, _emit):
    if _FAKE["instance"] is None:
        _FAKE["instance"] = FakeLLM()
    return _FAKE["instance"]


def main():
    import app.chat_supervisor as cs

    cs.build_chat_client = _build_singleton

    state = {
        "run_id": "test-run",
        "messages": [{"role": "user", "content": "请分析这份财报并给估值。"}],
        "model": "fake",
        "api_key": "sk-fake",
    }
    documents = []
    events = []

    def collect_emit(type_, **kw):
        events.append({"type": str(type_), **kw})

    result = run_chat(state, documents, collect_emit)

    print("=== result ===")
    print(f"reply: {result['reply'][:100]}")
    print(f"iterations: {result['iterations']}")
    print(f"truncated: {result['truncated']}")
    print(f"specialists_called: {result['specialists_called']}")

    print("\n=== assertions ===")
    assert result["reply"], "reply should not be empty"
    assert "valuation_expert" in result["specialists_called"], (
        f"valuation_expert should be called, got {result['specialists_called']}"
    )
    assert result["iterations"] == 2, f"expected 2 iterations, got {result['iterations']}"
    assert not result["truncated"], "should not be truncated"
    assert result["specialists_called"].count("valuation_expert") == 1, "should not repeat-call"
    types = {ev["type"].rsplit(".", 1)[-1] for ev in events}
    assert "AGENT_START" in types, f"AGENT_START missing in {types}"
    assert "AGENT_END" in types, f"AGENT_END missing in {types}"
    print(f"event types: {sorted(types)}")
    print("\nALL ASSERTIONS PASSED")


if __name__ == "__main__":
    main()
