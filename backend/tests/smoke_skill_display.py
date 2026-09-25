"""回归测试：/技能名 命令必须完整保留在聊天记录里。

若将剥离命令后的正文存为 display_text，用户只发送 `/financial_analysis`
时会落盘为空串，前端渲染出空气泡，即聊天记录中丢失该条指令。
前端在 result 事件里会用后端消息整体替换本地乐观消息，于是用户气泡
在回复完成的瞬间消失。

本测试用假 LLM 走完 /api/chat 全流程，断言：
    1. 落盘 messages.jsonl 的用户消息 display_text == 用户原文（含 /命令）
    2. 给模型看的 content 里带「显式指定技能」注入（模型行为不受影响）
    3. result 事件的 messages 里同样保留（前端刷新/替换后的显示源）
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from _harness import isolate_data_dir
from fastapi.testclient import TestClient

from app.api import app
from app.config import settings
from app.llm import Delta


class FakeClient:
    """直接输出 reply 决策，走通 supervisor loop 即可，不调真模型。"""

    def stream_messages(self, messages, **kwargs):
        yield Delta(
            content=json.dumps(
                {"action": "reply", "content": "技能已就绪，请问要分析哪家公司？"},
                ensure_ascii=False,
            )
        )


def main():
    from app import chat_supervisor

    # 落盘目录重定向到临时目录：否则测试对话会出现在前端侧边栏里
    isolate_data_dir()

    chat_supervisor.build_chat_client = lambda state, emit: FakeClient()
    client = TestClient(app)
    run_id = "smoke-disp"

    with client.stream(
        "POST",
        "/api/chat",
        data={
            "message": "/financial_analysis",
            "run_id": run_id,
            "attachments": "[]",
        },
        headers={
            "X-LLM-Model": "fake-model",
            "X-LLM-Api-Key": "test-key",
            "X-LLM-Base-Url": "http://localhost:9/v1",
        },
    ) as resp:
        assert resp.status_code == 200, f"HTTP {resp.status_code}"
        events = [
            json.loads(line[len("data: ") :])
            for line in resp.iter_lines()
            if line.startswith("data: ")
        ]

    types = [e.get("type") for e in events]
    assert "result" in types, f"缺少 result 事件：{types}"

    # 1) 落盘文件：display_text 必须是用户原文
    path = Path(settings.runs_dir) / run_id / "messages.jsonl"
    msgs = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    first = msgs[0]
    assert first["role"] == "user", first.get("role")
    assert first.get("display_text") == "/financial_analysis", (
        f"/技能命令丢失：display_text={first.get('display_text')!r}"
    )
    # 2) 模型看到的 content 仍带技能指令注入（不影响调度行为）
    assert "financial_analysis" in first["content"], first["content"][:120]
    assert "意图见上方技能指令" in first["content"]  # 空正文的明确说明
    # 只有命令、没有正文时，指令必须给出可行动作，否则主管只会回复「已收到技能指令」
    assert "禁止只回答" in first["content"], (
        f"缺少行动要求，模型会退回空确认：{first['content'][:200]}"
    )
    assert "用 ask 询问用户" in first["content"], first["content"][:200]

    # 3) result 事件里的 messages（前端替换气泡的数据源）同样保留
    result_ev = next(e for e in events if e.get("type") == "result")
    norm_user = next(m for m in result_ev["payload"]["messages"] if m.get("role") == "user")
    assert norm_user.get("display_text") == "/financial_analysis", (
        f"result 事件里 display_text 丢失：{norm_user.get('display_text')!r}"
    )

    print("=== 落盘 messages.jsonl ===")
    for m in msgs:
        print(f"  [{m['role']}] display={m.get('display_text')!r}")


def test_empty_ack_guard() -> None:
    """主管只回「已收到技能指令」这类空确认时，必须重新决策而不是直接收尾。

    用户发的是技能命令，空确认会让整轮白跑，界面上表现为
    「问了等于没问，只能反复重发」，历史里堆满重复的成对话术。
    """
    import app.chat_supervisor as cs

    scripted = [
        {"action": "reply", "content": "已收到技能指令。"},
        {"action": "reply", "content": "技能已就绪，请问要分析哪家公司？"},
    ]

    class ScriptedClient:
        def __init__(self) -> None:
            self.calls = 0

        def stream_messages(self, messages, **kwargs):
            decision = scripted[min(self.calls, len(scripted) - 1)]
            self.calls += 1
            yield Delta(content=json.dumps(decision, ensure_ascii=False))

    cs.build_chat_client = lambda state, emit: ScriptedClient()

    events: list[tuple[str, str]] = []
    result = cs.run_chat(
        {
            "run_id": "ack-guard",
            "messages": [{"role": "user", "content": "/financial_analysis"}],
            "model": "fake",
            "api_key": "x",
        },
        [],
        lambda t, **kw: events.append(
            (str(getattr(t, "value", t)), str(kw.get("message") or "")),
        ),
    )

    assert result["reply"] == "技能已就绪，请问要分析哪家公司？", (
        f"空确认未被拦下，最终回复仍是：{result['reply']!r}"
    )
    assert any("没有实质内容" in m for _, m in events), "未记录空确认拦截日志"
    print("  空确认已被拦下并重决策，最终回复：", result["reply"])


if __name__ == "__main__":
    main()
    test_empty_ack_guard()
    print("\nRESULT: ALL PASS（/技能命令完整保留 + 空确认不再空转）")
