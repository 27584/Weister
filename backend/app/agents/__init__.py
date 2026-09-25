"""智能体包。

导入时完成全部注册：工具、技能、专家与主管。
"""

from __future__ import annotations

from .. import tools as _tools  # 导入即完成工具注册（副作用）
from ..core.registry import registry
from .base import AgentRunner, ToolContext
from .coordinator import register as register_coordinator
from .specialists import register as register_specialists


def bootstrap() -> None:
    """确保工具、技能与智能体都已注册。幂等，可重复调用。"""
    _ = _tools  # 保持引用，避免被 tree-shake 优化掉导入
    registry.load_skills()
    register_specialists()
    register_coordinator()


bootstrap()

__all__ = ["AgentRunner", "ToolContext", "bootstrap", "registry"]
