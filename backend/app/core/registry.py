"""Tool / Skill / Agent 注册表。

三者关系：
    Tool   原子函数，模型可直接调用
    Skill  Markdown 提示词文件，启动时加载并由 AgentRunner 内联进 system prompt
    Agent  持有 LLM 的决策者，有独立的 system prompt 与工具白名单
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"

# ReAct 循环的防御性步数上限（每步 = 一轮 LLM 调用）。
# 常规任务所需步数远低于此值，循环通常在「模型不再返回 tool_calls」
# 或「连续多步无进展」时终止。该上限用于防止模型持续重复调用工具而
# 陷入无法收敛的循环（会持续消耗 Token）。可按智能体单独调整。
DEFAULT_MAX_STEPS = 24


_TYPE_MAP = {
    "str": "string",
    "int": "integer",
    "float": "number",
    "bool": "boolean",
    "dict": "object",
    "list": "array",
}


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_schema: dict[str, str]
    handler: Callable[..., Any]
    tags: list[str] = field(default_factory=list)
    inject: list[str] = field(default_factory=list)

    def spec(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
            "tags": self.tags,
            "inject": self.inject,
        }

    def json_schema(self) -> dict[str, Any]:
        """把简化格式的 input_schema 转成标准 JSON Schema。

        简化格式形如 {"text": "str", "max_chars": "int（可选）"}，
        带「（可选）」标记的参数不进入 required。
        """
        properties: dict[str, Any] = {}
        required: list[str] = []

        for name, desc in self.input_schema.items():
            optional = "可选" in desc
            base = desc.replace("（可选）", "").strip()
            json_type = "string"
            for key, mapped in _TYPE_MAP.items():
                if base.startswith(key):
                    json_type = mapped
                    break
            properties[name] = {"type": json_type, "description": desc}
            if not optional:
                required.append(name)

        schema: dict[str, Any] = {"type": "object", "properties": properties}
        if required:
            schema["required"] = required
        return schema


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    tools: list[str]
    body: str
    path: str
    tags: list[str] = field(default_factory=list)

    def spec(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "tools": self.tools,
            "tags": self.tags,
            "path": self.path,
        }


@dataclass(frozen=True)
class AgentSpec:
    key: str
    name: str
    role: str
    system_prompt: str
    tools: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    max_steps: int = DEFAULT_MAX_STEPS

    def spec(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "name": self.name,
            "role": self.role,
            "tools": self.tools,
            "skills": self.skills,
            "max_steps": self.max_steps,
        }


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---"):
        return {}, text

    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text

    meta: dict[str, Any] = {}
    current_list: str | None = None

    for raw in parts[1].splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        if line.startswith("  - ") and current_list:
            meta.setdefault(current_list, []).append(line[4:].strip())
            continue
        if ":" in line:
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip()
            if value:
                meta[key] = value
                current_list = None
            else:
                meta[key] = []
                current_list = key

    return meta, parts[2].lstrip("\n")


class Registry:
    def __init__(self) -> None:
        self.tools: dict[str, Tool] = {}
        self.skills: dict[str, Skill] = {}
        self.agents: dict[str, AgentSpec] = {}

    def add_tool(self, tool: Tool) -> Tool:
        self.tools[tool.name] = tool
        return tool

    def add_agent(self, agent: AgentSpec) -> AgentSpec:
        self.agents[agent.key] = agent
        return agent

    def load_skills(self) -> None:
        if not SKILLS_DIR.is_dir():
            return
        for path in sorted(SKILLS_DIR.glob("*.md")):
            text = path.read_text(encoding="utf-8")
            meta, body = _parse_frontmatter(text)
            name = meta.get("name") or path.stem
            self.skills[name] = Skill(
                name=name,
                description=meta.get("description", ""),
                tools=list(meta.get("tools") or []),
                body=body,
                path=str(path.relative_to(SKILLS_DIR.parent)),
                tags=list(meta.get("tags") or []),
            )

    def tool(self, name: str) -> Tool:
        if name not in self.tools:
            raise KeyError(f"未注册的工具：{name}")
        return self.tools[name]

    def skill(self, name: str) -> Skill:
        if name not in self.skills:
            raise KeyError(f"未加载的技能：{name}")
        return self.skills[name]

    def catalog(self) -> dict[str, Any]:
        return {
            "tools": [t.spec() for t in self.tools.values()],
            "skills": [s.spec() for s in self.skills.values()],
            "agents": [a.spec() for a in self.agents.values()],
        }


registry = Registry()
