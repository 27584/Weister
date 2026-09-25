"""回归测试：终止条件必须是「有没有进展」，而不是数轮数。

固定轮数上限会在任务做到一半时把结论截断；改成进展驱动后：
    - 连续调度多位专家（哪怕超过原先的 6 轮）也必须跑完，直到主管给出回复
    - 重复派单 / 非法动作 / 重复提问这类「没有新信息」的轮次累计到阈值才收尾
    - 用户作答算进展，可以再次提问（不再受次数限制）
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app.api  # noqa: F401  —— 触发 bootstrap_agents()
from app import chat_supervisor as cs
from app import runctx
from app.llm import Delta

FINAL = "分析完成，结论如下。"


class ScriptedClient:
    """按脚本吐主管决策。

    同一个 client 也会被 specialist 复用（AgentRunner 调 stream_messages 时带
    tools 参数，主管调用不带）。据此区分：带 tools 的是专家执行，直接回一段正文；
    不带的是主管决策，按脚本顺序发。
    """

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


def run(decisions: list[dict], answer: bool = False) -> dict:
    cs.build_chat_client = lambda state, emit: ScriptedClient(decisions)
    events: list[dict] = []

    def emit(t, **kw) -> None:
        events.append({"type": getattr(t, "value", t), **kw})

    # 交互桥靠上下文变量拿事件出口，不绑定则提问会立刻失败
    runctx.bind("progress-test", emit)

    if answer:
        import threading
        import time

        from app import interaction

        def auto() -> None:
            answered: set[str] = set()
            for _ in range(400):
                time.sleep(0.02)
                for e in events:
                    if e.get("type") != "ask_user":
                        continue
                    qid = (e.get("payload") or {}).get("qid", "")
                    if not qid or qid in answered:
                        continue
                    answered.add(qid)
                    interaction.answer(
                        qid,
                        {
                            "answers": [{"selected": ["合并"], "other": ""}],
                        },
                    )

        threading.Thread(target=auto, daemon=True).start()

    return cs.run_chat(
        {
            "run_id": "progress-test",
            "messages": [{"role": "user", "content": "分析这家公司"}],
            "model": "fake",
            "api_key": "x",
        },
        [],
        emit,
    )


def delegate(key: str) -> dict:
    return {"action": "delegate", "agent": key, "task": f"{key} 的任务"}


def check(label: str, ok: bool, detail: str = "") -> bool:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
    return ok


def test_long_chain() -> bool:
    print("=== 1. 长链路：超过原先 6 轮也必须跑完 ===")
    # 7 位专家 + 最终回复 = 8 轮，轮数预算式的实现会在中途被截断
    keys = [
        "financial_analyst",
        "valuation_expert",
        "risk_reviewer",
        "devils_advocate",
        "market_analyst",
        "research_assistant",
        "report_writer",
    ]
    r = run([*map(delegate, keys), {"action": "reply", "content": FINAL}])
    ok = check("最终回复未被截断", r["reply"] == FINAL, r["reply"][:40])
    ok &= check(
        "全部 7 位专家都被调度",
        len(r["specialists_called"]) == 7,
        str(len(r["specialists_called"])),
    )
    ok &= check("truncated 为 False", r["truncated"] is False)
    ok &= check("轮数 > 6", r["iterations"] > 6, str(r["iterations"]))
    return ok


def test_idle_stop() -> bool:
    print("\n=== 2. 停滞才收尾：连续重复派单不会无限跑 ===")
    r = run(
        [
            delegate("financial_analyst"),
            delegate("financial_analyst"),
            delegate("financial_analyst"),
            delegate("financial_analyst"),
        ]
    )
    ok = check("已收尾（未无限循环）", r["truncated"] is True)
    ok &= check(
        "专家只被调度一次",
        r["specialists_called"] == ["financial_analyst"],
        str(r["specialists_called"]),
    )
    ok &= check("回复复用了专家结论", bool(r["reply"]) and r["reply"] != FINAL)
    ok &= check("轮数受控", r["iterations"] <= cs.MAX_IDLE_ROUNDS + 2, str(r["iterations"]))
    return ok


def test_unknown_action() -> bool:
    print("\n=== 3. 无效动作累计到阈值后收尾 ===")
    r = run([{"action": "dance"}] * 10)
    ok = check("未知动作会收尾", r["truncated"] is True)
    ok &= check("轮数不超过阈值+1", r["iterations"] <= cs.MAX_IDLE_ROUNDS + 1, str(r["iterations"]))
    return ok


def test_progress_resets() -> bool:
    print("\n=== 4. 有进展就重置：停滞与有效动作交替时不应收尾 ===")
    r = run(
        [
            {"action": "dance"},  # 无进展
            delegate("financial_analyst"),  # 有进展，重置
            {"action": "dance"},  # 无进展
            delegate("valuation_expert"),  # 有进展，重置
            {"action": "dance"},  # 无进展
            {"action": "reply", "content": FINAL},  # 正常结束
        ]
    )
    ok = check("未被停滞误伤", r["reply"] == FINAL, r["reply"][:40])
    ok &= check(
        "两位专家都调度成功",
        r["specialists_called"] == ["financial_analyst", "valuation_expert"],
        str(r["specialists_called"]),
    )
    return ok


def test_repeat_ask() -> bool:
    print("\n=== 5. 提问不受次数限制，但同一批问题不重复问 ===")
    q = [{"question": "用哪个口径？", "options": ["合并", "母公司"]}]
    other = [{"question": "时间范围？", "options": ["近三年", "近五年"]}]
    r = run(
        [
            {"action": "ask", "questions": q},
            {"action": "ask", "questions": other},  # 不同问题 → 允许再问
            {"action": "ask", "questions": q},  # 与第一次相同 → 跳过
            {"action": "reply", "content": FINAL},
        ],
        answer=True,
    )
    ok = check("最终正常回复", r["reply"] == FINAL, r["reply"][:40])
    ok &= check("未被提问次数硬限制拦下", r["iterations"] >= 4, str(r["iterations"]))
    return ok


def main() -> None:
    ok = True
    ok &= test_long_chain()
    ok &= test_idle_stop()
    ok &= test_unknown_action()
    ok &= test_progress_resets()
    ok &= test_repeat_ask()
    print("\nRESULT:", "ALL PASS（进展驱动终止）" if ok else "FAIL")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
