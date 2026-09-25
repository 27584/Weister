"""验证同 run_id 下连续消息会追加历史，而不是覆盖/清空。

用假 run_chat 替换真 LLM，两轮对话后断言 messages.jsonl 里有两条 user + 两条 assistant。
"""

import asyncio
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from _harness import isolate_data_dir

from app.api import ChatRequest, Credentials, _chat_stream
from app.api import chat as chat_mod
from app.events import EventType, NodeStatus


def make_fake_run_chat():
    calls = []

    def fake_run_chat(state, documents, emit):
        calls.append(state["run_id"])
        messages = list(state.get("messages") or [])
        emit(
            EventType.LOG,
            status=NodeStatus.RUNNING,
            message=f"第 {len(calls)} 轮，历史 {len(messages)} 条",
        )
        reply = f"回复第 {len(calls)} 轮"
        return {
            "reply": reply,
            "messages": messages + [{"role": "assistant", "content": reply}],
            "iterations": 1,
            "truncated": False,
            "specialists_called": [],
        }

    return fake_run_chat, calls


def make_history_helpers(tmp: str):
    def save(run_id: str, messages: list[dict]) -> None:
        base = __import__("pathlib").Path(tmp) / run_id
        base.mkdir(parents=True, exist_ok=True)
        from app.chat_supervisor import serialize_messages

        (base / "messages.jsonl").write_text(serialize_messages(messages), encoding="utf-8")

    def load(run_id: str) -> list[dict]:
        path = __import__("pathlib").Path(tmp) / run_id / "messages.jsonl"
        if not path.exists():
            return []
        from app.chat_supervisor import deserialize_messages

        return deserialize_messages(path.read_text(encoding="utf-8"))

    return save, load


async def drive(req: ChatRequest):
    chunks = []
    async for chunk in _chat_stream(
        req, {}, Credentials(provider="deepseek", model="ds", api_key="x")
    ):
        chunks.append(chunk)
    for chunk in chunks:
        body = chunk.split("data: ", 1)[1].strip()
        ev = json.loads(body)
        if ev.get("type") == "result":
            return ev.get("run_id")
    return None


def main():
    # _save_chat_events 走真实落盘路径，把数据目录重定向到临时目录
    isolate_data_dir()
    tmp = tempfile.mkdtemp(prefix="weister_conv_")
    save, load = make_history_helpers(tmp)
    try:
        # 让 api 层的读写函数落到临时目录
        chat_mod.save_chat_history = save
        chat_mod.load_chat_history = load

        fake, calls = make_fake_run_chat()
        chat_mod.run_chat = fake

        # 第一轮：不带 run_id
        run_id_1 = asyncio.run(drive(ChatRequest(run_id="", message="你好", attachments=[])))
        assert run_id_1, "第一轮应返回 run_id"

        # 第二轮：带同一个 run_id
        run_id_2 = asyncio.run(
            drive(ChatRequest(run_id=run_id_1, message="再问一下", attachments=[]))
        )
        assert run_id_2 == run_id_1, "第二轮 run_id 应相同"

        history = load(run_id_1)
        user_msgs = [m for m in history if m.get("role") == "user"]
        assistant_msgs = [m for m in history if m.get("role") == "assistant"]

        print("run_id:", run_id_1)
        print("calls:", calls)
        print("user messages:", [m.get("content") for m in user_msgs])
        print("assistant messages:", [m.get("content") for m in assistant_msgs])

        assert len(user_msgs) == 2, f"应有两条 user 消息，实际 {len(user_msgs)}"
        assert len(assistant_msgs) == 2, f"应有两条 assistant 消息，实际 {len(assistant_msgs)}"
        assert "你好" in [m.get("content") for m in user_msgs]
        assert "再问一下" in [m.get("content") for m in user_msgs]
        print("\nALL PASS: 同 run_id 连续消息正确追加历史")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
