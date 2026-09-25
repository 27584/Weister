"""回归测试：流式碎片落盘前必须合并。

落盘数据显示（对话 35ccc846cdb6）：thinking 内容仅 25092 字节，落盘却占 853784 字节，
单条记录外壳约 177 字节而内容平均 5.4 字节 —— 97.1% 是 JSON 外壳。
逐字吐出的 thinking / token 各自占一条 JSONL，把事件文件撑到 1.3MB，
而同一对话的 messages.jsonl 只有 16.8KB。

本测试锁住 _compact_stream_events 的四条性质：
    1. 体积显著下降，且内容一个字都不能少
    2. 换了 agent 的连续流不能合并（否则归属错乱）
    3. 不同类型不能合并
    4. 非流式事件原样保留
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.api import _compact_stream_events


def make_event(seq: int, etype: str, msg: str, agent: str) -> dict:
    """按后端真实落盘形态构造一条事件。"""
    return {
        "type": etype,
        "status": "running",
        "message": msg,
        "payload": {"agent": agent},
        "node": "supervisor",
        "seq": seq,
        "run_id": "compact-test",
    }


def check(label: str, ok: bool, detail: str = "") -> bool:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
    return ok


def main() -> None:
    ok = True

    print("=== 1. 体积与内容完整性 ===")
    # 600 条 thinking 碎片，模拟一次完整的思考过程
    pieces = ["我", "先", "核", "对", "现", "金", "流", "与", "毛", "利", "率"]
    raw = [
        make_event(i, "thinking", pieces[i % len(pieces)], "financial_analyst") for i in range(600)
    ]
    compacted = _compact_stream_events(raw)

    raw_bytes = sum(len(json.dumps(e, ensure_ascii=False)) for e in raw)
    new_bytes = sum(len(json.dumps(e, ensure_ascii=False)) for e in compacted)
    ratio = new_bytes / raw_bytes

    ok &= check(
        "碎片被合并", len(compacted) < len(raw) / 10, f"{len(raw)} 条 → {len(compacted)} 条"
    )
    ok &= check(
        "体积下降超过 90%", ratio < 0.10, f"{raw_bytes}B → {new_bytes}B（剩 {ratio * 100:.1f}%）"
    )
    ok &= check(
        "内容一个字不丢",
        "".join(e["message"] for e in compacted) == "".join(e["message"] for e in raw),
    )

    print("\n=== 2. 换 agent 的连续流不能合并 ===")
    raw = [
        make_event(1, "thinking", "甲的想法", "financial_analyst"),
        make_event(2, "thinking", "乙的想法", "valuation_expert"),
    ]
    compacted = _compact_stream_events(raw)
    ok &= check("不同 agent 保持两条", len(compacted) == 2, f"实际 {len(compacted)} 条")

    print("\n=== 3. 不同类型不能合并 ===")
    raw = [
        make_event(1, "thinking", "想一想", "financial_analyst"),
        make_event(2, "token", "说出口", "financial_analyst"),
    ]
    compacted = _compact_stream_events(raw)
    ok &= check("thinking 与 token 不合并", len(compacted) == 2)

    print("\n=== 4. 非流式事件原样保留 ===")
    raw = [
        make_event(1, "log", "第 1 轮调度", "coordinator"),
        make_event(2, "log", "第 2 轮调度", "coordinator"),
        make_event(3, "agent_end", "完成", "financial_analyst"),
    ]
    compacted = _compact_stream_events(raw)
    ok &= check("log 不被合并", len(compacted) == 3)
    ok &= check(
        "内容不变", [e["message"] for e in compacted] == ["第 1 轮调度", "第 2 轮调度", "完成"]
    )

    print("\n=== 5. 合并后仍是合法事件（字段齐全）===")
    one = _compact_stream_events(
        [make_event(1, "thinking", "A", "x"), make_event(2, "thinking", "B", "x")]
    )[0]
    ok &= check(
        "保留 type / payload / seq",
        one.get("type") == "thinking"
        and (one.get("payload") or {}).get("agent") == "x"
        and one.get("seq") == 1,
        json.dumps(one, ensure_ascii=False)[:120],
    )

    print("\nRESULT: " + ("ALL PASS（流式碎片已合并）" if ok else "FAILED"))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
