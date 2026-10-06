# 第三方依赖清单

本文档列明 Weister 使用的全部第三方开源项目、模型与数据，包括名称、版本、来源、许可证及使用范围，以明确第三方成果与自主开发部分的边界。

---

## 一、后端依赖

### 运行时依赖

| 名称 | 版本 | 来源 | 许可证 | 使用范围 |
| --- | --- | --- | --- | --- |
| FastAPI | ≥0.115.0 | https://github.com/fastapi/fastapi | MIT | HTTP 接口框架，提供 REST 与 SSE 端点 |
| Uvicorn | ≥0.32.0 | https://github.com/encode/uvicorn | BSD-3-Clause | ASGI 服务器，运行 FastAPI 应用 |
| python-multipart | ≥0.0.12 | https://github.com/Kludex/python-multipart | Apache-2.0 | 解析文件上传的表单数据 |
| Pydantic | ≥2.9.0 | https://github.com/pydantic/pydantic | MIT | 请求/响应模型定义与数据校验 |
| pydantic-settings | ≥2.6.0 | https://github.com/pydantic/pydantic-settings | MIT | 环境变量与 .env 配置加载 |
| LangGraph | ≥0.2.60 | https://github.com/langchain-ai/langgraph | MIT | 智能体图编排，节点调度与状态管理 |
| LangChain Core | ≥0.3.25 | https://github.com/langchain-ai/langchain | MIT | 消息抽象与流式接口 |
| HTTPX | ≥0.27.2 | https://github.com/encode/httpx | BSD-3-Clause | 调用 OpenAI 兼容的 LLM 接口 |
| python-dotenv | ≥1.0.1 | https://github.com/theskumar/python-dotenv | BSD-3-Clause | 读取 .env 文件 |
| PyMuPDF | ≥1.24.0 | https://github.com/pymupdf/PyMuPDF | **AGPL-3.0** | 解析 PDF 财报，提取文本与分页信息 |
| MCP Python SDK | ≥1.0.0 | https://github.com/modelcontextprotocol/python-sdk | MIT | 以 Model Context Protocol 暴露工具 |
| tiktoken | ≥0.7.0 | https://github.com/openai/tiktoken | MIT | 估算上下文 token 用量（聊天上下文档位与裁剪） |

### 开发依赖

| 名称 | 版本 | 来源 | 许可证 | 使用范围 |
| --- | --- | --- | --- | --- |
| Ruff | ≥0.7.0 | https://github.com/astral-sh/ruff | MIT | Python 代码检查与格式化（`check.ps1`） |
| pytest | ≥8.0.0 | https://github.com/pytest-dev/pytest | MIT | 单元测试运行 |
| pytest-asyncio | ≥0.24.0 | https://github.com/pytest-dev/pytest-asyncio | Apache-2.0 | 异步测试支持 |

### 可选依赖（需显式安装，默认不装）

| 名称 | 版本 | 来源 | 许可证 | 使用范围 |
| --- | --- | --- | --- | --- |
| python-docx | ≥1.1.0 | https://github.com/python-openxml/python-docx | MIT | 解析 `.docx`（`uv sync --extra office`） |
| openpyxl | ≥3.1.0 | https://foss.heptapod.net/openpyxl/openpyxl | MIT | 解析 `.xlsx`（`uv sync --extra office`） |
| RapidOCR（onnxruntime） | ≥1.3.0 | https://github.com/RapidAI/RapidOCR | Apache-2.0 | 扫描件 PDF 的 OCR 兜底（`uv sync --extra ocr`） |
| python-pptx | 未锁定 | https://github.com/scanny/python-pptx | MIT | 解析 `.pptx`；当前未写入 `pyproject.toml`，需手动 `uv pip install python-pptx` |

### 关于 PyMuPDF 的许可证说明

PyMuPDF 采用 **AGPL-3.0** 与商业许可双授权模式。本项目为非商业用途，遵循 AGPL-3.0 使用。

使用范围严格限定为：

- 读取用户上传的 PDF 文件
- 提取每页纯文本
- 不做任何二次分发或商业集成

若后续需要商业使用，应替换为许可证更宽松的替代方案（如 `pdfplumber`，MIT 许可），或购买 PyMuPDF 商业授权。

---

## 二、前端与桌面端依赖

### 前端运行时依赖

| 名称 | 版本 | 来源 | 许可证 | 使用范围 |
| --- | --- | --- | --- | --- |
| Next.js | 16.3.4 | https://github.com/vercel/next.js | MIT | React 框架，提供路由、SSR 与构建 |
| React | 19.2.8 | https://github.com/facebook/react | MIT | UI 组件库 |
| React DOM | 19.2.8 | https://github.com/facebook/react | MIT | React 的浏览器渲染器 |
| Apache ECharts | ^6.1.0 | https://github.com/apache/echarts | Apache-2.0 | **当前源码未引用**：`package.json` 中保留，供后续图表视图使用；`frontend/src` 无任何 import |
| echarts-for-react | ^3.0.6 | https://github.com/hustcc/echarts-for-react | MIT | **当前源码未引用**（同上） |
| Framer Motion | ^13.2.0 | https://github.com/framer/motion | MIT | 界面过渡动画与布局动画（`AgentStage.tsx` 的窗口动画） |
| Lucide React | ^1.43.0 | https://github.com/lucide-icons/lucide | ISC | 图标库 |
| react-markdown | ^10.1.0 | https://github.com/remarkjs/react-markdown | MIT | 渲染研究报告的 Markdown |
| remark-gfm | ^4.0.1 | https://github.com/remarkjs/remark-gfm | MIT | Markdown 表格、删除线等 GFM 扩展 |
| react-resizable-panels | ^4.12.4 | https://github.com/bvaughn/react-resizable-panels | MIT | **当前源码未引用**：协作面板的拖拽调宽由 `page.tsx` 手写 mouse 事件实现 |
| daisyui | ^5 | https://github.com/saadeghi/daisyui | MIT | 语义化的 UI 组件类库（btn / card / tabs / table / alert / badge / modal / progress / stat 等） |
| animate.css | ^4.1.1 | https://github.com/animate-css/animate.css | MIT | 入场/退出动画类，在 `globals.css` 全局导入，用于界面过渡效果 |

### 开发依赖

| 名称 | 版本 | 来源 | 许可证 | 使用范围 |
| --- | --- | --- | --- | --- |
| TypeScript | ^5 | https://github.com/microsoft/TypeScript | Apache-2.0 | 类型系统与编译 |
| Tailwind CSS | ^4 | https://github.com/tailwindlabs/tailwindcss | MIT | 原子化 CSS 框架 |
| @tailwindcss/postcss | ^4 | https://github.com/tailwindlabs/tailwindcss | MIT | Tailwind 的 PostCSS 集成 |
| ESLint | ^9 | https://github.com/eslint/eslint | MIT | JavaScript/TypeScript 代码检查 |
| eslint-config-next | 16.3.4 | https://github.com/vercel/next.js | MIT | Next.js 官方 ESLint 规则 |
| @types/node | ^20 | https://github.com/DefinitelyTyped/DefinitelyTyped | MIT | Node.js 类型定义 |
| @types/react | ^19 | https://github.com/DefinitelyTyped/DefinitelyTyped | MIT | React 类型定义 |
| @types/react-dom | ^19 | https://github.com/DefinitelyTyped/DefinitelyTyped | MIT | React DOM 类型定义 |

### 桌面端依赖（electron/ 子包，devDependencies）

| 名称 | 版本 | 来源 | 许可证 | 使用范围 |
| --- | --- | --- | --- | --- |
| Electron | 33.4.11 | https://github.com/electron/electron | MIT | 桌面壳：主进程拉起前后端子进程、加载窗口、窗口控制 IPC |
| electron-builder | 25.0.0 | https://github.com/electron-userland/electron-builder | MIT | 打包为 Windows portable 免安装单文件（`electron/release/`） |

桌面端打包还会附带 **Python 嵌入式发行版**（python.org 官方 `python-3.12.9-embed-amd64.zip`，PSF License Agreement）作为后端运行时，由 `scripts/prepare-python.ps1` 下载并安装上述后端依赖——分发包内含的第三方 Python 库以 `uv.lock` / `pyproject.toml` 版本为准，许可证同「后端依赖」表。

---

## 三、AI 模型

本项目**不内置任何模型权重**，通过 OpenAI 兼容协议调用外部 API。支持的提供商与模型如下：

| 提供商 | 模型示例 | 调用方式 | 使用范围 |
| --- | --- | --- | --- |
| DeepSeek 深度求索 | deepseek-chat、deepseek-reasoner | HTTPS API | 智能体的推理引擎 |
| 通义千问 | qwen-plus、qwen-max | HTTPS API | 同上 |
| 智谱 GLM | glm-4-plus、glm-4-flash | HTTPS API | 同上 |
| 月之暗面 Kimi | moonshot-v1-8k | HTTPS API | 同上 |
| OpenAI | gpt-4o、gpt-4o-mini | HTTPS API | 同上 |
| Ollama 本地 | qwen2.5:7b、deepseek-r1:7b 等本地标签 | 本机 HTTP（OpenAI 兼容） | 同上；无外网时的离线预案 |
| 自定义 | 任意 OpenAI 兼容端点 | HTTPS API | 同上 |

**模型权重的版权归各提供商所有**，本项目不修改、不分发、不再训练，仅通过官方 API 调用。

用户需自行提供 API Key，密钥存储于 `backend/data/profiles.json`（本地文件，不上传）。

---

## 四、数据来源

| 数据 | 来源 | 许可证 | 使用范围 |
| --- | --- | --- | --- |
| 虚构演示样例 | 本项目虚构 | — | `backend/data/samples/annual_report.txt`，主体为虚构的「某科技股份有限公司」，数字均为演示用 |
| 真实年报样例 | 宁德时代新能源科技股份有限公司 2024 年年度报告（公开披露文件） | 版权归宁德时代所有 | `backend/data/samples/catl_2024_annual.pdf`，仅用于演示 PDF 解析 / 抽取 / 估值链路；不修改、不二次分发 |
| 行情与财务数据 | 腾讯财经 `qt.gtimg.cn` · 东方财富 `push2*` / `datacenter-web` · 新浪财经 `hq.sinajs.cn`（公开接口，以 A 股为主） | 归各数据提供方 | 运行时按需请求，仅用于本次分析展示，不做归档、不二次分发 |
| 联网检索结果 | Tavily / 博查 Bocha / 自建 SearXNG / 百度 / 必应中国（按此优先级降级，前三个的密钥由用户配置，后两个免密钥） | 归各服务方 | 仅取摘要与链接用于研究，报告中标注来源 |
| 用户上传文件 | 用户自行提供 | 归用户所有 | 仅在本地解析，不持久化原文，不上传第三方 |

**声明**：

- `annual_report.txt` 中的「某科技股份有限公司」为虚构主体，所有数字均为演示用，不对应任何真实上市公司
- `catl_2024_annual.pdf` 是**真实**上市公司的公开年报，仅作为 PDF 解析能力的演示样本随仓库分发；如权利人提出异议将立即移除
- 用户上传的财报数据仅用于本次分析，分析结束后除检查点中的摘要外不留存原文
- 行情与联网检索是**在线调用**：系统不自建、不归档第三方金融数据库，网络不可用时相应工具会明确报错降级

---

## 五、算法与设计参考

以下为本项目在设计与实现时参考的公开资料。**未直接复制其代码**，仅借鉴架构思路。

| 项目 | 来源 | 许可证 | 参考内容 |
| --- | --- | --- | --- |
| Model Context Protocol | https://modelcontextprotocol.io | MIT | 工具暴露协议设计 |
| LangGraph 官方示例 | https://github.com/langchain-ai/langgraph/tree/main/examples | MIT | 多智能体编排模式 |
| ReAct 论文 | https://arxiv.org/abs/2210.03629 | — | 推理与行动交替的智能体范式 |
| Supervisor 模式 | LangGraph 文档 | MIT | 主管调度多专家的架构 |

---

## 六、字体与图标

| 名称 | 来源 | 许可证 | 使用范围 |
| --- | --- | --- | --- |
| Geist Sans | https://github.com/vercel/geist-font | SIL OFL 1.1 | 界面正文字体 |
| Geist Mono | https://github.com/vercel/geist-font | SIL OFL 1.1 | 代码与数字等宽字体 |
| Lucide Icons | https://github.com/lucide-icons/lucide | ISC | 界面图标 |

字体通过 `next/font` 加载，构建时自动内联，不额外分发字体文件。

---

## 七、自主开发范围声明

以下为本项目**自主实现**的部分，未抄袭任何第三方代码：

| 模块 | 说明 |
| --- | --- |
| 三层抽象设计 | Tool / Skill / Agent 的注册表与关系定义 |
| 注册表实现 | `core/registry.py` 的数据结构与加载逻辑 |
| ReAct 执行器 | `agents/base.py` 的循环、action 解析、工具注入 |
| 智能体定义 | 8 个智能体（1 主管 + 4 评审专家 + 1 市场数据研究员 + 1 信息研究员 + 1 撰写人）的角色设定与 Prompt |
| 技能文件 | 9 份技能说明书（`app/skills/*.md`）的内容 |
| 估值算法实现 | DCF 两阶段模型、敏感性矩阵、相对估值的具体代码 |
| 编排器 | `orchestrator.py`（建模形态）与 `chat_supervisor.py`（对话形态）的节点定义与调度 |
| 事件协议 | `events.py` 的 15 种事件类型设计 |
| 检查点机制 | 断点续跑的状态保存与恢复 |
| 前端界面 | 智能体工作台、结果面板、设置面板的全部组件 |
| MCP 集成 | 把现有工具暴露为 MCP 工具的适配层 |
| 桌面端壳层 | `electron/main.cjs` 的启动序列 / 动态端口 / 加载窗口 / 失败回显，`preload.cjs` 的桥协议，`scripts/prepare-frontend.cjs` 的 standalone 物化，`scripts/build.ps1` / `prepare-python.ps1` 构建链 |
| 路径解析 | `backend/app/paths.py` 的跨平台数据目录定位 |

**第三方库的使用方式**均为「调用其公开 API」，未修改其源码，未复制其内部实现。

---

## 八、许可证全文索引

| 许可证 | 全文链接 |
| --- | --- |
| MIT | https://opensource.org/licenses/MIT |
| Apache-2.0 | https://www.apache.org/licenses/LICENSE-2.0 |
| BSD-3-Clause | https://opensource.org/licenses/BSD-3-Clause |
| ISC | https://opensource.org/licenses/ISC |
| AGPL-3.0 | https://www.gnu.org/licenses/agpl-3.0.html |
| SIL OFL 1.1 | https://scripts.sil.org/OFL |

---

## 九、版本锁定

精确版本见：

- 后端：`backend/uv.lock`
- 前端：`frontend/pnpm-lock.yaml`

复现环境时使用：

```bash
cd backend && uv sync --frozen
cd frontend && pnpm install --frozen-lockfile
```

---

*最后更新：2026-10-07（复核：工具 23 · 技能 9 · 智能体 8 · 提供商 7；补桌面端 Electron / electron-builder 依赖与嵌入式 Python 说明）*
