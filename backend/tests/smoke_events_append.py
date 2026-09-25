"""回归测试：events.jsonl 必须**追加写入**，多轮对话才能完整还原协作面板。

若每次覆盖写入，同一对话执行多轮后仅保留最后一轮的事件，
切换或刷新后协作面板将缺失此前各轮的记录。
"""

import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.api import store as store_mod


def main():
    tmp = tempfile.mkdtemp(prefix="weister_evtappend_")

    class FakeSettings:
        runs_dir = tmp

    real = store_mod.settings
    store_mod.settings = FakeSettings()
    try:
        store_mod.save_chat_events(
            "r1",
            [
                {"type": "run_start", "message": "开始"},
                {"type": "token", "message": "第一轮"},
            ],
        )
        store_mod.save_chat_events(
            "r1",
            [
                {"type": "run_start", "message": "开始"},
                {"type": "token", "message": "第二轮"},
            ],
        )
        evs = store_mod.load_chat_events("r1")
        msgs = [e.get("message") for e in evs]
        print("累积事件:", msgs)
        assert len(evs) == 4, f"应累积 4 条，实际 {len(evs)}"
        assert "第一轮" in msgs and "第二轮" in msgs, "两轮事件都应保留"

        # 空列表不应写入
        store_mod.save_chat_events("r1", [])
        assert len(store_mod.load_chat_events("r1")) == 4, "空事件不应改变文件"

        # 另一个 run 互不影响
        store_mod.save_chat_events("r2", [{"type": "run_start", "message": "other"}])
        assert len(store_mod.load_chat_events("r2")) == 1
        assert len(store_mod.load_chat_events("r1")) == 4

        print("ALL PASS: events.jsonl 追加累积，多轮可完整还原")
    finally:
        store_mod.settings = real
        shutil.rmtree(tmp, ignore_errors=True)
    raise SystemExit(0)


if __name__ == "__main__":
    main()
