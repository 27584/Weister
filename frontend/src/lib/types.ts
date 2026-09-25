export type EventType =
  | "run_start"
  | "node_start"
  | "node_end"
  | "agent_start"
  | "agent_end"
  | "tool_call"
  | "tool_result"
  | "thinking"
  | "token"
  | "log"
  | "result"
  | "error"
  | "run_end"
  /** 智能体向用户提问并阻塞等待作答（由 /api/chat/answer 回传） */
  | "ask_user"
  /** 智能体为对话命名，前端同步侧边栏标题 */
  | "title";

export type NodeStatus = "pending" | "running" | "success" | "failed";

export interface AgentEvent {
  type: EventType;
  run_id: string;
  seq: number;
  node: string | null;
  status: NodeStatus | null;
  message: string | null;
  payload: Record<string, unknown>;
}

export interface Citation {
  page: number;
  excerpt: string;
}

export interface TraceItem {
  node: string;
  elapsed_ms: number;
  [key: string]: unknown;
}

export interface DcfRow {
  year: number;
  growth: number;
  revenue: number;
  fcf: number;
  pv: number;
}

export interface DcfResult {
  rows?: DcfRow[];
  pv_explicit?: number;
  terminal_value?: number;
  pv_terminal?: number;
  enterprise_value?: number;
  equity_value?: number;
  net_debt?: number;
}

export interface RelativeResult {
  pe?: { multiple: number[]; equity_value: number[] };
  ps?: { multiple: number[]; equity_value: number[] };
}

export interface SensitivityResult {
  wacc: number[];
  growth: number[];
  /** WACC ≤ 永续增长率时该格为 null（终值发散、无法计算），渲染为「—」 */
  grid: (number | null)[][];
}

export interface ValuationSummary {
  low: number;
  mid: number;
  high: number;
  methods: Record<string, number | number[]>;
}

export interface Assumptions {
  wacc?: number;
  terminal_growth?: number;
  forecast_years?: number;
  growth_rates?: number[];
  fcf_margin?: number;
  rationale?: Record<string, string>;
}

export interface FinalResult {
  extracted: {
    company?: string | null;
    period?: string | null;
    currency?: string | null;
    unit?: string | null;
    fields?: Record<string, number | null>;
    evidence?: { field: string; quote: string; page: number }[];
  };
  metrics: Record<string, number | boolean>;
  assumptions?: Assumptions;
  dcf?: DcfResult;
  relative?: RelativeResult;
  sensitivity?: SensitivityResult;
  valuation_summary?: ValuationSummary;
  expert_opinions?: ExpertOpinion[];
  report_md: string;
  citations: Citation[];
  trace: TraceItem[];
}

export interface ProviderInfo {
  key: string;
  label: string;
  base_url: string;
  models: string[];
  doc: string;
}

export interface ProviderCatalog {
  default: string;
  providers: ProviderInfo[];
}

export interface LLMProfile {
  id: string;
  name: string;
  provider: string;
  model: string;
  fallbackModels: string[];
  /** 设置中「检测」得到的可用模型列表，对话框下拉直接复用 */
  models?: string[];
  apiKey: string;
  baseUrl: string;
}

/** 联网搜索源配置（设置面板填写，随请求头发给后端） */
export interface SearchConfig {
  /** Tavily API Key，https://tavily.com */
  tavilyApiKey: string;
  /** 博查 Bocha API Key，https://open.bochaai.com */
  bochaApiKey: string;
  /** 自建 SearXNG 地址，如 http://127.0.0.1:8080 */
  searxngUrl: string;
}

export const EMPTY_SEARCH: SearchConfig = {
  tavilyApiKey: "",
  bochaApiKey: "",
  searxngUrl: "",
};

export interface LLMStore {
  profiles: LLMProfile[];
  activeId: string;
  search?: SearchConfig;
}

export interface ExpertOpinion {
  agent: string;
  name: string;
  role: string;
  opinion: string;
  elapsed_ms: number;
  steps?: number;
  tools_used?: string[];
  /** 内联进 system prompt 的技能名（不是运行时按需加载的） */
  loaded_skills?: string[];
  /** 是否因触及 max_steps 被强制收尾 —— 为真时结论可能不完整 */
  truncated?: boolean;
  trace?: { step: number; tool: string; ok: boolean; summary: string }[];
}

export interface AgentRun {
  name: string;
  role: string;
  output: string;
  steps: number;
  tools_used: string[];
  elapsed_ms: number;
}

export interface AgentSpec {
  key: string;
  name: string;
  role: string;
  tools: string[];
  skills: string[];
  /** ReAct 循环的防御性步数上限，与后端 AgentSpec.max_steps 对齐 */
  max_steps: number;
}

export interface SkillSpec {
  name: string;
  description: string;
  tools: string[];
}

export interface ToolSpec {
  name: string;
  description: string;
  input_schema: Record<string, string>;
  tags: string[];
}

export interface RegistryCatalog {
  tools: ToolSpec[];
  skills: SkillSpec[];
  agents: AgentSpec[];
}

export const NODE_LABELS: Record<string, string> = {
  ingest: "文档解析",
  extract: "数据提取",
  coordinator: "主管调度",
  analysis: "分析组",
  review: "评审组",
  report: "报告撰写",
};

// 顺序必须与后端 orchestrator.py 的 NODES 常量保持一致，
// 否则流水线面板会漏节点、进度分母也会算错。
export const NODE_ORDER = [
  "ingest",
  "extract",
  "coordinator",
  "analysis",
  "review",
  "report",
] as const;
export type NodeName = (typeof NODE_ORDER)[number];

export interface NodeState {
  status: NodeStatus;
  message?: string;
  payload?: Record<string, unknown>;
  startedAt?: number;
  endedAt?: number;
}

/* ---------------- 人机交互 ---------------- */

export interface AskOption {
  label: string;
  description: string;
}

export interface AskQuestion {
  question: string;
  /** 不超过 12 字的短标签 */
  header: string;
  multiSelect: boolean;
  options: AskOption[];
}

/** 后端 ask_user 事件的载荷：一次询问可包含多道问题，前端逐道展示 */
export interface PendingAsk {
  qid: string;
  title: string;
  total: number;
  questions: AskQuestion[];
}

/** 单道问题的作答结果，按顺序与 questions 一一对应 */
export interface AskAnswer {
  selected: string[];
  /** 用户选择「其他（自行输入）」时填写的内容 */
  other: string;
}
