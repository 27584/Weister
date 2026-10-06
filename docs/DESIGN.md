# Weister 系统设计文档

> 金融投研智能体 · 多智能体协作的自动化估值建模系统
> 文档基于**当前代码实测**编写（backend/app 50 个 Python 文件 + frontend/src 31 个源文件 + electron/ 桌面壳，2026-10-07 复核），非纯文档转述。

---

## 0. 阅读须知：与既有文档的差异

仓库中已有的 `docs/ARCHITECTURE.md` 部分内容与当前实现**已经不一致**，本文件以代码为准。主要差异见 [第 10 节](#10-代码与文档不一致项)。

架构图见同目录 [`architecture.html`](./architecture.html)（浏览器直接打开）。

---

## 1. 系统概览

Weister 读取上市公司财报（PDF / TXT），自动完成**结构化抽取 → 指标计算 → DCF 与相对估值建模 → 四位专家并行评审 → 生成带来源标注的买方投资简报**。

| 维度 | 事实 |
| --- | --- |
| 编排框架 | 建模形态：LangGraph `StateGraph`，6 个节点线性串联 + 组内并行；对话形态：`chat_supervisor.py` 的主管循环（非 StateGraph） |
| 智能体数量 | 8 个（1 主管 + 4 评审专家 + 1 市场数据研究员 + 1 信息研究员 + 1 撰写人），另有 1 个节点级伪智能体 `extractor` |
| 工具数量 | 23 个（文档 2 · 抽取与指标 6 · 估值 5 · 行情 3 · 联网 3 · 计算 1 · 技能 2 · 交互 2） |
| 技能数量 | 9 份 Markdown 技能说明书（`app/skills/*.md`） |
| 事件类型 | 15 种，统一走 SSE |
| 对外协议 | REST + SSE；另提供 MCP stdio 服务器 |
| REST 端点 | 27 条（meta 17 · analyze 3 · chat 7） |
| 持久化 | 检查点（断点续跑）+ 运行日志（审计复现），均为文件 JSON |
| 桌面形态 | Electron portable 单文件：动态端口拉起后端（嵌入式 Python）与前端（standalone）子进程，数据统一落 `%APPDATA%\Weister\data` |

---

## 2. 技术栈

| 层 | 技术 | 说明 |
| --- | --- | --- |
| 前端 | Next.js 16 · TypeScript · Tailwind v4 · DaisyUI v5 · Framer Motion | App Router，`"use client"` 单页交互 |
| 后端 | Python ≥3.12 · FastAPI · Uvicorn | ASGI，`StreamingResponse` 承载 SSE |
| 编排 | LangGraph ≥0.2.60 · LangChain Core | 状态图 + `get_stream_writer()` 自定义事件 |
| 文档解析 | PyMuPDF ≥1.24（AGPL-3.0） | 逐页提文本，保留页码 |
| HTTP 客户端 | HTTPX ≥0.27 | 流式调用 OpenAI 兼容端点 |
| 模型协议 | OpenAI 兼容 | DeepSeek / 通义千问 / 智谱 GLM / Kimi / OpenAI / Ollama 本地 / 自定义 |
| 工具互操作 | MCP Python SDK ≥1.0 | stdio 模式对外暴露纯计算工具 |
| 配置 | pydantic-settings | `.env` 兜底，前端请求头优先 |
| 桌面端 | Electron 33 · electron-builder 25 | Windows portable 免安装单文件；内置 Python 3.12 嵌入式运行时与 Next.js standalone，动态端口拉起前后端子进程 |

---

## 3. 分层架构

```
┌──────────────────────────────────────────────────────────────┐
│ 表现层   frontend/src/                                        │
│  page.tsx · ChatPanel · PipelineProgress · PipelineResultView  │
│  AgentStage · ConversationSidebar · SettingsModal               │
├──────────────────────────────────────────────────────────────┤
│ 传输层   app/api/                                               │
│   REST 端点 · SSE 帧封装 · 请求头凭据解析 · CORS              │
├──────────────────────────────────────────────────────────────┤
│ 编排层   orchestrator.py · state.py · checkpoint.py           │
│   LangGraph 图 · 节点定义 · 专家团并行调度 · 断点续跑          │
├──────────────────────────────────────────────────────────────┤
│ 智能体层 agents/                                              │
│   base.py(ReAct 执行器) · coordinator.py · specialists.py      │
├──────────────────────────────────────────────────────────────┤
│ 能力层   core/registry.py · tools/ · skills/                   │
│   Tool / Skill / Agent 注册表 · 原子能力 · 提示词说明书         │
├──────────────────────────────────────────────────────────────┤
│ 基础设施 llm.py · providers.py · storage.py · events.py        │
│   runlog.py · config.py · mcp_server.py · models.py            │
└──────────────────────────────────────────────────────────────┘
```

**依赖方向**：严格单向向下。`tools/` 中的函数是纯能力，不知道谁在调用它们；`agents/` 不感知 `orchestrator`，只通过 `emit` 回调向外发事件。

**注册时机**：`import app.agents` 时触发 `bootstrap()` —— 导入 `tools` 包（模块级 `registry.add_tool`）、`registry.load_skills()`（扫描 `skills/*.md`）、注册 6 位专家 + 撰写人 + 主管。`app/api/` 在模块顶层调用 `bootstrap_agents()` 保证注册完成。

---

## 4. 核心模块

### 4.1 注册表 `core/registry.py`

三个不可变 dataclass 构成系统的类型骨架。

```python
@dataclass(frozen=True)
class Tool:
    name: str                      # 模型调用时使用的唯一标识
    description: str               # 展示给模型的用途说明
    input_schema: dict[str, str]   # 简化格式 {"参数名": "类型描述"}
    handler: Callable[..., Any]
    tags: list[str]
    inject: list[str]              # 需要运行时注入的对象

@dataclass(frozen=True)
class Skill: name, description, tools, body, path, tags

@dataclass(frozen=True)
class AgentSpec:
    key, name, role, system_prompt
    tools: list[str]               # 工具白名单
    skills: list[str]              # 要内联进 system prompt 的技能
```

**两个关键设计：**

1. **`inject` 注入机制**。`extract_fields` 需要 `LLMClient` 和流式回调，但这些不该出现在模型的参数列表里。执行器在调用前按声明注入：

   ```python
   if "client" in tool.inject:   kwargs["client"]   = ctx.client
   if "on_delta" in tool.inject: kwargs["on_delta"] = ctx.delta_handler(step)
   ```

   同时 `inject` 也是 MCP 暴露的过滤器——带注入的工具无法脱离运行时上下文独立调用。

2. **`Tool.json_schema()`**。把简化格式实时转换成标准 JSON Schema，供 OpenAI `tools` 参数与 MCP 客户端复用。带「（可选）」标记的参数不进入 `required`：

   ```python
   optional = "可选" in desc
   base = desc.replace("（可选）", "").strip()
   for key, mapped in _TYPE_MAP.items():   # str→string, dict→object, list→array ...
       if base.startswith(key): json_type = mapped; break
   ```

**Skill 为什么用 Markdown 而不是函数**：技能的核心价值是「怎么做」的流程知识，不是「能做什么」的能力。用文件存储让金融背景的队友也能参与编写迭代，不必改代码。`_parse_frontmatter()` 手写了一个迷你 YAML 解析器，只支持本项目用到的 `key: value` 与列表语法，避免引入 PyYAML 依赖。

### 4.2 智能体执行器 `agents/base.py` — ReAct 循环

**这是全系统最核心的模块。**当前实现使用**原生 function calling**：把工具声明为 OpenAI 格式的 `tools` 参数，模型返回结构化 `tool_calls`，**不需要任何文本解析**。

单轮流程：

```
1. 构造 messages = [system(含工具说明+技能正文)] + 历史对话
2. client.stream_messages(..., tools=tool_decls) 流式拉取
3. 分片处理：
     delta.reasoning → THINKING 事件
     delta.content   → TOKEN 事件 + 累积进 buffer
     delta.tool_call → 按 index 累积 {id, name, arguments}
                       （arguments 是分片字符串，必须拼接后再 json.loads）
4. 无 tool_calls 且正文非空 → 正文即最终结论，跳出
5. 有 tool_calls → 追加 assistant 消息 → 逐个执行 → 结果以 role="tool" 回灌
```

**终止条件（三重保险 + 防御性硬上限）：**

| 条件 | 行为 |
| --- | --- |
| 模型未返回 `tool_calls` 且正文非空 | 正常收敛，正文即最终结论 |
| 完全空输出且连续 3 步 | 判定停滞，用 `best_body` 收尾 |
| 有工具调用 | 视为有进展，停滞计数清零 |
| 触及 `spec.max_steps`（默认 24） | 强制收尾，`agent_end.payload.truncated = true` |

**为什么仍有 `max_steps`**：终止以进展检测为主，常规任务触不到 24 步这个上限；但进展检测把「有工具调用」一律视为有进展，模型若稳定地反复调用工具就能无限跑——只有硬上限能截断。触顶后不丢弃已有内容，由循环外的收尾逻辑复用 `best_body`。

**权限校验在两层**：工具必须存在于注册表，且必须在 `spec.tools` 白名单内，否则以 `role="tool"` 消息返回明确的拒绝原因（而非静默失败），让模型能自我纠正。

**工具结果回灌**：成功返回的 dict 除了序列化进对话（超过 6000 字截断），同时存入 `artifacts[name]` —— 编排器靠这个字典提取结构化产物。

**System Prompt 构建**（`build_system_prompt`）：

```python
def _render_skills(names):
    """把技能正文完整拼进 prompt。
    内联而非运行时加载，原因有二：
        1. 省去每个智能体一轮 load_skill 调用
        2. 让技能正文成为稳定的 prompt 前缀，命中 API 的自动缓存
    因此这里不做时间戳、随机数等易变内容的拼接。
    """
```

技能正文被**内联**进 system prompt，而非让智能体运行时调 `load_skill` 工具拉取。

### 4.3 图编排 `orchestrator.py`

`StateGraph(InvestState)` 注册 6 个节点，用 `add_edge` 顺序串联：

```
START → ingest → extract → coordinator → analysis → review → report → END
```

| 节点 | 执行者 | 并行度 | 产出 |
| --- | --- | --- | --- |
| `ingest` | 调度中心 | — | `document_text` / `chunks` / `focus_text` / `focus_pages` / `citations` |
| `extract` | 数据提取员（伪智能体） | — | `extracted` / `metrics` |
| `coordinator` | 投研主管 | — | 静态计划（6 位专家分两组） |
| `analysis` | 财务分析师 + 估值专家 | **2 线程并行** | `analyses` / `assumptions` / `dcf` / `relative` / `sensitivity` / `valuation_summary` |
| `review` | 风险审查员 + 反方质疑者 | **2 线程并行** | `expert_opinions` |
| `report` | 报告撰写人 | — | `report_md` |

**`coordinator` 节点是确定性的**：计划来自模块级常量 `COORDINATOR_PLAN` + `REVIEW_PLAN`，不调用 LLM。`registry.agents["coordinator"]` 只用来取名字展示。这是一个务实取舍——主管的"调度决策"被固化为流程设计，换来的是确定性与零 Token 消耗。

**`extract` 节点不是 ReAct 循环**：它直接调用 `extract_fields(source_text, client, max_chars=40000, on_delta=...)` 再 `compute_metrics()`，只借用事件协议对外表现为一个"智能体"（`payload.agent = "extractor"`）。这样前端窗口与常规智能体一致，但省掉多轮 ReAct 开销。

**专家团并行为什么需要队列**：LangGraph 的 `get_stream_writer()` 绑定在 runnable context 里，子线程中直接调用会抛 `Called get_config outside of a runnable context`。解决方式是子线程把事件写进 `queue.Queue`，主线程轮询取出后统一发送：

```python
event_queue: queue.Queue[dict[str, Any]] = queue.Queue()

with ThreadPoolExecutor(max_workers=len(plan)) as pool:
    futures = {pool.submit(_run_agent, spec, task, state, node, event_queue, cached): key for ...}
    pending = set(futures)
    while pending:
        done, pending = wait(pending, timeout=0.08, return_when=FIRST_COMPLETED)
        _drain(emit, event_queue)      # 主线程发送队列中的事件
        for fut in done:
            results.append(fut.result())
            saved[result["agent"]] = result
            _save_ckpt(state, {"agents": saved})   # 每个 agent 完成即落盘
    _drain(emit, event_queue)          # 收尾
```

`timeout=0.08` 让主线程每 80ms 检查一次队列，事件延迟控制在可接受范围。四位专家的 `thinking` / `token` 事件会**交错到达**，前端按 `payload.agent` 分流到各自窗口，交错不影响显示。

**产物提取（artifacts → state）**：`analysis_group` 遍历各位专家返回的 `artifacts`，把工具名直接映射为状态字段：

```python
if "build_assumptions" in valuation_artifacts:   patch["assumptions"] = ...
if "dcf_valuation"      in valuation_artifacts:   patch["dcf"] = ...
if "relative_valuation" in valuation_artifacts:   patch["relative"] = ...
if "sensitivity_grid"   in valuation_artifacts:   patch["sensitivity"] = ...
```

**降级兜底**：若估值专家没调 `summarize_valuation` 但有 `dcf_valuation`，编排器会主动补齐——缺 `relative` 就用抽取字段里的 `net_profit` / `revenue` 现算，再调 `summarize_valuation` 汇总。保证结果面板不会出现空档。

### 4.4 事件协议 `events.py`

`events.py` 是前后端**唯一契约**。15 种事件类型：

| 类型 | 触发时机 | 关键 payload |
| --- | --- | --- |
| `run_start` | 开始执行 | `provider`, `model`, `base_url` |
| `node_start` | 节点开始 | — |
| `node_end` | 节点结束 | 节点特定数据 |
| `agent_start` | 智能体开始 | `agent`, `name`, `role` |
| `agent_end` | 智能体结束 | `opinion`, `elapsed_ms`, `steps`, `tools_used` |
| `tool_call` | 调用工具 | `agent`, `step`, `tool`, `input` |
| `tool_result` | 工具返回 | `ok`, `result` / `error` |
| `thinking` | 推理片段 | `agent`, `step` |
| `token` | 正文片段 | `agent`, `step` |
| `log` | 日志 | 重试信息、步数 |
| `result` | 最终结果 | 完整结构化数据 |
| `error` | 出错 | 错误消息 |
| `ask_user` | 向用户提问并阻塞等待 | `qid`, `questions[]`（由 `/api/chat/answer` 作答） |
| `title` | 对话命名 | `title` |
| `run_end` | 执行结束 | — |

```python
class AgentEvent(BaseModel):
    type: EventType
    run_id: str
    seq: int          # 全局递增序号，前端按序渲染
    node: str | None
    status: NodeStatus | None    # pending / running / success / failed
    message: str | None
    payload: dict[str, Any]
```

`seq` 由 `app/api/sse.py` 的 `wrap()` 统一分配——**所有事件都经过它**，包括从子线程队列里"抬升"出来的事件，因此序号严格单调。

### 4.5 传输层 `app/api/`

**凭据传递约定**（安全设计的核心决策）：

```python
"""模型凭据（API Key、Base URL 等）一律走请求头，不放在 URL 或表单里。
原因是 uvicorn 的 access log 会记录完整请求行（含查询串），
把 Key 放 URL 会导致密钥明文出现在日志、浏览器历史与代理记录中。
"""
```

请求头契约（凭据 5 个 + 搜索 3 个，共 8 个；连同 `Content-Type`，CORS 需显式列出 9 个否则预检失败）：

| 请求头 | 含义 |
| --- | --- |
| `X-LLM-Provider` | 提供商 key |
| `X-LLM-Model` | 模型名 |
| `X-LLM-Fallback-Models` | 备用模型，逗号分隔 |
| `X-LLM-Api-Key` | API 密钥 |
| `X-LLM-Base-Url` | 自定义端点 |
| `X-Search-Tavily-Key` | Tavily 搜索 Key |
| `X-Search-Bocha-Key` | 博查搜索 Key |
| `X-Search-Searxng-Url` | 自建 SearXNG 地址 |

**SSE 帧格式**：

```python
def _sse(event: dict) -> str:
    return f"event: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
```

**一次执行同时拿事件流与最终状态**：

```python
async for mode, chunk in graph.astream(state, stream_mode=["custom", "values"]):
    if mode == "custom":  yield wrap(chunk)      # 实时事件
    else:                 final_state = chunk    # 最终快照
```

避免了「先跑一遍拿事件、再跑一遍拿状态」的重复执行（重复执行意味着双倍 Token）。

**错误路径完整**：凭据校验失败（`cred.api_key or settings.llm_api_key` 为空）→ 发 `error` + `run_end(failed)`；图执行抛异常 → 同样收敛为 `error` + `run_end(failed)`，并 `logger.finish("failed")`。不会出现"流断了但前端不知道"的情况。

### 4.6 LLM 客户端 `llm.py`

统一走 OpenAI 兼容协议，封装三类能力：

**① 流式解析**（`_iter_deltas`）：兼容不同提供商的推理字段命名。

```python
content   = delta.get("content") or ""
reasoning = delta.get("reasoning_content") or delta.get("reasoning") or ""
```

**② 指数退避重试 + 抖动**：

```python
RETRY_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}
MAX_ATTEMPTS = 8 ; BACKOFF_BASE = 2.0 ; BACKOFF_CAP = 60.0

@staticmethod
def _backoff(attempt: int) -> float:
    base = min(BACKOFF_BASE ** attempt, BACKOFF_CAP)
    return base * (0.7 + random.random() * 0.6)   # 抖动，避免惊群
```

覆盖三类失败：`RETRY_STATUS` 响应码、`httpx.TimeoutException`（超时 300s）、`httpx.HTTPError`（网络）。

**③ 备用模型链**：`FALLBACK_AFTER = 3`，同一模型连续失败 3 次即 `_switch_model()` 弹出下一个备用模型并把 `attempt` 归零，通过 `on_switch` 回调通知前端。

**不限制输出长度**：`max_tokens` 默认 `None` 不传参。理由是推理模型的 `reasoning` 与 `content` 共享该预算，限制它会挤压正文空间。

### 4.7 工具集 `tools/`

**23 个工具，按性质分类：**

| 工具 | 类型 | 所在模块 | 说明 |
| --- | --- | --- | --- |
| `parse_document` | 解析 | parsing.py | PDF/TXT → 全文 + 分页 + 切片 + 财务关键页 |
| `extract_fields` | **LLM 驱动** | extraction.py | 结构化抽取 8 个财务字段 + 原文证据 |
| `compute_metrics` | 确定性 | metrics.py | 派生指标 5 项 |
| `financial_ratio_suite` | 确定性 | ratios.py | 盈利 / 偿债 / 营运 / 现金流质量全套比率 |
| `yoy_compare` | 确定性 | ratios.py | 两期同比与变动量 |
| `peer_comparison` | 确定性 | compare.py | 多公司指标对比表（JSON + Markdown） |
| `locate_evidence` | 确定性 | source_trace.py | 原文定位与页码溯源 |
| `build_assumptions` | **LLM 驱动** | valuation.py | 生成 DCF 假设（含 rationale） |
| `dcf_valuation` | 确定性 | valuation.py | 两阶段 DCF |
| `sensitivity_grid` | 确定性 | valuation.py | WACC × g 二维矩阵 |
| `relative_valuation` | 确定性 | valuation.py | PE / PS 隐含市值 |
| `summarize_valuation` | 确定性 | valuation.py | 综合估值区间 |
| `stock_quote` | 行情 | market.py | A 股实时快照 |
| `stock_history` | 行情 | market.py | 历史 K 线（前复权） |
| `financial_history` | 行情 | market.py | 定期报告主要财务指标 |
| `web_search` | 联网 | web.py | 多源降级检索 |
| `fetch_url` | 联网 | web.py | 抓取网页正文 |
| `current_datetime` | 联网 | web.py | 当前日期时间 |
| `python_calc` | 计算 | compute.py | 受限 AST 沙箱计算 |
| `list_skills` | 元 | skills.py | 列出技能 |
| `load_skill` | 元 | skills.py | 加载技能正文 |
| `ask_user` | 交互 | interact.py | 向用户提问并阻塞等待作答 |
| `set_conversation_title` | 交互 | interact.py | 为对话命名 |

**财务关键页定位**（`parsing.py`）——长文档的 Token 优化关键：

```python
FINANCIAL_KEYWORDS = ["营业收入", "归属于上市公司股东的净利润",
                      "经营活动产生的现金流量净额", "加权平均净资产收益率", ...]  # 15 个

def locate_financial_pages(pages, *, top_k=10, min_hits=2):
    # 按页面命中的不同关键词数打分；同分页码小者优先（核心摘要在前部）
    # 无页面达标则退化为前 top_k 页
```

选中页面由 `build_focus_text()` 拼成**带页码标记**的文本（`【第 N 页】`），使模型能生成 `[p9]` 形式的引用。后续所有 LLM 环节优先消费 `focus_text`，避免把封面、目录送给模型。

**指标计算**（`metrics.py`，纯确定性）：

| 指标 | 公式 | 意义 |
| --- | --- | --- |
| `net_margin` | 净利润 / 营业收入 | 盈利水平 |
| `ocf_to_revenue` | 经营现金流 / 营业收入 | 现金含量 |
| `debt_ratio` | 总负债 / 总资产 | 杠杆 |
| `profit_cash_gap` | 经营现金流 − 净利润 | 利润与现金的绝对差 |
| `profit_cash_divergence` | 布尔 | 利润为正却现金流为负，或偏离 >50% |

`profit_cash_divergence` 是系统最看重的信号——财务分析师的 system prompt 里明确要求"当利润与现金流背离时，这是最重要的发现，必须放在结论首位"。

**JSON 修补**（`extraction.py`）——对抗截断的鲁棒性设计：

```
_scan(text)           → 返回未闭合括号栈 + 是否停在字符串中
_close_brackets(text) → 补引号、补括号
_repair_json(text)    → 快速路径（补括号）；失败则慢路径：
                        从尾部逐层截断到上一个逗号再闭合，最多 20 轮
_parse_json_safe(text)→ 剥 ``` 围栏 → json.loads → 失败则 _repair_json 重试
```

被 `build_assumptions._parse_assumptions()` 复用，并附**保守默认值兜底**（`wacc=0.10, g=0.025, years=5, fcf_margin=0.08`）与边界校验（`wacc <= terminal_growth` 时强制抬高 5 个百分点）。

**估值方法**：

- `dcf_valuation`：两阶段。显式预测期逐年 `revenue *= (1+g)` → `fcf = revenue × fcf_margin` → 折现求和；终值 `TV = FCF_n × (1+g_term) / (WACC − g_term)`；`EV = PV(显式期) + PV(TV)`；`Equity = EV − NetDebt`。传入 `shares_outstanding` 时直接算好每股价值，**避免模型自行换算出错**。
- `sensitivity_grid`：双重循环遍历 WACC × g，逐点重跑 `dcf_valuation` 取 `equity_value`；`WACC <= g` 的位置填 0.0。
- `summarize_valuation`：收集 DCF 权益价值 + PE/PS 区间端点，过滤非正值后取 min / 均值 / max 作为 low / mid / high。

### 4.8 持久化：检查点 · 运行日志 · 存储

**三种持久化职责严格分离：**

| | 检查点 `checkpoint.py` | 运行日志 `runlog.py` | 存储 `storage.py` |
| --- | --- | --- | --- |
| 目的 | 断点续跑 | 审计与复现 | 配置与样例 |
| 粒度 | 节点级 | 事件级 | — |
| 位置 | `data/checkpoints/{run_id}.json` | `data/runs/{run_id}/events.jsonl` + `summary.json` | `data/profiles.json` · `data/samples/*.txt` |

上表 `data/` 是相对数据根目录的写法：根目录由 `paths.py` 的 `resolve_data_dir()` 统一解析——`DATA_DIR` 环境变量优先，默认落平台用户数据目录（Windows `%APPDATA%\Weister\data`），桌面端由 Electron 注入同一路径；开发模式即 `backend/data/`。

**检查点写入用原子替换**，避免半写文件：

```python
tmp = _path(run_id).with_suffix(".tmp")
tmp.write_text(json.dumps(payload, ensure_ascii=False, default=str), encoding="utf-8")
tmp.replace(_path(run_id))
```

检查点同时携带**每个专家的输出**（`ckpt["agents"]`），使续跑时已完成专家直接复用、跳过 LLM 调用。

**运行日志用 JSONL 而非 JSON 数组**：流式追加写入，不需要在内存累积，进程崩溃时已写入内容仍可读。

**敏感信息脱敏**（递归处理嵌套结构）：

```python
SENSITIVE_KEYS = {"api_key", "apikey", "authorization", "token", "secret"}

def _sanitize(value):
    if isinstance(value, dict):
        return {k: ("***" if k.lower() in SENSITIVE_KEYS else _sanitize(v))
                for k, v in value.items()}
    ...
```

单条 `message` 截断到 2000 字（报告全文等超长内容需要时从检查点或 `/api/analyze` 结果里读）。

### 4.9 MCP 服务器 `mcp_server.py`

把注册表里的工具通过 Model Context Protocol 暴露给外部客户端（Claude Desktop、Cline 等）。MCP 层的职责是**协议适配**，不新增能力。

**暴露过滤规则**：

```python
EXCLUDED = {"parse_document"}

for name, tool in registry.tools.items():
    if name in EXCLUDED or tool.inject:   # 依赖运行时注入的一律不暴露
        continue
```

- `parse_document` 排除：需要文件字节流，脱离 HTTP 上传上下文无意义
- `extract_fields` / `build_assumptions` 排除：`inject` 里有 `client` / `on_delta`
- 其余 20 个纯计算与元工具全部暴露

被排除的工具若被调用会返回明确的错误说明原因，而非静默失败。启动：`uv run python -m app.mcp_server`（stdio 模式，供客户端作为子进程拉起）。

### 4.10 前端

```
frontend/src/
├── app/
│   ├── page.tsx            # 单页编排：状态中枢 + 事件分发
│   ├── layout.tsx          # 根布局
│   └── globals.css         # Tailwind v4 主题变量
├── components/
│   ├── ChatPanel.tsx       # 对话流（默认形态）
│   ├── PipelineProgress.tsx # 六节点进度条（含耗时）
│   ├── PipelineResult.tsx  # 结果面板（四标签，导出 PipelineResultView）
│   ├── AgentStage.tsx      # 智能体协作面板（每 Agent 一窗口）
│   ├── ConversationSidebar.tsx # 会话列表
│   ├── SettingsModal.tsx   # 模型设置弹窗（多档案 + 探测）
│   ├── WindowControls.tsx  # 桌面端窗口三按钮（最小化/最大化·还原/关闭，无桥时 return null）
│   ├── chat/ · settings/   # TokenRing · SearchApiCard 等子组件
│   └── CapabilitiesPanel.tsx # 技能 / 工具 / 智能体目录
├── hooks/
│   └── useAgentTimeline.ts # 事件流 → 每 Agent 时间线
└── lib/
    ├── types.ts            # 与后端 events.py 对齐的类型定义
    ├── api.ts              # SSE 消费 + 凭据头 + REST 封装
    ├── desktop.ts          # window.WEISTER 桥类型 + useDesktopBridge（服务端快照 null 防 hydration 错位）
    ├── apiBase.ts          # API 基址唯一来源：WEISTER.API_BASE → NEXT_PUBLIC_API_BASE → 127.0.0.1:8000
    └── llmStore.ts         # 档案本地缓存
```

**桌面端桥接**：Electron `preload.cjs` 注入 `window.WEISTER`（动态 API 基址、窗口控制 IPC、最大化状态订阅）。`page.tsx` 的 `<header>` 在桌面端加 `app-drag` 拖动区并嵌入 `<WindowControls />`——页面顶栏即窗口标题栏；浏览器下桥为 `null`，三按钮与拖动区不渲染，观感与 Web 版一致。

**事件分发的双通道**（`page.tsx` 的 `handleEvent`）：

```tsx
timeline.push(event);                      // 通道一：按 agent 分流到工作台

if (event.type === "node_start") { setActiveNode(event.node); setNodeStates(...) }
if (event.type === "node_end")   { setNodeStates(...) }
if (event.type === "error")      { setError(...) }
if (event.type === "result")     { setResult(event.payload as FinalResult) }
```

**`useAgentTimeline` 的路由与批处理**：

```tsx
let key = event.payload?.agent            // 有 agent 字段 → 该智能体窗口
       ?? (SYSTEM_TYPES.includes(event.type) ? SYSTEM_KEY : null);
if (!key) return;                          // 纯节点事件归入「调度中心」窗口
```

- **路由键**：`payload.agent` 优先，否则归入 `__system__`（调度中心）
- **批处理**：事件先进 `bufferRef`，用 `requestAnimationFrame` 合并 flush，避免逐 token `setState` 造成渲染风暴
- **文本合并**：连续同类型 `token`/`thinking`/`log` 项追加到同一 item，而非新增条目
- **相位机**：`idle → thinking → tool → thinking → ... → done | error`，`tool_call` 时调 `closeThinkingItems()` 给推理段落打上「已结束」标记

**SSE 消费**（`api.ts`）：手写帧解析，按 `\n\n` 切帧、取 `data: ` 行、`JSON.parse`，无法解析的帧静默忽略。

---

## 5. 数据流

### 5.1 端到端时序

```
① 配置阶段
   SettingsPanel → llmStore(localStorage) → PUT /api/profiles → data/profiles.json

② 触发
   用户点「运行」→ api.analyze({ file, question, llm, onEvent })
       ├─ demo  → GET  /api/analyze/demo
       └─ 上传  → POST /api/analyze   (FormData: file + question；凭据在请求头)
   api/analyze.py: raw = await file.read()
           run_id = uuid4().hex[:12]
           checkpoint.save(run_id, {finished: False, completed_nodes: [], agents: {}})
           → StreamingResponse(_run_stream(...), media_type="text/event-stream")

③ 流内
   _run_stream:
       resolve(provider, model, base_url) → (pkey, pbase, pmodel)
       LLMClient(...) 校验凭据失败即提前返回 error        # 提前失败，避免跑一半才报错
       logger.start(...)  → RUN_START 事件
       state = { run_id, filename, raw_bytes, question, provider, model,
                 fallback_models, base_url, api_key }
       graph.astream(state, stream_mode=["custom", "values"])

④ 图内（每个节点）
   节点函数 → _make_emitter(node, run_id) 绑定 get_stream_writer()
           → emit(...) → writer({type, run_id, node, status, message, payload})
   ingest: parse_pdf / parse_text → chunk_text → locate_financial_pages
           → build_focus_text → citations → _save_ckpt + _mark_node
   extract: extract_fields(focus_text, client, max_chars=40000, on_delta)
            → compute_metrics → _save_ckpt
   coordinator: 静态计划 → _mark_node
   analysis: _run_group(COORDINATOR_PLAN)  ─┐
   review:   _run_group(REVIEW_PLAN, extra=前置分析结论) ─┤ 各自 2 线程并行
                                            └─ 子线程写 queue，主线程 _drain 抬升
   report: 汇总 analyses + expert_opinions → AgentRunner.run() → report_md
           → checkpoint.mark_finished(run_id)

⑤ 出口
   custom 事件 → wrap() 分配 seq + logger.event() → SSE 帧
   values 快照 → final_state
   → RESULT 事件（全量 payload）→ RUN_END → logger.finish("success")

⑥ 前端
   consumeStream 解析帧 → handleEvent
       ├─ timeline.push → useAgentTimeline（按 agent 分流 + rAF 批处理）→ AgentStage
       ├─ node_start/end → nodeStates → Pipeline
       └─ result → setResult → PipelineResultView（四标签）
```

### 5.2 帧示例

```
event: thinking
data: {"type":"thinking","run_id":"96579d894f26","seq":42,"node":"analysis","status":"running","message":"先看收入结构...","payload":{"agent":"valuation_expert","step":2}}

event: tool_call
data: {"type":"tool_call","seq":43,"node":"analysis","status":"running","message":"tool: dcf_valuation","payload":{"agent":"valuation_expert","step":2,"tool":"dcf_valuation","input":{"base_revenue":1234.5,"assumptions":{...}}}}
```

双换行分隔事件帧；`message` 承载增量文本，`payload` 承载结构化元数据。

### 5.3 状态传递的三个通道

| 通道 | 载体 | 用途 |
| --- | --- | --- |
| **事件通道** | `queue.Queue` → `emit` → SSE | 实时展示，不参与计算 |
| **artifacts 通道** | `AgentRunner` 返回的 `artifacts` 字典 | 结构化产物，供编排器提取到 state |
| **检查点通道** | `checkpoint.save/load` | 跨进程持久化 + 断点续跑 |

`InvestState` 中列表型字段用 `operator.add` 归约，使并行节点各自追加而不互相覆盖：

```python
trace:  Annotated[list[dict[str, Any]], operator.add]
errors: Annotated[list[str], operator.add]
```

`total=False` 让字段全部可选，避免并行节点互相覆盖未设置的键。

---

## 6. 断点续跑

每个节点开头先查检查点，命中则直接返回缓存值：

```python
ckpt = _load_ckpt(state)
if node in (ckpt.get("completed_nodes") or []) and ckpt.get("document_text"):
    emit(NODE_START, message="从检查点恢复文档解析")
    return {"document_text": ckpt["document_text"], ..., "trace": [_trace(node, 0, {"resumed": True})]}
```

**专家级缓存**更细：`_run_group` 读取 `ckpt["agents"][key]`，有 `output` 就直接复用（发 `agent_start` + `agent_end` 两个 `resumed: True` 事件，前端能看到"已恢复"），**不消耗 Token**。

恢复入口目前只在接口层：`GET /api/runs/latest` + `GET /api/analyze/resume?run_id=...`；前端 hook `useAnalyzeRun().resume()` 已实现但界面未挂按钮。`checkpoint.latest()` 按 mtime 倒序找第一个 `finished != True` 的记录。

---

## 7. 稳定性设计

| 机制 | 实现位置 | 说明 |
| --- | --- | --- |
| 不限制输出长度 | `llm.py` | 不传 `max_tokens`，让模型自行决定收尾时机 |
| 重试退避 | `llm.py` | 指数退避 + 随机抖动，最多 8 次，覆盖超时 / 网络 / 5xx / 429 |
| 备用模型链 | `llm.py` | 主模型连续失败 3 次自动切换下一个 |
| 单次执行 | `app/api/sse.py` | `astream(["custom","values"])` 一次拿事件与最终状态 |
| 断点续跑 | `checkpoint.py` + 各节点 | 节点级 + 专家级双层缓存 |
| JSON 修补 | `extraction.py` | 截断 JSON 自动补齐；失败则逐层截断重试 |
| 假设兜底 | `valuation.py` | 缺字段补保守默认值 + 边界校验 |
| 估值兜底 | `orchestrator.py` | 缺 `summarize_valuation` 时编排器主动补齐 |
| 停滞检测 | `base.py` | 连续多步无进展（无工具调用且正文为空）则收尾 |
| 原子写入 | `checkpoint.py` / `storage.py` | `tmp` → `replace`，避免半写文件 |
| 日志脱敏 | `runlog.py` | 递归替换敏感键为 `***` |
| 提前失败 | `app/api/analyze.py` | 流开始前按 `cred.api_key or settings.llm_api_key` 直接校验凭据 |

---

## 8. 前端实时渲染

**界面结构**（顶栏 + 主区 flex 布局，`app/page.tsx`）：

```
┌──────────────────────────────────────────────────────────────┐
│ W Weister   模型状态 · 新对话 · 协作 · 设置 · 对话|建模        │
├────────────┬──────────────────────────┬──────────────────────┤
│  会话侧栏   │  对话流 / 流水线结果       │  智能体协作面板       │
│ （可折叠）  │  输入框（/ 选技能）        │ （可拖动调宽）        │
└────────────┴──────────────────────────┴──────────────────────┘
```

**结果面板四标签**：研究报告（Markdown + 来源标注）· 估值建模（区间卡片 + 分方法估值 + DCF 关键值 + 相对估值 + 敏感性表格）· 结构化数据（财务字段 + 派生指标）· 专家意见（各专家长文输出，Markdown 渲染）。

**渲染性能三道防线**：
1. `useAgentTimeline` 用 `requestAnimationFrame` 批处理，单帧内多个事件合并为一次 `setState`
2. 连续 token 追加到同一 item，不新增 DOM 条目
3. `appendItem` / `closeThinkingItems` 返回原引用（无变化时）避免无谓重渲染

---

## 9. 关键设计决策与权衡

| 决策 | 选择 | 理由 | 代价 |
| --- | --- | --- | --- |
| 工具调用方式 | **原生 function calling** | 结构化、无需文本解析、不易被模型格式漂移破坏 | 依赖端点支持 `tools` 参数 |
| 技能存储 | Markdown 文件 | 金融队友可参与编写，无需改代码 | 需自写 frontmatter 解析 |
| 技能加载 | **内联进 system prompt** | 省一轮工具调用 + 稳定前缀命中 API 缓存 | prompt 变长，占用上下文 |
| 编排框架 | LangGraph | 状态图 + 内置流式 writer | 子线程无法直接用 writer，需要队列桥接 |
| 专家并行 | `ThreadPoolExecutor` + `queue` | LLM 调用是 IO 密集，线程足够；队列解决 context 绑定 | 事件乱序，但按 agent 分流后无影响 |
| 凭据传递 | HTTP 请求头 | 避免 access log / 浏览器历史 / 代理记录泄露 | CORS 需显式声明头 |
| 输出长度 | 不设限 | reasoning 与 content 共享预算，限制会挤压正文 | 极端情况下输出失控（用停滞检测兜底） |
| 步数限制 | 硬上限 24 步 | 防御模型反复调工具导致的死循环 | 常规任务触不到，纯防御 |
| 持久化 | 文件 JSON / JSONL | 无外部依赖，竞赛环境零配置；JSONL 崩溃可读 | 不适合高并发多实例 |
| 结构化输出 | 提示词约束 + JSON 修补 | 兼容不支持的 JSON Mode 的端点 | 需要修补逻辑 |
| 主管决策（建模形态） | 固化为常量计划 | 确定、可测、零 Token | 失去动态调度能力 |
| 主管决策（对话形态） | LLM 逐轮输出决策 JSON | 按需调度 7 位专家，支持 reply / delegate / ask | 需要字段规范化与纠偏重试兜底 |

---

## 10. 代码与文档不一致项

以下为本次实测发现的**文档滞后于代码**之处，建议同步修订 `docs/ARCHITECTURE.md`：

| # | `docs/ARCHITECTURE.md` 描述 | 代码实际 |
| --- | --- | --- |
| 1 | 用正则 `ACTION_BLOCK` 解析 ` ```action ` 代码块，兼容 `json` 围栏 | **已改为原生 function calling**，`base.py` 中不存在 `ACTION_BLOCK` / `NOISE_TAGS` 正则；模型返回结构化 `tool_calls` |
| 2 | 用 `NOISE_TAGS` 剥离模型自带的 XML 工具调用语法 | 该逻辑已随 function calling 改造移除 |
| 3 | `AgentSpec` 含 `max_steps=6` / `max_output_tokens=4096` / `max_output_chars=8000` | 三个字段**均已删除**；ReAct 循环不设上限，靠停滞检测终止 |
| 4 | `total_chars + reasoning_chars > max_output_chars` 触发**输出熔断** | 该熔断逻辑已移除 |
| 5 | 智能体通过 `load_skill` 工具在运行时获取技能正文 | 技能正文由 `_render_skills()` **内联进 system prompt**；`load_skill` 仅作为工具保留（主要供 MCP 客户端） |
| 6 | 事件表曾在文档里写成 13 种 | 已修正为 15 种（含 `ask_user` / `title`），与代码一致 ✅ |
| 7 | `parse_document` 列在"不暴露"表中 | 代码中 `EXCLUDED = {"parse_document"}`，与文档一致 ✅ |

**另有 3 处实现层面的小问题**（不影响功能，**已于 2026-09-11 全部修复**）：

| # | 位置 | 现象 | 处理 |
| --- | --- | --- | --- |
| A | `base.py` / `orchestrator.py` | `shared` / `ToolContext.state` 被传入但从未被写入，导致 `agent_end.payload.loaded_skills` **恒为空数组**；前端 `useAgentTimeline` 与 `types.ts` 中针对 `loaded_skills` 的渲染逻辑成为死代码 | **已修**。技能本就由 `_render_skills()` 内联进 system prompt，因此改为如实上报 `spec.skills`。注意 7 个走 ReAct 循环的智能体工具白名单里**都没有** `load_skill`，去追踪运行时调用永远只会得到空数组 |
| B | `frontend/src/lib/types.ts` | `NODE_ORDER` 只有 5 个节点（`ingest, coordinator, analysis, review, report`），**漏了 `extract`**，导致流水线面板不显示"数据提取"节点（其事件仍会进入"数据提取员"窗口） | **已修**（2026-09-11）。补上 `extract` 的 `NODE_ORDER` 项与 `NODE_LABELS` 标签（`PipelineProgress` 按名称渲染，无独立图标表）；`tsc --noEmit` 通过（0 错误） |
| C | `app/api/analyze.py` `_run_stream` / `analyze_resume` | 开头构造的 `LLMClient` 仅用于 `require_configured()` 校验后即丢弃；实际客户端由 `orchestrator.build_client()` 重新构造，属冗余。另外 `/api/analyze/resume` 的 `question` 使用硬编码默认值，未恢复原始问题 | **已修**。改为直接按同一规则判定凭据（请求头优先、回退 `.env`），不再构造一次性实例；`question` 写入初始检查点并在续跑时读回 |

**另发现 1 处此前未记录的缺口（已于 2026-09-11 修复）**：

| # | 位置 | 现象 |
| --- | --- | --- |
| D | `tools/parsing.py` → `orchestrator.ingest` | **扫描件静默失败**：`parse_pdf` 对纯图像 PDF 返回 0 字符且不报错，空文本被一路带到抽取与估值，最终产出一份「格式完整但没有依据」的报告。现已加可读性闸门：检测无文字层页面 → 可用时走 OCR 兜底 → 文本实质为空则**显式报错**。实测 9 页扫描件在 `ingest` 即被拦下，且**未发生任何 LLM 调用**。 |

---

## 11. 改进建议

**已完成（2026-09-11）**

1. ~~修复 `NODE_ORDER` 缺 `extract`~~ —— 流水线面板完整反映 6 个节点
2. ~~补齐 `loaded_skills` 死代码链路~~ —— 改为如实上报内联进 prompt 的 `spec.skills`
3. ~~给 `AgentSpec` 加 `max_steps` 硬上限~~ —— 默认 24 步，触顶置 `truncated` 并透出到前端，不再可能无限循环
4. ~~`/api/analyze/resume` 恢复原始 `question`~~ —— `question` 随初始检查点落盘，续跑时读回
5. ~~清理 `_run_stream` 的冗余 `LLMClient` 构造~~
6. ~~**扫描件静默失败**（第 10 节 D）~~ —— `ingest` 加可读性闸门；无 Tesseract 时明确报错而非静默产出空结论
7. ~~**UI 去 AI 味，正式切换浅色专业风**~~ —— 弃用 `glow-border` / `pulse-ring` / `scan-line` 三个自制特效；新建 DaisyUI 主题 `weister`（白底深灰字、单一克制的强调色、`--depth: 0`、`--noise: 0`）；6 个界面组件（`globals.css` + `page.tsx` + `PipelineProgress` / `AgentStage` / `PipelineResult` / `SettingsPanel`）统一改用 DaisyUI 语义类（`btn` / `card` / `tabs` / `table` / `alert` / `modal` / `stat` / `progress` / `badge`）。验证：构建退出码 0、生产 CSS 含 33 个 DaisyUI 选择器 + `--color-primary: #1c4b7d`、源码层 0 个 AI 味残留

**已完成（2026-09-12）**

8. ~~**聊天形态 + supervisor loop**~~ —— 见 [第 13 节](#13-聊天形态Supervisor-Loop2026-09-12-新增)（取代长期项目 #13「主管真正参与调度」）：删除 6 节点固定 DAG，改为 `coordinator` 真 LLM 决策（每轮输出 `{"action":"reply|delegate","agent":..,"task":..,"content":..}`），specialist 复用 `AgentRunner.run()`。`/api/chat` POST + `/api/chat/{run_id}` GET 已可端到端访问（详见 [USAGE.md § 聊天模式](USAGE.md#聊天模式推荐)）。

**已完成（2026-09-26 ~ 10-07）**

9. ~~**桌面客户端完整落地**~~ —— Electron 壳 + 嵌入式 Python 打包（详见 [ARCHITECTURE.md 桌面端进程拓扑](ARCHITECTURE.md#桌面端进程拓扑) 与 [DEVELOPMENT.md 桌面端构建](DEVELOPMENT.md#桌面端构建)）：PyInstaller 方案弃用，改为 python.org 嵌入式发行版 + `-s` 旗标隔离；`electron/main.cjs` 动态端口（8000/3000 起 +1 最多 20）拉起前后端子进程；`paths.py` 数据目录唯一来源（`%APPDATA%\Weister\data`）；`prepare-frontend.cjs` 解决 standalone 符号链接与 BUILD_ID 同源；portable 免安装单文件输出

**短期（低风险，待办）**

10. **收敛 `ruff` 合规**：`pyproject.toml` 声明了 ruff（`ruff>=0.7.0`，实际装的是 0.16.6），实测 `ruff check app` 有 **5 个既存告警**（全部集中在 `tools/parsing.py` 的 OCR 容错分支），`ruff format` 会重排 **2 个文件**（`chat_supervisor.py` / `tools/ratios.py`）。建议先明确 `[tool.ruff.lint] select` 规则集，再一次性收敛——**不要混在功能改动里做**，否则 diff 会被格式化噪音淹没
11. **给 `ToolContext.state` 找到真实用途，或删掉它**：`shared` 目前仍被传入但无人写入，是留给「需要跨步共享状态的注入式工具」的挂点。留着的代价是容易被误当成可用容器（本次的 `loaded_skills` 就是踩了这个坑）

**中期**

12. **API Key 加密存储**：`data/profiles.json` 与 localStorage 均明文，建议至少做本地密钥加密或改为仅内存持有
13. **结构化输出改用原生 JSON Schema**：为支持 `response_format` 的端点启用严格模式，可大幅降低对 `_repair_json` 的依赖
14. **检查点改用 SQLite**：当前文件方案不支持并发多实例，也缺少索引；SQLite 可零依赖解决
15. **给 `/api/chat` 加运行中的取消接口**：目前中断依赖前端 `AbortSignal`，后端无法主动终止已启动的 supervisor loop

**长期**

16. **补充评测基线**：对固定样例跑 N 次，记录字段抽取准确率、DCF 权益价值的中位数与极差、事件流完整率、重试触发次数，让"稳定性设计"从声称变成可量化验收的证据

---

## 13. 聊天形态（Supervisor Loop，2026-09-12 新增）

> 本节为 8 号工作的展开。完整使用指南见 [USAGE.md § 聊天模式](USAGE.md#聊天模式推荐)。

### 13.1 目标与适用

- 取代固定 6 节点 DAG，让用户在聊天形态下**中途不断追加问题、文件、图片**，由 `coordinator` 真 LLM 按需调用专家。
- 不破坏 v1：`/api/analyze` 与 6 节点 DAG 保留作对比与续跑入口。

### 13.2 文件结构

| 文件 | 角色 |
| --- | --- |
| `backend/app/chat_supervisor.py` | supervisor loop 主入口、prompt 模板、决策解析、消息序列化 |
| `backend/app/tools/parsing.py` | `parse_docx` / `parse_xlsx` / `parse_pptx` / `detect_image_mime` / `parse_any` |
| `backend/app/api/chat.py` | `POST /api/chat` + `GET /api/chat/{run_id}` + `/api/chat/estimate` + `/api/chat/answer`，附件解析、SSE 收尾 |
| `backend/app/config.py` | 新增 `runs_dir` / `runs_dir_path` 指向 `./data/runs/<id>/messages.jsonl` |
| `backend/tests/smoke_chat.py` | singleton FakeLLM 验证 delegate→reply 流程 |
| `frontend/src/lib/api.ts` | `chat()` / `ChatMessage` / `getChatHistory()` / `filesToPreviews()` |
| `frontend/src/hooks/useChat.ts` | `useChat({ llm, onEvent })` hook；`onEvent` 是给协作面板的二级 sink |
| `frontend/src/components/ChatPanel.tsx` · `ChatComposer.tsx` · `SettingsModal.tsx` | 三段式聊天 UI 组件 |
| `frontend/src/app/page.tsx` | 主页面（删除左栏；右抽屉可折叠协作面板） |

### 13.3 Supervisor 决策协议

```json
{"action":"reply",     "content":"<短回复>"}
{"action":"delegate",  "agent":"<key>", "task":"<具体任务>"}
{"action":"ask",       "title":"<标题>", "questions":[{"question":"..","header":"..","multiSelect":false,"options":[{"label":"..","description":".."}]}]}
```

- `agent ∈ delegateable_agents()` = 注册表中除主管外的全部智能体：(financial_analyst, valuation_expert, risk_reviewer, devils_advocate, market_analyst, research_assistant, report_writer)
- `task` 必填；解析失败时把上一轮 specialist 摘要作为兜底回复
- `_parse_decision` 容忍三种格式：纯 JSON、```json … ``` 围栏、夹在 LLM 自由文本中
- 终止不设调度轮数预算：连续 `MAX_IDLE_ROUNDS = 3` 轮无进展即收尾，另有 `ABSOLUTE_ROUND_LIMIT = 50` 兜底防死循环

### 13.4 与 v1 DAG 的边界

- `chat_supervisor` 不动 `orchestrator.graph`，新旧两条链路共置
- `AgentRunner.run()` 直接复用，specialist 的工具调用、ReAct 循环、`max_steps` 防御全部生效
- checkpoints 仍走 `data/checkpoints/<id>.json`（v1）；聊天的 messages 走 `data/runs/<id>/messages.jsonl`（v2）—— 目录分开避免冲突
- 凭据解析逻辑沿用 v1（请求头 `X-LLM-*`，回退 `.env`）

---

## 12. 目录结构（实测）

```
Weister/
├── README.md                 项目说明
├── dev.ps1                   一键启动（清端口 → 查依赖 → 备 .env → 起后端 → 健康检查 → 起前端）
├── check.ps1                 质量门禁（ruff + pytest + tsc）
├── docs/
│   ├── ARCHITECTURE.md       架构详解（与代码同步）
│   ├── DESIGN.md             ← 本文档
│   ├── architecture.html     ← 系统架构图
│   ├── USAGE.md              使用指南与故障排查（含桌面客户端章）
│   ├── DEVELOPMENT.md        开发与扩展指南（含桌面端构建章）
│   └── THIRD_PARTY.md        第三方依赖清单（名称/版本/来源/许可证/使用范围）
│
├── scripts/
│   ├── build.ps1             桌面客户端一键构建（prepare-python → standalone → electron-builder）
│   └── prepare-python.ps1    准备 backend/python/ 嵌入式 Python（._pth 重写 + -s 隔离 + 依赖校验）
│
├── electron/                 桌面客户端壳（Electron 33，portable 打包）
│   ├── main.cjs              主进程：动态端口（8000/3000 起 +1 最多 20）· 拉起前后端子进程 ·
│   │                         加载窗口（进度/失败回显）· frame:false · cleanup
│   ├── preload.cjs           只注入 window.WEISTER 桥（API_BASE/IS_DESKTOP/VERSION/窗口控制）
│   ├── loading.html          启动加载页（独立无边框小窗，自带标题栏）
│   ├── build/icon.ico        应用图标（深墨底白 W）
│   ├── scripts/prepare-frontend.cjs  prebuild 钩子：static/public 同步进 standalone ·
│   │                         pnpm 符号链接物化 · BUILD_ID 校验 · 铺到 build/frontend
│   └── package.json          electron-builder 配置（appId/productName/portable/extraResources）
│
├── backend/
│   ├── pyproject.toml        依赖与 ruff 配置（line-length=100, py312）
│   ├── .env.example          含 DATA_DIR（留空即 %APPDATA%\Weister\data）
│   ├── python/               嵌入式 Python 运行时（build.ps1 生成，不纳入版本控制）
│   ├── app/
│   │   ├── main.py           入口（仅 `from .api import app`）
│   │   ├── __main__.py       `python -m app` 入口（读 HOST/PORT 环境变量，桌面端启动用）
│   │   ├── paths.py          落盘路径唯一来源（DATA_DIR 优先 → %APPDATA%\Weister\data；
│   │   │                     env_file() 绝对路径，防两种启动方式读到不同 .env）
│   │   ├── api/              HTTP 接口 · SSE · 凭据头 · CORS（meta/analyze/chat/sse/store/helpers/deps）
│   │   ├── orchestrator.py   LangGraph 图 · 6 节点 · 专家团并行调度
│   │   ├── state.py          InvestState（TypedDict, total=False）
│   │   ├── events.py         15 种事件类型 · NodeStatus · AgentEvent
│   │   ├── llm.py            LLMClient（流式 / 重试 / 备用链）· parse_json_loose
│   │   ├── providers.py      7 家提供商注册表 · resolve / catalog
│   │   ├── models.py         模型列表拉取与连通性探测
│   │   ├── decision.py       主管决策解析与字段规范化
│   │   ├── interaction.py    ask_user 交互桥（提问 / 等待 / 唤醒）
│   │   ├── runctx.py         运行上下文（run_id + emit 绑定）
│   │   ├── searchcfg.py      搜索源配置（请求头 / 存档绑定）
│   │   ├── tokens.py         上下文预算与 token 估算
│   │   ├── chat_supervisor.py 对话形态：主管 supervisor 循环
│   │   ├── checkpoint.py     运行检查点（原子写）
│   │   ├── runlog.py         运行日志（events.jsonl + summary.json + 脱敏）
│   │   ├── storage.py        data 目录读写（profiles / samples）
│   │   ├── config.py         pydantic-settings 环境配置（data_dir 走 paths.py）
│   │   ├── mcp_server.py     MCP stdio 服务器（协议适配）
│   │   ├── core/registry.py  Tool / Skill / AgentSpec 注册表
│   │   ├── tools/
│   │   │   ├── __init__.py   导入即注册
│   │   │   ├── parsing.py    PDF/TXT 解析 · 切片 · 财务关键页定位
│   │   │   ├── extraction.py LLM 结构化抽取 · JSON 修补
│   │   │   ├── metrics.py    派生指标（纯确定性）
│   │   │   ├── ratios.py     财务比率套件 · 同比对比
│   │   │   ├── compare.py    同业对比
│   │   │   ├── source_trace.py 原文定位与页码溯源
│   │   │   ├── market.py     A 股行情 / K 线 / 历史财务
│   │   │   ├── web.py        联网搜索 · 抓取 · 当前时间
│   │   │   ├── compute.py    受限 AST 沙箱计算
│   │   │   ├── interact.py   ask_user · set_conversation_title
│   │   │   ├── valuation.py  假设 / DCF / 敏感性 / 相对估值 / 汇总
│   │   │   └── skills.py     list_skills · load_skill
│   │   ├── skills/          9 份技能说明书（financial_analysis · valuation_modeling · investment_report · market_data · web_research · supervisor_coordination · risk_analysis · peer_benchmark · earnings_quality）
│   │   └── agents/
│   │       ├── __init__.py   bootstrap()：注册工具 + 技能 + 智能体
│   │       ├── base.py       AgentRunner · ToolContext · build_system_prompt
│   │       ├── coordinator.py    投研主管
│   │       └── specialists.py    6 位专家 + 报告撰写人
│   └── data/                 运行时数据（开发模式；桌面端落 %APPDATA%\Weister\data）
│       ├── profiles.json     模型配置（API Key 明文）
│       ├── samples/          演示样例
│       ├── checkpoints/      运行检查点
│       └── runs/             运行日志
│
└── frontend/
    ├── package.json
    ├── next.config.ts        output: "standalone"（桌面端打包前置）
    └── src/
        ├── app/              page.tsx（桌面端顶栏加 app-drag + WindowControls）· layout.tsx · globals.css
        ├── components/       ChatPanel · PipelineProgress · PipelineResult · AgentStage ·
        │                     ConversationSidebar · SettingsModal · WindowControls（窗口三按钮）
        ├── hooks/            useAgentTimeline.ts
        └── lib/              types.ts · api.ts · llmStore.ts · desktop.ts（WEISTER 桥）·
                              apiBase.ts（API 基址解析：桥 → env → 127.0.0.1:8000）
```

---

## 附录 A：API 速查

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/health` | 健康检查 |
| GET | `/api/providers` | 提供商列表 |
| GET | `/api/registry` | 工具 / 技能 / 智能体清单 |
| GET | `/api/profiles` | 读取模型配置 |
| PUT | `/api/profiles` | 保存模型配置 |
| GET | `/api/samples` | 列出演示样例 |
| POST | `/api/samples` | 新增演示样例 |
| GET | `/api/runs` | 运行历史 |
| GET | `/api/runs/latest` | 最近未完成的检查点 |
| GET | `/api/runs/{id}` | 单个检查点详情 |
| DELETE | `/api/runs/{id}` | 删除检查点 |
| POST | `/api/models` | 探测模型列表或连通性 |
| POST | `/api/search/test` | 搜索源连通性测试 |
| POST | `/api/analyze` | 上传文件执行（SSE） |
| GET | `/api/analyze/demo` | 用样例执行（SSE） |
| GET | `/api/analyze/resume` | 从检查点续跑（SSE） |
| POST | `/api/chat` | 对话形态一轮聊天（multipart：message + run_id + attachments + files） |
| POST | `/api/chat/estimate` | 上下文 token 估算 |
| POST | `/api/chat/answer` | 回答 `ask_user` 的选择 |
| GET | `/api/chat/{run_id}` | 读取某会话历史（messages.jsonl） |
| GET | `/api/conversations` | 会话列表 |
| GET | `/api/conversations/{run_id}/events` | 某会话的事件流 |
| DELETE | `/api/conversations/{run_id}` | 删除会话 |
| GET | `/api/logs` | 运行日志列表 |
| GET | `/api/logs/{id}` | 单次运行的完整事件流 |
| DELETE | `/api/logs/{id}` | 删除运行日志 |

> 全部共 27 条路径（meta 17 · analyze 3 · chat 7）；交互式文档见 http://127.0.0.1:8000/docs

## 附录 B：智能体与工具权限矩阵

| 智能体 | 工具白名单 | 内联技能 |
| --- | --- | --- |
| `coordinator` 投研主管 | —（建模形态为固定节点，不调 LLM；对话形态只输出决策 JSON） | — |
| `financial_analyst` 财务分析师 | `extract_fields` · `compute_metrics` · `financial_ratio_suite` · `yoy_compare` · `locate_evidence` · `peer_comparison` · `financial_history` · `python_calc` · `web_search` · `fetch_url` · `current_datetime` · `ask_user` · `set_conversation_title`（13） | `financial_analysis` · `market_data` · `earnings_quality` · `peer_benchmark` |
| `valuation_expert` 估值专家 | `build_assumptions` · `dcf_valuation` · `relative_valuation` · `sensitivity_grid` · `summarize_valuation` · `financial_ratio_suite` · `peer_comparison` · `stock_quote` · `stock_history` · `financial_history` · `python_calc` · `web_search` · `fetch_url` · `current_datetime` · `ask_user` · `set_conversation_title`（16） | `valuation_modeling` · `peer_benchmark` · `market_data` |
| `risk_reviewer` 风险审查员 | `compute_metrics` · `financial_ratio_suite` · `yoy_compare` · `locate_evidence` · `stock_quote` · `financial_history` · `python_calc` · `web_search` · `fetch_url` · `current_datetime` · `ask_user` · `set_conversation_title`（12） | `financial_analysis` · `market_data` · `risk_analysis` |
| `devils_advocate` 反方质疑者 | `stock_quote` · `stock_history` · `financial_history` · `financial_ratio_suite` · `peer_comparison` · `python_calc` · `web_search` · `fetch_url` · `current_datetime` · `ask_user` · `set_conversation_title`（11） | `financial_analysis` · `market_data` · `risk_analysis` · `peer_benchmark` |
| `market_analyst` 市场数据研究员 | `stock_quote` · `stock_history` · `financial_history` · `python_calc` · `web_search` · `fetch_url` · `current_datetime` · `ask_user` · `set_conversation_title`（9） | `market_data` |
| `research_assistant` 信息研究员 | `web_search` · `fetch_url` · `current_datetime` · `stock_quote` · `ask_user` · `set_conversation_title`（6） | `web_research` |
| `report_writer` 报告撰写人 | `ask_user` · `set_conversation_title`（2） | `investment_report` |
| （`extractor` 数据提取员） | 节点内直接调用 `extract_fields` + `compute_metrics` | — |

> 只有主管没有工具白名单；其余 7 个走 ReAct 循环的智能体都可调用交互工具，在信息不足时向用户确认。技能不是运行时按需加载的，而是在 `build_system_prompt` 里整体内联进 system prompt。
