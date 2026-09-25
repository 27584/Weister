"""ReAct 智能体执行器。

使用原生 function calling：把工具声明为 OpenAI 格式的 tools 参数，
模型返回结构化的 tool_calls 字段，不需要任何文本解析。

每轮循环：
    1. 调用 LLM，流式接收正文、推理与工具调用
    2. 若返回 tool_calls，逐个执行并把结果回灌对话
    3. 若无 tool_calls，其正文即为最终结论

终止条件：
    - 模型未返回 tool_calls（已给出结论）
    - 连续多步既无工具调用也无新内容（判定为停滞）
    - 触及 spec.max_steps 安全上限（仅防御真正的死循环）

注意：进展检测会把「有工具调用」一律视为有进展。若模型稳定地反复调用
工具并每次都有返回，进展检测永远不会触发，只有 max_steps 能截断它。

不对单轮输出长度设限：推理与正文共享 API 预算，
任何人为截断都会挤压正文空间。
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..core.registry import AgentSpec, Tool, registry
from ..events import EventType, NodeStatus
from ..llm import LLMClient


@dataclass
class ToolContext:
    client: LLMClient
    emit: Callable[..., None]
    node: str
    agent_key: str
    state: dict[str, Any] = field(default_factory=dict)

    def delta_handler(self, step: int) -> Callable[[Any], None]:
        def handle(delta: Any) -> None:
            if getattr(delta, "reasoning", None):
                self.emit(
                    EventType.THINKING,
                    status=NodeStatus.RUNNING,
                    message=delta.reasoning,
                    payload={"agent": self.agent_key, "step": step},
                )
            if getattr(delta, "content", None):
                self.emit(
                    EventType.TOKEN,
                    status=NodeStatus.RUNNING,
                    message=delta.content,
                    payload={"agent": self.agent_key, "step": step},
                )

        return handle


@dataclass
class ToolCallRecord:
    step: int
    name: str
    input: dict[str, Any]
    ok: bool
    summary: str


def _describe_tools(names: list[str]) -> str:
    lines: list[str] = []
    for name in names:
        tool = registry.tools.get(name)
        if tool is None:
            continue
        params = ", ".join(f"{k}: {v}" for k, v in tool.input_schema.items()) or "无参数"
        lines.append(f"- `{name}`（{params}）：{tool.description}")
    return "\n".join(lines) if lines else "（无可用工具）"


def _render_skills(names: list[str]) -> str:
    """把技能正文完整拼进 prompt。

    内联而非运行时加载，原因有二：
        1. 省去每个智能体一轮 load_skill 调用
        2. 让技能正文成为稳定的 prompt 前缀，命中 API 的自动缓存

    system prompt 必须逐字稳定，任何变动都会导致缓存失效，
    因此这里不做时间戳、随机数等易变内容的拼接。
    """
    blocks: list[str] = []
    for name in names:
        skill = registry.skills.get(name)
        if skill is None:
            continue
        blocks.append(f"### {skill.name}\n\n{skill.body.strip()}")
    return "\n\n---\n\n".join(blocks)


def build_system_prompt(spec: AgentSpec) -> str:
    tools = _describe_tools(spec.tools)
    skills = _render_skills(spec.skills)

    skill_section = (
        f"""

## 技能指引

以下是你负责领域的完整操作规范，请严格遵循。

{skills}
"""
        if skills
        else ""
    )

    return f"""{spec.system_prompt}

## 可用工具

{tools}
{skill_section}
## 工作方式

通过工具调用接口使用上述工具，系统会自动执行并把结果返回给你。

- 需要外部信息或计算时，调用相应工具
- 不要在正文里书写 JSON 或代码块来模拟工具调用
- 信息足够时直接输出最终结论，无需额外的结束标记
- 数据不足时如实说明，不要编造
- 若连续几轮既没有调用工具也没有产出新内容，说明已陷入停顿，应立即给出当前最优结论
"""


class AgentRunner:
    def __init__(self, spec: AgentSpec) -> None:
        self.spec = spec

    def _tool_declarations(self) -> list[dict[str, Any]]:
        """把白名单里的工具转成 OpenAI tools 声明。"""
        out: list[dict[str, Any]] = []
        for name in self.spec.tools:
            tool = registry.tools.get(name)
            if tool is None:
                continue
            out.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.json_schema(),
                    },
                }
            )
        return out

    def _execute_tool(
        self,
        tool: Tool,
        payload: dict[str, Any],
        ctx: ToolContext,
        step: int,
    ) -> tuple[bool, Any, str]:
        handler = tool.handler
        kwargs = dict(payload)

        try:
            if "client" in tool.inject:
                kwargs["client"] = ctx.client
            if "on_delta" in tool.inject:
                kwargs["on_delta"] = ctx.delta_handler(step)
            result = handler(**kwargs)
        except Exception as exc:  # noqa: BLE001
            return False, None, f"{type(exc).__name__}: {exc}"

        preview = json.dumps(result, ensure_ascii=False, default=str)
        if len(preview) > 400:
            preview = preview[:400] + "…"
        return True, result, preview

    def run(
        self,
        task: str,
        client: LLMClient,
        emit: Callable[..., None],
        node: str,
        shared: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        spec = self.spec
        system = build_system_prompt(spec)
        messages: list[dict[str, Any]] = [{"role": "user", "content": task}]
        tool_decls = self._tool_declarations()

        trace: list[ToolCallRecord] = []
        artifacts: dict[str, Any] = {}
        started = time.perf_counter()

        ctx = ToolContext(
            client=client,
            emit=emit,
            node=node,
            agent_key=spec.key,
            state=shared if shared is not None else {},
        )

        final_output = ""
        best_body = ""
        stale_steps = 0
        truncated = False
        step = 0

        # 终止以进展检测为主（无工具调用且正文非空，或连续多步无进展）。
        # max_steps 是防御性上限：只要模型仍在调用工具，进展检测即判定为"有进展"，
        # 因此持续重复调用工具的模型可能长期不收敛，需要由硬上限截断。
        # 触顶后不丢弃已有内容，由循环外的收尾逻辑复用 best_body。
        while True:
            step += 1
            if step > spec.max_steps:
                truncated = True
                emit(
                    EventType.LOG,
                    status=NodeStatus.RUNNING,
                    message=f"{spec.name} · 达到步数上限 {spec.max_steps}，强制收尾",
                    payload={
                        "agent": spec.key,
                        "step": step,
                        "limit": spec.max_steps,
                        "truncated": True,
                    },
                )
                break

            emit(
                EventType.LOG,
                status=NodeStatus.RUNNING,
                message=f"{spec.name} · 第 {step} 步",
                payload={"agent": spec.key, "step": step},
            )

            # ---- 单轮调用 ----
            buffer: list[str] = []
            pending: dict[int, dict[str, str]] = {}

            for delta in client.stream_messages(
                [{"role": "system", "content": system}, *messages],
                tools=tool_decls,
            ):
                if delta.reasoning:
                    emit(
                        EventType.THINKING,
                        status=NodeStatus.RUNNING,
                        message=delta.reasoning,
                        payload={"agent": spec.key, "step": step},
                    )
                if delta.content:
                    buffer.append(delta.content)
                    emit(
                        EventType.TOKEN,
                        status=NodeStatus.RUNNING,
                        message=delta.content,
                        payload={"agent": spec.key, "step": step},
                    )
                if delta.tool_call:
                    # arguments 是分片累积的，按 index 拼接
                    idx = delta.tool_call["index"]
                    slot = pending.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                    if delta.tool_call["id"]:
                        slot["id"] = delta.tool_call["id"]
                    if delta.tool_call["name"]:
                        slot["name"] = delta.tool_call["name"]
                    slot["arguments"] += delta.tool_call["arguments"]

            content = "".join(buffer).strip()
            if len(content) > len(best_body):
                best_body = content

            # ---- 无工具调用：本轮正文即最终结论 ----
            if not pending:
                if content:
                    final_output = content
                    break
                # 完全空输出，计入停滞
                stale_steps += 1
                if stale_steps >= 3:
                    emit(
                        EventType.LOG,
                        status=NodeStatus.RUNNING,
                        message=f"{spec.name} · 连续 {stale_steps} 步无进展，收尾",
                        payload={"agent": spec.key, "step": step},
                    )
                    final_output = best_body
                    break
                messages.append(
                    {
                        "role": "user",
                        "content": "请继续，或直接给出最终结论。",
                    }
                )
                continue

            # ---- 有工具调用：记录 assistant 消息并逐个执行 ----
            messages.append(
                {
                    "role": "assistant",
                    "content": content,
                    "tool_calls": [
                        {
                            "id": call["id"] or f"call_{idx}",
                            "type": "function",
                            "function": {
                                "name": call["name"],
                                "arguments": call["arguments"] or "{}",
                            },
                        }
                        for idx, call in sorted(pending.items())
                    ],
                }
            )

            succeeded = False
            for idx, call in sorted(pending.items()):
                name = call["name"]
                call_id = call["id"] or f"call_{idx}"

                # 参数解析
                try:
                    payload = json.loads(call["arguments"]) if call["arguments"] else {}
                    if not isinstance(payload, dict):
                        payload = {}
                except json.JSONDecodeError as exc:
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call_id,
                            "content": f"参数不是合法 JSON：{exc}",
                        }
                    )
                    continue

                # 工具存在性与权限
                tool = registry.tools.get(name)
                if tool is None:
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call_id,
                            "content": f"工具 {name} 不存在。可用工具：{', '.join(spec.tools)}",
                        }
                    )
                    continue

                if name not in spec.tools:
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call_id,
                            "content": f"无权调用 {name}。你的工具：{', '.join(spec.tools)}",
                        }
                    )
                    continue

                emit(
                    EventType.TOOL_CALL,
                    status=NodeStatus.RUNNING,
                    message=f"tool: {name}",
                    payload={"agent": spec.key, "step": step, "tool": name, "input": payload},
                )

                ok, result, summary = self._execute_tool(tool, payload, ctx, step)
                trace.append(ToolCallRecord(step, name, payload, ok, summary))

                emit(
                    EventType.TOOL_RESULT,
                    status=NodeStatus.SUCCESS if ok else NodeStatus.FAILED,
                    message=f"{name} · {'成功' if ok else '失败'}",
                    payload={
                        "agent": spec.key,
                        "step": step,
                        "tool": name,
                        "ok": ok,
                        "result": result if ok else None,
                        "error": None if ok else summary,
                    },
                )

                if ok and isinstance(result, dict):
                    artifacts[name] = result
                if ok:
                    succeeded = True

                observation = (
                    json.dumps(result, ensure_ascii=False, default=str)
                    if ok
                    else f"错误：{summary}"
                )
                if len(observation) > 6000:
                    observation = observation[:6000] + "…（已截断）"

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": observation,
                    }
                )

            # 只有真正拿到工具结果才算有进展。
            # 若本轮调用全部失败（工具不存在 / 越权 / 参数非法 / 执行抛异常），
            # 模型很可能陷入「反复重试同一个坏调用」的死循环；此时不能清零停滞计数，
            # 否则进展检测永不触发，只能靠 max_steps 兜底白白消耗轮次。
            if succeeded:
                stale_steps = 0
            else:
                stale_steps += 1
                if stale_steps >= 3:
                    emit(
                        EventType.LOG,
                        status=NodeStatus.RUNNING,
                        message=f"{spec.name} · 连续 {stale_steps} 步工具调用失败，收尾",
                        payload={"agent": spec.key, "step": step},
                    )
                    final_output = best_body
                    break

        elapsed = int((time.perf_counter() - started) * 1000)

        if not final_output:
            final_output = best_body or "未产出有效内容。"
            if final_output == "未产出有效内容。":
                emit(
                    EventType.LOG,
                    status=NodeStatus.RUNNING,
                    message=f"{spec.name} · 未产出有效内容",
                    payload={"agent": spec.key},
                )

        return {
            "agent": spec.key,
            "name": spec.name,
            "role": spec.role,
            "output": final_output,
            "artifacts": artifacts,
            "steps": len(trace),
            "tools_used": [t.name for t in trace],
            "elapsed_ms": elapsed,
            # 是否因触及 max_steps 被强制收尾。为真说明结论可能不完整，
            # 调用方应把它带到前端/日志里，而不是当作正常完成。
            "truncated": truncated,
            "trace": [
                {"step": t.step, "tool": t.name, "ok": t.ok, "summary": t.summary} for t in trace
            ],
        }
