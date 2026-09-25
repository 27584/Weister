"use client";

import { useCallback, useRef, useState } from "react";
import { analyze, analyzeResume } from "@/lib/api";
import type { LLMConfig } from "@/lib/api";
import type { AgentEvent, NodeState } from "@/lib/types";
import { reduceNodeStates } from "@/components/PipelineProgress";
import { extractReportMd } from "@/lib/md";

export interface AnalyzeResultPayload {
  report_md?: string;
  extracted?: unknown;
  metrics?: unknown;
  valuation_summary?: unknown;
  dcf?: unknown;
  relative?: unknown;
  sensitivity?: unknown;
  citations?: unknown;
  trace?: unknown;
  run_id?: string;
  analyses?: unknown;
  expert_opinions?: unknown;
}

export interface AnalyzeResult {
  reply: string;
  nodes: Partial<Record<string, NodeState>>;
  running: boolean;
  error: string | null;
  result: AnalyzeResultPayload | null;
  runId: string | null;
  run: (opts: {
    file?: File;
    question?: string;
    demo?: boolean;
    llm: LLMConfig;
    onEvent?: (ev: AgentEvent) => void;
  }) => Promise<void>;
  resume: (runId: string, llm: LLMConfig) => Promise<void>;
  reset: () => void;
}

/** 一键建模（/api/analyze）SSE 运行状态 */
export function useAnalyzeRun(): AnalyzeResult {
  const [nodes, setNodes] = useState<Partial<Record<string, NodeState>>>({});
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<AnalyzeResultPayload | null>(null);
  const [reply, setReply] = useState("");
  const [runId, setRunId] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const reset = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setNodes({});
    setRunning(false);
    setError(null);
    setResult(null);
    setReply("");
    setRunId(null);
  }, []);

  const handleEvent = useCallback((ev: AgentEvent) => {
    setNodes((prev) => reduceNodeStates(prev, ev));
    if (ev.run_id) setRunId(ev.run_id);
    if (ev.type === "result" && ev.payload) {
      const p = ev.payload as AnalyzeResultPayload;
      setResult(p);
      const md = extractReportMd(p).trim();
      setReply(md || "分析完成（无报告正文）");
    }
    if (ev.type === "error") {
      setError(ev.message || "执行失败");
    }
  }, []);

  const run = useCallback(
    async ({
      file,
      question,
      demo,
      llm,
      onEvent,
    }: {
      file?: File;
      question?: string;
      demo?: boolean;
      llm: LLMConfig;
      onEvent?: (ev: AgentEvent) => void;
    }) => {
      abortRef.current?.abort();
      const ac = new AbortController();
      abortRef.current = ac;
      setNodes({});
      setError(null);
      setResult(null);
      setReply("");
      setRunId(null);
      setRunning(true);
      try {
        await analyze({
          file,
          question,
          demo,
          llm,
          signal: ac.signal,
          onEvent: (ev) => {
            handleEvent(ev);
            onEvent?.(ev);
          },
        });
      } catch (e) {
        if (!ac.signal.aborted) {
          setError(e instanceof Error ? e.message : String(e));
        }
      } finally {
        setRunning(false);
      }
    },
    [handleEvent],
  );

  const resume = useCallback(
    async (rid: string, llm: LLMConfig) => {
      abortRef.current?.abort();
      const ac = new AbortController();
      abortRef.current = ac;
      setError(null);
      setResult(null);
      setReply("");
      setRunning(true);
      try {
        await analyzeResume(rid, llm, ac.signal, handleEvent);
      } catch (e) {
        if (!ac.signal.aborted) {
          setError(e instanceof Error ? e.message : String(e));
        }
      } finally {
        setRunning(false);
      }
    },
    [handleEvent],
  );

  return { reply, nodes, running, error, result, runId, run, resume, reset };
}
