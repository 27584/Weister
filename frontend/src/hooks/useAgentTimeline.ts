"use client";

import { useCallback, useRef, useState } from "react";
import type { AgentEvent } from "@/lib/types";

export type AgentPhase = "idle" | "thinking" | "tool" | "done" | "error";

export interface AgentItem {
  id: number;
  kind: "thinking" | "token" | "tool_call" | "tool_result" | "log" | "error" | "node";
  text: string;
  done?: boolean;
  /** 工具调用的完整入参 / 返回结果（JSON 文本），供折叠面板展开查看 */
  detail?: string;
  /** 仅 tool_result：调用是否成功 */
  ok?: boolean;
  /** 展示语气：reason = 主管的决策依据，需要比普通日志醒目 */
  tone?: "reason";
  /** 详情被截断时为 true —— 提示用户展开看到的不是全量 */
  detailTruncated?: boolean;
}

export interface AgentState {
  key: string;
  name: string;
  role: string;
  phase: AgentPhase;
  step: number;
  tools: string[];
  currentTool: string | null;
  items: AgentItem[];
  startedAt: number | null;
  elapsedMs: number;
  loadedSkills: string[];
}

export type AgentsByKey = Record<string, AgentState>;
/** run_id → { agentKey → AgentState }。按对话隔离协作面板状态。 */
export type TimelineStore = Record<string, AgentsByKey>;

export const SYSTEM_KEY = "__system__";

const AGENT_META: Record<string, { name: string; role: string }> = {
  [SYSTEM_KEY]: { name: "调度中心", role: "文档解析与节点编排" },
  extractor: { name: "数据提取员", role: "字段抽取与指标计算" },
  coordinator: { name: "投研主管", role: "任务分解与调度" },
  financial_analyst: { name: "财务分析师", role: "财报解析与指标核算" },
  valuation_expert: { name: "估值专家", role: "DCF 与相对估值建模" },
  risk_reviewer: { name: "风险审查员", role: "识别风险与验证条件" },
  devils_advocate: { name: "反方质疑者", role: "挑战主结论" },
  report_writer: { name: "报告撰写人", role: "整合专家意见成文" },
  market_analyst: { name: "市场数据研究员", role: "行情与历史财务核查" },
  research_assistant: { name: "信息研究员", role: "联网调研与信息核查" },
};

export function agentMeta(key: string): { name: string; role: string } {
  return AGENT_META[key] ?? { name: key, role: "" };
}

/** 本次运行未参与的 agent 的占位态（工作台里始终展示完整团队） */
export function idleAgent(key: string): AgentState {
  return { ...emptyAgent(key), phase: "idle" };
}

function emptyAgent(key: string): AgentState {
  const meta = agentMeta(key);
  return {
    key,
    name: meta.name,
    role: meta.role,
    phase: key === SYSTEM_KEY ? "thinking" : "idle",
    step: 0,
    tools: [],
    currentTool: null,
    items: [],
    startedAt: null,
    elapsedMs: 0,
    loadedSkills: [],
  };
}

/** 详情区最多保留的字符数。工具结果可能是整份财报抽取结果，
    全量塞进 DOM 会拖慢渲染，超出的部分截断并标注。 */
const DETAIL_MAX_CHARS = 6000;

/** 把工具入参 / 返回值格式化成可阅读文本。
    对象走缩进 JSON，字符串原样输出，空值给出明确占位。 */
export function formatDetail(value: unknown): { text: string; truncated: boolean } {
  if (value === undefined || value === null) return { text: "", truncated: false };
  let text: string;
  if (typeof value === "string") {
    text = value;
  } else {
    try {
      text = JSON.stringify(value, null, 2);
    } catch {
      text = String(value);
    }
  }
  text = text.trim();
  if (!text) return { text: "", truncated: false };
  if (text.length <= DETAIL_MAX_CHARS) return { text, truncated: false };
  return {
    text: text.slice(0, DETAIL_MAX_CHARS) + "\n…（内容过长已截断）",
    truncated: true,
  };
}

function appendItem(
  list: AgentItem[],
  kind: AgentItem["kind"],
  text: string,
  seq: number,
  extra?: Partial<AgentItem>,
): AgentItem[] {
  const last = list[list.length - 1];
  if (
    last &&
    last.kind === kind &&
    (kind === "token" || kind === "thinking" || kind === "log" || kind === "node")
  ) {
    const next = list.slice(0, -1);
    // log / node 是离散的行，合并时要补换行；token / thinking 是连续流，直接拼
    const sep = kind === "log" || kind === "node" ? "\n" : "";
    next.push({ ...last, text: last.text + sep + text, ...extra });
    return next;
  }
  return [...list, { id: seq, kind, text, ...extra }];
}

function closeThinkingItems(list: AgentItem[]): AgentItem[] {
  let changed = false;
  const next = list.map((it) => {
    if (it.kind === "thinking" && !it.done) {
      changed = true;
      return { ...it, done: true };
    }
    return it;
  });
  return changed ? next : list;
}

/** 把一批事件应用到某个 agent 的 state（纯函数，便于按 run 分别累积） */
function applyEvents(
  current: AgentState,
  events: AgentEvent[],
  seqRef: { current: number },
): AgentState {
  const updated: AgentState = { ...current, items: current.items.slice() };

  for (const ev of events) {
    const payload = ev.payload ?? {};
    const msg = ev.message ?? "";

    if (ev.type === "agent_start") {
      updated.phase = "thinking";
      updated.startedAt = updated.startedAt ?? Date.now();
      if (typeof payload.name === "string") updated.name = payload.name;
      if (typeof payload.role === "string") updated.role = payload.role;
    }

    if (ev.type === "node_start") {
      updated.phase = "thinking";
      updated.startedAt = updated.startedAt ?? Date.now();
      if (msg) {
        seqRef.current += 1;
        updated.items = appendItem(updated.items, "node", `▶ ${msg}`, seqRef.current);
      }
    }

    if (ev.type === "node_end") {
      updated.phase = "done";
      if (msg) {
        seqRef.current += 1;
        updated.items = appendItem(updated.items, "node", `✓ ${msg}`, seqRef.current);
      }
    }

    if (ev.type === "thinking" && msg) {
      seqRef.current += 1;
      updated.items = appendItem(updated.items, "thinking", msg, seqRef.current);
      if (updated.phase !== "tool") updated.phase = "thinking";
    }

    if (ev.type === "token" && msg) {
      seqRef.current += 1;
      updated.items = appendItem(updated.items, "token", msg, seqRef.current);
    }

    if (ev.type === "log" && msg) {
      if (typeof payload.step === "number") updated.step = payload.step;
      seqRef.current += 1;
      // 主管的决策依据：单独标记，让它在协作面板里比普通日志醒目
      const isReason = typeof payload.reason === "string" && payload.reason !== "";
      updated.items = appendItem(
        updated.items,
        "log",
        msg,
        seqRef.current,
        isReason ? { tone: "reason" } : undefined,
      );
    }

    if (ev.type === "tool_call") {
      const tool = msg.replace("tool: ", "");
      updated.currentTool = tool;
      updated.phase = "tool";
      updated.items = closeThinkingItems(updated.items);
      seqRef.current += 1;
      const callDetail = formatDetail(payload.input);
      updated.items = appendItem(
        updated.items,
        "tool_call",
        tool,
        seqRef.current,
        {
          detail: callDetail.text,
          detailTruncated: callDetail.truncated,
          done: true,
        },
      );
      if (tool && !updated.tools.includes(tool)) {
        updated.tools = [...updated.tools, tool];
      }
    }

    if (ev.type === "tool_result") {
      updated.currentTool = null;
      updated.phase = "thinking";
      const ok = payload.ok !== false;
      const tool = typeof payload.tool === "string" ? payload.tool : "";
      seqRef.current += 1;
      // 失败时 result 恒为 None，真正的原因在 error 字段里
      const resultDetail = formatDetail(ok ? payload.result : payload.error);
      updated.items = appendItem(
        updated.items,
        "tool_result",
        ok ? `${tool} 完成` : `${tool} 失败`,
        seqRef.current,
        {
          ok,
          detail: resultDetail.text,
          detailTruncated: resultDetail.truncated,
          done: true,
        },
      );
      if (
        tool === "load_skill" &&
        ok &&
        payload.result &&
        typeof payload.result === "object"
      ) {
        const skill = (payload.result as Record<string, unknown>).name;
        if (typeof skill === "string" && !updated.loadedSkills.includes(skill)) {
          updated.loadedSkills = [...updated.loadedSkills, skill];
        }
      }
    }

    if (ev.type === "agent_end") {
      updated.phase = "done";
      updated.currentTool = null;
      updated.items = closeThinkingItems(updated.items);
      if (typeof payload.elapsed_ms === "number") {
        updated.elapsedMs = payload.elapsed_ms;
      }
      if (Array.isArray(payload.loaded_skills)) {
        updated.loadedSkills = payload.loaded_skills as string[];
      }
    }

    if (ev.type === "error") {
      updated.phase = "error";
      updated.items = closeThinkingItems(updated.items);
      seqRef.current += 1;
      updated.items = appendItem(updated.items, "error", msg, seqRef.current);
    }

    if (ev.type === "run_start" && msg) {
      seqRef.current += 1;
      updated.items = appendItem(updated.items, "node", msg, seqRef.current);
    }

    if (ev.type === "run_end") {
      updated.phase = "done";
      updated.items = closeThinkingItems(updated.items);
    }
  }

  return updated;
}

/** 缺少 run_id 的事件归入此分桶 */
const FALLBACK_RUN = "__default__";

export function useAgentTimeline() {
  // 按 run_id 分桶保存，切换对话只换 activeRunId，数据不丢
  const [store, setStore] = useState<TimelineStore>({});
  const bufferRef = useRef<Record<string, Record<string, AgentEvent[]>>>({});
  const frameRef = useRef<number | null>(null);
  const seqRef = useRef(0);
  /** 需要在下一次 flush 后把残留的「进行中」相位收敛为「已完成」的 run */
  const finalizeRef = useRef<Set<string>>(new Set());

  const flush = useCallback(() => {
    frameRef.current = null;
    const pending = bufferRef.current;
    bufferRef.current = {};
    const toFinalize = finalizeRef.current;
    finalizeRef.current = new Set();

    const runIds = new Set([...Object.keys(pending), ...toFinalize]);
    if (runIds.size === 0) return;

    setStore((prevStore) => {
      const nextStore = { ...prevStore };
      for (const runId of runIds) {
        const agentPending = pending[runId] ?? {};
        const prevAgents = nextStore[runId] ?? {};
        const nextAgents: AgentsByKey = { ...prevAgents };
        for (const key of Object.keys(agentPending)) {
          const current = nextAgents[key] ?? emptyAgent(key);
          nextAgents[key] = applyEvents(current, agentPending[key], seqRef);
        }
        // 部分历史落盘缺少 run_end 事件，重放后相位会停留在「思考中 / 调用工具」。
        // 载入已结束的对话时统一收敛为「已完成」。
        if (toFinalize.has(runId)) {
          for (const [k, a] of Object.entries(nextAgents)) {
            if (a.phase === "thinking" || a.phase === "tool") {
              nextAgents[k] = { ...a, phase: "done", currentTool: null };
            }
          }
        }
        nextStore[runId] = nextAgents;
      }
      return nextStore;
    });
  }, []);

  const schedule = useCallback(() => {
    if (frameRef.current !== null) return;
    frameRef.current = requestAnimationFrame(flush);
  }, [flush]);

  const push = useCallback(
    (event: AgentEvent) => {
      const runId = event.run_id || FALLBACK_RUN;
      let key =
        typeof event.payload?.agent === "string" ? event.payload.agent : null;

      if (!key) {
        const systemTypes: string[] = [
          "node_start",
          "node_end",
          "run_start",
          "run_end",
          "log",
          "tool_call",
          "tool_result",
          "error",
        ];
        if (systemTypes.includes(event.type)) {
          key = SYSTEM_KEY;
        } else {
          return;
        }
      }

      const buf = bufferRef.current;
      if (!buf[runId]) buf[runId] = {};
      if (!buf[runId][key]) buf[runId][key] = [];
      buf[runId][key].push(event);
      schedule();
    },
    [schedule],
  );

  /** 清空：给定 runId 只清该对话；不传则清全部 */
  const reset = useCallback((runId?: string) => {
    if (frameRef.current !== null) {
      cancelAnimationFrame(frameRef.current);
      frameRef.current = null;
    }
    bufferRef.current = {};
    if (runId) {
      setStore((prev) => {
        if (!(runId in prev)) return prev;
        const next = { ...prev };
        delete next[runId];
        return next;
      });
    } else {
      seqRef.current = 0;
      setStore({});
    }
  }, []);

  /** 载入「已结束」的历史对话后调用：把残留的 thinking/tool 相位收敛为 done */
  const finalize = useCallback(
    (runId: string) => {
      finalizeRef.current.add(runId);
      schedule();
    },
    [schedule],
  );

  return { store, push, reset, finalize };
}
