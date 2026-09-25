"""回归测试：人机交互桥（ask_user / set_conversation_title）。

覆盖三条链路：
    1. interaction 桥本身：等待 → 作答 → 唤醒；超时与中断的收尾
    2. 工具层：问题规范化（补「其他」与补充说明题）、作答摘要、
       标题写入与「默认不覆盖」语义
    3. supervisor 的 ask 动作：假 LLM 先吐 ask 再吐 reply，
       验证事件推送、答案回灌与最终回复

网络无关，全本地完成。
"""

import json
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from _harness import isolate_data_dir

import app.api  # noqa: F401  —— 触发 bootstrap_agents()
from app import chat_supervisor, interaction, runctx
from app.core.registry import registry
from app.events import EventType
from app.llm import Delta
from app.tools.interact import build_ask_payload, set_conversation_title

OTHER_LABEL = "其他（自行输入）"


def check(label: str, ok: bool, detail: str = "") -> bool:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
    return ok


def test_bridge() -> bool:
    print("=== 1. interaction 桥：等待 / 作答 / 超时 / 中断 ===")
    captured: list[dict] = []

    # 上下文必须在等待线程内绑定：ContextVar 不跨线程传播。
    # 生产环境同理 —— runctx.bind 在 worker 线程入口执行，
    # 工具调用发生在同一调用栈内，因此读得到。
    def bind() -> None:
        runctx.bind(
            "run-bridge",
            lambda type_, **kw: captured.append(
                {"type": type_, **kw},
            ),
        )

    result_box: list[dict] = []

    def waiter() -> None:
        bind()
        result_box.append(interaction.ask({"title": "确认口径", "questions": []}))

    t = threading.Thread(target=waiter, daemon=True)
    t.start()
    time.sleep(0.3)

    ok = True
    ok &= check(
        "提问已推送 ask_user 事件", len(captured) == 1 and captured[0]["type"] == EventType.ASK_USER
    )
    qid = (captured[0]["payload"] or {}).get("qid", "") if captured else ""
    ok &= check("事件带 qid", bool(qid), qid)
    ok &= check("等待期间注册表中存在待答问题", interaction.pending_count() == 1)

    answers = [{"selected": ["合并报表"], "other": ""}]
    ok &= check("answer() 命中等待中的提问", interaction.answer(qid, {"answers": answers}))

    t.join(timeout=5)
    ok &= check("等待线程被唤醒", not t.is_alive())
    got = result_box[0] if result_box else {}
    ok &= check("工具收到 answered=True", got.get("answered") is True)
    ok &= check("答案原样回传", got.get("answers") == answers)
    ok &= check("唤醒后注册表清空", interaction.pending_count() == 0)

    # 超时路径：无人作答时应自行返回，不能把线程挂死
    box2: list[dict] = []

    def waiter2() -> None:
        bind()
        box2.append(interaction.ask({"title": "x", "questions": []}, timeout=0.4))

    t2 = threading.Thread(target=waiter2, daemon=True)
    t2.start()
    t2.join(timeout=5)
    ok &= check("超时后线程自行结束", not t2.is_alive())
    ok &= check(
        "超时返回 answered=False",
        bool(box2) and box2[0].get("answered") is False,
        str(box2[0].get("reason")) if box2 else "",
    )

    # 中断路径：客户端断开时应唤醒全部等待
    box3: list[dict] = []

    def waiter3() -> None:
        bind()
        box3.append(interaction.ask({"title": "x", "questions": []}, timeout=30))

    t3 = threading.Thread(target=waiter3, daemon=True)
    t3.start()
    time.sleep(0.3)
    woke = interaction.cancel_run("run-bridge")
    t3.join(timeout=5)
    ok &= check("cancel_run 唤醒等待", woke == 1 and not t3.is_alive())
    ok &= check("中断后 answered=False", bool(box3) and box3[0].get("answered") is False)
    ok &= check(
        "无效 qid 的 answer() 返回 False", interaction.answer("nope", {"answers": []}) is False
    )
    return ok


def test_payload() -> bool:
    print("\n=== 2. 问题规范化与作答摘要 ===")
    ok = True
    payload = build_ask_payload(
        [
            {
                "question": "用哪个口径？",
                "header": "口径",
                "options": [
                    {"label": "合并", "description": "含子公司"},
                    {"label": "母公司", "description": "仅本部"},
                ],
            },
            {
                "question": "覆盖哪些方面？",
                "header": "范围",
                "multiSelect": True,
                "options": ["盈利质量", "现金流"],
            },
        ],
        "确认分析口径",
    )

    questions = payload["questions"]
    ok &= check(
        "末尾自动追加补充说明题", len(questions) == 3 and questions[-1]["header"] == "补充说明"
    )
    ok &= check(
        "每个问题都带「其他」选项",
        all(any(o["label"] == OTHER_LABEL for o in q["options"]) for q in questions),
    )
    ok &= check(
        "字符串选项被规范化", questions[1]["options"][0] == {"label": "盈利质量", "description": ""}
    )
    ok &= check("multiSelect 保留", questions[1]["multiSelect"] is True)

    # 参数错误应当明确报错，而不是让模型以为提问已发出
    for bad, label in [
        ("[]", "空数组"),
        ("not json", "非法 JSON"),
        ('[{"question":"x"}]', "缺选项"),
    ]:
        try:
            build_ask_payload(bad)
            ok &= check(f"{label} 应报错", False)
        except ValueError:
            ok &= check(f"{label} 明确报错", True)

    from app.tools.interact import summarize_answers

    text = summarize_answers(
        payload,
        [
            {"selected": ["合并"], "other": ""},
            {"selected": ["盈利质量", OTHER_LABEL], "other": "重点看应收账款"},
            {"selected": ["没有，按以上选择继续"], "other": ""},
        ],
    )
    ok &= check("摘要包含用户选择", "合并" in text and "盈利质量" in text)
    ok &= check(
        "自填内容覆盖「其他」标签", "其他：重点看应收账款" in text and text.count(OTHER_LABEL) == 0
    )
    return ok


def test_title() -> bool:
    print("\n=== 3. set_conversation_title：写入与默认不覆盖 ===")
    from app.config import settings

    emitted: list[dict] = []
    runctx.bind(
        "run-title-test",
        lambda type_, **kw: emitted.append(
            {"type": type_, **kw},
        ),
    )

    ok = True
    first = set_conversation_title("茅台 2025H1 盈利质量分析")
    ok &= check(
        "首次设置成功", first["updated"] is True and first["title"].endswith("盈利质量分析")
    )
    ok &= check("推送 title 事件", any(e["type"] == EventType.TITLE for e in emitted))

    second = set_conversation_title("另一个标题")
    ok &= check(
        "默认不覆盖已有标题", second["updated"] is False and second["title"] == first["title"]
    )
    ok &= check(
        "不覆盖时不重复推送事件", len([e for e in emitted if e["type"] == EventType.TITLE]) == 1
    )

    third = set_conversation_title("改后的标题", overwrite="true")
    ok &= check(
        "显式 overwrite 可修改", third["updated"] is True and third["title"] == "改后的标题"
    )

    try:
        set_conversation_title("   ")
        ok &= check("空标题应报错", False)
    except ValueError:
        ok &= check("空标题明确报错", True)

    # 落盘路径确实存在，否则 /api/conversations 读不到
    path = settings.runs_dir_path / "run-title-test" / "title.txt"
    ok &= check("标题已落盘", path.exists() and path.read_text(encoding="utf-8") == "改后的标题")
    return ok


def test_supervisor_ask() -> bool:
    print("\n=== 4. supervisor 的 ask 动作：提问 → 作答 → 继续 ===")
    ask_payload = {
        "action": "ask",
        "title": "确认分析口径",
        "questions": [
            {
                "question": "用哪个口径？",
                "header": "口径",
                "options": [
                    {"label": "合并报表", "description": "含子公司"},
                    {"label": "母公司报表", "description": "仅本部"},
                ],
            },
        ],
    }
    scripted = [ask_payload, {"action": "reply", "content": "按合并口径完成分析。"}]

    class ScriptedClient:
        def __init__(self) -> None:
            self.calls = 0

        def stream_messages(self, messages, **kwargs):
            decision = scripted[min(self.calls, len(scripted) - 1)]
            self.calls += 1
            yield Delta(content=json.dumps(decision, ensure_ascii=False))

    client = ScriptedClient()
    chat_supervisor.build_chat_client = lambda state, emit: client

    events: list[dict] = []

    def emit(type_, *, status=None, message=None, payload=None, node_override=None):
        events.append({"type": type_, "message": message, "payload": payload or {}})

    runctx.bind("run-ask-test", emit)

    # 后台作答：模拟前端收到 ask_user 后提交答案
    def auto_answer() -> None:
        for _ in range(100):
            time.sleep(0.05)
            ask_events = [e for e in events if e["type"] == EventType.ASK_USER]
            if ask_events:
                qid = ask_events[0]["payload"]["qid"]
                interaction.answer(
                    qid,
                    {
                        "answers": [
                            {"selected": ["合并报表"], "other": ""},
                            {"selected": ["没有，按以上选择继续"], "other": ""},
                        ],
                    },
                )
                return

    threading.Thread(target=auto_answer, daemon=True).start()

    state = {
        "run_id": "run-ask-test",
        "messages": [{"role": "user", "content": "帮我分析这家公司"}],
        "model": "fake",
        "api_key": "x",
    }
    result = chat_supervisor.run_chat(state, [], emit)

    ok = True
    ask_events = [e for e in events if e["type"] == EventType.ASK_USER]
    ok &= check("推送了 ask_user 事件", len(ask_events) == 1)
    ok &= check("最终回复正确", result["reply"] == "按合并口径完成分析。", result["reply"])
    ok &= check("调度了 2 轮（提问 + 回复）", client.calls == 2, str(client.calls))
    ok &= check("未调度任何专家", result["specialists_called"] == [])
    msgs = result["messages"]
    ok &= check(
        "用户作答已回灌 messages",
        any(m.get("role") == "user" and "合并报表" in str(m.get("content", "")) for m in msgs),
    )
    return ok


def test_registry() -> bool:
    print("\n=== 5. 注册表：工具与专家挂载 ===")
    ok = True
    for name in ("ask_user", "set_conversation_title"):
        ok &= check(f"工具 {name} 已注册", registry.tool(name) is not None)

    missing = [
        a.key
        for a in registry.agents.values()
        if a.key != "coordinator" and "ask_user" not in a.tools
    ]
    ok &= check("全部专家都能向用户提问", not missing, ",".join(missing))
    return ok


def main() -> None:
    # 落盘目录重定向到临时目录：title.txt / messages 不能写进真实对话
    isolate_data_dir()
    ok = True
    ok &= test_bridge()
    ok &= test_payload()
    ok &= test_title()
    ok &= test_supervisor_ask()
    ok &= test_registry()
    print("\nRESULT:", "ALL PASS" if ok else "FAIL")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
