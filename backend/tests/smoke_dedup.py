"""验证「同一专家不会重复调度」。

mock 一个始终返回 delegate(valuation_expert) 的 supervisor。
期望：专家只跑 1 次；重复派单被计为无进展，累计到阈值后收尾并给出回复，
而不是耗尽迭代预算 —— 但也不再一刀切断：重复派单只是跳过，主管仍有机会改派。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import chat_supervisor as cs
from app.chat_supervisor import run_chat
from app.llm import Delta


class StubbornLLM:
    """supervisor 永远 delegate 同一个专家；specialist 正常给结论。"""

    def __init__(self):
        self.supervisor_calls = 0
        self.specialist_calls = 0

    def stream_messages(self, messages, *, tools=None, tool_choice=None):
        sys_msg = messages[0]["content"] if messages else ""
        if sys_msg.startswith("你是投研团队的主管"):
            self.supervisor_calls += 1
            text = (
                '{"action": "delegate", "agent": "valuation_expert",'
                f' "task": "再估一次 #{self.supervisor_calls}"}}'
            )
            yield Delta(content=text)
        else:
            self.specialist_calls += 1
            yield Delta(
                content=f"（估值专家第 {self.specialist_calls} 次输出：权益价值 80~120 亿元。）"
            )


_SINGLETON = {}


def _build(_state, _emit):
    if "llm" not in _SINGLETON:
        _SINGLETON["llm"] = StubbornLLM()
    return _SINGLETON["llm"]


def main():
    cs.build_chat_client = _build

    state = {
        "run_id": "dedup-test",
        "messages": [{"role": "user", "content": "帮我估个值"}],
        "model": "fake",
        "api_key": "sk-fake",
    }
    events = []

    def collect_emit(type_, **kw):
        events.append({"type": str(type_), "message": kw.get("message") or ""})

    result = run_chat(state, [], collect_emit)

    print("=== result ===")
    print("iterations        :", result["iterations"])
    print("specialists_called:", result["specialists_called"])
    print("reply head        :", result["reply"][:60])
    print("truncated         :", result["truncated"])

    print("\n=== 关键日志 ===")
    for e in events:
        if "重复调度" in e["message"] or "调度：" in e["message"] or "收尾" in e["message"]:
            print(" -", e["message"])

    print("\n=== assertions ===")
    called = result["specialists_called"]
    assert called.count("valuation_expert") == 1, (
        f"valuation_expert 只应被调用 1 次，实际 {called.count('valuation_expert')} 次: {called}"
    )
    # 1 次成功调度 + 连续无进展累计到阈值后收尾
    assert result["iterations"] <= cs.MAX_IDLE_ROUNDS + 2, (
        f"应在无进展累计到阈值后收尾，实际 {result['iterations']} 轮"
    )
    assert result["truncated"] is True, "无进展收尾时 truncated 应为 True"
    assert result["reply"], "收尾后仍应有回复内容"
    print("OK: 重复调度被拦住，专家只跑 1 次，且仍产出了回复")
    print("\nALL ASSERTIONS PASSED")


if __name__ == "__main__":
    main()
