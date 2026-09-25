"""冒烟测试公共夹具：把落盘目录重定向到临时目录。

这些测试直接调用 /api/chat 或读写 messages.jsonl，若不隔离就会往
`backend/data/runs` 里写真实对话 —— 它们会出现在前端侧边栏，
看起来像「凭空多出一堆重复对话」。每个测试开头调用一次 `isolate_data_dir()` 即可。
"""

from __future__ import annotations

import atexit
import os
import shutil
import tempfile

from app.config import settings


def isolate_data_dir() -> str:
    """把 settings.data_dir 指向一个临时目录，进程退出时自动清理。

    返回临时目录路径。多次调用只有第一次生效（后续复用同一目录），
    因为 settings 是单例，重定向一次即全局生效。
    """
    marker = os.environ.get("_WEISTER_SMOKE_DATA_DIR")
    if marker and os.path.isdir(marker):
        settings.data_dir = marker
        return marker

    tmp = tempfile.mkdtemp(prefix="weister-smoke-")
    os.environ["_WEISTER_SMOKE_DATA_DIR"] = tmp
    atexit.register(shutil.rmtree, tmp, ignore_errors=True)
    settings.data_dir = tmp
    return tmp
