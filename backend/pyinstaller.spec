# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包规格：把 FastAPI 后端打成 onedir 目录。

用法：
    cd backend
    uv run pyinstaller pyinstaller.spec

产物：
    dist/backend/backend.exe      主程序
    dist/backend/_internal/       依赖与资源

Electron 通过 child_process.spawn 拉起 backend.exe，
并通过 DATA_DIR 环境变量指定数据目录（%APPDATA%/Weister/data）。
"""

import sys
from pathlib import Path

block_cipher = None

# PyInstaller 需要显式收集的隐式导入
hidden_imports = [
    # uvicorn 子模块（PyInstaller 无法自动发现）
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.protocols.websockets.websockets_impl",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    # FastAPI / Starlette
    "fastapi",
    "starlette",
    # pymupdf
    "pymupdf",
    "fitz",
    # tiktoken
    "tiktoken",
    "tiktoken_ext",
    "tiktoken_ext.openai_public",
    # langgraph / langchain
    "langgraph",
    "langchain_core",
    # mcp
    "mcp",
    # pydantic
    "pydantic",
    "pydantic_settings",
]

# 非代码资源：技能 Markdown + 样例文件
# PyInstaller 的 datas 格式：(源路径, 目标目录)
datas = [
    # skills/*.md → _internal/app/skills/
    ("app/skills", "app/skills"),
    # data/samples/ → _internal/data/samples/（样例文件）
    ("data/samples", "data/samples"),
]

a = Analysis(
    ["app/__main__.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 排除不需要的大模块以减小体积
        "matplotlib",
        "numpy",
        "pandas",
        "scipy",
        "IPython",
        "notebook",
        "jupyter",
        "pytest",
        "ruff",
    ],
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,  # 后端服务需要控制台输出日志
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="backend",
)
