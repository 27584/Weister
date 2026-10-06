"""桌面客户端入口：直接运行 backend.exe 时由此模块启动 uvicorn。

用法：
    python -m app                # 开发模式
    backend.exe                  # PyInstaller 打包后

PyInstaller 的 entry point 指向此文件。启动时从环境变量读取 DATA_DIR
（由 Electron 主进程传入），未设置时回退到 exe 同级的 ./data 目录。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _resolve_data_dir() -> str:
    """确定数据目录。

    优先级：
        1. 环境变量 DATA_DIR（Electron 主进程传入 %APPDATA%/Weister/data）
        2. PyInstaller 打包时 exe 同级的 ./data
        3. 开发模式下的 backend/data
    """
    env = os.environ.get("DATA_DIR")
    if env:
        return env

    # PyInstaller onedir 模式：sys.executable 指向 backend/backend.exe
    # 数据目录放在 exe 同级
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return str(Path(sys.executable).parent / "data")

    return "./data"


def main() -> None:
    os.environ.setdefault("DATA_DIR", _resolve_data_dir())

    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8000,
        log_level="info",
    )


if __name__ == "__main__":
    main()
