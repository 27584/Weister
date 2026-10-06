"""桌面客户端入口：用嵌入式 Python 直接启动 uvicorn。

用法：
    python -m app                # 开发模式
    python.exe -m app            # 桌面客户端（嵌入式 Python）

桌面客户端通过 Electron 主进程拉起 python.exe -m uvicorn app.main:app。
启动时从环境变量读取 DATA_DIR（由 Electron 传入 %APPDATA%/Weister/data）。
"""

from __future__ import annotations

import os


def _resolve_data_dir() -> str:
    """确定数据目录。

    优先级：
        1. 环境变量 DATA_DIR（Electron 主进程传入）
        2. 开发模式下的 ./data（相对 backend/ 目录）
    """
    env = os.environ.get("DATA_DIR")
    if env:
        return env
    return "./data"


def main() -> None:
    os.environ.setdefault("DATA_DIR", _resolve_data_dir())

    import uvicorn

    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))

    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
