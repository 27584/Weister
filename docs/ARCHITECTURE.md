# Weister 架构详解

本文档说明系统的分层设计、执行器实现与数据流。

---

## 目录

- [整体分层](#整体分层)
- [桌面端进程拓扑](#桌面端进程拓扑)
- [注册表](#注册表)
- [ReAct 执行器](#react-执行器)
- [专家团并行](#专家团并行)
- [事件协议](#事件协议)
- [状态与检查点](#状态与检查点)
- [LLM 客户端](#llm-客户端)
- [MCP 服务器](#mcp-服务器)
- [运行日志](#运行日志)

---

## 整体分层

```
┌─────────────────────────────────────────────────────┐
│  api/               HTTP 接口 · SSE 流              │
├─────────────────────────────────────────────────────┤
│  orchestrator.py    LangGraph 图 · 专家团调度        │
├─────────────────────────────────────────────────────┤
│  agents/            ReAct 执行器 · 智能体定义        │
├─────────────────────────────────────────────────────┤
│  core/registry.py   Tool / Skill / Agent 注册表      │
├─────────────────────────────────────────────────────┤
│  llm.py · providers.py  LLM 客户端 · 提供商注册表    │
├─────────────────────────────────────────────────────┤
│  tools/             文档解析 · 抽取 · 指标与估值计算  │
└─────────────────────────────────────────────────────┘
```

**依赖方向**：上层依赖下层，下层不感知上层。`tools/` 中的函数是纯能力，不知道谁在调用它们。

---

## 桌面端进程拓扑

桌面形态下，Electron 主进程（`electron/main.cjs`）是两个子服务的父进程与编排者：

```
┌────────────────────────── Weister.exe (Electron) ──────────────────────────┐
│                                                                            │
│  main.cjs   whenReady 启动序列：                                            │
│    1. findFreePort(8000) / findFreePort(3000)  被占用则 +1，最多 20 个       │
│    2. startBackend    打包版 resources/backend/python/python.exe -s -m app  │
│    3. waitForService  轮询 /api/health，60 次 × 1s                          │
│    4. startFrontend   electron.exe + ELECTRON_RUN_AS_NODE=1 跑 standalone   │
│    5. waitForHttp     轮询 /，60 次 × 500ms                                 │
│    6. createWindow    frame:false，页面顶栏即标题栏                          │
│                                                                            │
│  ├─ backend 子进程   env: PORT / HOST=127.0.0.1 / DATA_DIR / CORS_ORIGINS   │
│  ├─ frontend 子进程  （ELECTRON_RUN_AS_NODE，无需系统 Node）                 │
│  └─ loading window   启动加载页，reportProgress / reportError（尾 6 行回显）  │
└────────────────────────────────────────────────────────────────────────────┘
         │ preload 注入 window.WEISTER 桥
         ▼
   渲染进程（frontend standalone 页面）──SSE──▶ 127.0.0.1:{动态后端端口}
```

关键机制：

- **动态端口**：后端 8000 / 前端 3000 冲突时自动递增；`CORS_ORIGINS`、`WEISTER_API_BASE`、`preload.cjs` 的 `API_BASE` 全部按实际端口注入，前端经 `lib/apiBase.ts` 的 `resolveApiBase()` 优先读桥上的基址
- **嵌入式 Python 隔离**：打包版后端用 Python 官方嵌入式发行版（`backend/python/`，由 `scripts/prepare-python.ps1` 生成）。嵌入式包的 `._pth` 隔离模式忽略 `PYTHON*` 环境变量，故必须以命令行 `-s` 旗标启动（`sys.flags.no_user_site=1`），防止构建机用户级 site-packages 泄漏进分发包
- **数据目录**：`backend/app/paths.py` 是落盘路径唯一来源——`DATA_DIR` 环境变量优先，默认按平台落用户数据目录（Windows 为 `%APPDATA%\Weister\data`）。Electron 同步 `app.setPath("userData", .../Weister)`，与后端 `APP_NAME="Weister"` 对齐，前后端共用同一份数据。刻意不回退 `./data`：打包后工作目录常为只读安装目录
- **进程清理**：`cleanup()` 挂在 `window-all-closed` / `before-quit` / `SIGINT` / `SIGTERM`，退出时杀掉两个子进程
- **失败可见性**：子进程输出进环形缓冲（40 行），启动失败时在加载窗口回显错误消息与末 6 行，避免只见一句 backend not responding

---

## 注册表

`core/registry.py` 定义三个不可变数据结构：

### Tool

```python
@dataclass(frozen=True)
class Tool:
    name: str                          # 唯一标识，模型调用时使用
    description: str                   # 展示给模型的用途说明
    input_schema: dict[str, str]       # 参数名 → 类型描述
    handler: Callable[..., Any]        # 实际执行函数
    tags: list[str]                    # 分类标签
    inject: list[str]                  # 需要注入的运行时对象
```

`inject` 是关键设计。`extract_fields` 需要 `LLMClient` 和流式回调，但这些不该出现在模型的参数列表里。执行器在调用前按 `inject` 声明注入：

```python
if "client" in tool.inject:
    kwargs["client"] = ctx.client
if "on_delta" in tool.inject:
    kwargs["on_delta"] = ctx.delta_handler(step)
```

### Skill

Skill 不是代码，是 Markdown 文件。`load_skills()` 解析 frontmatter：

```markdown
---
name: valuation_modeling
description: 自动化估值建模。当需要建立 DCF 模型时使用。
tools:
  - build_assumptions
  - dcf_valuation
tags:
  - finance
  - valuation
---

# 估值建模技能

## 工作流程
...
```

解析后存入注册表。技能正文由 `build_system_prompt()` 通过 `_render_skills()` **整体内联进 system prompt**（省去每轮 `load_skill` 调用，并让技能正文成为稳定前缀以命中 API 缓存）；`load_skill` 工具仍保留，主要供 MCP 客户端按需拉取。

**为什么用文件而不是函数**：技能的核心价值是「怎么做」的流程知识，不是「能做什么」的能力。用 Markdown 存储让金融背景的队友也能参与编写和迭代，不需要改代码。

### AgentSpec

```python
@dataclass(frozen=True)
class AgentSpec:
    key: str                    # 唯一标识
    name: str                   # 显示名
    role: str                   # 角色描述
    system_prompt: str          # 核心指令
    tools: list[str]            # 工具白名单
    skills: list[str]           # 可用技能
    max_steps: int = 24         # 最多循环步数（DEFAULT_MAX_STEPS，仅防御死循环）
```

`tools` 是白名单，执行器会拒绝不在列表中的工具调用。这让每个智能体的能力边界显式可控。

输出长度不在这里约束：`AgentSpec` 没有输出 token / 字符上限字段，`LLMClient` 默认不传 `max_tokens`（见下文「输出长度与终止」）。

---

## ReAct 执行器

`agents/base.py` 的 `AgentRunner.run()` 是核心循环。

### 单轮流程

```
1. 构造 messages：[system] + 历史对话
2. 流式调用 LLM，逐 token 推送事件
3. 累积输出，同时统计正文字数与推理字数
4. 累计正文字数与推理字数（仅用于展示，不做字符熔断）
5. 若返回 `tool_calls`，逐个执行工具并把结果回灌对话
6. 若本轮没有 `tool_calls`，该轮正文即为最终结论
```

### 工具调用协议（原生 function calling）

执行器把注册表里的工具转成 OpenAI 格式的 `tools` 声明，通过 `LLMClient.stream_messages(..., tools=...)` 传入：

```python
{"type": "function", "function": {"name": "extract_fields", "description": "...", "parameters": {...}}}
```

模型直接返回结构化的 `tool_calls` 字段（`llm.py` 在流式分片中累积 `delta.tool_calls`），**不需要任何文本正则解析**——`agents/base.py` 中已不存在 `ACTION_BLOCK`。早期文档里描述的文本 action 协议是 function calling 改造前的实现。

模型自带的 XML 工具调用语法（部分端点会注入 `<dots_function_call>` / `<invoke>` / `<parameter>`）由**前端**在渲染前剥离，见 `frontend/src/components/AgentStage.tsx` 的 `NOISE` 正则数组；后端不做二次过滤，原文照常写进事件流与检查点，便于排查。

### 输出长度与终止

系统**不传 `max_tokens`**（`llm.py` 中默认 `None`），让模型自行决定收尾时机，避免挤压正文空间。真正的边界有三处：

1. **`max_steps`（默认 24）**：只有模型持续调用工具且每次都有返回时才会命中，用于防御真正的死循环；命中后强制收尾，并在 `agent_end.payload` 标记 `truncated: true`
2. **工具结果截断**：单条观察超过 6000 字先截断再回灌（`agents/base.py`）
3. **上下文预算**：`tokens.py` 按模型窗口预留输出部分后裁剪历史，裁剪时优先保留最近的消息

`reasoning_content` 单独累计用于前端展示，不参与上述任何判定。

### 工具结果回灌

执行成功后把结果 JSON 序列化塞回对话：

```python
observation = json.dumps(result, ensure_ascii=False, default=str)
if len(observation) > 6000:
    observation = observation[:6000] + "…（已截断）"
messages.append({"role": "tool", "tool_call_id": call_id, "content": observation})
```

同时把成功返回的 dict 存进 `artifacts`，供编排器提取结构化数据。

---

## 专家团并行

`orchestrator.py` 的 `_run_group()` 用线程池并行执行多个智能体。

### 为什么需要队列

LangGraph 的 `get_stream_writer()` 绑定在 runnable context 里。在子线程中直接调用会抛：

```
Called get_config outside of a runnable context
```

解决方案是让子线程把事件写进队列，主线程轮询取出后发送：

```python
event_queue: queue.Queue[dict[str, Any]] = queue.Queue()

with ThreadPoolExecutor(max_workers=len(plan)) as pool:
    futures = {pool.submit(_run_agent, ..., event_queue): key for ...}

    pending = set(futures)
    while pending:
        done, pending = wait(pending, timeout=0.08, return_when=FIRST_COMPLETED)
        _drain(emit, event_queue)      # 主线程发送队列中的事件
        for fut in done:
            results.append(fut.result())
    _drain(emit, event_queue)          # 收尾
```

`timeout=0.08` 让主线程每 80ms 检查一次队列，事件延迟在可接受范围。

### 事件交错

四位专家的 `thinking` / `token` 事件会交错到达。前端按 `payload.agent` 分流到各自的窗口，因此交错不影响显示。

---

## 事件协议

`events.py` 定义 15 种事件类型：

| 类型 | 触发时机 | 关键 payload |
| --- | --- | --- |
| `run_start` | 开始执行 | `provider`, `model` |
| `node_start` | 节点开始 | — |
| `node_end` | 节点结束 | 节点特定数据 |
| `agent_start` | 智能体开始 | `agent`, `name`, `role` |
| `agent_end` | 智能体结束 | `opinion`, `elapsed_ms`, `steps` |
| `tool_call` | 调用工具 | `agent`, `step`, `input` |
| `tool_result` | 工具返回 | `ok`, `result` / `error` |
| `thinking` | 推理片段 | `agent`, `step` |
| `token` | 正文片段 | `agent`, `step` |
| `log` | 日志 | 重试信息、步数 |
| `result` | 最终结果 | 完整结构化数据 |
| `error` | 出错 | 错误消息 |
| `ask_user` | 需要用户确认/选择 | `question`、`options` |
| `title` | 会话标题生成 | `title` |
| `run_end` | 执行结束 | — |

所有事件带 `seq` 序号，前端按序渲染。

### SSE 帧格式

```
event: thinking
data: {"type":"thinking","run_id":"abc123","seq":42,"node":"analysis","message":"...","payload":{"agent":"valuation_expert","step":2}}

```

双换行分隔事件帧。

---

## 状态与检查点

### InvestState

LangGraph 的全局状态，所有节点读写同一份：

```python
class InvestState(TypedDict, total=False):
    # 输入
    run_id: str
    filename: str
    raw_bytes: bytes
    question: str

    # LLM 配置
    provider: str
    model: str
    fallback_models: list[str]
    api_key: str
    base_url: str

    # 中间产物
    document_text: str
    extracted: dict
    metrics: dict
    assumptions: dict
    dcf: dict
    relative: dict
    sensitivity: dict
    valuation_summary: dict

    # 输出
    analyses: dict
    expert_opinions: list
    report_md: str
    citations: list

    # 累积字段用 operator.add 归约
    trace: Annotated[list, operator.add]
```

`total=False` 让字段可选，避免并行节点互相覆盖未设置的键。

### 检查点

每节点完成后调用 `_save_ckpt()` 写 JSON：

```json
{
  "run_id": "abc123",
  "filename": "annual_report.txt",
  "finished": false,
  "completed_nodes": ["ingest", "extract"],
  "stage": "extract",
  "document_text": "...",
  "extracted": {...},
  "metrics": {...},
  "agents": {
    "financial_analyst": {"output": "...", "elapsed_ms": 12345}
  }
}
```

恢复时节点先检查是否已完成，是则直接返回缓存值，跳过 LLM 调用。

> 落盘位置由 `backend/app/paths.py` 统一解析：开发模式在 `backend/data/`，桌面客户端在 `%APPDATA%\Weister\data\`（`DATA_DIR` 环境变量可覆盖）。下文 `data/checkpoints/`、`data/runs/` 均指该数据目录下的相对位置。

---

## LLM 客户端

`llm.py` 的 `LLMClient` 封装三类能力。

### 流式输出

```python
for delta in client.stream_messages(messages):   # 不传 max_tokens，由模型自行收尾
    if delta.reasoning:
        ...
    if delta.content:
        ...
```

`_iter_deltas()` 解析 SSE 分片，同时提取 `content` 与 `reasoning_content`：

```python
content = delta.get("content") or ""
reasoning = delta.get("reasoning_content") or delta.get("reasoning") or ""
```

不同提供商的推理字段名不同，这里做了兼容。

### 重试退避

```python
RETRY_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}
MAX_ATTEMPTS = 8
BACKOFF_BASE = 2.0
BACKOFF_CAP = 60.0
```

```python
@staticmethod
def _backoff(attempt: int) -> float:
    base = min(BACKOFF_BASE ** attempt, BACKOFF_CAP)
    return base * (0.7 + random.random() * 0.6)   # 加抖动，避免惊群
```

### 备用模型链

```python
FALLBACK_AFTER = 3   # 连续失败 3 次触发切换
```

`_switch_model()` 从 `fallback_models` 弹出下一个模型，重置失败计数，并通过 `on_switch` 回调通知前端。

---

## MCP 服务器

`app/mcp_server.py` 把注册表中的工具通过 **Model Context Protocol** 暴露给外部客户端（Claude Desktop、Cline 等）。

### 为什么需要 MCP

工具在应用内是 Python 函数，通过注册表被智能体调用；同时源码包含 MCP 模块用于工具互操作（MCP 已是该领域的事实标准）。

MCP 层的作用是**协议适配**：把注册表里的 `Tool` 转换成 MCP 的 `types.Tool`，把调用请求路由到对应的 handler，把结果序列化为文本内容返回。

### 暴露范围

暴露范围是**注册表里除 3 个之外的全部工具**（23 - 3 = 20）：判定条件是「`inject` 为空且不在 `EXCLUDED` 中」。

| 工具 | 是否暴露 | 原因 |
| --- | --- | --- |
| 其余 20 个（估值 4 · 指标 4 · 行情 3 · 联网 3 · 计算 1 · 技能 2 · 交互 3） | ✅ | 纯计算或只读 |
| `extract_fields` | ❌ | 需要注入 `LLMClient` |
| `build_assumptions` | ❌ | 需要注入 `LLMClient` |
| `parse_document` | ❌ | 需要文件字节流，且在 `EXCLUDED` 中显式排除 |

20 个暴露工具：`ask_user` · `compute_metrics` · `current_datetime` · `dcf_valuation` · `fetch_url` · `financial_history` · `financial_ratio_suite` · `list_skills` · `load_skill` · `locate_evidence` · `peer_comparison` · `python_calc` · `relative_valuation` · `sensitivity_grid` · `set_conversation_title` · `stock_history` · `stock_quote` · `summarize_valuation` · `web_search` · `yoy_compare`

被排除的工具若被调用，会返回明确的错误信息说明原因，而不是静默失败。

### Schema 转换

注册表里的 `input_schema` 是简化格式 `{"参数名": "类型描述"}`，需要转成标准 JSON Schema：

```python
TYPE_MAP = {
    "str": "string",
    "int": "integer",
    "float": "number",
    "bool": "boolean",
    "dict": "object",
    "list": "array",
}
```

转换时还要识别描述中的「（可选）」标记，据此决定是否加入 `required` 列表。

### 请求处理

MCP 2.x 使用低层 API，通过 `add_request_handler` 注册方法处理器：

```python
server.add_request_handler("tools/list", types.ListToolsRequest, handle_list_tools)
server.add_request_handler("tools/call", types.CallToolRequestParams, handle_call_tool)
```

处理器签名是 `async def handler(ctx, params) -> Result`。

### 启动方式

```bash
cd backend
uv run python -m app.mcp_server
```

以 stdio 模式运行，适合被 MCP 客户端作为子进程拉起。

### 客户端配置示例

Claude Desktop 的 `claude_desktop_config.json`：

```json
{
  "mcpServers": {
    "weister": {
      "command": "uv",
      "args": ["run", "--directory", "C:/path/to/Weister/backend", "python", "-m", "app.mcp_server"]
    }
  }
}
```

---

## 运行日志

`app/runlog.py` 把执行过程中的每个事件持久化到文件，用于事后审计与问题复现。

### 与检查点的区别

| | 检查点 | 运行日志 |
| --- | --- | --- |
| 目的 | 断点续跑 | 审计与复现 |
| 内容 | 节点完成状态、Agent 输出 | 完整事件流（含时间戳） |
| 粒度 | 节点级 | 事件级 |
| 位置 | `data/checkpoints/` | `data/runs/` |

### 文件结构

```
data/runs/{run_id}/
├── events.jsonl      逐行 JSON，每个事件一行
└── summary.json      运行摘要
```

**events.jsonl** 样例：

```json
{"kind": "run_start", "filename": "annual_report.txt", "provider": "deepseek", "model": "deepseek-chat", "question": "分析盈利质量、现金流风险并给出估值区间。", "seq": 1, "ts": 1789052049.415874}
{"kind": "event", "type": "tool_call", "node": "analysis", "message": "tool: dcf_valuation", "payload": {"agent": "valuation_expert"}, "seq": 42, "ts": 1789052051.234567}
{"kind": "event", "type": "tool_result", "node": "analysis", "message": "dcf_valuation · 成功", "seq": 43, "ts": 1789052051.289012}
{"kind": "run_end", "status": "success", "seq": 128, "ts": 1789052060.123456}
```

使用 JSONL 而非单个 JSON 数组的原因：流式追加写入，不需要在内存里累积，进程崩溃时已写入的内容仍然可读。

**summary.json** 样例：

```json
{
  "run_id": "96579d894f26",
  "status": "success",
  "started_at": 1789052049.4157772,
  "ended_at": 1789052060.1234567,
  "duration_ms": 10708,
  "event_count": 128,
  "tool_calls": {
    "extract_fields": 1,
    "build_assumptions": 1,
    "dcf_valuation": 1,
    "sensitivity_grid": 1
  },
  "errors": []
}
```

### 敏感信息脱敏

日志会自动移除 API Key 等敏感字段：

```python
SENSITIVE_KEYS = {"api_key", "apikey", "authorization", "token", "secret"}

def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: ("***" if k.lower() in SENSITIVE_KEYS else _sanitize(v))
            for k, v in value.items()
        }
    ...
```

递归处理嵌套结构，任何层级出现这些键名都会被替换为 `***`。

### 消息截断

单条消息可能很长（如报告全文），日志中截断到 2000 字：

```python
message = event.get("message")
if isinstance(message, str):
    record["message"] = message[:2000]
```

需要完整内容时从检查点或结果接口读取。

### 查询接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/logs` | 日志摘要列表 |
| GET | `/api/logs/{run_id}` | 单次运行的完整事件流 |
| DELETE | `/api/logs/{run_id}` | 删除日志 |

---

## 数据流全景

```
用户点击运行
    │
    ▼
POST /api/analyze  ──▶  创建检查点  ──▶  graph.astream(state)
                                              │
                          ┌───────────────────┴───────────────────┐
                          │                                       │
                     custom 事件流                          values 快照
                          │                                       │
                          ▼                                       ▼
                   SSE 逐条推送                            最终 state
                          │                                       │
                          ▼                                       ▼
                    前端分流渲染                           result 事件
                          │
        ┌─────────────────┼─────────────────┐
        ▼                 ▼                 ▼
   调度中心窗口     各智能体窗口       结果面板
```

`astream(stream_mode=["custom", "values"])` 一次执行同时拿到事件流与最终状态，避免了「先跑一遍拿事件、再跑一遍拿状态」的重复执行。
