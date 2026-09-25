"""MCP 服务器。

把注册表中的工具通过 Model Context Protocol 暴露出去，
使外部 MCP 客户端（如 Claude Desktop、Cline 等）能够调用本项目的金融工具。

启动方式：
    uv run python -m app.mcp_server

协议说明：https://modelcontextprotocol.io
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from mcp import types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from . import tools as _tools  # noqa: F401  触发工具注册
from .core.registry import Tool, registry

# 加载 skills/*.md，否则 list_skills 与 load_skill 会返回空
registry.load_skills()

# 不通过 MCP 暴露的工具（依赖运行时注入或仅内部使用）
EXCLUDED = {"parse_document"}

TYPE_MAP = {
    "str": "string",
    "int": "integer",
    "float": "number",
    "bool": "boolean",
    "dict": "object",
    "list": "array",
}


def _json_schema(tool: Tool) -> dict[str, Any]:
    """把注册表的 input_schema 转成 JSON Schema。

    注册表存的是 {"参数名": "类型描述"} 的简化格式，
    这里转换成标准 JSON Schema 供 MCP 客户端使用。
    """
    properties: dict[str, Any] = {}
    required: list[str] = []

    for name, desc in tool.input_schema.items():
        optional = "可选" in desc
        base_type = desc.replace("（可选）", "").strip()

        for key, json_type in TYPE_MAP.items():
            if base_type.startswith(key):
                properties[name] = {"type": json_type, "description": desc}
                break
        else:
            properties[name] = {"type": "string", "description": desc}

        if not optional:
            required.append(name)

    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


def _available_tools() -> list[types.Tool]:
    """收集可通过 MCP 暴露的工具。"""
    out: list[types.Tool] = []
    for name, tool in registry.tools.items():
        if name in EXCLUDED or tool.inject:
            continue
        out.append(
            types.Tool(
                name=name,
                description=tool.description,
                input_schema=_json_schema(tool),
            )
        )
    return out


def _build_server() -> Server:
    server = Server("weister")

    async def handle_list_tools(ctx: Any, params: types.ListToolsRequest) -> types.ListToolsResult:
        return types.ListToolsResult(tools=_available_tools())

    async def handle_call_tool(
        ctx: Any, params: types.CallToolRequestParams
    ) -> types.CallToolResult:
        name = params.name
        arguments = params.arguments or {}

        tool = registry.tools.get(name)
        if tool is None:
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=f"工具不存在：{name}")],
                is_error=True,
            )

        if name in EXCLUDED:
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=f"该工具不通过 MCP 暴露：{name}")],
                is_error=True,
            )

        if tool.inject:
            missing = "、".join(tool.inject)
            return types.CallToolResult(
                content=[
                    types.TextContent(
                        type="text",
                        text=(
                            f"工具 {name} 需要运行时注入 {missing}，"
                            f"无法通过 MCP 独立调用。请在 Weister 应用内使用。"
                        ),
                    )
                ],
                is_error=True,
            )

        try:
            result = tool.handler(**arguments)
        except TypeError as exc:
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=f"参数错误：{exc}")],
                is_error=True,
            )
        except Exception as exc:  # noqa: BLE001
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=f"{type(exc).__name__}: {exc}")],
                is_error=True,
            )

        text = json.dumps(result, ensure_ascii=False, indent=2, default=str)
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=text)],
        )

    server.add_request_handler("tools/list", types.ListToolsRequest, handle_list_tools)
    server.add_request_handler("tools/call", types.CallToolRequestParams, handle_call_tool)
    return server


async def _run() -> None:
    server = _build_server()
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def main() -> None:
    """入口：以 stdio 模式运行 MCP 服务器。"""
    asyncio.run(_run())


if __name__ == "__main__":
    main()
