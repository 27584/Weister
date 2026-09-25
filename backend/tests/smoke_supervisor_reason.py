"""回归测试：主管决策依据可见 + 历史预算随模型窗口变化。

两项都是主人直接指出的痛点：
    1. 「黑箱」——只看见主管派了谁，看不见它为什么这么派。
       决策 JSON 里要求带 reason，后端抽出来单独 emit 一条日志。
    2. 「1M 窗口的模型你只给 20K」——历史预算原先硬编码 20000 字符，
       与模型能力完全脱钩。改为从 context_limit_for_model() 反推。
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app.api  # noqa: F401  —— 触发 bootstrap_agents()
from app import chat_supervisor as cs
from app import runctx
from app.llm import Delta
from tests._harness import isolate_data_dir

isolate_data_dir()

FINAL = "分析完成。"


class ScriptedClient:
    """主管按脚本吐决策；专家执行直接回一段正文。"""

    def __init__(self, decisions: list[dict]) -> None:
        self.decisions = decisions
        self.calls = 0

    def stream_messages(self, messages, **kwargs):
        if "tools" in kwargs:
            yield Delta(content="专家结论（测试替身）")
            return
        d = self.decisions[min(self.calls, len(self.decisions) - 1)]
        self.calls += 1
        yield Delta(content=json.dumps(d, ensure_ascii=False))


def run(decisions: list[dict]) -> list[dict]:
    cs.build_chat_client = lambda state, emit: ScriptedClient(decisions)
    events: list[dict] = []

    def emit(t, **kw) -> None:
        events.append({"type": getattr(t, "value", t), **kw})

    runctx.bind("reason-test", emit)
    cs.run_chat(
        {
            "run_id": "reason-test",
            "messages": [{"role": "user", "content": "分析这家公司"}],
            "model": "deepseek-chat",
            "api_key": "x",
        },
        [],
        emit,
    )
    return events


def check(label: str, ok: bool, detail: str = "") -> bool:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
    return ok


def test_reason_emitted() -> bool:
    print("=== 1. 决策带 reason 时必须单独 emit 一条日志 ===")
    ok = True
    reason = "用户问的是盈利质量，需要财务口径核算"
    events = run(
        [
            {
                "action": "delegate",
                "reason": reason,
                "agent": "financial_analyst",
                "task": "分析盈利质量",
            },
            {"action": "reply", "reason": "专家结论已完整回答", "content": FINAL},
        ]
    )

    reason_logs = [
        e for e in events if e["type"] == "log" and "决策依据" in (e.get("message") or "")
    ]
    ok &= check("产生了决策依据日志", len(reason_logs) >= 1, f"实际 {len(reason_logs)} 条")
    if reason_logs:
        ok &= check("日志里含原始依据", reason in reason_logs[0]["message"])
        ok &= check(
            "payload 带 reason 字段",
            reason_logs[0].get("payload", {}).get("reason") == reason,
            "前端靠这个字段决定要不要高亮",
        )
        ok &= check(
            "payload 带 action", reason_logs[0].get("payload", {}).get("action") == "delegate"
        )

    return ok


def test_reason_optional() -> bool:
    print("\n=== 2. 模型没给 reason 时不能凭空造一条 ===")
    ok = True
    events = run(
        [
            {"action": "delegate", "agent": "financial_analyst", "task": "分析盈利质量"},
            {"action": "reply", "content": FINAL},
        ]
    )
    reason_logs = [
        e for e in events if e["type"] == "log" and "决策依据" in (e.get("message") or "")
    ]
    ok &= check("无 reason 时不产生依据日志", len(reason_logs) == 0, f"实际 {len(reason_logs)} 条")
    return ok


def test_history_budget_scales() -> bool:
    print("\n=== 3. 历史预算随模型窗口变化，不再是死数 ===")
    ok = True
    from app.chat_supervisor import (
        MIN_HISTORY_TOKENS,
        history_token_budget,
    )

    big = history_token_budget({"model": "gpt-4.1"})  # 1M 窗口
    mid = history_token_budget({"model": "deepseek-chat"})  # 64K
    small = history_token_budget({"model": "gpt-4"})  # 8K

    ok &= check("大窗模型明显大于中窗", big > mid * 5, f"gpt-4.1={big} vs deepseek={mid}")
    ok &= check("1M 窗口拿到 50 万以上预算", big > 500_000, f"实际 {big}")
    ok &= check(
        "小窗模型不低于下限", small >= MIN_HISTORY_TOKENS, f"gpt-4={small} >= {MIN_HISTORY_TOKENS}"
    )
    ok &= check("未知模型也有合理预算", history_token_budget({"model": ""}) >= MIN_HISTORY_TOKENS)

    return ok


def main() -> None:
    ok = True
    ok &= test_reason_emitted()
    ok &= test_reason_optional()
    ok &= test_history_budget_scales()
    print("\nRESULT: " + ("ALL PASS（决策依据可见 + 预算随窗口）" if ok else "FAILED"))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
