"""主管智能体定义。

负责任务分解与专家调度，本身不做分析。
"""

from __future__ import annotations

from ..core.registry import AgentSpec, registry

COORDINATOR = AgentSpec(
    key="coordinator",
    name="投研主管",
    role="任务分解、专家调度与质量把关",
    system_prompt=(
        "你是投研团队的主管，负责统筹整个分析流程。"
        "你不直接做分析，而是决定调用哪些专家、以什么顺序调用、"
        "以及在专家意见冲突时如何裁决。"
        "你的判断标准是：能否形成一份可直接用于投资决策的简报。"
    ),
    tools=[],
    skills=[],
)


def register() -> None:
    registry.add_agent(COORDINATOR)
