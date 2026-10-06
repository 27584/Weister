"""路径解析：所有落盘位置的唯一来源。

原则：这里不出现任何与「某台机器」绑定的写死路径。凡是要读文件、要落盘的
位置，一律按「环境变量 → 平台标准用户目录」解析成**绝对路径**，于是从哪个
工作目录启动、装在哪台机器上，行为完全一致。

历史教训：``data_dir`` 曾默认 ``"./data"``。那是相对 cwd 的隐式写死路径——
命令行下跑到 backend/data，Electron 打包后则落到安装目录（Program Files
只读，或卸载即丢），同一份代码在两处行为不同。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

#: backend/ 根目录（本文件位于 backend/app/paths.py）
BACKEND_ROOT = Path(__file__).resolve().parent.parent

#: 应用名。必须与 Electron 侧 app.getPath("userData") 的末级目录同名，
#: 否则前后端会各写一份数据。
APP_NAME = "Weister"


def user_data_dir() -> Path:
    """平台标准的用户数据目录（绝对路径，不含应用子目录）。"""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / APP_NAME
        return Path.home() / "AppData" / "Roaming" / APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    base = os.environ.get("XDG_DATA_HOME")
    return (Path(base) if base else Path.home() / ".local" / "share") / APP_NAME


def resolve_data_dir() -> Path:
    """数据目录，绝对路径。

    优先级：
        1. ``DATA_DIR`` 环境变量（Electron 主进程传入 ``%APPDATA%\\Weister\\data``）
        2. 平台用户数据目录下的 ``Weister/data``（Windows 即 ``%APPDATA%\\Weister\\data``）

    刻意不再回退到 ``./data``：相对路径会把数据写进安装目录。若调用方传了
    相对值，按 ``backend/`` 解析，仍然与 cwd 无关。
    """
    env = os.environ.get("DATA_DIR")
    if env:
        path = Path(env).expanduser()
        if not path.is_absolute():
            path = BACKEND_ROOT / path
        return path.resolve()
    return (user_data_dir() / "data").resolve()


def env_file() -> Path:
    """``backend/.env`` 的绝对路径。

    pydantic-settings 对相对 ``env_file`` 按 cwd 解析，那样
    ``python -m app`` 与 ``uvicorn --reload`` 会读到不同的配置。
    """
    return BACKEND_ROOT / ".env"
