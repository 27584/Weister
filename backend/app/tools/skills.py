"""技能加载工具。

让智能体在运行时按需获取 SKILL.md 的完整操作说明。
"""

from __future__ import annotations

from ..core.registry import Tool, registry


def load_skill(name: str) -> dict[str, str]:
    skill = registry.skill(name)
    return {
        "name": skill.name,
        "description": skill.description,
        "tools": ", ".join(skill.tools) if skill.tools else "无",
        "instructions": skill.body,
    }


def list_skills() -> dict[str, list[dict[str, str]]]:
    return {
        "skills": [
            {
                "name": s.name,
                "description": s.description,
                "tools": ", ".join(s.tools) if s.tools else "无",
            }
            for s in registry.skills.values()
        ]
    }


registry.add_tool(
    Tool(
        name="list_skills",
        description="列出所有可用技能的名称与用途。在不确定该用哪个技能时先调用它。",
        input_schema={},
        handler=list_skills,
        tags=["meta"],
    )
)

registry.add_tool(
    Tool(
        name="load_skill",
        description="加载指定技能的完整操作说明。调用后你会获得该技能的详细工作流程、输出规范与常见陷阱。",
        input_schema={"name": "str"},
        handler=load_skill,
        tags=["meta"],
    )
)
