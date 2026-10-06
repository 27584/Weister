# Weister 开发与扩展指南

本文档面向需要修改代码或扩展功能的开发者。

---

## 目录

- [开发环境](#开发环境)
- [代码规范](#代码规范)
- [新增工具](#新增工具)
- [新增技能](#新增技能)
- [新增智能体](#新增智能体)
- [修改执行流程](#修改执行流程)
- [扩展 MCP 工具](#扩展-mcp-工具)
- [新增日志字段](#新增日志字段)
- [前端扩展](#前端扩展)
- [调试技巧](#调试技巧)
- [桌面端构建](#桌面端构建)
- [测试与验证](#测试与验证)

---

## 开发环境

### 后端

```bash
cd backend
uv sync
uv run uvicorn app.main:app --reload --port 8000
```

代码规范检查：

```bash
uv run ruff check app
uv run ruff format app
```

配置在 `pyproject.toml`：

```toml
[tool.ruff]
line-length = 100
target-version = "py312"
```

### 前端

```bash
cd frontend
pnpm install
pnpm dev
```

类型检查与构建：

```bash
pnpm build
```

### 验证注册表

修改工具 / 技能 / 智能体后，用这条命令快速验证：

```bash
cd backend
uv run python -c "
from app.main import app
from app.core.registry import registry
c = registry.catalog()
print('tools  :', [t['name'] for t in c['tools']])
print('skills :', [s['name'] for s in c['skills']])
print('agents :', [a['key'] for a in c['agents']])
"
```

---

## 代码规范

### 分层原则

| 层 | 可以依赖 | 不可以依赖 |
| --- | --- | --- |
| `tools/` | `core/`、`llm.py` | `agents/`、`orchestrator.py` |
| `agents/` | `core/`、`llm.py`、`events.py` | `orchestrator.py`、`chat_supervisor.py`、`api/` |
| `orchestrator.py` / `chat_supervisor.py` | 以上全部 | `api/` |
| `api/` | 以上全部 | — |

下层不得感知上层。`tools/` 中的函数不应该知道是谁在调用它。

### 注释规范

**模块级 docstring**：每个 `.py` 文件开头一句话说明职责。

```python
"""文档解析。

支持 PDF 与纯文本，输出全文、分页引用与切片列表。
"""
```

**函数 docstring**：非显而易见的函数需要说明参数含义与副作用。简单的工具函数可以省略。

**行内注释**：只解释「为什么」，不解释「是什么」。

```python
# 差
i += 1  # 索引加一

# 好
# LangGraph 的 writer 绑定在 runnable context，子线程直接调用会抛异常，
# 因此改用队列把事件传回主线程
event_queue.put(payload)
```

### 类型标注

所有函数签名都要标注类型。使用 `from __future__ import annotations` 让标注延迟求值。

```python
from __future__ import annotations

def compute_metrics(extracted: dict[str, Any]) -> dict[str, Any]:
    ...
```

---

## 新增工具

工具是模型可直接调用的原子能力。

### 步骤

**1. 在 `tools/` 下新建模块或在现有模块追加**

```python
# backend/app/tools/my_tools.py
"""自定义工具集。"""
from __future__ import annotations

from typing import Any

from ..core.registry import Tool, registry


def calculate_wacc(
    equity: float,
    debt: float,
    cost_equity: float,
    cost_debt: float,
    tax_rate: float,
) -> dict[str, Any]:
    total = equity + debt
    if total <= 0:
        raise ValueError("权益与债务之和必须为正")

    weight_e = equity / total
    weight_d = debt / total
    wacc = weight_e * cost_equity + weight_d * cost_debt * (1 - tax_rate)

    return {
        "wacc": round(wacc, 4),
        "weight_equity": round(weight_e, 4),
        "weight_debt": round(weight_d, 4),
    }


registry.add_tool(Tool(
    name="calculate_wacc",
    description="按资本资产定价模型计算加权平均资本成本",
    input_schema={
        "equity": "float",
        "debt": "float",
        "cost_equity": "float",
        "cost_debt": "float",
        "tax_rate": "float",
    },
    handler=calculate_wacc,
    tags=["valuation", "deterministic"],
))
```

**2. 在 `tools/__init__.py` 中导入**

```python
from . import my_tools as _my_tools  # noqa: F401
```

导入即注册。若不加这行，工具不会被加载。

**3. 验证**

```bash
uv run python -c "
from app.core.registry import registry
import app.tools
print([t.name for t in registry.tools.values()])
"
```

### 注入运行时对象

工具若需要 `LLMClient` 或流式回调，用 `inject` 声明：

```python
registry.add_tool(Tool(
    name="my_llm_tool",
    description="...",
    input_schema={"text": "str"},
    handler=my_llm_tool,
    inject=["client", "on_delta"],
))
```

函数签名相应接收：

```python
def my_llm_tool(
    text: str,
    client: LLMClient,
    on_delta: Callable[[Any], None] | None = None,
) -> dict[str, Any]:
    ...
```

**注意**：不要把这些参数写进 `input_schema`，否则模型会尝试自己填。

### 错误处理

工具内抛异常会被执行器捕获并转成失败结果回灌给模型：

```python
try:
    result = handler(**kwargs)
except Exception as exc:
    return False, None, f"{type(exc).__name__}: {exc}"
```

因此可以直接抛 `ValueError`，让模型看到错误信息并决定下一步。

---

## 新增技能

技能是 Markdown 提示词文件，告诉智能体「这类任务该怎么做」。

### 步骤

在 `backend/app/skills/` 下创建 `my_skill.md`：

```markdown
---
name: comparable_analysis
description: 可比公司分析。当需要选择可比公司并计算估值倍数时使用。
tools:
  - calculate_wacc
  - relative_valuation
tags:
  - finance
  - valuation
---

# 可比公司分析技能

## 适用场景

- 需要为标的公司筛选可比公司
- 需要计算行业平均估值倍数

## 工作流程

### 第一步：筛选可比公司

选择标准（按优先级排序）：

1. 同行业、同细分赛道
2. 收入规模差异在 3 倍以内
3. 商业模式相似

### 第二步：计算倍数

调用 `relative_valuation`，传入标的的净利润与营收。

## 输出规范

- 列出每家可比公司的名称与选取理由
- 给出倍数区间及其分布
- 说明极端值是否剔除及原因

## 常见陷阱

1. **周期股**：高点时 PE 偏低，需用正常化盈利
2. **亏损公司**：PE 失效，改用 PS
3. **一次性损益**：需剔除后再计算倍数
```

### frontmatter 字段

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `name` | 是 | 唯一标识，与文件名一致 |
| `description` | 是 | 展示给模型，说明何时使用 |
| `tools` | 否 | 该技能涉及的工具名列表 |
| `tags` | 否 | 分类标签 |

### 验证

```bash
uv run python -c "
from app.core.registry import registry
registry.load_skills()
print([s.name for s in registry.skills.values()])
"
```

---

## 新增智能体

### 步骤

**1. 在 `agents/specialists.py` 添加定义**

```python
MACRO_ANALYST = AgentSpec(
    key="macro_analyst",
    name="宏观分析师",
    role="评估宏观经济对标的的影响",
    system_prompt=(
        "你是宏观分析师，负责评估利率、汇率、政策等宏观因素"
        "对标的公司经营与估值的影响。"
        "你的分析必须落到具体财务科目上，不要泛泛而谈。"
    ),
    tools=["list_skills", "load_skill", "compute_metrics"],
    skills=["financial_analysis"],
    max_steps=4,
)
```

**2. 加入 `SPECIALISTS` 列表**

```python
SPECIALISTS = [
    FINANCIAL_ANALYST,
    VALUATION_EXPERT,
    RISK_REVIEWER,
    DEVILS_ADVOCATE,
    MACRO_ANALYST,
]
```

**3. 在编排器中安排到某个分组**

编辑 `orchestrator.py`：

```python
COORDINATOR_PLAN = [
    {"key": "financial_analyst", "node": "analysis", "task": "..."},
    {"key": "valuation_expert", "node": "analysis", "task": "..."},
    {"key": "macro_analyst", "node": "analysis", "task": "评估宏观因素影响。"},
]
```

同一 `node` 的智能体会并行执行。

**4. 前端补充元数据**

`frontend/src/hooks/useAgentTimeline.ts`：

```typescript
const AGENT_META: Record<string, { name: string; role: string }> = {
  macro_analyst: { name: "宏观分析师", role: "评估宏观经济影响" },
};
```

`frontend/src/lib/runMeta.ts`（顺序须与后端注册顺序保持一致）：

```typescript
export const AGENT_ORDER = [
  SYSTEM_KEY,
  "coordinator",
  "financial_analyst",
  "valuation_expert",
  "risk_reviewer",
  "devils_advocate",
  "market_analyst",
  "research_assistant",
  "report_writer",
];
```

显示名与角色在 `frontend/src/hooks/useAgentTimeline.ts` 的 `AGENT_META` 里补充（`extractor` 是节点级伪智能体，只出现在 `AGENT_META` 与 `AgentStage` 中，不在 `AGENT_ORDER` 里）。

**5. 验证**

```bash
uv run python -c "
from app.main import app
from app.core.registry import registry
print([a.key for a in registry.agents.values()])
"
```

### 调整智能体行为

| 参数 | 作用 |
| --- | --- |
| `system_prompt` | 核心指令，决定角色定位与输出风格 |
| `tools` | 工具白名单，不在列表中的调用会被拒绝 |
| `skills` | 可加载的技能，影响 system prompt 中的技能清单 |
| `max_steps` | 最多循环步数（默认 24），仅防御真正的死循环 |

> 输出长度不在 `AgentSpec` 上约束：`LLMClient.stream_messages()` 默认不传 `max_tokens`，由模型自行收尾；单条工具结果超 6000 字会在回灌前截断。

---

## 修改执行流程

### 调整节点顺序

编辑 `orchestrator.py` 的 `NODES`：

```python
NODES = [
    ("ingest", ingest),
    ("extract", extract),
    ("coordinator", coordinator),
    ("analysis", analysis_group),
    ("review", review_group),
    ("report", report),
]
```

`build_graph()` 按列表顺序线性连接。

### 增加分支或条件

当前是线性图。若需条件分支，改用 LangGraph 的条件边：

```python
g.add_conditional_edges(
    "extract",
    lambda s: "skip" if not (s.get("extracted") or {}).get("fields", {}).get("revenue") else "go",
    {"skip": "report", "go": "coordinator"},
)
```

### 调整专家分组

编辑 `COORDINATOR_PLAN` 和 `REVIEW_PLAN`。同一列表内的智能体并行，两个列表之间串行。

---

## 扩展 MCP 工具

MCP 服务器自动从注册表读取工具，**新增工具通常无需改 MCP 代码**。

### 自动暴露

在 `tools/` 注册新工具后，只要满足：

1. 不在 `mcp_server.py` 的 `EXCLUDED` 集合中
2. `inject` 为空（不依赖运行时对象）

就会被自动暴露给 MCP 客户端。

### 排除工具

若某工具不应通过 MCP 暴露（如需注入 LLM 客户端），把它加入 `EXCLUDED`：

```python
# backend/app/mcp_server.py
EXCLUDED = {"parse_document", "my_special_tool"}
```

或者在注册时声明 `inject`，MCP 层会自动跳过：

```python
registry.add_tool(Tool(
    name="my_llm_tool",
    ...
    inject=["client"],   # 有此字段即不暴露
))
```

### 自定义 Schema

注册表的 `input_schema` 是简化格式。若需要更复杂的 JSON Schema（如嵌套对象、枚举），在 `_json_schema()` 中扩展转换逻辑：

```python
def _json_schema(tool: Tool) -> dict[str, Any]:
    # 当前实现：类型关键词映射
    # 扩展点：支持 enum、array items、嵌套 object
    ...
```

### 验证

启动 MCP 服务器后，用 Inspector 检查：

```bash
npx @modelcontextprotocol/inspector uv run python -m app.mcp_server
```

或在 Python 中直接调用：

```python
from app.mcp_server import _available_tools
for t in _available_tools():
    print(t.name, list(t.input_schema.get("properties", {}).keys()))
```

---

## 新增日志字段

日志记录在 `RunLogger.event()` 中，默认写入事件的 `type` / `node` / `status` / `message` / `payload`。

### 添加自定义字段

若需要记录额外信息，在节点中把它放进 `payload`：

```python
emit(
    EventType.TOOL_RESULT,
    status=NodeStatus.SUCCESS,
    message="计算完成",
    payload={
        "agent": spec.key,
        "metrics": metrics,
        "my_custom_field": "value",   # 会自动出现在日志里
    },
)
```

日志会自动序列化整个 `payload`，无需改 `runlog.py`。

### 修改脱敏规则

若某个新字段含敏感信息，加入 `SENSITIVE_KEYS`：

```python
# backend/app/runlog.py
SENSITIVE_KEYS = {"api_key", "apikey", "authorization", "token", "secret", "my_secret"}
```

匹配是大小写不敏感的。

### 调整消息截断长度

默认截断到 2000 字（`runlog.py` 的 `RunLogger.event()` 内直接写死长度）：

```python
# backend/app/runlog.py
message = event.get("message")
if isinstance(message, str):
    record["message"] = message[:2000]   # 改这里的字面量即可调整上限
```

### 日志格式说明

采用 JSONL（每行一个 JSON 对象）而非单个 JSON 数组，原因是：

- **流式追加**：不需要在内存里累积，写完即落盘
- **崩溃安全**：进程异常退出时，已写入的行仍可读取
- **便于 grep**：可直接用文本工具搜索特定事件

---

## 前端扩展

### 新增结果标签页

编辑 `components/PipelineResult.tsx`（导出组件 `PipelineResultView`）：

**1. 在 `TABS` 添加项**（现有 4 项，`TabKey` 联合类型需同步扩展）

```typescript
type TabKey = "report" | "valuation" | "data" | "experts" | "my_tab";

const TABS: { key: TabKey; label: string }[] = [
  { key: "report", label: "研究报告" },
  { key: "valuation", label: "估值建模" },
  { key: "data", label: "结构化数据" },
  { key: "experts", label: "专家意见" },
  { key: "my_tab", label: "我的视图" },
];
```

**2. 添加渲染分支**

```tsx
{result && tab === "my_tab" && (
  <div className="rounded-[var(--radius-box)] border border-base-300 bg-base-100 p-3">
    {/* 内容 */}
  </div>
)}
```

### 新增事件类型

**1. 后端 `events.py` 添加枚举值**

```python
class EventType(str, Enum):
    MY_EVENT = "my_event"
```

**2. 在节点中发送**

```python
emit(EventType.MY_EVENT, status=NodeStatus.RUNNING, message="...", payload={...})
```

**3. 前端 `lib/types.ts` 同步类型**

```typescript
export type EventType =
  | "run_start"
  | "my_event";
```

**4. 在 `useAgentTimeline.ts` 中处理**

```typescript
if (ev.type === "my_event") {
  // 更新对应 agent 的状态
}
```

### 调整布局

主界面是「顶栏 + 主区」的 flex 布局（`app/page.tsx`）：

- 顶栏：模型状态、新对话、协作、设置、`对话 / 建模` 形态切换
- 会话侧栏：`ConversationSidebar`，可折叠
- 内容区：`appMode === "chat"` 时是 `ChatPanel`；`"pipeline"` 时是 `PipelineProgress` + `PipelineResultView`
- 右侧：`AgentStage` 协作面板，宽度可拖动（拖动条 `onMouseDown` 改宽度）

智能体窗口内部用动态网格：单个窗口占满一行，两个及以上均为两列。

```tsx
const cols = list.length <= 1 ? 1 : 2;

<div style={{ gridTemplateColumns: "repeat(" + cols + ", minmax(0, 1fr))" }}>
```

**关键**：所有 flex/grid 子项都要加 `min-w-0`，否则长文本会撑破容器。

---

## 调试技巧

### 查看完整事件流

用 curl 直接观察 SSE：

```bash
curl -N "http://127.0.0.1:8000/api/analyze/demo" \
  -H "X-LLM-Provider: deepseek" \
  -H "X-LLM-Model: deepseek-chat" \
  -H "X-LLM-Api-Key: sk-..."
```

`-N` 禁用缓冲，事件会实时打印。

### 检查检查点内容

```bash
curl http://127.0.0.1:8000/api/runs
curl http://127.0.0.1:8000/api/runs/{run_id} | python -m json.tool
```

关注 `completed_nodes`、`agents`、`report_md` 字段。

### 单测某个工具

```bash
uv run python -c "
from app.tools.valuation import dcf_valuation
result = dcf_valuation(
    base_revenue=1e10,
    assumptions={
        'wacc': 0.10,
        'terminal_growth': 0.025,
        'forecast_years': 5,
        'growth_rates': [0.15, 0.12, 0.10, 0.08, 0.06],
        'fcf_margin': 0.08,
    },
    net_debt=1e9,
)
print(result)
"
```

### 观察某位智能体的行为

最直接的方式是看该智能体窗口的日志行，会显示「第 N 步」和工具调用记录。

也可以在后端加临时日志：

```python
# agents/base.py 的循环内
print(f"[{spec.key}] step {step}: {reply[:200]}")
```

### 后端日志

`dev.ps1` 用 `Start-Process -NoNewWindow` 直启进程，日志直接打在启动它的终端里（不再落 `be_err.log`）。
要单独观察后端输出，手动启动即可：

```bash
cd backend
uv run uvicorn app.main:app --reload --port 8000
```

### 前端构建错误

```bash
cd frontend
pnpm build 2>&1 | Select-Object -Last 30
```

TypeScript 错误会在这里暴露。

---

## 桌面端构建

### 目录与角色

```
electron/
├── main.cjs                        主进程：启动序列 / 动态端口 / 加载窗口 / 进程清理
├── preload.cjs                     注入 window.WEISTER 桥（API 基址 + 窗口控制）
├── loading.html                    启动加载页（独立无边框小窗）
├── build/icon.ico · icon.png       应用图标（深墨底白 W）
├── scripts/prepare-frontend.cjs    打包前置（见下）
└── package.json                    electron-builder 配置，portable 目标 → release/
```

### 桌面端开发调试

```bash
# 前端先构建 standalone（桌面壳跑的是 standalone server.js，不是 next dev）
cd frontend && pnpm build

# 从 electron 目录启动壳（开发模式会用 backend/.venv 的 Python + .next/standalone）
cd electron
pnpm install
pnpm dev
```

开发模式下 Electron 直接复用仓库内 `backend/.venv` 与 `frontend/.next/standalone`，改前端代码后需重新 `pnpm build` 再重启壳。

### 打包前置：prepare-frontend.cjs

electron-builder 打包前由 `prebuild` 钩子自动执行，做四件事：

1. 把 `frontend/.next/static` 与 `frontend/public` 同步进 standalone（与 BUILD_ID 同源，缺了会 chunk 404 白屏）
2. 探测 standalone/node_modules 里的 pnpm 符号链接并解引用物化（junction 指向构建机绝对路径，换机器即断），自检 next / react / react-dom 为真实目录
3. 校验 `standalone/.next/BUILD_ID` 存在
4. 把 standalone 铺到 `electron/build/frontend`——electron-builder 的 extraResources 会按 glob 展开跳过 `.` 开头目录，`.next` 必须换成无隐藏段的路径

### 一键构建

```powershell
.\scripts\build.ps1                 # 三步全跑
.\scripts\build.ps1 -SkipBackend    # backend/python 已就绪时
```

三步依次是：

| 步骤 | 脚本 | 产物 |
| --- | --- | --- |
| 1. 嵌入式 Python | `scripts/prepare-python.ps1` | `backend/python/`（Python 3.12 嵌入式发行版 + 12 个运行时依赖） |
| 2. 前端 standalone | frontend `pnpm build` | `frontend/.next/standalone/` |
| 3. Electron 打包 | electron `pnpm build`（electron-builder） | `electron/release/*.exe`（portable 免安装单文件） |

### 嵌入式 Python 的隔离约束（重要）

`scripts/prepare-python.ps1` 头部注释记录了完整踩坑链路，改打包逻辑前先读它。要点：

- 嵌入式包的 `._pth` 使 Python 进入 isolated 模式，**忽略 `PYTHON*` 环境变量**，`PYTHONNOUSERSITE` 无效
- 唯一可靠的隔离开关是命令行 `-s` 旗标——`electron/main.cjs` 的 `BACKEND_ARGS = ["-s", "-m", "app"]` 不可改成其他启动方式
- 验证脚本会检查每个依赖模块的 `__file__` 是否 resolve 到 `backend/python` 内部，防止「构建机 pip 假装装好、分发机 ModuleNotFoundError」的假通过
- 后端入口必须是 `python -m app`（`app/__main__.py` 读 `HOST`/`PORT` 环境变量；直接跑 uvicorn 不读 `PORT`，会静默回退 8000 与动态端口分配不一致）

### 数据目录约定

桌面版数据统一落 `%APPDATA%\Weister\data`：

- `backend/app/paths.py` 的 `APP_NAME = "Weister"` 必须与 Electron `userData` 末级目录同名，否则前后端各写一份数据
- `.env` 读取用绝对路径（`paths.env_file()`），`python -m app` 与 `uvicorn --reload` 读到同一份
- 改任何落盘逻辑时从 `paths.py` 取路径，不要用相对 `cwd` 的写法——打包后工作目录是安装目录

---

## 测试与验证

### 冒烟测试

修改代码后依次执行：

```bash
# 1. 模块导入
cd backend
uv run python -c "from app.main import app; print('import OK')"

# 2. 注册表完整
uv run python -c "
from app.main import app
from app.core.registry import registry
c = registry.catalog()
assert len(c['tools']) >= 23
assert len(c['skills']) >= 9
assert len(c['agents']) >= 8
print('registry OK')
"

# 3. 前端构建
cd ../frontend
pnpm build
```

### 端到端验证

启动服务后：

```bash
curl http://127.0.0.1:8000/api/health
curl -N "http://127.0.0.1:8000/api/analyze/demo" \
  -H "X-LLM-Provider: custom" \
  -H "X-LLM-Model: xxx" \
  -H "X-LLM-Api-Key: sk-xxx" \
  -H "X-LLM-Base-Url: https://..."
```

预期事件序列：

```
run_start
node_start(ingest)
node_end(ingest)
agent_start(extractor)
tool_call(extract_fields)
tool_result(extract_fields)
agent_end(extractor)
node_end(extract)
node_start(coordinator)
...
result
run_end
```

### 回归检查清单

修改后确认：

- [ ] `uv run python -c "from app.main import app"` 无报错
- [ ] `pnpm build` 通过
- [ ] `/api/registry` 返回的数量正确
- [ ] 用样例跑一次完整流程
- [ ] 结果面板四个标签页都有数据
- [ ] 断点续跑能跳过已完成节点

---

## 常见开发陷阱

### 1. 工具未注册

在 `tools/` 新增模块后，必须在 `tools/__init__.py` 导入，否则不会被加载。

### 2. 子线程调用 writer 抛异常

LangGraph 的 `get_stream_writer()` 绑定在 runnable context。子线程中要用队列传回主线程发送。参考 `orchestrator.py` 的 `_run_group()`。

### 3. 前端容器被撑开

任何包含长文本的 flex/grid 子项都要加 `min-w-0`。

### 4. 工具返回过长挤爆上下文

单条工具结果超过 6000 字会先截断再回灌（`agents/base.py`）。新增工具若返回体很大，最好在工具内部裁剪或分页，别依赖下游截断。

### 5. 重复执行图

用 `astream(stream_mode=["custom", "values"])` 一次拿事件与状态，不要 `astream` 完再 `ainvoke`。

### 6. 事件类型前后端不同步

新增 `EventType` 后若没同步 `frontend/src/lib/types.ts` 与 `hooks/useAgentTimeline.ts`，该事件会被前端静默忽略（未知类型直接跳过）。改完记得两端一起过。
