"use client";

import { MessageSquarePlus, Trash2, Bot } from "lucide-react";
import type { ConversationSummary } from "@/lib/api";

interface Props {
  conversations: ConversationSummary[];
  activeId: string;
  onSelect: (runId: string) => void;
  onNew: () => void;
  onDelete: (runId: string) => void;
}

function formatTime(ts: number) {
  if (!ts) return "";
  const d = new Date(ts);
  const now = new Date();
  if (d.toDateString() === now.toDateString()) {
    return d.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
  }
  return d.toLocaleDateString("zh-CN", { month: "numeric", day: "numeric" });
}

export function ConversationSidebar({
  conversations,
  activeId,
  onSelect,
  onNew,
  onDelete,
}: Props) {
  return (
    <aside className="flex w-[260px] shrink-0 flex-col overflow-hidden border-r border-base-300 bg-base-100">
      <div className="flex shrink-0 items-center justify-between gap-2 border-b border-base-300 px-3 py-2.5">
        <h2 className="text-[15px] font-semibold text-base-content">对话</h2>
        <button onClick={onNew} className="btn btn-primary btn-xs gap-1" title="新对话">
          <MessageSquarePlus className="h-3.5 w-3.5" />
          新对话
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-2">
        {conversations.length === 0 ? (
          <div className="flex flex-col items-center justify-center gap-2 py-10 text-center">
            <Bot className="h-8 w-8 text-base-content/90" />
            <p className="text-[14px] font-medium text-base-content/90">暂无对话</p>
            <p className="text-[13px] text-base-content/90">点击「新对话」开始</p>
          </div>
        ) : (
          <div className="flex flex-col gap-1">
            {conversations.map((c) => (
              <button
                key={c.run_id}
                onClick={() => onSelect(c.run_id)}
                className={`group flex w-full items-center gap-2 rounded-[var(--radius-box)] border px-2.5 py-2 text-left transition-colors ${
                  c.run_id === activeId
                    ? "border-primary/40 bg-primary/[0.10]"
                    : "border-transparent hover:bg-base-200"
                }`}
              >
                <span className="flex min-w-0 flex-1 flex-col gap-0.5 text-left">
                  <span className="truncate text-[14px] font-medium text-base-content">
                    {c.title}
                  </span>
                  <span className="truncate text-[13px] text-base-content/90">
                    {c.message_count} 条 · {formatTime(c.updated_at)}
                  </span>
                </span>
                <span
                  onClick={(e) => {
                    e.stopPropagation();
                    if (
                      window.confirm(
                        `删除对话「${c.title}」？\n聊天记录与协作面板数据都会被删除，不可恢复。`,
                      )
                    ) {
                      onDelete(c.run_id);
                    }
                  }}
                  className="invisible rounded p-1 text-base-content/90 hover:bg-base-300 hover:text-error group-hover:visible"
                  title="删除对话"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </span>
              </button>
            ))}
          </div>
        )}
      </div>
    </aside>
  );
}
