"""SSE 事件协议。

前后端唯一契约：后端把执行过程中的每个动作转成 AgentEvent，
前端按 seq 顺序渲染到对应的智能体窗口。
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class NodeStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


class EventType(str, Enum):
    RUN_START = "run_start"
    NODE_START = "node_start"
    NODE_END = "node_end"
    AGENT_START = "agent_start"
    AGENT_END = "agent_end"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    THINKING = "thinking"
    TOKEN = "token"
    LOG = "log"
    RESULT = "result"
    ERROR = "error"
    RUN_END = "run_end"
    # 交互类：向前端提问并等待回答（ask_user 由 /api/chat/answer 作答）
    ASK_USER = "ask_user"
    # 标题变更：智能体为对话命名，前端同步侧边栏
    TITLE = "title"


class AgentEvent(BaseModel):
    type: EventType
    run_id: str
    seq: int
    node: str | None = None
    status: NodeStatus | None = None
    message: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
