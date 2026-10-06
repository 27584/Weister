# Weister

> 金融投研智能体 · 多智能体协作的自动化估值建模系统

面向金融投研场景的多智能体系统，对标**自动化估值建模**方向：读取上市公司财报，自动完成结构化抽取 → 指标计算 → DCF 与相对估值建模 → 多专家并行评审 → 生成带来源标注的投资简报。

系统读取上市公司财报，自动完成结构化抽取、指标计算、DCF 与相对估值建模，由四位专家智能体并行评审，最终生成带来源标注的买方投资简报。

---

## 亮点

- **多智能体协作**：对话形态由投研主管（LLM）按需调度全部 7 位专家；建模形态由财务分析师 / 估值专家 / 风险审查员 / 反方质疑者四路并行评审，报告撰写人综合成文
- **规范的三层抽象**：Tool（原子函数）· Skill（提示词说明书）· Agent（ReAct 决策者），与主流开源 Agent 底座一致
- **实时可视化**：每位智能体一个独立工作窗口，实时显示思考、工具调用与输出流
- **可追溯可复现**：全流程事件流、节点耗时追踪、原文页码引用、断点续跑
- **金融专业性**：严格区分事实 / 推论 / 观点，估值假设附依据，风险附反向验证条件
- **开箱即用的桌面客户端**：一键构建 Windows 免安装单文件（portable），自带嵌入式 Python 运行时与启动加载窗口，双击即用

---

## 技术栈

| 层 | 技术 |
| --- | --- |
| 前端 | Next.js 16 · TypeScript · Tailwind v4 · DaisyUI v5 · Framer Motion · animate.css |
| 后端 | Python ≥3.12（开发环境实测 3.14）· FastAPI · LangGraph · PyMuPDF |
| 通信 | Server-Sent Events（SSE） |
| 模型 | OpenAI 兼容协议（DeepSeek / 通义千问 / 智谱 GLM / Kimi / OpenAI / Ollama 本地 / 自定义） |
| 桌面端 | Electron 33 · electron-builder（Windows portable 免安装单文件，内置嵌入式 Python 运行时） |

---

## 快速开始

### 前置要求

- **Node.js** ≥ 20
- **pnpm** ≥ 9
- **uv**（Python 包管理器，[安装指引](https://docs.astral.sh/uv/)）
- 桌面端构建另需：PowerShell（`scripts/build.ps1`）、可访问 python.org 的网络（下载嵌入式 Python）

### 一键启动

```powershell
# 首次运行会自动安装依赖
.\dev.ps1

# 需要后端热重载时
.\dev.ps1 -Reload

# 停止服务
.\dev.ps1 -Stop
```

脚本会自动完成：清理占用端口 → 检查依赖 → 准备 .env → 启动后端并健康检查 → 启动前端。

> 编码约定：`dev.ps1` / `check.ps1` 含中文输出，必须以 **UTF-8 with BOM** 保存。
> Windows PowerShell 5.1 会把无 BOM 的 `.ps1` 按 ANSI（中文系统为 GBK）解码，
> 中文串错位后会吞掉引号与换行，从而抛出假性的 `MissingEndCurlyBrace` 解析错误；
> 使用 PowerShell 7（`pwsh`）运行不受此限制，但仍建议保留 BOM 以免编辑器误存。

### 手动启动

```bash
# 后端
cd backend
uv sync
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000

# 前端（另开终端）
cd frontend
pnpm install
pnpm dev
```

### 桌面客户端构建（Windows）

```powershell
.\scripts\build.ps1            # 全量：嵌入式 Python → 前端 standalone → Electron portable
.\scripts\build.ps1 -SkipBackend   # 已准备过 backend/python 时跳过第一步
```

脚本三步：① `scripts/prepare-python.ps1` 下载 Python 3.12 嵌入式包到 `backend/python/` 并安装依赖；② 前端 `pnpm build`（standalone 输出）；③ `electron` 目录 `pnpm build`（electron-builder 打包，产物在 `electron/release/*.exe`）。

> 嵌入式 Python 全程以 `-s` 旗标运行以隔离用户级 site-packages——这是踩过
> 「构建机 pip 假安装 → 分发机 `ModuleNotFoundError: uvicorn`」的坑后确定的方案，
> 细节见 `scripts/prepare-python.ps1` 头部注释。桌面端启动链路与数据目录说明见
> [USAGE.md](docs/USAGE.md) 的「桌面客户端」章节。

### 访问

- 前端：http://localhost:3000
- 后端 API 文档：http://127.0.0.1:8000/docs

首次使用点顶栏「设置」弹窗配置 API Key 后即可在**对话形态**提问；顶栏「建模」切到**流水线形态**，点「运行内置样例」可看到完整六节点流程。

---

## 执行流程

系统有**两种运行形态**，共用同一套 Tool / Skill / Agent 资产：

| 形态 | 入口 | 编排方式 | 接口 |
| --- | --- | --- | --- |
| **对话**（默认） | 顶栏「对话」 | 投研主管（LLM）逐轮决策调度哪位专家，结果回灌后继续判断 | `POST /api/chat` |
| **建模** | 顶栏「建模」 | 固定六节点 DAG（`COORDINATOR_PLAN` + `REVIEW_PLAN`，确定性调度、不耗 Token） | `POST /api/analyze` |

下面是**建模形态**的固定拓扑：

```
┌─────────┐   ┌─────────┐   ┌─────────────┐
│ ingest  │──▶│ extract │──▶│ coordinator │
│ 文档解析 │   │ 数据提取 │   │  主管调度    │
└─────────┘   └─────────┘   └──────┬──────┘
                                    │
                    ┌───────────────┴───────────────┐
                    ▼                               ▼
            ┌───────────────┐               ┌───────────────┐
            │   analysis    │               │    review     │
            │ 财务 + 估值    │               │ 风险 + 反方    │
            │  并行执行      │               │  并行执行      │
            └───────┬───────┘               └───────┬───────┘
                    └───────────────┬───────────────┘
                                    ▼
                            ┌───────────────┐
                            │    report     │
                            │  综合成文      │
                            └───────────────┘
```

| 节点 | 参与者 | 职责 | 产出 |
| --- | --- | --- | --- |
| ingest | 调度中心 | PDF/TXT 解析、分页、切片 | 全文、页码引用 |
| extract | 数据提取员 | 结构化抽取 + 派生指标 | 财务字段、指标 |
| coordinator | 投研主管 | 按固定计划编排专家（确定性调度，不消耗 Token） | 执行计划 |
| analysis | 财务分析师、估值专家 | 并行分析财报与估值建模 | 分析结论、DCF 结果 |
| review | 风险审查员、反方质疑者 | 并行识别风险、挑战结论 | 风险清单、反驳意见 |
| report | 报告撰写人 | 综合四方意见撰写简报 | 投资研究报告 |

每个智能体运行在独立的 **ReAct 循环** 中：

```
思考（流式输出） → 返回 tool_calls → 执行工具 → 观察结果回灌 → 继续思考
                                                    ↓
                              直到某轮不再调用工具，正文即为结论
```

---

## 三层抽象

系统按主流开源 Agent 底座的范式组织代码：

| 层 | 载体 | 职责 | 位置 |
| --- | --- | --- | --- |
| **Tool** | Python 函数 | 原子能力，模型可直接调用，无决策能力 | `backend/app/tools/` |
| **Skill** | Markdown 文件 | 任务说明书，告诉智能体「这类任务该怎么做」 | `backend/app/skills/` |
| **Agent** | Python 定义 | 持有 LLM 的决策者，有独立 System Prompt 与工具白名单 | `backend/app/agents/` |

### 已注册能力

**23 个工具**

| 类别 | 工具 |
| --- | --- |
| 文档 | `parse_document`（PDF/TXT 解析 + 可读性诊断） |
| 溯源 | `locate_evidence`（原文定位与页码溯源） |
| 抽取与指标 | `extract_fields` · `compute_metrics` · `financial_ratio_suite` · `yoy_compare` · `peer_comparison` |
| 估值 | `build_assumptions` · `dcf_valuation` · `relative_valuation` · `sensitivity_grid` · `summarize_valuation` |
| 行情（A 股） | `stock_quote` · `stock_history` · `financial_history` |
| 联网 | `web_search` · `fetch_url` · `current_datetime` |
| 计算 | `python_calc` |
| 技能 | `list_skills` · `load_skill` |
| 交互 | `ask_user` · `set_conversation_title` |

**9 个技能**

| 技能 | 说明 |
| --- | --- |
| `financial_analysis` | 财报解析与指标核算流程 |
| `valuation_modeling` | DCF 与相对估值建模流程 |
| `investment_report` | 投资简报撰写规范 |
| `market_data` | A 股行情与历史财务；非 A 股改用搜索 |
| `web_research` | 联网调研与来源标注 |
| `supervisor_coordination` | 主管调度协议（改文件即可热更新路由） |
| `risk_analysis` | 风险清单 + 反向验证条件 |
| `peer_benchmark` | 同业对标表与差异解读 |
| `earnings_quality` | 盈利质量（利润含金量）核查 |

**8 个智能体**

| 智能体 | 角色 | 工具 |
| --- | --- | --- |
| `coordinator` | 投研主管（对话形态的 LLM 调度 / 建模形态不调 LLM） | — |
| `financial_analyst` | 财务分析师 | 抽取 · 指标 · 比率 · 同比 · 溯源 · 同业 · 财务历史 · 计算 · 搜索 |
| `valuation_expert` | 估值专家 | 估值工具组 · 比率 · 同业 · 行情 · 财务历史 · 计算 · 搜索 |
| `risk_reviewer` | 风险审查员 | 指标 · 比率 · 同比 · 溯源 · 行情 · 财务历史 · 计算 · 搜索 |
| `devils_advocate` | 反方质疑者 | 行情 · 财务历史 · 比率 · 同业 · 计算 · 搜索 |
| `market_analyst` | 市场数据研究员 | 行情 · K 线 · 历史财务 · 计算 · 搜索 |
| `research_assistant` | 信息研究员 | 联网搜索 · 抓取 · 行情 |
| `report_writer` | 报告撰写人 | 交互（提问 · 会话命名） |

除主管外，7 位专家均可调用 `ask_user` / `set_conversation_title`。运行时可通过 `GET /api/registry` 查询全部清单（含每个智能体的完整工具白名单与内联技能）。

---

## 界面说明

顶栏：模型状态徽标（未配置时提示「点击设置」）· 新对话 · 协作 · 设置（弹窗）·「对话 / 建模」形态切换。桌面客户端下顶栏同时充当窗口标题栏（可拖动移动窗口），右端有最小化 / 最大化·还原 / 关闭三按钮；浏览器访问时这三处自动隐藏，与 Web 版观感一致。

```
┌────────────┬──────────────────────────┬────────────────────┐
│            │                          │                    │
│  会话侧栏   │   对话流 / 流水线结果      │  智能体协作面板     │
│ （可折叠）  │   输入框（/ 选技能）       │ （可拖动调宽）      │
│            │                          │                    │
└────────────┴──────────────────────────┴────────────────────┘
```

- **会话侧栏**：全部会话（含建模会话）列表、新建、删除；点条目切回对应会话
- **对话形态**（默认）：消息流 + 输入框，输入 `/` 直接选技能（如 `/valuation_modeling`）；模型配置走顶栏「设置」弹窗，界面已无常驻左侧设置栏
- **建模形态**：顶部流水线进度（6 节点耗时）+ 上传区（PDF/TXT/MD）+「运行内置样例」，下方是结果面板
- **智能体协作面板**：每位智能体一个独立滚动窗口，显示思考 / 工具调用 / 输出；窗口可放大聚焦
- **结果面板**（建模形态）：四个标签页
  - 研究报告（Markdown 渲染，含来源标注）
  - 估值建模（区间卡片 + 分方法估值 + DCF 关键值 + 相对估值 + 敏感性表格）
  - 结构化数据（财务字段 + 派生指标）
  - 专家意见（各专家长文输出，Markdown 渲染）

---

## 模型配置

支持**多档案**管理，每个档案独立保存提供商、模型、API Key 与备用模型链。

### 配置位置

`backend/data/profiles.json`

```json
{
  "profiles": [
    {
      "id": "default",
      "name": "DeepSeek",
      "provider": "deepseek",
      "model": "deepseek-chat",
      "fallbackModels": ["deepseek-reasoner"],
      "apiKey": "sk-...",
      "baseUrl": ""
    }
  ],
  "activeId": "default",
  "search": {
    "tavilyApiKey": "",
    "bochaApiKey": "",
    "searxngUrl": ""
  }
}
```

界面修改会同步写入此文件，同时缓存到浏览器 localStorage。`search` 为联网搜索源配置（设置弹窗「搜索 API」页签写入），同名请求头优先于此处的存档。

### 内置提供商

| 提供商 | key | 默认端点 |
| --- | --- | --- |
| DeepSeek 深度求索 | `deepseek` | `https://api.deepseek.com/v1` |
| 通义千问 | `qwen` | `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| 智谱 GLM | `glm` | `https://open.bigmodel.cn/api/paas/v4` |
| 月之暗面 Kimi | `moonshot` | `https://api.moonshot.cn/v1` |
| OpenAI | `openai` | `https://api.openai.com/v1` |
| Ollama 本地 | `ollama` | `http://127.0.0.1:11434/v1` |
| 自定义 | `custom` | 自行填写 |

### 模型探测

设置面板中的「检测」按钮会调用 `POST /api/models`：

- **列表模式**：拉取提供商支持的全部模型
- **探测模式**：对候选模型发最小请求，验证连通性

---

## 稳定性设计

| 机制 | 说明 |
| --- | --- |
| **不限制输出长度** | 不传 `max_tokens`，让模型自行决定收尾时机，避免挤压正文空间 |
| **重试退避** | 指数退避 + 随机抖动，最多 8 次，覆盖超时 / 网络错误 / 5xx / 429 |
| **备用模型链** | 主模型连续失败 3 次自动切换至下一个备用模型 |
| **单次执行** | `astream(["custom","values"])` 一次拿事件与最终状态，不重复跑图 |
| **断点续跑** | 每节点写检查点，中断后可从任意位置继续，已完成节点的 LLM 调用直接复用 |
| **JSON 修补** | 抽取结果被截断时自动补齐未闭合括号、并从尾部逐层截断重试（`extraction.py`）；主管决策解析容忍围栏与夹带文字（`decision.py`），失败时纠偏重试一次 |
| **噪声过滤** | 前端渲染前剥离模型自带的 XML 工具调用标签（`AgentStage.tsx` 的 `NOISE`）；后端保留原文以便排查 |

---

## 断点续跑

每个节点执行完成后写入 `backend/data/checkpoints/{run_id}.json`，记录：

- 已完成节点列表
- 各智能体的输出与工具调用记录
- 文档解析结果、抽取字段、估值结果、报告全文

恢复方式（当前仅后端接口 + hook，界面未挂按钮）：

- `GET /api/runs/latest` 取最近未完成的检查点
- `GET /api/analyze/resume?run_id=...` 从该检查点续跑（已完成节点直接复用结果）
- 前端 `useAnalyzeRun().resume(runId, llm)` 已实现，可挂到任意按钮上

---

## 目录结构

```
.
├── README.md                  本文档
├── dev.ps1                    一键启动脚本（开发）
├── check.ps1                  质量门禁（ruff + pytest + tsc）
├── scripts/
│   ├── build.ps1              桌面客户端一键构建（三步）
│   └── prepare-python.ps1     准备嵌入式 Python 运行时（backend/python/）
├── CHANGELOG.md               版本变更记录
├── docs/                      详细文档
│   ├── ARCHITECTURE.md        架构详解
│   ├── USAGE.md               使用指南与故障排查
│   ├── DEVELOPMENT.md         开发与扩展指南
│   ├── DESIGN.md              系统设计（分层 / 数据流 / 设计决策）
│   ├── THIRD_PARTY.md         第三方依赖清单（名称/版本/来源/许可证/使用范围）
│   └── architecture.html      架构图（浏览器直接打开）
│
├── electron/                  桌面客户端（Electron 壳）
│   ├── main.cjs               主进程：拉起后端/前端、动态端口、加载窗口
│   ├── preload.cjs            注入 window.WEISTER 桥（API 基址 + 窗口控制）
│   ├── loading.html           启动加载窗口
│   ├── scripts/prepare-frontend.cjs  打包前物化 standalone（符号链接解引用等）
│   └── package.json           electron-builder 配置（portable 目标）
│
├── backend/
│   ├── pyproject.toml
│   ├── .env.example
│   ├── python/                嵌入式 Python 运行时（构建脚本生成，不纳入版本控制）
│   ├── app/
│   │   ├── main.py            应用入口（挂载 app/api/ 各路由）
│   │   ├── __main__.py        `python -m app` 入口（读 HOST/PORT 环境变量）
│   │   ├── paths.py           路径解析：数据目录按平台落 %APPDATA%（唯一来源）
│   │   ├── api/               HTTP 接口与 SSE（meta / analyze / chat / sse / store / helpers / deps）
│   │   ├── orchestrator.py    建模形态：图编排与专家团调度
│   │   ├── chat_supervisor.py 对话形态：主管 supervisor 循环
│   │   ├── decision.py        主管决策解析与字段规范化
│   │   ├── interaction.py     ask_user 交互（等待用户选择）
│   │   ├── state.py           LangGraph 状态定义
│   │   ├── events.py          SSE 事件协议
│   │   ├── llm.py             LLM 客户端（流式 / 重试 / 备用链）
│   │   ├── providers.py       提供商注册表
│   │   ├── models.py          模型探测
│   │   ├── tokens.py          上下文预算与 token 估算
│   │   ├── checkpoint.py      运行检查点
│   │   ├── runlog.py          运行日志持久化
│   │   ├── runctx.py          运行上下文
│   │   ├── searchcfg.py       搜索源配置
│   │   ├── mcp_server.py      MCP 服务器（对外暴露工具）
│   │   ├── storage.py         data 目录读写
│   │   ├── config.py          环境配置
│   │   ├── core/
│   │   │   └── registry.py    Tool / Skill / Agent 注册表
│   │   ├── tools/             原子能力（14 个模块 / 23 个工具）
│   │   ├── skills/            技能说明书（9 份 *.md）
│   │   └── agents/            ReAct 执行器与智能体定义
│   └── data/                  运行时数据（仅开发模式；桌面端落 %APPDATA%\Weister\data）
│       ├── profiles.json      模型配置
│       ├── samples/           演示样例（annual_report.txt + catl_2024_annual.pdf）
│       ├── checkpoints/       运行检查点
│       └── runs/              运行日志（events.jsonl / messages.jsonl + summary.json）
│
└── frontend/
    ├── package.json
    ├── next.config.ts         output: standalone（桌面端打包前置）
    └── src/
        ├── app/               页面与全局样式
        ├── components/        UI 组件（chat/ · settings/ 子目录 · WindowControls）
        ├── hooks/             状态逻辑
        └── lib/               协议、API、配置（desktop.ts / apiBase.ts）
```

---

## API 速查

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/health` | 健康检查 |
| GET | `/api/providers` | 提供商列表 |
| GET | `/api/registry` | 工具 / 技能 / 智能体清单 |
| GET | `/api/skills/{name}` | 技能正文与所属智能体 |
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
| POST | `/api/analyze` | 上传文件执行 |
| GET | `/api/analyze/demo` | 用样例执行 |
| GET | `/api/analyze/resume` | 从检查点续跑 |
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

完整交互式文档见 http://127.0.0.1:8000/docs

---

## 文档索引

| 文档 | 内容 |
| --- | --- |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 分层设计、事件协议、执行器实现、数据流 |
| [docs/USAGE.md](docs/USAGE.md) | 界面操作、配置管理、桌面客户端、常见问题排查 |
| [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) | 新增工具 / 技能 / 智能体、调试技巧 |
| [docs/DESIGN.md](docs/DESIGN.md) | 系统设计：分层、数据流、关键设计决策与取舍 |
| [docs/THIRD_PARTY.md](docs/THIRD_PARTY.md) | 第三方依赖清单与自主开发范围声明 |
| [docs/architecture.html](docs/architecture.html) | 可视化架构图（浏览器直接打开） |

---

## 安全提示

- **API Key 明文存储**：`data/profiles.json` 与浏览器 localStorage 均不加密，演示时注意遮挡
- **访问日志**：凭据（`X-LLM-Api-Key` 等）一律走请求头，不出现在 URL 中，因此不会写进 uvicorn 的 access log；业务参数（如 `question`、附件）仍走表单，但不含密钥。`backend/.env` 里的兜底 Key 以明文保存
- **第三方依赖**：使用开源项目时请遵守对应许可证

---

## 许可证

本项目为竞赛参赛作品。使用的第三方开源库遵循各自许可证。
