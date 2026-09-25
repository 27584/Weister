"use client";

import { memo, useState } from "react";
import {
  AlertCircle,
  Bot,
  Brain,
  Check,
  ChevronDown,
  Copy,
  Download,
  FileText,
  HelpCircle,
  Image as ImageIcon,
  Loader2,
  Square,
  User,
  Wrench,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useAutoScroll } from "@/hooks/useAutoScroll";
import { AskUserCard } from "@/components/AskUserCard";
import { copyText, downloadMarkdown, messagesToMarkdown } from "@/lib/exportChat";
import type { AskAnswer, PendingAsk } from "@/lib/types";
import type { ChatMessage } from "@/lib/api";

interface Props {
  messages: ChatMessage[];
  running: boolean;
  activeAgent: string | null;
  error: string | null;
  truncated: boolean;
  iterations: number;
  onAbort: () => void;
  /** 模型推理过程（thinking 流），实时展示 */
  thinking?: string;
  /** 运行中长时间无事件 —— 提示仍在等待，避免界面呈现为无响应 */
  stalled?: boolean;
  /** 智能体发出的待答问题；非空时在消息流末尾展示选项卡片 */
  pendingAsk?: PendingAsk | null;
  onAnswer?: (answers: AskAnswer[]) => void;
  onSkipAsk?: () => void;
}

const ROLE_META: Record<
  ChatMessage["role"],
  { label: string; icon: typeof User; tone: string }
> = {
  user: { label: "你", icon: User, tone: "bg-primary text-primary-content" },
  assistant: { label: "助手", icon: Bot, tone: "bg-base-200 text-base-content" },
  tool: { label: "工具", icon: Wrench, tone: "bg-warning/15 text-warning" },
  system: { label: "系统", icon: AlertCircle, tone: "bg-base-200/70 text-base-content/90" },
};

const MessageAvatar = memo(function MessageAvatar({
  role,
  tone,
  icon: Icon,
}: {
  role: ChatMessage["role"];
  tone: string;
  icon: typeof User;
}) {
  return (
    <div
      className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full ${tone}`}
      title={ROLE_META[role].label}
    >
      <Icon className="h-3.5 w-3.5" />
    </div>
  );
});

const UserBubble = memo(function UserBubble({ msg }: { msg: ChatMessage }) {
  return (
    <div className="flex items-start gap-2.5 flex-row-reverse">
      <MessageAvatar role="user" tone={ROLE_META.user.tone} icon={User} />
      <div className="flex max-w-[80%] flex-col items-end gap-1.5">
        {msg.images && msg.images.length > 0 && (
          <div className="flex flex-wrap gap-1.5 justify-end">
            {msg.images.map((img, i) => (
              <img
                key={i}
                src={img.url}
                alt={img.name}
                className="h-24 w-24 rounded-[var(--radius-field)] border border-base-300 object-cover"
              />
            ))}
          </div>
        )}
        {msg.attachments && msg.attachments.length > 0 && (
          <div className="flex flex-wrap gap-1.5 justify-end">
            {msg.attachments.map((att, i) => {
              const bad = att.readable === false;
              const meta: string[] = [];
              if (att.kind) meta.push(att.kind);
              if (att.pages) meta.push(`${att.pages} 页`);
              if (typeof att.chars === "number") meta.push(`${att.chars} 字`);
              return (
                <span
                  key={i}
                  title={att.name}
                  className={`flex items-center gap-1.5 rounded-[var(--radius-field)] border px-2 py-1 text-[14px] ${
                    bad
                      ? "border-warning/40 bg-warning/[0.08] text-base-content"
                      : "border-base-300 bg-base-200/60 text-base-content/90"
                  }`}
                >
                  <FileText className={`h-3.5 w-3.5 shrink-0 ${bad ? "text-warning" : ""}`} />
                  <span className="max-w-[220px] truncate">{att.name}</span>
                  {meta.length > 0 && (
                    <span className="shrink-0 text-base-content/85">
                      · {meta.join(" / ")}
                    </span>
                  )}
                  {bad && <span className="shrink-0 text-warning">未提取到文本</span>}
                </span>
              );
            })}
          </div>
        )}
        {msg.content && (
          <div className="rounded-[var(--radius-box)] rounded-tr-sm bg-primary px-3.5 py-2.5 text-[14px] font-medium leading-relaxed text-white whitespace-pre-wrap">
            {msg.content}
          </div>
        )}
      </div>
    </div>
  );
});

const AssistantBubble = memo(function AssistantBubble({ msg }: { msg: ChatMessage }) {
  const text = msg.content || "";
  const [copied, setCopied] = useState(false);
  return (
    <div className="flex items-start gap-2.5">
      <MessageAvatar role="assistant" tone={ROLE_META.assistant.tone} icon={Bot} />
      <div className="flex max-w-[88%] flex-col gap-1.5">
        {msg.by && (
          <p className="text-[14px] text-base-content/90">
            <span className="font-medium text-base-content">{msg.by}</span>
            <span className="mx-1.5 text-base-content/35">·</span>
            <span className="text-base-content/90">回答</span>
          </p>
        )}
        <div
          className={`prose-report group relative rounded-[var(--radius-box)] rounded-tl-sm border border-base-300 bg-base-100 px-3.5 py-2.5 text-[14px] leading-relaxed ${
            msg.streaming ? "stream-caret" : ""
          }`}
        >
          {text.trim() ? (
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
          ) : (
            <span className="inline-flex items-center gap-1.5 text-base-content/90">
              <Loader2 className="h-3 w-3 animate-spin" />
              生成中
            </span>
          )}
          {text.trim() && !msg.streaming && (
            <button
              type="button"
              title="复制全文"
              onClick={async () => {
                if (await copyText(text)) {
                  setCopied(true);
                  setTimeout(() => setCopied(false), 1500);
                }
              }}
              className="absolute top-1.5 right-1.5 rounded-[var(--radius-field)] border border-base-300 bg-base-200/90 p-1 opacity-0 transition-opacity group-hover:opacity-100"
            >
              {copied ? (
                <Check className="h-3 w-3 text-success" />
              ) : (
                <Copy className="h-3 w-3 text-base-content/90" />
              )}
            </button>
          )}
        </div>
      </div>
    </div>
  );
});

const ToolBubble = memo(function ToolBubble({ msg }: { msg: ChatMessage }) {
  const detail = msg.toolDetail || "";
  const failed = msg.toolOk === false;

  // 没有详情时保持单行，不给出误导性的空折叠面板
  if (!detail) {
    return (
      <div className="flex items-start gap-2.5 pl-9">
        <span className="flex items-center gap-1.5 rounded-[var(--radius-field)] border border-warning/25 bg-warning/[0.05] px-2.5 py-1 font-mono text-[14px] text-base-content/90">
          <Wrench className="h-3 w-3 text-warning" />
          {msg.content}
        </span>
      </div>
    );
  }

  return (
    <div className="flex items-start gap-2.5 pl-9">
      <details className="max-w-[80%] rounded-[var(--radius-field)] border border-warning/25 bg-warning/[0.05]">
        <summary className="flex cursor-pointer select-none items-center gap-1.5 px-2.5 py-1 font-mono text-[14px] text-base-content">
          <Wrench className="h-3 w-3 shrink-0 text-warning" />
          <span className={failed ? "text-error" : ""}>{msg.content}</span>
          <span className="tnum text-[14px] text-base-content/85">
            {detail.length} 字
          </span>
        </summary>
        <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-words border-t border-warning/20 px-2.5 py-1.5 font-mono text-[14px] leading-relaxed text-base-content/90">
          {detail}
        </pre>
      </details>
    </div>
  );
});

const SystemBubble = memo(function SystemBubble({ msg }: { msg: ChatMessage }) {
  return (
    <div className="flex items-center gap-2 pl-9 text-[14px] text-base-content/90">
      <AlertCircle className="h-3 w-3 shrink-0" />
      <span className="font-mono">{msg.content}</span>
    </div>
  );
});

function renderMessage(msg: ChatMessage) {
  switch (msg.role) {
    case "user":
      return <UserBubble key={msg.id} msg={msg} />;
    case "assistant":
      return <AssistantBubble key={msg.id} msg={msg} />;
    case "tool":
      return <ToolBubble key={msg.id} msg={msg} />;
    case "system":
      return <SystemBubble key={msg.id} msg={msg} />;
    default:
      return null;
  }
}

export function ChatPanel({
  messages,
  running,
  activeAgent,
  error,
  truncated,
  iterations,
  onAbort,
  thinking = "",
  stalled = false,
  pendingAsk = null,
  onAnswer,
  onSkipAsk,
}: Props) {
  // 与智能体协作窗口同一套自动下滑逻辑（见 useAutoScroll）：
  // 贴底时跟随流式输出，用户往上翻则停止跟随并显示「回到底部」
  const { scrollRef, autoFollow, jumpToBottom } = useAutoScroll(
    [messages, thinking, pendingAsk],
    50,
  );

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden rounded-[var(--radius-box)] border border-base-300 bg-base-100">
      <div className="flex shrink-0 items-center justify-between gap-2 border-b border-base-300 px-3 py-2">
        <div className="flex items-center gap-2">
          <h2 className="text-[14px] font-semibold tracking-wide text-base-content/90">
            对话
          </h2>
          {running && (
            <span className="flex items-center gap-1.5 text-[14px] font-medium text-base-content">
              {pendingAsk ? (
                <>
                  <HelpCircle className="h-3 w-3 text-primary" />
                  等待你的选择…
                </>
              ) : (
                <>
                  <Loader2 className="h-3 w-3 animate-spin text-primary" />
                  {activeAgent ? `${activeAgent} 处理中…` : "调度中…"}
                </>
              )}
            </span>
          )}
          {iterations > 0 && !running && (
            <span className="font-mono text-[14px] text-base-content/90">
              {iterations} 轮
            </span>
          )}
        </div>
        {running ? (
          <button
            onClick={onAbort}
            className="btn btn-xs gap-1 border-error/40 text-error"
          >
            <Square className="h-2.5 w-2.5 fill-error" />
            停止
          </button>
        ) : (
          messages.some((m) => m.role === "assistant" && (m.content || "").trim()) && (
            <button
              type="button"
              title="导出对话为 Markdown"
              onClick={() =>
                downloadMarkdown(
                  `weister-chat-${Date.now()}.md`,
                  messagesToMarkdown(messages),
                )
              }
              className="btn btn-xs gap-1 border-base-300 bg-base-100 text-base-content/90"
            >
              <Download className="h-3 w-3" />
              导出
            </button>
          )
        )}
      </div>

      <div className="relative min-h-0 flex-1 overflow-hidden">
        <div
          ref={scrollRef}
          className="h-full overflow-x-hidden overflow-y-auto px-4 py-4"
        >
        {messages.length === 0 && (
          <div className="flex h-full flex-col items-center justify-center gap-3 text-center">
            <div className="flex h-12 w-12 items-center justify-center rounded-full bg-base-200">
              <Bot className="h-6 w-6 text-base-content" />
            </div>
            <div>
              <p className="text-[14px] font-medium text-base-content">开始一次新的对话</p>
              <p className="mt-1 text-[14px] text-base-content/90">
                输入你的问题，或拖入文件 / 图片。系统会自动调度多智能体协作分析。
              </p>
            </div>
            <div className="mt-2 flex flex-wrap justify-center gap-2 text-[14px]">
              {[
                "分析这份财报的盈利质量",
                "估算公司估值区间",
                "识别主要风险",
                "给一份研究简报",
              ].map((s) => (
                <span
                  key={s}
                  className="rounded-[var(--radius-field)] border border-base-300 bg-base-200/50 px-2.5 py-1 text-base-content/90"
                >
                  {s}
                </span>
              ))}
            </div>
          </div>
        )}

        <div className="mx-auto flex max-w-3xl flex-col gap-3">
          {messages.map(renderMessage)}

          {pendingAsk && onAnswer && (
            <AskUserCard
              ask={pendingAsk}
              onSubmit={onAnswer}
              onSkip={onSkipAsk ?? (() => onAnswer([]))}
            />
          )}

          {/* 思考过程：running 时展开实时推理，结束后收起，可手动展开 */}
          {(thinking || running) && (
            <details
              open={running && !pendingAsk}
              className="rounded-[var(--radius-box)] border border-base-300 bg-base-200/40 px-3 py-2"
            >
              <summary className="flex cursor-pointer select-none items-center gap-1.5 text-[14px] font-medium text-base-content">
                {running ? (
                  <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-primary" />
                ) : (
                  <Brain className="h-3.5 w-3.5 shrink-0 text-base-content" />
                )}
                <span>
                  {pendingAsk
                    ? "等待你的选择"
                    : running
                      ? stalled
                        ? "仍在等待模型响应…"
                        : "模型思考中…"
                      : "思考过程"}
                </span>
                {thinking && (
                  <span className="font-mono text-[14px] font-normal text-base-content/90">
                    {thinking.length} 字
                  </span>
                )}
              </summary>
              <div className="mt-2 max-h-64 overflow-y-auto whitespace-pre-wrap break-words text-[14px] leading-relaxed text-base-content/90">
                {thinking ||
                  (stalled
                    ? "模型暂无输出（可能正在推理或网络较慢），可点上方「停止」中断本次请求。"
                    : "（正在等待模型返回推理内容…）")}
              </div>
            </details>
          )}
        </div>
        </div>

        {!autoFollow && messages.length > 0 && (
          <button
            onClick={jumpToBottom}
            className="btn btn-xs absolute right-4 bottom-3 gap-1 border-base-300 bg-base-100 text-base-content/90"
          >
            <ChevronDown className="h-3 w-3" />
            回到底部
          </button>
        )}
      </div>

      {(error || truncated) && (
        <div
          role="alert"
          className={`flex shrink-0 items-start gap-2 border-t px-3 py-2 text-[14px] ${
            error
              ? "border-error/30 bg-error/[0.05] text-base-content"
              : "border-warning/30 bg-warning/[0.05] text-base-content"
          }`}
        >
          <AlertCircle
            className={`mt-px h-3.5 w-3.5 shrink-0 ${
              error ? "text-error" : "text-warning"
            }`}
          />
          <span className="break-words">
            {error
              ? error
              : "对话未能自然结束，已使用最近一次专家结论收尾，结论可能不完整。"}
          </span>
        </div>
      )}
    </div>
  );
}