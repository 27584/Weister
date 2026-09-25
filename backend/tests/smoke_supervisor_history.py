"""回归测试：主管必须能看到专家结论（历史不能被冻结）。

背景（2026-09-14 真实故障）：
    run_chat 用 `list(state["messages"])` 拷贝出 messages，专家结论 append 到这份
    拷贝；但 _build_supervisor_messages 读的是 state["messages"] —— 那份从头到尾
    没变过。于是主管每一轮看到的历史都一模一样，看不到刚跑完的专家结论，
    反复派同一个人（日志：「主管重复调度 financial_analyst」），
    最终触发无进展收尾，用户拿到「对话未能自然结束」的提示。

修复：_build_supervisor_messages / _run_supervisor_iteration 改为显式接收
run_chat 里实时累积的 messages，不再从 state 取快照。

本测试锁住两件事：
    1. 第二轮主管收到的 prompt 里，必须包含第一位专家的结论文本
    2. 同一专家被重复派单时，必须回灌一条引导指令（internal），
       让主管知道可以直接 reply 或换人
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app.api  # noqa: F401  —— 触发 bootstrap_agents()
from app import chat_supervisor as cs
from app import runctx
from app.llm import Delta

SPECIALIST_OUTPUT = "贵州茅台 2025 年毛利率 91.3%，同比提升 0.4 个百分点。"
FINAL = "分析完成，结论如下。"

# 记录主管每次决策时看到的完整 prompt
supervisor_prompts: list[str] = []


class RecordingClient:
    """主管决策时记录 prompt；专家执行时返回固定结论。"""

    def __init__(self, decisions: list[dict]) -> None:
        self.decisions = decisions
        self.calls = 0

    def stream_messages(self, messages, **kwargs):
        if "tools" in kwargs:
            yield Delta(content=SPECIALIST_OUTPUT)
            return
        # 主管调用：把整份 prompt 存下来供断言
        supervisor_prompts.append(json.dumps(messages, ensure_ascii=False))
        d = self.decisions[min(self.calls, len(self.decisions) - 1)]
        self.calls += 1
        yield Delta(content=json.dumps(d, ensure_ascii=False))


def run(decisions: list[dict]) -> dict:
    supervisor_prompts.clear()
    cs.build_chat_client = lambda state, emit: RecordingClient(decisions)
    events: list[dict] = []

    def emit(t, **kw) -> None:
        events.append({"type": getattr(t, "value", t), **kw})

    runctx.bind("history-test", emit)

    return cs.run_chat(
        {
            "run_id": "history-test",
            "messages": [{"role": "user", "content": "分析贵州茅台的盈利质量"}],
            "model": "fake",
            "api_key": "x",
        },
        [],
        emit,
    )


def check(label: str, ok: bool, detail: str = "") -> bool:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
    return ok


def test_specialist_result_reaches_supervisor() -> bool:
    print("=== 1. 专家结论必须出现在主管下一轮的 prompt 里 ===")
    ok = True

    run(
        [
            {"action": "delegate", "agent": "financial_analyst", "task": "分析盈利质量"},
            {"action": "reply", "content": FINAL},
        ]
    )

    ok &= check(
        "主管至少决策 2 次", len(supervisor_prompts) >= 2, f"实际 {len(supervisor_prompts)} 次"
    )

    second_prompt = supervisor_prompts[1] if len(supervisor_prompts) > 1 else ""
    ok &= check(
        "第二轮 prompt 含专家结论正文",
        SPECIALIST_OUTPUT in second_prompt,
        "缺失则主管看不到已产出的结论，必然重复派单",
    )

    # 反面：第一轮还没跑专家，不该有结论
    first_prompt = supervisor_prompts[0] if supervisor_prompts else ""
    ok &= check("第一轮 prompt 不含专家结论（尚未产出）", SPECIALIST_OUTPUT not in first_prompt)

    # 两轮 prompt 必须不同 —— 若相同说明历史被冻结
    ok &= check("两轮 prompt 内容不同（历史未被冻结）", first_prompt != second_prompt)

    return ok


def test_repeat_delegate_injects_guidance() -> bool:
    print("\n=== 2. 重复派单必须回灌引导指令 ===")
    ok = True

    result = run(
        [
            {"action": "delegate", "agent": "financial_analyst", "task": "分析盈利质量"},
            {"action": "delegate", "agent": "financial_analyst", "task": "再分析一次"},
            {"action": "reply", "content": FINAL},
        ]
    )

    # 引导指令以 internal 标记进入 messages，不会显示给用户
    internals = [m for m in result["messages"] if m.get("internal")]
    ok &= check("产生了 internal 引导消息", len(internals) >= 1, f"实际 {len(internals)} 条")
    if internals:
        body = internals[0].get("content", "")
        ok &= check("引导里点名了已用过的专家", "财务分析师" in body)
        ok &= check("引导给出了 reply / 换人两个出路", "reply" in body and "尚未用过" in body)

    # 引导之后主管能看到它
    third_prompt = supervisor_prompts[2] if len(supervisor_prompts) > 2 else ""
    ok &= check(
        "下一轮 prompt 含引导指令", "不要再调度" in third_prompt or "尚未用过" in third_prompt
    )

    return ok


def test_isolation() -> bool:
    print("\n=== 3. 数据目录隔离 ===")
    from tests._harness import isolate_data_dir

    isolate_data_dir()
    print("  [PASS] 落盘已重定向到临时目录")
    return True


def main() -> None:
    ok = True
    ok &= test_specialist_result_reaches_supervisor()
    ok &= test_repeat_delegate_injects_guidance()
    ok &= test_isolation()
    print("\nRESULT: " + ("ALL PASS（主管历史未被冻结）" if ok else "FAILED"))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
