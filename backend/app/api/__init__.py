"""HTTP 接口层。

按领域拆分路由：
    deps.py      凭据解析与搜索配置
    sse.py       SSE 帧编码
    store.py     聊天落盘
    helpers.py   附件 / 技能命令 / 用户消息
    analyze.py   一键建模流水线
    chat.py      聊天 supervisor
    meta.py      健康检查 / 配置 / 历史 CRUD

凭据传递约定：
    模型凭据（API Key、Base URL 等）一律走请求头，不放在 URL 或表单里。
    原因是 uvicorn 的 access log 会记录完整请求行（含查询串），
    把 Key 放 URL 会导致密钥明文出现在日志、浏览器历史与代理记录中。

    请求头名称：
        X-LLM-Provider         提供商 key
        X-LLM-Model            模型名
        X-LLM-Fallback-Models  备用模型，逗号分隔
        X-LLM-Api-Key          API 密钥
        X-LLM-Base-Url         自定义端点
        X-Search-Tavily-Key    Tavily 搜索 Key
        X-Search-Bocha-Key     博查搜索 Key
        X-Search-Searxng-Url   自建 SearXNG 地址
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .. import tools as _tools  # noqa: F401  导入即注册工具
from ..agents import bootstrap as bootstrap_agents
from ..config import settings
from ..core.registry import registry
from . import analyze, chat, meta
from .deps import (
    DEFAULT_QUESTION as DEFAULT_QUESTION,
)
from .deps import (
    DEMO_QUESTION as DEMO_QUESTION,
)
from .deps import (
    Credentials,
    credentials,
)
from .deps import (
    bind_search_config as bind_search_config,
)
from .helpers import (
    build_attachments,
    build_user_message,
    doc_label,
    skill_command_context,
    split_skill_command,
)
from .sse import sse as _sse
from .store import (
    compact_stream_events,
    conversation_title,
    load_chat_documents,
    load_chat_events,
    load_chat_history,
    load_chat_title,
    save_chat_documents,
    save_chat_events,
    save_chat_history,
)

bootstrap_agents()

app = FastAPI(title="Weister", version="0.3.1")

# 允许的请求头需要显式列出，否则浏览器预检会拒绝
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=[
        "Content-Type",
        "X-LLM-Provider",
        "X-LLM-Model",
        "X-LLM-Fallback-Models",
        "X-LLM-Api-Key",
        "X-LLM-Base-Url",
        "X-Search-Tavily-Key",
        "X-Search-Bocha-Key",
        "X-Search-Searxng-Url",
    ],
)

app.include_router(meta.router)
app.include_router(analyze.router)
app.include_router(chat.router)

# 测试 / 兼容再导出：历史代码与 smoke 脚本从 app.api 取这些符号
ChatRequest = chat.ChatRequest
_chat_stream = chat._chat_stream
_run_stream = analyze._run_stream
_init_checkpoint = analyze._init_checkpoint
_compact_stream_events = compact_stream_events
_save_chat_history = save_chat_history
_load_chat_history = load_chat_history
_save_chat_events = save_chat_events
_load_chat_events = load_chat_events
_save_chat_documents = save_chat_documents
_load_chat_documents = load_chat_documents
_build_attachments = build_attachments
_doc_label = doc_label
_split_skill_command = split_skill_command
_skill_command_context = skill_command_context
_build_user_message = build_user_message
_load_chat_title = load_chat_title
_conversation_title = conversation_title

__all__ = [
    "DEFAULT_QUESTION",
    "DEMO_QUESTION",
    "Credentials",
    "_sse",
    "app",
    "bind_search_config",
    "credentials",
    "registry",
]
