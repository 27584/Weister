"""回归测试：工具调用事件必须携带完整入参与返回值。

前端的「工具调用折叠面板」直接读这些字段展示详情：
    tool_call   → payload.input
    tool_result → payload.result（失败时读 payload.error）

字段一旦缺失，面板就会退化成一行没有内容的标题。本测试锁住这份契约，
同时覆盖失败分支 —— 失败时 result 恒为 None，原因只在 error 里。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.agents import bootstrap as bootstrap_agents
from app.agents.base import AgentRunner
from app.core.registry import registry
from app.llm import Delta
from tests._harness import isolate_data_dir

isolate_data_dir()
bootstrap_agents()


class FakeClient:
    """先请求一个工具，工具结果回灌后再给最终结论。"""

    def __init__(self, tool: str, args: dict, final: str = "结论如下。") -> None:
        self.tool = tool
        self.args = args
        self.final = final
        self.round = 0

    def stream_messages(self, messages, **kwargs):
        has_tool_result = any(isinstance(m, dict) and m.get("role") == "tool" for m in messages)
        if not has_tool_result:
            yield Delta(
                tool_call={
                    "index": 0,
                    "id": "call_1",
                    "name": self.tool,
                    "arguments": __import__("json").dumps(self.args, ensure_ascii=False),
                }
            )
            return
        yield Delta(content=self.final)


def capture(tool: str, args: dict) -> list[dict]:
    """跑一次 specialist，返回它 emit 出的全部事件。"""
    # 挑一位确实持有该工具的专家
    spec = next(a for a in registry.agents.values() if tool in (a.tools or []))
    events: list[dict] = []

    def emit(type_, **kw) -> None:
        events.append({"type": getattr(type_, "value", type_), **kw})

    AgentRunner(spec).run("请调用工具", FakeClient(tool, args), emit, "test")
    return events


def check(label: str, ok: bool, detail: str = "") -> bool:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
    return ok


def main() -> None:
    ok = True

    print("=== 1. 成功的工具调用：入参与返回值都要完整 ===")
    # current_datetime 纯离线、无副作用，返回值稳定
    events = capture("current_datetime", {})
    calls = [e for e in events if e["type"] == "tool_call"]
    results = [e for e in events if e["type"] == "tool_result"]

    ok &= check("产生了 tool_call 事件", len(calls) == 1, f"实际 {len(calls)}")
    ok &= check("产生了 tool_result 事件", len(results) == 1, f"实际 {len(results)}")

    if calls:
        p = calls[0].get("payload") or {}
        ok &= check("tool_call 含 tool 名", bool(p.get("tool")), repr(p.get("tool")))
        # 无入参的工具（如 current_datetime）input 是 {}，键存在即可
        ok &= check("tool_call 含 input 键", "input" in p, f"keys={list(p)}")

    if results:
        p = results[0].get("payload") or {}
        ok &= check("tool_result 含 tool 名", bool(p.get("tool")), repr(p.get("tool")))
        ok &= check("tool_result 含 ok 标记", p.get("ok") is True)
        ok &= check(
            "tool_result 含 result", p.get("result") is not None, f"result={p.get('result')!r}"
        )

    print("\n=== 2. 带参数的调用：入参要原样带回 ===")
    # python_calc 是纯计算，离线可用；参数故意用非平凡值以便核对
    events = capture("python_calc", {"code": "2 ** 10"})
    calls = [e for e in events if e["type"] == "tool_call"]
    if calls:
        got = (calls[0].get("payload") or {}).get("input")
        ok &= check("入参完整回传", got == {"code": "2 ** 10"}, repr(got))
    else:
        ok &= check("入参完整回传", False, "未产生 tool_call")

    results = [e for e in events if e["type"] == "tool_result"]
    if results:
        p = results[0].get("payload") or {}
        val = (p.get("result") or {}).get("result") if isinstance(p.get("result"), dict) else None
        ok &= check("返回值带上计算结果", str(val) == "1024", f"result={p.get('result')!r}")

    print("\n=== 3. 失败分支：原因必须落在 error 字段 ===")
    # 受限执行环境会拒绝 import，用合法工具 + 被拦截的参数触发失败
    events = capture("python_calc", {"code": "import os"})
    results = [e for e in events if e["type"] == "tool_result"]
    if results:
        p = results[0].get("payload") or {}
        ok &= check("失败时 ok 为 False", p.get("ok") is False, f"ok={p.get('ok')}")
        ok &= check("失败时 error 有内容", bool(p.get("error")), repr(p.get("error")))
        ok &= check("失败时 result 为 None", p.get("result") is None, f"result={p.get('result')!r}")
    else:
        ok &= check("失败分支产生了 tool_result", False, "未产生事件")

    print("\nRESULT: " + ("ALL PASS（工具事件携带完整详情）" if ok else "FAILED"))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
