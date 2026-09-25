import type { AgentEvent } from "@/lib/types";

/** 与 useAgentTimeline 的 SYSTEM_KEY 保持一致 */
const SYSTEM_KEY = "__system__";

/** 生成一个客户端 run_id（与后端 uuid4().hex[:12] 同风格），
    让「新对话」能立刻出现在列表里，不必等首条消息发完。 */
export function genRunId(): string {
  const raw =
    globalThis.crypto?.randomUUID?.() ??
    `${Date.now().toString(36)}${Math.random().toString(36).slice(2)}`;
  return raw.replace(/[^a-z0-9]/gi, "").slice(0, 12);
}

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

/** 从事件流里还原「最后一轮」的元信息：思考过程 / 已调度专家 / 轮数 / 是否触顶 */
export function deriveRunMeta(events: AgentEvent[]) {
  let start = 0;
  for (let i = 0; i < events.length; i++) {
    if (events[i].type === "run_start") start = i;
  }
  const slice = events.slice(start);

  const thinking = slice
    .filter((e) => e.type === "thinking" && e.message)
    .map((e) => e.message as string)
    .join("");

  const specialistsCalled: string[] = [];
  for (const e of slice) {
    const agent = e.payload?.agent;
    if (
      e.type === "agent_start" &&
      typeof agent === "string" &&
      agent !== "coordinator" &&
      !specialistsCalled.includes(agent)
    ) {
      specialistsCalled.push(agent);
    }
  }

  // 轮数/是否收尾优先读 result 事件（结构化），不回退到解析日志文本
  let iterations = 0;
  let truncated = false;
  for (const e of slice) {
    if (e.type === "result" && typeof e.payload === "object" && e.payload) {
      const p = e.payload as { iterations?: number; truncated?: boolean };
      if (typeof p.iterations === "number") iterations = p.iterations;
      if (typeof p.truncated === "boolean") truncated = p.truncated;
    }
  }
  // 旧 conversation 可能没有 result 事件：用日志作为后备判断 truncated，但不再猜 iterations
  if (!truncated) {
    truncated = slice.some(
      (e) => e.type === "log" && /无实质进展|提前收尾|已达调度上限/.test(e.message || ""),
    );
  }

  return { thinking, specialistsCalled, iterations, truncated };
}
