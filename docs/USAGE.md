# Weister 使用指南

本文档说明界面操作、配置管理与常见问题排查。

---

## 目录

- [首次使用](#首次使用)
- [桌面客户端](#桌面客户端)
- [配置模型](#配置模型)
- [聊天模式（推荐）](#聊天模式推荐)
- [运行分析（v1 DAG，留作对比）](#运行分析v1-dag留作对比)
- [理解结果](#理解结果)
- [断点续跑](#断点续跑)
- [MCP 集成](#mcp-集成)
- [运行日志](#运行日志)
- [常见问题](#常见问题)

---

## 首次使用

### 1. 启动服务

```powershell
.\dev.ps1
```

看到以下输出表示成功：

```
[0/4] 检查环境
[1/4] 清理占用端口
[2/4] 检查依赖
[3/4] 启动后端
  后端就绪 (PID 12345, version 0.3.1)
[4/4] 启动前端

服务已启动

  前端  http://localhost:3000
  后端  http://127.0.0.1:8000/docs
```

> 前端分支：`frontend/.next/BUILD_ID` 存在且未带 `-Reload` 时用 `pnpm start`（生产模式，秒开）；否则用 `pnpm dev`。
> 首次运行会自动建 venv / 装依赖，需要等一会儿。

### 2. 打开界面

浏览器访问 http://localhost:3000

---

## 桌面客户端

不想装 Node / uv 环境的话，可以直接用免安装的桌面版：双击 `electron/release/Weister-*.exe`（构建方法见 [DEVELOPMENT.md](DEVELOPMENT.md) 的「桌面端构建」），或由 `scripts\build.ps1` 一键产出。

### 它是怎么启动的

双击 exe 后 Electron 会按顺序自动完成（进度显示在启动加载窗口上）：

1. **分配端口**：后端默认 8000、前端默认 3000，被占用时自动 +1 递增（最多试 20 个）——所以不用手动关掉占端口的程序
2. **启动后端**：使用包内自带的 Python 嵌入式运行时（`resources/backend/python/`），无需系统安装 Python
3. **启动界面**：用 Electron 内置 Node 跑 Next.js standalone 服务，无需系统安装 Node
4. **就绪检查**：后端 `/api/health` 与前端首页各轮询 60 秒，通过后打开主窗口

启动失败时，加载窗口会显示具体原因（含后端进程输出的末几行），而不是一句笼统的超时提示。

### 数据保存在哪里

桌面版**不写**安装目录，所有数据统一放在：

```
%APPDATA%\Weister\data\
├── profiles.json    模型配置（API Key 等）
├── samples\         演示样例
├── checkpoints\     建模运行检查点
└── runs\            会话历史与运行日志
```

- 卸载或删除 exe 不影响这份数据；「完全重置」见[常见问题](#如何完全重置)
- 高级：设置 `DATA_DIR` 环境变量可以把数据指到任意目录（相对路径按 backend 目录解析）

### 与浏览器版的差异

- 顶栏同时是**窗口标题栏**：按住顶栏空白处可拖动窗口，右端有最小化 / 最大化·还原 / 关闭三按钮
- 后端地址由桌面壳自动注入（`window.WEISTER.API_BASE`），界面上不需要也不能改端口
- 其余功能（配置模型、聊天、建模、断点续跑）与浏览器版完全一致

### 常见桌面端问题

- **双击后卡在加载窗口**：先看加载窗口上的错误详情。若提示 backend not responding，多半是杀毒软件拦截了包内 python.exe——把 `resources\backend\python\` 加入白名单后重试
- **想看后端日志**：数据目录在 `%APPDATA%\Weister\data\`，运行日志在 `runs\` 子目录，界面「协作」面板也能看实时事件流

---

## 配置模型

首次运行前必须配置 API Key。

### 界面配置

1. 点顶栏「设置」打开模型配置弹窗
2. 在「提供商」下拉选择服务商
3. 在「模型」下拉选择具体模型
4. 在「API Key」填入密钥
5. 状态徽章变为「已配置」（「模型设置」卡片右上角）

### 多档案管理

每个档案是一组独立的「提供商 + 模型 + Key」配置。

| 操作 | 方式 |
| --- | --- |
| 新增档案 | 点「配置档案」右侧的「+ 新增」 |
| 切换档案 | 点击档案卡片 |
| 重命名 | 点「重命名」后编辑 |
| 删除 | 切换到该档案后点卡片右侧的垃圾桶图标 |

切换档案时会自动清空上一次的模型检测结果。

### 检测可用模型

点「可选模型」区块的「检测」按钮：

- 会调用提供商的 `/v1/models` 接口拉取模型列表
- 列表支持关键字筛选
- 点某个模型即可切换为当前模型

点「连通性测试」会对列表前 20 个模型发最小请求：

- ✅ 绿色对勾：可用
- ❌ 红色叉号：失败（鼠标悬停看错误详情）

### 配置备用模型链

当主模型持续不可用时自动切换。

1. 在模型列表中，对非当前模型点右侧的「+」
2. 该模型加入「备用模型链」区块，按序号排队
3. 主模型连续失败 3 次后自动切换到第 1 个备用

点备用模型右侧的「×」移除。

### 配置联网搜索源（可选）

「设置 → 搜索 API」可填三项（也可写进 `backend/.env`）：

| 变量 | 说明 |
| --- | --- |
| `TAVILY_API_KEY` | Tavily，LLM 生态常用 |
| `BOCHA_API_KEY` | 博查，国内可用性最好 |
| `SEARXNG_URL` | 自建 SearXNG 实例地址 |

按 `tavily → bocha → searxng → 百度 → 必应中国` 的顺序降级（见 `backend/app/tools/web.py` 的 `providers` 列表）；全部留空时走免密钥的百度 / 必应中国。
面板里的「测试」按钮对应 `POST /api/search/test`。

### 配置文件位置

界面保存的配置写入 `backend/data/profiles.json`（桌面版在 `%APPDATA%\Weister\data\profiles.json`）：

```json
{
  "profiles": [
    {
      "id": "p1",
      "name": "DeepSeek",
      "provider": "deepseek",
      "model": "deepseek-chat",
      "fallbackModels": ["deepseek-reasoner"],
      "apiKey": "sk-...",
      "baseUrl": ""
    }
  ],
  "activeId": "p1"
}
```

也可以直接编辑这个文件，刷新页面即生效。

### 本地模型 / 离线演示（Ollama）

现场无外网时，用本机 OpenAI 兼容端点即可，无需改代码：

1. 安装并启动 [Ollama](https://ollama.com)，拉取模型，例如：

```powershell
ollama pull qwen2.5:7b
ollama serve   # 若未以服务方式运行
```

2. 界面「提供商」选 **Ollama 本地**（或「自定义」）
3. Base URL 保持 `http://127.0.0.1:11434/v1`（Ollama 默认）
4. 模型名填 `qwen2.5:7b` 等本地标签；API Key 可留空或填任意非空串
5. 点「检测」确认连通

> 小参数模型对 JSON 决策协议服从性较弱。系统已做字段规范化与纠偏重试，但仍建议：
> - 优先 7B+ 指令模型
> - 演示前用「连通性测试 + 一句『你好』」冒烟
> - 关键演示同时准备云端 Key 作为备用档案

自建 vLLM / llama.cpp 的 OpenAI 兼容服务同理：提供商选「自定义」，填 Base URL 即可。

---

## 聊天模式（推荐）

> 自 2026-09-12 起，UI 默认为**聊天形态**。左侧文件侧栏已移除，设置改为独立弹窗。
>
> 聊天模式与原 `/api/analyze`（6 节点硬编码 DAG）并存——前者是默认入口，后者保留作对比 / 续跑用。

### 主界面布局

```
┌──────────────────────────────────────────────────────────────────────┐
│ W  Weister  · 多智能体投研 · 自由对话与协作   [新对话] [协作] [设置] │
├─────────────────────────────────────────────┬────────────────────────┤
│                                             │                        │
│  对话流                                     │  智能体协作（折叠）     │
│  ··· 历史消息 ···                           │  · 调度中心             │
│                                             │  · coordinator 投研主管 │
│                                             │  · financial_analyst   │
│                                             │  · valuation_expert    │
│                                             │  · risk_reviewer       │
│                                             │  · devils_advocate     │
│                                             │  · market_analyst      │
│                                             │  · research_assistant  │
│                                             │  · report_writer       │
│                                             │                        │
├─────────────────────────────────────────────┴────────────────────────┤
│ 📎 [输入框]                              [发送]                      │
└──────────────────────────────────────────────────────────────────────┘
```

- 顶栏右侧「协作」按钮：折叠/展开智能体协作面板（默认折叠，看到「本轮调度 N 位专家」时点开看每个专家在做什么）
- 顶栏「设置」：弹窗方式打开模型配置
- 顶栏「新对话」：清空聊天与时间线，run_id 重置

### 与聊天机器人的区别

| 维度 | 普通聊天 | Weister 聊天模式 |
| --- | --- | --- |
| 谁回话 | 一个 LLM | 投研主管（coordinator）做真 LLM 决策，按需调度 7 位专家 |
| 任务 | 一问一答 | 用户可连续追问、追加资料、变更方向；专家结果自动回灌给主管做下一步判断 |
| 文档 | 仅作为上下文片段 | 支持中途**追加上传**（PDF/Word/Excel/PPT/TXT/MD + 图片） |
| 图片 | 仅展示 | 多模态直传 LLM（`image_url` content 数组），主管与专家都能看图 |
| 历史 | 上下文窗口（丢就丢） | 落盘 `data/runs/{run_id}/messages.jsonl`，刷新可继续 |

### 附件支持矩阵

| 类别 | 格式 | 处理路径 |
| --- | --- | --- |
| 文档 | `.pdf` | `tools.parsing.parse_pdf`（PyMuPDF） |
| 文档 | `.docx` | `parse_docx`（python-docx） |
| 表格 | `.xlsx` | `parse_xlsx`（openpyxl） |
| 演示 | `.pptx` | `parse_pptx`（python-pptx 文本提取） |
| 文本 | `.txt` / `.md` | 直接读 |
| 图片 | `.png`/`.jpg`/`.jpeg`/`.gif`/`.webp` | 不解析文本，转 `image_url` 多模态格式 |

> **依赖说明**：`.docx` / `.xlsx` 需装可选依赖（`cd backend && uv sync --extra office`）；
> `.pptx` 依赖 `python-pptx`，当前未纳入任何 extra，需手动 `uv pip install python-pptx`；
> 扫描件 OCR 走 `uv sync --extra ocr`（内置 RapidOCR，无需系统 Tesseract），也可安装系统 Tesseract + `chi_sim+eng` 语言包，两者都缺时接口会返回明确的安装提示，不会静默失败。

### 一个完整流程示例

1. **首问上传资料**

   ```
   我：看看这份年报，重点是利润质量与现金流。
       （拖入 annual_report.pdf）
   ```

2. **supervisor 看标题决定调度顺序**

   ```
   系统：「第 1 轮调度」
   系统：「投研主管 评估下一步」
   系统：「主管调度：财务分析师」
   专家：（financial_analyst 输出...）
   系统：「第 2 轮调度」
   系统：「投研主管 评估下一步」
   系统：「主管调度：估值专家」
   ```

3. **主管最终 reply**

   ```
   助手：经过财务分析师和估值专家的协同分析，估值区间 80~120 亿元…
   ```

4. **追问变更方向**

   ```
   我：换个思路——有没有被忽略的负面证据？
   系统：「第 3 轮调度」
   系统：「主管调度：反方质疑者」
   助手：……
   ```

5. **中途补传图**

   ```
   我：（拖入某结构图.png）这两条线的区别是什么？
   系统：「第 4 轮调度」——多模态 content 数组里加入 image_url
   ```

### 上限与防护

- **supervisor 不设固定轮数预算**：终止以「是否还有进展」为准——连续 `MAX_IDLE_ROUNDS = 3` 轮无进展即收尾，另有 `ABSOLUTE_ROUND_LIMIT = 50` 兜底防死循环（`backend/app/chat_supervisor.py`）
- **specialist 仍走 AgentRunner**：每次调度复用现有 ReAct 循环 + `max_steps` 防御
- **已调度的专家下一轮默认不复调**：除非用户明确要求重新评估

### API 速查

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/chat` | 跑一轮聊天（multipart：message + run_id + attachments + files）|
| POST | `/api/chat/estimate` | 上下文 token 估算（输入框用量条） |
| POST | `/api/chat/answer` | 回答 `ask_user` 的选择 |
| GET | `/api/chat/{run_id}` | 读取历史 `messages.jsonl`，用于刷新后续聊 |
| GET | `/api/conversations` | 会话列表（侧栏数据） |
| GET | `/api/conversations/{run_id}/events` | 某会话事件流，用于还原协作面板 |
| DELETE | `/api/conversations/{run_id}` | 删除会话（聊天记录 + 协作面板数据） |

```bash
# 简单问候
curl -X POST http://127.0.0.1:8000/api/chat \
  -H "X-LLM-Provider: deepseek" \
  -H "X-LLM-Model: deepseek-chat" \
  -H "X-LLM-Api-Key: sk-..." \
  -F "message=你好" \
  -F "attachments=[]" \
  -F "run_id="

# 带附件
curl -X POST http://127.0.0.1:8000/api/chat \
  -H "X-LLM-Provider: deepseek" \
  -H "X-LLM-Api-Key: sk-..." \
  -F "message=帮我看这份年报" \
  -F "attachments=[{\"id\":\"f0\",\"name\":\"annual_report.pdf\",\"mime\":\"application/pdf\"}]" \
  -F "files=@annual_report.pdf" \
  -F "run_id="

# 续聊
curl -X POST http://127.0.0.1:8000/api/chat \
  -H "X-LLM-Api-Key: sk-..." \
  -F "message=继续" \
  -F "attachments=[]" \
  -F "run_id=ba70f548ef05"
```

### 历史落盘位置

每条 `run_id` 的对话历史写到：

```
backend/data/runs/{run_id}/messages.jsonl   （桌面版：%APPDATA%\Weister\data\runs\）
```

JSONL 格式（每行一条 message），便于追加写入与续读。视觉消息（`image_url`）也保留，刷新后可重建多模态上下文。

---

## 运行分析（v1 DAG，留作对比）

### 用内置样例

点「运行内置样例」按钮，使用 `backend/data/samples/annual_report.txt`。

### 用自己的财报

1. 点「选择财报 PDF/TXT」挑一个文件（也可以是 `.md`）
2. 点「上传分析」（建模形态的提问固定为后端的默认问题 `DEFAULT_QUESTION`，如需自定义问题，直接调 `POST /api/analyze` 并带 `question` 字段）
3. 运行中可在右侧「协作面板」看每个智能体的实时动作

### 观察执行

右侧「智能体工作台」会依次出现窗口：

| 阶段 | 窗口 |
| --- | --- |
| 文档解析 | 调度中心 |
| 数据提取 | 数据提取员 |
| 计划制定 | 投研主管 |
| 分析组 | 财务分析师、估值专家（并行） |
| 评审组 | 风险审查员、反方质疑者（并行） |
| 报告撰写 | 报告撰写人 |

每个窗口内实时显示：

- **思考块**（紫色）：模型的推理过程，运行中展开，完成后自动折叠
- **工具调用**（琥珀色）：正在调用的工具名
- **工具返回**（绿色）：调用结果摘要
- **正文输出**（白色）：模型的最终回复
- **日志**（灰色）：步数、重试信息

窗口右上角的放大图标可切换单窗口聚焦视图。

### 手动滚动

每个窗口默认自动跟随最新内容。向上滚动后会停止跟随，右下角出现「回到底部」按钮。

---

## 理解结果

结果面板有四个标签页。

### 研究报告

Markdown 渲染的买方投资简报，包含：

- 摘要与核心结论
- 盈利质量分析
- 现金流风险分析
- 估值分析（DCF + 相对估值 + 综合区间）
- 风险与反向验证条件（表格）
- 数据不足说明
- 结论与建议

关键结论标注来源，格式为 `[p3]`（第 3 页）或 `[风险审查员]`（专家意见）。

### 估值建模

- 三张区间卡片：估值下沿 / 中位数 / 上沿
- 分方法估值（DCF、PE、PS 各自的结果或区间）
- DCF 关键值（企业价值、权益价值、终值现值、每股价值、净债务、终值占比）
- 相对估值（PE / PS 倍数与隐含市值的原始结果）
- 敏感性表格（WACC × 永续增长率 → 股权价值）

### 结构化数据

- 关键财务字段：营业收入、净利润、经营现金流、总资产、总负债、EPS、总股本
- 派生指标：净利率、现金流/营收、资产负债率、利润现金缺口、利润现金流背离

### 专家意见

- 各专家（财务分析师 / 估值专家 / 风险审查员 / 反方质疑者）的完整长文输出，Markdown 渲染。报告撰写人的产出进「研究报告」页，不出现在这里。

---

## 断点续跑

### 什么情况会中断

- 网络故障导致 LLM 调用失败且重试耗尽
- 模型服务返回持续 5xx
- 用户主动关闭浏览器（后端仍在跑，但前端不再接收）

### 如何恢复

**当前入口：后端接口 + 前端 hook**（界面尚未挂载按钮）

```bash
# 1. 找到最近未完成的检查点
curl http://127.0.0.1:8000/api/runs/latest

# 2. 从该检查点续跑（SSE 流，已完成节点直接复用结果）
curl -N "http://127.0.0.1:8000/api/analyze/resume?run_id={run_id}"
```

前端已在 `useAnalyzeRun()` 中暴露 `resume(runId, llm)`，需要按钮时接到任意组件即可。

恢复时会跳过已完成节点的 LLM 调用，直接复用检查点中的结果。

### 查看检查点

```bash
# 列出全部运行
curl http://127.0.0.1:8000/api/runs

# 查看某个检查点
curl http://127.0.0.1:8000/api/runs/{run_id}

# 删除检查点
curl -X DELETE http://127.0.0.1:8000/api/runs/{run_id}
```

---

## MCP 集成

Weister 的工具可以通过 **Model Context Protocol** 暴露给外部 AI 客户端，如 Claude Desktop、Cline。

### 可用的工具

实际暴露 **20 个**（23 个工具中排除 3 个），按类别：

| 类别 | 工具 |
| --- | --- |
| 估值 | `dcf_valuation` · `sensitivity_grid` · `relative_valuation` · `summarize_valuation` |
| 指标 | `compute_metrics` · `financial_ratio_suite` · `yoy_compare` · `peer_comparison` |
| 行情 | `stock_quote` · `stock_history` · `financial_history` |
| 联网 | `web_search` · `fetch_url` · `current_datetime` |
| 计算 | `python_calc` |
| 技能 | `list_skills` · `load_skill` |
| 交互 | `ask_user` · `set_conversation_title` · `locate_evidence` |

不暴露的工具及原因：

| 工具 | 原因 |
| --- | --- |
| `extract_fields` | 需要注入 `LLMClient` |
| `build_assumptions` | 需要注入 `LLMClient` |
| `parse_document` | 需要文件字节流（并在 `mcp_server.EXCLUDED` 中显式排除） |

### 在 Claude Desktop 中配置

编辑配置文件：

**Windows**：`%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "weister": {
      "command": "uv",
      "args": [
        "run",
        "--directory",
        "C:/Users/你的用户名/Desktop/Weister/backend",
        "python",
        "-m",
        "app.mcp_server"
      ]
    }
  }
}
```

重启 Claude Desktop 后，对话中会出现工具图标。

### 测试 MCP 服务器

用官方 Inspector 调试：

```bash
npx @modelcontextprotocol/inspector uv run python -m app.mcp_server
```

浏览器会打开调试界面，可以手动调用每个工具查看返回。

### 在终端中直接调用

```bash
cd backend
uv run python -m app.mcp_server
```

服务器以 stdio 模式运行，会等待 MCP 协议的 JSON-RPC 消息。手动输入 `{"jsonrpc":"2.0","id":1,"method":"tools/list"}` 加换行可以看到工具列表。

---

## 运行日志

每次运行都会在 `backend/data/runs/{run_id}/` 下生成日志（桌面版在 `%APPDATA%\Weister\data\runs\`）。

### 查看日志列表

```bash
curl http://127.0.0.1:8000/api/logs
```

返回每个运行的摘要：

```json
{
  "logs": [
    {
      "run_id": "96579d894f26",
      "status": "success",
      "duration_ms": 10708,
      "event_count": 128,
      "tool_calls": {"extract_fields": 1, "dcf_valuation": 1},
      "errors": []
    }
  ]
}
```

### 查看完整事件流

```bash
curl "http://127.0.0.1:8000/api/logs/{run_id}?limit=100"
```

返回按时间排序的事件数组，包含每次工具调用、模型输出和错误。

### 直接读取文件

```bash
# 事件流（JSONL 格式）
type backend\data\runs\{run_id}\events.jsonl

# 摘要
type backend\data\runs\{run_id}\summary.json
```

### 日志内容说明

| 字段 | 说明 |
| --- | --- |
| `seq` | 事件序号，从 1 递增 |
| `ts` | Unix 时间戳 |
| `kind` | `run_start` / `event` / `run_end` |
| `type` | 事件类型（见架构文档） |
| `node` | 所属节点 |
| `status` | 事件状态（`running` / `success` / `failed`，节点外事件为 `null`） |
| `message` | 事件消息（最长 2000 字） |
| `payload` | 事件负载，API Key 已脱敏为 `***` |

### 清理日志

```bash
# 删除单次运行
curl -X DELETE http://127.0.0.1:8000/api/logs/{run_id}

# 清空全部（注意：data\runs\ 同时存放会话历史，会一并删除）
Remove-Item backend\data\runs\* -Recurse -Force
```

> `data/runs/{run_id}/` 里既有流水线的 `events.jsonl` / `summary.json`，也有对话形态的 `messages.jsonl` / `documents.json` / `title.txt`。想只清流水线日志，删 `events.jsonl` 与 `summary.json` 即可。

---

## 常见问题

### 启动时报 WinError 10013

**现象**

```
ERROR: [WinError 10013] 以一种访问权限不允许的方式做了一个访问套接字的尝试。
```

**原因**：端口 8000 或 3000 被其他进程占用。

**解决**：新版 `dev.ps1` 会自动清理。若仍失败，手动执行：

```powershell
.\dev.ps1 -Stop
.\dev.ps1
```

桌面客户端不受此问题影响——它从 8000/3000 起自动尝试 +1 递增的空闲端口（最多 20 个）。

### 点击运行后立即报「未提供 API Key」

在「模型设置」中填入 Key，或检查 `backend/data/profiles.json` 的 `activeId` 指向的档案是否有 Key。

### 模型一直返回 503

提供商侧过载。三种处理：

1. 等待几秒重试（客户端已内置最多 8 次指数退避）
2. 在设置中切换到其他模型
3. 配置备用模型链

### 某个智能体一直转圈不结束

**原因**：模型在该轮输出异常长，或工具调用进入循环。

**已内置保护**：

- 单轮不设 token 上限（不传 `max_tokens`，由模型自行收尾）
- 单个智能体最多 `max_steps` 步（默认 24，`DEFAULT_MAX_STEPS`，仅用于防御死循环）
- 单条工具结果超 6000 字先截断再回灌，避免上下文爆炸
- 上下文超预算时按「从最近往前保留」裁剪历史（`tokens.py`）

**若仍出现**，检查该窗口的日志：

- 是否在反复调用同一个工具
- 是否给出完整的 `tool_calls`（或该收尾时没有输出结论）

可在 `agents/specialists.py` 中调低对应智能体的 `max_steps`。

### 报告里出现 `<parameter>` 之类的标签

**原因**：某些模型端点会注入自有的 XML 工具调用语法。

**已内置保护**：前端渲染前统一剥离。若仍有残留，说明出现了新的标签格式，可在 `NOISE` 正则数组中补充：

- `frontend/src/components/AgentStage.tsx` 的 `NOISE` 正则数组（目前只有前端做剥离）
- 后端不再做二次过滤（`agents/base.py` 中已无 `NOISE_TAGS`），原文会原样写进事件流与检查点，便于定位

### 估值标签页没有数据

**原因**：估值专家的工具调用结果未被正确回写。

**排查**：

1. 查看估值专家窗口，确认是否成功调用了 `dcf_valuation`
2. 查看分析组的 `node_end` 事件 payload 中是否有 `valuation_summary`
3. 检查 `backend/data/checkpoints/{run_id}.json` 中的 `dcf` 字段

### 前端页面显示 "This page couldn't load"

前端进程崩溃。重启：

```powershell
.\dev.ps1 -Stop
.\dev.ps1
```

### 中文显示乱码

PowerShell 控制台的编码问题，不影响实际功能。可在启动前执行：

```powershell
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
```

### 如何完全重置

```powershell
# 停止服务
.\dev.ps1 -Stop

# 清除检查点
Remove-Item backend\data\checkpoints\*.json

# 清除模型配置
Remove-Item backend\data\profiles.json

# 重新启动
.\dev.ps1
```

桌面版把上面 `backend\data\` 换成 `%APPDATA%\Weister\data\` 即可（先退出应用再删）。

### 如何添加自己的演示样例

把 `.txt` 文件放进 `backend/data/samples/`，或调用接口：

```bash
curl -X POST http://127.0.0.1:8000/api/samples \
  -H "Content-Type: application/json" \
  -d '{"name":"my_report","text":"营业收入 100 亿元..."}'
```

然后访问：

```
http://127.0.0.1:8000/api/analyze/demo?sample=my_report
```
