"use client";

import { memo, useEffect, useMemo, useRef, useState } from "react";
import { motion } from "framer-motion";
import {
  Brain,
  Wrench,
  Check,
  X,
  CircleAlert,
  Loader2,
  BookOpen,
  Lightbulb,
  Terminal,
  ChevronRight,
  ChevronDown,
  Maximize2,
  Minimize2,
  MessageSquare,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useAutoScroll } from "@/hooks/useAutoScroll";
import {
  idleAgent,
  type AgentState,
  type AgentPhase,
  type AgentItem,
} from "@/hooks/useAgentTimeline";

interface Props {
  agents: Record<string, AgentState>;
  order: string[];
  zoomKey: string | null;
  onZoom: (key: string | null) => void;
}

const PHASE: Record<
  AgentPhase,
  { badge: string; label: string; dot: string }
> = {
  idle: { badge: "badge-ghost", label: "待命", dot: "bg-base-content/25" },
  thinking: { badge: "badge-primary badge-outline", label: "思考中", dot: "bg-primary" },
  tool: { badge: "badge-warning badge-outline", label: "调用工具", dot: "bg-warning" },
  done: { badge: "badge-success badge-outline", label: "已完成", dot: "bg-success" },
  error: { badge: "badge-error badge-outline", label: "出错", dot: "bg-error" },
};

const NOISE = [
  /<dots_function_call>[\s\S]*?<\/dots_function_call>/g,
  /<invoke\b[\s\S]*?<\/invoke>/g,
  /<parameter\b[\s\S]*?<\/parameter>/g,
  /<\/?(dots_function_call|invoke|parameter)\b[^>]*>/g,
];

function stripNoise(text: string): string {
  let out = text;
  for (const re of NOISE) out = out.replace(re, "");
  return out;
}

/* ---------- 思考块：完成后自动折叠 ---------- */

const ThinkingBlock = memo(function ThinkingBlock({ item }: { item: AgentItem }) {
  const [open, setOpen] = useState(!item.done);
  const touchedRef = useRef(false);

  useEffect(() => {
    if (item.done && !touchedRef.current) setOpen(false);
  }, [item.done]);

  const text = stripNoise(item.text);
  const preview =
    text.length > 56 ? text.slice(0, 56).replace(/\s+/g, " ") + "…" : text;

  return (
    <div className="my-1.5">
      <div className="collapse collapse-arrow border border-base-300 bg-base-200/60">
        <input
          type="checkbox"
          checked={open}
          onChange={() => {
            touchedRef.current = true;
            setOpen((v) => !v);
          }}
          aria-label="展开思考过程"
        />
        <div className="collapse-title flex min-h-0 items-center gap-1.5 py-1.5 pr-8 pl-2.5 text-[14px]">
          <Brain className="h-3 w-3 shrink-0 text-base-content/90" />
          <span className="shrink-0 font-medium text-base-content/90">思考</span>
          {!item.done && (
            <Loader2 className="h-2.5 w-2.5 shrink-0 animate-spin text-primary" />
          )}
          {item.done && !open && (
            <span className="min-w-0 flex-1 truncate text-base-content/90">
              {preview}
            </span>
          )}
          <span className="tnum ml-auto shrink-0 font-mono text-[14px] text-base-content/90">
            {text.length} 字
          </span>
        </div>
        {open && (
          <div className="collapse-content px-2.5">
            <p className="prose-report border-t border-base-300 pt-2 text-[14px] whitespace-pre-wrap text-base-content/90">
              {text}
            </p>
          </div>
        )}
      </div>
    </div>
  );
});

/* ---------- 输出块：Markdown 渲染 ---------- */

const OutputBlock = memo(function OutputBlock({
  item,
  streaming,
}: {
  item: AgentItem;
  streaming: boolean;
}) {
  const text = stripNoise(item.text);
  if (!text.trim()) return null;

  return (
    <div className="my-2 overflow-hidden rounded-[var(--radius-field)] border border-base-300 bg-base-100">
      <div className="flex items-center gap-1.5 border-b border-base-300 bg-base-200/70 px-2.5 py-1">
        <MessageSquare className="h-3 w-3 text-base-content/90" />
        <span className="text-[14px] font-medium text-base-content/90">
          输出
        </span>
        {streaming && (
          <span className="ml-auto flex items-center gap-1 text-[14px] text-primary">
            <Loader2 className="h-2.5 w-2.5 animate-spin" />
            生成中
          </span>
        )}
      </div>
      <div
        className={`prose-report px-3 py-2 text-[14px] ${
          streaming ? "stream-caret" : ""
        }`}
      >
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
      </div>
    </div>
  );
});

/* ---------- 工具调用：默认折叠，展开看完整入参 / 返回值 ---------- */

function previewOf(text: string): string {
  const flat = text.replace(/\s+/g, " ").trim();
  return flat.length > 60 ? flat.slice(0, 60) + "…" : flat;
}

/** 调用与结果共用一套折叠块，仅图标 / 配色 / 标签不同 */
const ToolBlock = memo(function ToolBlock({
  item,
  variant,
}: {
  item: AgentItem;
  variant: "call" | "result";
}) {
  const [open, setOpen] = useState(false);

  const detail = item.detail || "";
  const failed = variant === "result" && item.ok === false;
  const Icon = failed ? X : variant === "call" ? Wrench : Check;

  const tone = failed
    ? "border-error/30 bg-error/[0.05]"
    : variant === "call"
      ? "border-warning/30 bg-warning/[0.05]"
      : "border-base-300 bg-base-200/40";
  const iconTone = failed
    ? "text-error"
    : variant === "call"
      ? "text-warning"
      : "text-success";

  const label =
    variant === "call"
      ? "调用工具"
      : failed
        ? "调用失败"
        : "调用完成";

  // 没有详情时退化成单行，不给出误导性的空折叠面板
  if (!detail) {
    return (
      <div className={`my-1 flex items-center gap-2 px-2.5 py-1 ${tone} rounded-[var(--radius-field)] border`}>
        <Icon className={`h-3 w-3 shrink-0 ${iconTone}`} strokeWidth={2.5} />
        <span className="truncate font-mono text-[14px] text-base-content/90">
          {item.text}
        </span>
      </div>
    );
  }

  return (
    <div className="my-1.5">
      <div className={`collapse collapse-arrow border ${tone}`}>
        <input
          type="checkbox"
          checked={open}
          onChange={() => setOpen((v) => !v)}
          aria-label={`${label}：${item.text}`}
        />
        <div className="collapse-title flex min-h-0 items-center gap-1.5 py-1.5 pr-8 pl-2.5 text-[14px]">
          <Icon className={`h-3 w-3 shrink-0 ${iconTone}`} strokeWidth={2.5} />
          <span className="shrink-0 font-mono font-medium text-base-content">
            {item.text}
          </span>
          {!open && (
            <span className="min-w-0 flex-1 truncate font-mono text-[14px] text-base-content/85">
              {previewOf(detail)}
            </span>
          )}
          <span className="tnum ml-auto shrink-0 font-mono text-[14px] text-base-content/85">
            {detail.length} 字
          </span>
        </div>
        {open && (
          <div className="collapse-content px-2.5">
            <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words rounded-[var(--radius-field)] border border-base-300 bg-base-100 px-2 py-1.5 font-mono text-[14px] leading-relaxed text-base-content/90">
              {detail}
            </pre>
            {item.detailTruncated && (
              <p className="mt-1 text-[14px] text-base-content/85">
                内容较长，此处仅显示前 6000 字。
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  );
});

const ErrorLine = memo(function ErrorLine({ item }: { item: AgentItem }) {
  return (
    <div className="my-1.5 flex items-start gap-2 rounded-[var(--radius-field)] border border-error/30 bg-error/[0.05] px-2.5 py-1.5">
      <CircleAlert className="mt-px h-3.5 w-3.5 shrink-0 text-error" />
      <span className="font-mono text-[14px] leading-relaxed break-words text-base-content/90">
        {item.text}
      </span>
    </div>
  );
});

const NodeLine = memo(function NodeLine({ item }: { item: AgentItem }) {
  return (
    <div className="my-1 flex items-start gap-1.5">
      <ChevronRight className="mt-0.5 h-3 w-3 shrink-0 text-primary" />
      <span className="text-[14px] font-medium whitespace-pre-wrap text-base-content/90">
        {item.text}
      </span>
    </div>
  );
});

const LogLine = memo(function LogLine({ item }: { item: AgentItem }) {
  // 主管的决策依据：回答「它为什么派这位专家」，需要比普通日志显眼
  if (item.tone === "reason") {
    return (
      <div className="my-1.5 flex items-start gap-1.5 rounded-[var(--radius-field)] border border-primary/30 bg-primary/[0.05] px-2.5 py-1">
        <Lightbulb className="mt-px h-3 w-3 shrink-0 text-primary" />
        <span className="text-[14px] leading-relaxed text-base-content">
          {item.text}
        </span>
      </div>
    );
  }
  return (
    <div className="my-0.5 pl-5 font-mono text-[14px] whitespace-pre-wrap text-base-content/90">
      {item.text}
    </div>
  );
});

/* ---------- 条目分发 ---------- */

function renderItem(item: AgentItem, isLast: boolean, running: boolean) {
  switch (item.kind) {
    case "thinking":
      return <ThinkingBlock key={item.id} item={item} />;
    case "token":
      return <OutputBlock key={item.id} item={item} streaming={isLast && running} />;
    case "tool_call":
      return <ToolBlock key={item.id} item={item} variant="call" />;
    case "tool_result":
      return <ToolBlock key={item.id} item={item} variant="result" />;
    case "error":
      return <ErrorLine key={item.id} item={item} />;
    case "node":
      return <NodeLine key={item.id} item={item} />;
    default:
      return <LogLine key={item.id} item={item} />;
  }
}

/* ---------- 智能体窗口 ---------- */

const AgentWindow = memo(function AgentWindow({
  agent,
  zoomed,
  onToggleZoom,
}: {
  agent: AgentState;
  zoomed: boolean;
  onToggleZoom: () => void;
}) {
  const phase = PHASE[agent.phase];
  const active = agent.phase === "thinking" || agent.phase === "tool";
  // 与对话主区同一套自动下滑逻辑（见 useAutoScroll）
  const { scrollRef, autoFollow, jumpToBottom } = useAutoScroll([agent.items], 30);

  return (
    <div
      className={`flex h-full min-h-0 min-w-0 flex-col overflow-hidden rounded-[var(--radius-box)] border bg-base-100 ${
        active ? "border-primary/45" : "border-base-300"
      } ${agent.phase === "idle" ? "opacity-70" : ""}`}
    >
      <div className="flex shrink-0 items-center gap-2 border-b border-base-300 px-2.5 py-2">
        <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-[var(--radius-field)] border border-base-300 bg-base-200 text-[14px] font-semibold text-base-content/90">
          {agent.name.slice(0, 1)}
        </span>

        <div className="min-w-0 flex-1">
          <p className="truncate text-[14px] leading-tight font-semibold text-base-content">
            {agent.name}
          </p>
          <p className="truncate text-[14px] leading-tight text-base-content/90">
            {agent.role}
          </p>
        </div>

        <div className="flex shrink-0 items-center gap-1">
          <button
            onClick={onToggleZoom}
            className="btn btn-ghost btn-xs px-1"
            title={zoomed ? "缩小" : "放大"}
          >
            {zoomed ? (
              <Minimize2 className="h-3 w-3" />
            ) : (
              <Maximize2 className="h-3 w-3" />
            )}
          </button>
        </div>
      </div>

      <div className="flex shrink-0 flex-wrap items-center gap-x-2 gap-y-1 border-b border-base-300 bg-base-200/50 px-2.5 py-1">
        <span className={`badge badge-sm ${phase.badge}`}>
          <span className={`h-1 w-1 rounded-full ${phase.dot}`} />
          {phase.label}
        </span>
        {agent.step > 0 && (
          <span className="tnum font-mono text-[14px] text-base-content/90">
            第 {agent.step} 步
          </span>
        )}
        {agent.currentTool && (
          <span className="truncate font-mono text-[14px] text-warning">
            {agent.currentTool}
          </span>
        )}
        {agent.elapsedMs > 0 && (
          <span className="tnum ml-auto font-mono text-[14px] text-base-content/90">
            {(agent.elapsedMs / 1000).toFixed(1)}s
          </span>
        )}
      </div>

      {agent.loadedSkills.length > 0 && (
        <div className="flex shrink-0 flex-wrap gap-1 border-b border-base-300 px-2.5 py-1">
          {agent.loadedSkills.map((s) => (
            <span key={s} className="badge badge-sm badge-ghost gap-1">
              <BookOpen className="h-2.5 w-2.5" />
              {s}
            </span>
          ))}
        </div>
      )}

      <div className="relative min-h-0 flex-1 overflow-hidden">
        <div
          ref={scrollRef}
          className="h-full overflow-x-hidden overflow-y-auto px-2.5 py-2"
        >
          {agent.items.length === 0 && (
            <p className="py-2 text-[14px] text-base-content/90">等待任务…</p>
          )}
          {agent.items.map((item, i) =>
            renderItem(item, i === agent.items.length - 1, active),
          )}
        </div>

        {!autoFollow && (
          <button
            onClick={jumpToBottom}
            className="btn btn-xs absolute right-2.5 bottom-2 gap-1 border-base-300 bg-base-100 text-base-content/90"
          >
            <ChevronDown className="h-3 w-3" />
            回到底部
          </button>
        )}
      </div>
    </div>
  );
});

/* ---------- 工作台 ---------- */

export function AgentStage({ agents, order, zoomKey, onZoom }: Props) {
  const anyPresent = useMemo(() => order.some((k) => agents[k]), [agents, order]);

  // 只渲染本轮参与的专家：团队规模较大时，常驻的待命窗口会挤占有限的面板空间。
  const list = useMemo(() => {
    const all = order.map((k) => agents[k] ?? idleAgent(k));
    return all.filter((a) => a.items.length > 0 || a.phase !== "idle");
  }, [agents, order]);

  const activeCount = list.filter(
    (a) => a.phase === "thinking" || a.phase === "tool",
  ).length;
  const doneCount = list.filter((a) => a.phase === "done").length;

  if (list.length === 0) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 text-base-content/90">
        <Terminal className="h-7 w-7" />
        <p className="text-sm">智能体团队待命中</p>
        <p className="max-w-[240px] text-center text-[14px] text-base-content/90">
          {anyPresent
            ? "本轮尚未调度任何专家"
            : "开始对话后，本轮参与的专家会在此各自获得独立窗口"}
        </p>
      </div>
    );
  }

  if (zoomKey) {
    const focus = list.find((a) => a.key === zoomKey);
    if (focus) {
      return (
        <div className="flex h-full min-h-0 flex-col">
          <div className="mb-2 flex shrink-0 items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <h2 className="text-sm font-semibold tracking-wide text-base-content/90">
                智能体工作台
              </h2>
              <span className="badge badge-sm badge-primary badge-outline">
                {focus.name}
              </span>
            </div>
            <button
              onClick={() => onZoom(null)}
              className="btn btn-xs gap-1 border-base-300 bg-base-100 text-base-content/90"
            >
              <Minimize2 className="h-3 w-3" />
              全部窗口
            </button>
          </div>
          {/* 140ms 淡入：只用来标示"视图切换了"，不做弹跳/缩放这类装饰动画 */}
          <motion.div
            key={focus.key}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.14, ease: "easeOut" }}
            className="min-h-0 flex-1"
          >
            <AgentWindow agent={focus} zoomed onToggleZoom={() => onZoom(null)} />
          </motion.div>
        </div>
      );
    }
  }

  // 固定两列：团队人多时保持每格可读（面板本身可拖宽）
  const cols = list.length <= 1 ? 1 : 2;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="mb-1.5 flex shrink-0 items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-semibold tracking-wide text-base-content/90">
            智能体工作台
          </h2>
          <span className="tnum font-mono text-[14px] text-base-content/90">
            参与 {list.length} / {order.length} 位
          </span>
        </div>
        <span className="tnum font-mono text-[14px] text-base-content/90">
          {activeCount > 0
            ? `${activeCount} 个进行中`
            : `${doneCount} 位已完成`}
        </span>
      </div>

      {/* 全员状态条：一眼看出谁在干活、谁已完成 */}
      <div className="mb-2 flex shrink-0 flex-wrap gap-1">
        {order.map((key) => {
          const a = agents[key] ?? idleAgent(key);
          const meta = PHASE[a.phase];
          const active = a.phase === "thinking" || a.phase === "tool";
          const hasWork = a.items.length > 0 || a.phase !== "idle";
          return (
            <button
              key={key}
              type="button"
              disabled={!hasWork}
              onClick={() => hasWork && onZoom(key)}
              title={`${a.name} · ${meta.label}${a.currentTool ? ` · ${a.currentTool}` : ""}`}
              className={`badge badge-sm gap-1 ${
                active
                  ? "badge-primary badge-outline"
                  : a.phase === "done"
                    ? "badge-success badge-outline"
                    : a.phase === "error"
                      ? "badge-error badge-outline"
                      : "badge-ghost"
              } ${hasWork ? "cursor-pointer" : "opacity-40"}`}
            >
              <span className={`h-1.5 w-1.5 rounded-full ${meta.dot}`} />
              <span className="max-w-[72px] truncate">{a.name}</span>
            </button>
          );
        })}
      </div>

      <div
        className="grid min-h-0 flex-1 gap-2"
        style={{
          gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))`,
          gridAutoRows: "minmax(0, 1fr)",
        }}
      >
        {list.map((agent) => (
          <AgentWindow
            key={agent.key}
            agent={agent}
            zoomed={false}
            onToggleZoom={() => onZoom(agent.key)}
          />
        ))}
      </div>
    </div>
  );
}
