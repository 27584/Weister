"use client";

import { Check, Circle, Loader2, X } from "lucide-react";
import { NODE_LABELS, NODE_ORDER, type NodeState, type NodeStatus } from "@/lib/types";

const STATUS_UI: Record<
  NodeStatus,
  { icon: typeof Circle; label: string; cls: string; bar: string }
> = {
  pending: {
    icon: Circle,
    label: "等待",
    cls: "text-base-content/40",
    bar: "bg-base-content/15",
  },
  running: {
    icon: Loader2,
    label: "进行中",
    cls: "text-primary",
    bar: "bg-primary",
  },
  success: {
    icon: Check,
    label: "完成",
    cls: "text-success",
    bar: "bg-success",
  },
  failed: {
    icon: X,
    label: "失败",
    cls: "text-error",
    bar: "bg-error",
  },
};

export interface PipelineProgressProps {
  nodes: Partial<Record<string, NodeState>>;
  running: boolean;
}

/** 一键建模流水线：ingest → extract → coordinator → analysis → review → report */
export function PipelineProgress({ nodes, running }: PipelineProgressProps) {
  const doneCount = NODE_ORDER.filter((n) => nodes[n]?.status === "success").length;
  const pct = Math.round((doneCount / NODE_ORDER.length) * 100);

  return (
    <div className="shrink-0 border-b border-base-300 bg-base-200/40 px-3 py-2">
      <div className="mb-2 flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <h3 className="text-[14px] font-semibold text-base-content/90">建模流水线</h3>
          <span className="tnum font-mono text-[14px] text-base-content/85">
            {doneCount}/{NODE_ORDER.length}
          </span>
        </div>
        <span className="text-[14px] text-base-content/85">
          {running ? "执行中…" : doneCount === NODE_ORDER.length ? "已完成" : pct > 0 ? `${pct}%` : "未开始"}
        </span>
      </div>
      <progress
        className="progress progress-primary h-1.5 w-full"
        value={doneCount}
        max={NODE_ORDER.length}
      />
      <ol className="mt-2 grid grid-cols-3 gap-1.5 sm:grid-cols-6">
        {NODE_ORDER.map((name) => {
          const st = nodes[name];
          const status: NodeStatus = st?.status ?? "pending";
          const ui = STATUS_UI[status];
          const Icon = ui.icon;
          const elapsed =
            st?.startedAt && st?.endedAt
              ? `${((st.endedAt - st.startedAt) / 1000).toFixed(1)}s`
              : "";
          return (
            <li
              key={name}
              title={st?.message || NODE_LABELS[name] || name}
              className={`rounded-[var(--radius-field)] border px-1.5 py-1.5 ${
                status === "running"
                  ? "border-primary/45 bg-primary/[0.06]"
                  : status === "success"
                    ? "border-success/35 bg-success/[0.05]"
                    : status === "failed"
                      ? "border-error/35 bg-error/[0.05]"
                      : "border-base-300 bg-base-100"
              }`}
            >
              <div className="flex items-center gap-1">
                <Icon
                  className={`h-3 w-3 shrink-0 ${ui.cls} ${status === "running" ? "animate-spin" : ""}`}
                />
                <span className="truncate text-[14px] font-medium text-base-content">
                  {NODE_LABELS[name] || name}
                </span>
              </div>
              <p className="mt-0.5 truncate font-mono text-[14px] text-base-content/85">
                {elapsed || ui.label}
              </p>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

/** 从 SSE 事件流维护节点状态 */
export function reduceNodeStates(
  prev: Partial<Record<string, NodeState>>,
  ev: { type: string; node?: string | null; status?: string | null; message?: string | null },
): Partial<Record<string, NodeState>> {
  const node = ev.node;
  if (!node || !NODE_LABELS[node]) return prev;
  const now = Date.now();
  const cur = prev[node] ?? { status: "pending" as NodeStatus };

  if (ev.type === "node_start") {
    return {
      ...prev,
      [node]: { ...cur, status: "running", message: ev.message || undefined, startedAt: now },
    };
  }
  if (ev.type === "node_end") {
    const status: NodeStatus = ev.status === "failed" ? "failed" : "success";
    return {
      ...prev,
      [node]: { ...cur, status, message: ev.message || undefined, endedAt: now },
    };
  }
  if (ev.type === "error" && ev.status === "failed") {
    // 无 node 时保持不变；有 node 则标失败
    return {
      ...prev,
      [node]: { ...cur, status: "failed", message: ev.message || undefined, endedAt: now },
    };
  }
  if (ev.type === "run_end" && ev.status === "success") {
    // 未显式结束的节点在整轮成功时收敛为成功（若曾 running）
    const next = { ...prev };
    for (const k of NODE_ORDER) {
      const n = next[k];
      if (n?.status === "running") {
        next[k] = { ...n, status: "success", endedAt: now };
      }
    }
    return next;
  }
  return prev;
}
