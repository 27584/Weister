# Changelog

## Unreleased — 2026-10-07

### 桌面客户端：Electron 壳与免安装打包（完整落地）
- **打包方案切换**：后端从 PyInstaller 改为 **Python 嵌入式发行版**（`scripts/prepare-python.ps1` 下载 python-3.12.9-embed-amd64 到 `backend/python/`，重写 `python312._pth` 加入 `..` 使 `python -m app` 可解析）。嵌入式包的 `._pth` 隔离模式会忽略 `PYTHON*` 环境变量，故后端进程一律以 `-s` 命令行旗标启动（`sys.flags.no_user_site=1`），屏蔽构建机用户级 site-packages——此前 pip 假安装导致分发机 `ModuleNotFoundError: uvicorn`、后端秒退、客户端 60 秒超时报 backend not responding
- **Electron 主进程**（`electron/main.cjs`）：拉起后端（`-s -m app`）与前端（`ELECTRON_RUN_AS_NODE=1` 跑 Next.js standalone `server.js`，不依赖系统 Node）；**动态端口**——后端 8000 / 前端 3000 被占用时 +1 递增最多试 20 个，`CORS_ORIGINS` / `DATA_DIR` / `WEISTER_API_BASE` 按实际端口注入，消除固定端口撞车导致的 Failed to fetch
- **启动加载窗口**：460×340 无边框黑白加载页（`loading.html`），进度分 8→20→35→65→80→100 六段（分配端口 / 启动后端 / 等待后端就绪 / 启动界面 / 等待界面就绪 / 加载应用）；后端启动失败时回显子进程输出末 6 行（环形缓冲 40 行），不再只给一句 backend not responding
- **白屏修复**：`electron/scripts/prepare-frontend.cjs` 打包前置——把 `.next/static` 与 `public` 同步进 standalone（与 BUILD_ID 同源，防 chunk 404）、探测并物化 pnpm 符号链接（junction 指向构建机绝对路径，离机即断）、把 standalone 铺到 `electron/build/frontend`（electron-builder 的 extraResources 会 glob 跳过 `.` 开头目录，`.next` 必须换无隐藏段的路径）
- **数据目录**：新增 `backend/app/paths.py` 作为落盘路径唯一来源——`DATA_DIR` 环境变量优先，默认 `%APPDATA%\Weister\data`（Windows/macOS/Linux 各自解析），刻意不回退 `./data`；Electron 与后端共用 `app.setPath("userData", .../Weister)` 同一路径。`.env` 读取改为绝对路径，`python -m app` 与 `uvicorn --reload` 不会读到不同配置
- **窗口与桥**：主窗口 1400×900（最小 1024×700）`frame:false`，页面顶栏即标题栏（拖动区 + 最小化/最大化·还原/关闭三按钮，浏览器访问自动隐藏）；`preload.cjs` 只注入 `window.WEISTER` 桥（动态 API 基址 + 窗口控制 + 最大化状态订阅）
- **应用图标**：深墨底白 W 图标（`electron/build/icon.ico`），portable 输出自带
- **构建脚本**：新增 `scripts/build.ps1` 一键三步（prepare-python → 前端 standalone → electron-builder portable，`electron/release/*.exe`）；支持 `-SkipBackend` / `-SkipFrontend` / `-SkipElectron`
- 其他修复：React BUILD_ID 不匹配致前端无法 hydrate、标题栏注入滚动条、端口未传递卡加载页

### 文档
- 全套文档补齐桌面端章节：README（目录结构 / 桌面构建 / 技术栈）、USAGE（桌面客户端使用与数据目录）、DEVELOPMENT（桌面端开发与构建）、ARCHITECTURE（进程拓扑与路径解析）、DESIGN（目录结构 / 附录 A 端点 27 条）、THIRD_PARTY（Electron / electron-builder 依赖行）

## Unreleased — 2026-09-22

### 文档与源码逐条核对（以源码为准）
- 修正 `docs/architecture.html` 顶部统计：注册工具 10 → **23** · Markdown 技能 3 → **9** · 智能体 6 → **8** · SSE 事件类型 13 → **15**；REST 端点 18 → **23**；提供商 6 → **7**
- 重写 `architecture.html` 与 `DESIGN.md` 附录 B 的「智能体与工具权限矩阵」：补齐 `market_analyst` / `research_assistant` 两行，按 `specialists.py` 的实际白名单列出全部工具（此前 `devils_advocate` / `report_writer` 被误标为「无工具」）
- 修正与代码相反的终止条件描述：`architecture.html` / `DESIGN.md` 此前写「刻意不设 max_steps」，实际存在 `DEFAULT_MAX_STEPS = 24` 硬上限（`core/registry.py` + `agents/base.py`）
- 结果面板标签数 5 → **4**（`PipelineResult.tsx` 实际为 研究报告 / 估值建模 / 结构化数据 / 专家意见，无「指标图表」「追溯证据」）
- 补齐 `architecture.html` 工具清单（11 → 23 行）与事件表（13 → 15 行，补 `ask_user` / `title`）；MCP 暴露数 7 → **20**
- 修正过期数字：ruff 告警 25 → **5**、待格式化文件 25 → **2**、后端测试 22 → **50 项**、`tsc` 642 → **658 文件**
- 修正失效实现描述：`require_configured()` 已不在流路径调用（改由 `app/api/analyze.py` 直接判定凭据） · CORS `allow_headers` 5 → **9 个** · 凭据外的搜索请求头 `X-Search-*` 补入文档
- 修正前端描述：`AGENT_ORDER` 位于 `lib/runMeta.ts`（非 `page.tsx`）且不含 `extractor` · `AgentStage` 列数规则为 `<=1 ? 1 : 2` · 搜索源降级顺序为 `tavily → bocha → searxng → 百度 → 必应中国` · 设置徽章文案为「已配置」
- `THIRD_PARTY.md` 补记 Ollama 本地提供商；标注 `echarts` / `echarts-for-react` / `react-resizable-panels` 在源码中暂无引用；联网检索源顺序对齐 `tools/web.py`
- `README.md` 补 `profiles.json` 的 `search` 字段示例；按 `registry` 实际 tags 重列 23 个工具与 8 个智能体的工具范围；澄清「凭据走请求头」不等于「业务参数不进表单」
- `docs/ARCHITECTURE.md` 修正最后一处滞后描述：技能正文由 `_render_skills()` 内联进 system prompt，而非运行时调 `load_skill`

### 文档全量复核
- 对齐当前代码：23 工具 · 9 技能 · 8 智能体 · 15 种事件类型 · 7 个提供商（新增 Ollama 本地）
- 修正失效描述：`api.py` → `app/api/` 包 · `ResultPanel` → `PipelineResultView` · 文本 action 协议 → 原生 function calling · supervisor 固定 6 轮 → 进展检测（`MAX_IDLE_ROUNDS = 3` / `ABSOLUTE_ROUND_LIMIT = 50`） · 8000 字输出熔断 → 不传 `max_tokens` + `max_steps` 防御 · 前端 6 页签布局 → 对话 / 建模双形态
- THIRD_PARTY 补齐 tiktoken、可选依赖（python-docx / openpyxl / RapidOCR / python-pptx）与 pytest 系；数据来源补记腾讯 / 东方财富 / 新浪行情接口、联网检索源与真实年报样例（宁德时代 2024 年报）

### 桌面端：自定义标题栏与页面顶栏合并
- 此前 `electron/preload.cjs` 在 `DOMContentLoaded` 注入一条 `position:fixed; top:0; height:34px` 的 `#weister-titlebar`，并给根节点补 `padding-top:34px` —— 视觉上是在页面顶栏（含「设置」按钮那条）**上方又叠了一条栏**。现在改为「页面顶栏自身就是唯一标题栏」：
  - `preload.cjs` 删除注入的 DOM / CSS / `applyRootOffset()` / `MutationObserver`，只保留 `window.WEISTER` 桥，并新增 `onMaximizeState(cb)`（返回取消订阅函数）
  - `frontend/src/lib/desktop.ts`（新增）：`WeisterBridge` 类型 + `getDesktopBridge()` + `useDesktopBridge()`（`useSyncExternalStore`，服务端快照返回 `null`，不与 Web 版产生 hydration 错位）
  - `frontend/src/components/WindowControls.tsx`（新增）：最小化 / 最大化·还原 / 关闭三按钮，嵌在顶栏右端；桥不存在时返回 `null`
  - `frontend/src/app/globals.css`：新增 `.app-drag` / `.app-no-drag`，并用 `.app-drag button, input, select, textarea, a` 兜底，让顶栏内控件自动脱离拖动区
  - `frontend/src/app/page.tsx`：`<header>` 在桌面端加 `app-drag`，状态徽章之后插入 `<WindowControls />`；`electron/main.mjs` 保持 `frame:false`
  - `electron/loading.html` 保留自带标题栏（启动阶段是独立无边框小窗，与主窗口无关）
- 实测（Electron 33.4.11 + standalone 构建）：`headerCount=1`、`headerTop=0`、注入栏不存在、根节点 `padding-top:0`、无纵向滚动条、顶栏 10 个按钮全部 `no-drag`、点最大化后按钮切换为「还原」

### 工程 / 仓库卫生
- `dev.ps1` / `check.ps1` 统一为 UTF-8 with BOM——Windows PowerShell 5.1 会按 ANSI(GBK) 解码无 BOM 的 `.ps1`，中文串错位后会抛出假性的 `MissingEndCurlyBrace` 语法错误
- 清理构建缓存与临时产物（`.next`、`tsconfig.tsbuildinfo`、`__pycache__`、ruff/pytest 缓存），移除无引用的临时调试脚本 `backend/_run_py.js`

## 0.3.1 — 2026-09-17

### 新增工具
- `financial_ratio_suite`：盈利/偿债/营运/现金流质量全套比率
- `yoy_compare`：两期同比与变动
- `peer_comparison`：多公司对比表（JSON + Markdown）
- `locate_evidence`：原文定位与页码溯源

### 新增技能
- `risk_analysis`：风险清单 + 反向验证条件
- `peer_benchmark`：同业对标
- `earnings_quality`：盈利质量核查

### 智能体
- 财务分析师 / 风险审查员 / 反方 / 估值专家已挂载上述工具与技能

## 0.3.0 — 2026-09-17

### 架构
- `api.py` 拆分为 `app/api/` 包（deps / sse / store / helpers / analyze / chat / meta）
- 主管决策解析抽出为 `app/decision.py`（parse + 字段规范化）
- 前端：`lib/runMeta.ts`、`settings/*`、`chat/TokenRing` 模块化

### 模型兼容
- 兼容非标准决策字段：`next_action` / `expert` / `target` / 顶层 `question`/`options`
- 兼容 `request_user_input` 等动作别名
- 解析失败时自动纠偏重试一次
- 主管提示词强化：禁止抢答「无法联网」，非 A 股先检索

### 能力
- 分析型专家统一具备 `web_search` / `fetch_url`
- 行情工具对非 A 股给出明确能力边界提示
- README 能力清单对齐：19 工具 · 5 技能 · 8 智能体

### 工程
- ruff check/format 全绿；pytest 44 项
- 仓库卫生：运行时数据与 profiles 出索引；收紧 .gitignore
- 事件协议前后端一致性测试

### 安全
- `profiles.json` / `runs/` 不再纳入版本控制
- `.env.example` 补充搜索源与密钥说明

## 0.2.0
- 聊天 supervisor、交互工具、市场与联网工具
- 检查点与 SSE 事件流

## 0.1.0
- 初始：LangGraph 六节点流水线 + 估值工具链
