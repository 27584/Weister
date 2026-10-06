"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Paperclip,
  Send,
  Sparkles,
  X,
  FileText,
  ChevronDown,
  Bot,
} from "lucide-react";
import type { SkillSpec, ChatMessage, ChatAttachmentMeta } from "@/lib/api";
import type { LLMProfile } from "@/lib/types";
import { formatContextUsage, formatTokenCount } from "@/lib/tokens";
import { estimateChatTokens } from "@/lib/api";
import { TokenRing } from "@/components/chat/TokenRing";

interface Props {
  running: boolean;
  /** 第三个参数为当前选中的模型（覆盖 profile.model） */
  onSend: (text: string, files: File[], model: string) => void;
  onStop?: () => void;
  disabled?: boolean;
  /** 可用技能：输入 `/` 时弹出选择 */
  skills?: SkillSpec[];
  /** 当前对话历史，用于估算上下文用量 */
  messages?: ChatMessage[];
  /** 当前生效的模型配置 */
  profile?: LLMProfile | null;
  /** 设置中的全部配置档案：下拉列表 = 所有档案的模型（以设置为准） */
  profiles?: LLMProfile[];
  /** 选中模型：写回设置 store（必要时切换激活档案），保证两侧同源 */
  onSelectModel?: (model: string) => void;
  /** 当前对话 runId，用于调用后端 /api/chat/estimate */
  runId?: string;
}

const ACCEPT = ".pdf,.docx,.xlsx,.pptx,.txt,.md,.png,.jpg,.jpeg,.gif,.webp";

export function ChatComposer({
  running,
  onSend,
  onStop,
  disabled,
  skills = [],
  messages = [],
  profile,
  profiles = [],
  onSelectModel,
  runId,
}: Props) {
  const [text, setText] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [dragOver, setDragOver] = useState(false);
  const [previews, setPreviews] = useState<
    { url: string; name: string; mime: string; text?: string }[]
  >([]);
  const [menuIndex, setMenuIndex] = useState(0);
  const [menuDismissed, setMenuDismissed] = useState(false);
  const taRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  /* ---------- 模型选择 ---------- */
  const [selectedModel, setSelectedModel] = useState<string>(profile?.model || "");
  const [modelOpen, setModelOpen] = useState(false);
  const modelMenuRef = useRef<HTMLDivElement>(null);
  // 下拉内的模型搜索关键词（仅用于筛选，不新增模型）
  const [modelQuery, setModelQuery] = useState("");
  const modelInputRef = useRef<HTMLInputElement>(null);

  // 配置切换时，把输入框模型同步为新配置的默认模型
  useEffect(() => {
    if (profile?.model) setSelectedModel(profile.model);
  }, [profile?.model]);

  // 点击外部关闭模型下拉
  useEffect(() => {
    if (!modelOpen) return;
    const handler = (e: MouseEvent) => {
      if (!modelMenuRef.current?.contains(e.target as Node)) setModelOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [modelOpen]);

  // 下拉模型列表 = 设置中**所有配置档案**的模型（单一数据源 = 设置 store）。
  // 每个档案依次取：当前模型、备选模型、检测到的可选模型；不向 /api/models 另行拉取。
  const displayedModels = useMemo(() => {
    const base = new Set<string>();
    for (const p of profiles) {
      if (p.model) base.add(p.model);
      (p.fallbackModels || []).forEach((m) => base.add(m));
      (p.models || []).forEach((m) => base.add(m));
    }
    if (base.size === 0 && profile?.model) base.add(profile.model);
    return Array.from(base);
  }, [profiles, profile?.model]);

  // 搜索过滤后的模型列表
  const filteredModels = useMemo(() => {
    const q = modelQuery.trim().toLowerCase();
    if (!q) return displayedModels;
    return displayedModels.filter((m) => m.toLowerCase().includes(q));
  }, [displayedModels, modelQuery]);

  // 打开下拉时清空搜索并聚焦输入框
  useEffect(() => {
    if (!modelOpen) return;
    setModelQuery("");
    requestAnimationFrame(() => modelInputRef.current?.focus());
  }, [modelOpen]);

  const chooseModel = useCallback(
    (m: string) => {
      const model = m.trim();
      setSelectedModel(model);
      setModelOpen(false);
      setModelQuery("");
      // 选中即写回设置 store（必要时切换激活档案），设置与对话框永远同一份
      onSelectModel?.(model);
    },
    [onSelectModel],
  );

  /* ---------- `/` 技能命令 ---------- */

  // 形如 "/"、"/valu" → 弹出候选（有空格后即视为已选定，不再弹）
  const slashQuery = useMemo(() => {
    const m = /^\/([^\s]*)$/.exec(text);
    return m ? m[1].toLowerCase() : null;
  }, [text]);

  const matched = useMemo(() => {
    if (slashQuery === null) return [];
    return skills
      .filter((s) => s.name.toLowerCase().includes(slashQuery))
      .slice(0, 8);
  }, [slashQuery, skills]);

  const menuOpen = matched.length > 0 && !menuDismissed;

  // 已确定命令（"/name " 后面开始写正文）时显示标记
  const activeSkill = useMemo(() => {
    const m = /^\/([^\s]+)(\s|$)/.exec(text);
    if (!m) return null;
    return skills.find((s) => s.name === m[1]) ?? null;
  }, [text, skills]);

  const pickSkill = useCallback((name: string) => {
    setText(`/${name} `);
    setMenuDismissed(true);
    setMenuIndex(0);
    requestAnimationFrame(() => taRef.current?.focus());
  }, []);

  const addFiles = useCallback((incoming: File[]) => {
    if (incoming.length === 0) return;
    setFiles((prev) => [...prev, ...incoming]);
    const newPreviews = incoming.map((f) => ({
      url: f.type.startsWith("image/") ? URL.createObjectURL(f) : "",
      name: f.name,
      mime: f.type,
      text: undefined as string | undefined,
    }));
    // 文本类文件：读出正文，供后端在发送前就精确计入上下文（PDF/Word/Excel 无法在浏览器端解析，发送后从磁盘读）
    incoming.forEach((f, i) => {
      const isText =
        f.type.startsWith("text/") || /\.(txt|md|markdown|csv|json|log)$/i.test(f.name);
      if (!isText) return;
      const reader = new FileReader();
      reader.onload = () =>
        setPreviews((prev) =>
          prev.map((p, idx) =>
            idx === prev.length - incoming.length + i
              ? { ...p, text: String(reader.result || "") }
              : p,
          ),
        );
      reader.readAsText(f);
    });
    setPreviews((prev) => [...prev, ...newPreviews]);
  }, []);

  const removeFile = useCallback((idx: number) => {
    setFiles((prev) => prev.filter((_, i) => i !== idx));
    setPreviews((prev) => {
      const next = prev.filter((_, i) => i !== idx);
      const removed = prev[idx];
      if (removed?.url.startsWith("blob:")) URL.revokeObjectURL(removed.url);
      return next;
    });
  }, []);

  const handleSend = useCallback(() => {
    const t = text.trim();
    if (!t && files.length === 0) return;
    if (running) return;
    onSend(t, files, selectedModel);
    setText("");
    setFiles([]);
    setPreviews([]);
    setMenuDismissed(false);
    setMenuIndex(0);
    taRef.current?.focus();
  }, [text, files, running, onSend, selectedModel]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (menuOpen) {
        if (e.key === "ArrowDown") {
          e.preventDefault();
          setMenuIndex((i) => (i + 1) % matched.length);
          return;
        }
        if (e.key === "ArrowUp") {
          e.preventDefault();
          setMenuIndex((i) => (i - 1 + matched.length) % matched.length);
          return;
        }
        if (e.key === "Enter" || e.key === "Tab") {
          e.preventDefault();
          pickSkill(matched[Math.min(menuIndex, matched.length - 1)].name);
          return;
        }
        if (e.key === "Escape") {
          e.preventDefault();
          setMenuDismissed(true);
          return;
        }
      }
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    },
    [menuOpen, matched, menuIndex, pickSkill, handleSend],
  );

  const handlePaste = useCallback(
    (e: React.ClipboardEvent<HTMLTextAreaElement>) => {
      const items = e.clipboardData?.items;
      if (!items) return;
      const pasted: File[] = [];
      for (let i = 0; i < items.length; i++) {
        const it = items[i];
        if (it.kind === "file") {
          const f = it.getAsFile();
          if (f) pasted.push(f);
        }
      }
      if (pasted.length > 0) {
        e.preventDefault();
        addFiles(pasted);
      }
    },
    [addFiles],
  );

  // 自动调整高度
  useEffect(() => {
    const el = taRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 200) + "px";
  }, [text]);

  // 卸载时释放 object URL
  useEffect(() => {
    return () => {
      for (const p of previews) if (p.url.startsWith("blob:")) URL.revokeObjectURL(p.url);
    };
  }, [previews]);

  /* ---------- 上下文用量（后端精确计算） ---------- */
  const [usage, setUsage] = useState<{
    used: number;
    limit: number;
    reserve: number;
    breakdown: { system: number; conversation: number };
  } | null>(null);
  const [usageLoading, setUsageLoading] = useState(false);

  const attachmentsMeta: ChatAttachmentMeta[] = useMemo(
    () =>
      previews.map((p, i) => ({
        id: `f${i}`,
        name: p.name,
        mime: p.mime,
        ...(p.text ? { text: p.text } : {}),
      })),
    [previews],
  );

  useEffect(() => {
    // 运行中跳过：messages 每个 token 都会变，逐次估算没有意义；
    // running 翻回 false（回复完成 / 中止）时本 effect 会再跑一次，
    // 那时历史已落盘，估算才会把真实会话长度算进去。
    if (running) return;
    if (!profile?.apiKey?.trim() || !selectedModel) {
      setUsage(null);
      return;
    }
    setUsageLoading(true);
    const timer = setTimeout(() => {
      estimateChatTokens({
        runId: runId || "",
        message: text,
        attachments: attachmentsMeta,
        llm: {
          provider: profile.provider,
          model: selectedModel,
          apiKey: profile.apiKey,
          baseUrl: profile.baseUrl,
        },
      })
        .then((res) =>
          setUsage({
            used: res.tokens,
            limit: res.limit,
            reserve: res.reserve ?? 0,
            breakdown: res.breakdown ?? { system: 0, conversation: 0 },
          }),
        )
        .catch(() => setUsage(null))
        .finally(() => setUsageLoading(false));
    }, 300);
    return () => clearTimeout(timer);
    // messages 是关键依赖：回复完成后 result 事件会整体替换消息数组，
    // 没有它估算会一直停留在「发送前（空历史）」的陈旧结果上。
  }, [text, attachmentsMeta, selectedModel, profile, runId, running, messages]);

  // 占用率含输出预留：模型得有地方写回答（主流 harness 同一口径）
  const contextUsage = useMemo(() => {
    if (!usage) return { used: 0, limit: 0, pct: 0 };
    return {
      used: usage.used,
      limit: usage.limit,
      reserve: usage.reserve,
      pct: (usage.used + usage.reserve) / (usage.limit || 1),
    };
  }, [usage]);

  // 上下文用量文案：仅作悬停提示，不在输入区常驻占版面
  const contextTip = usage
    ? formatContextUsage(contextUsage)
    : usageLoading
      ? "正在估算上下文…"
      : "暂无上下文用量数据";

  const empty = text.trim().length === 0 && files.length === 0;
  // 模型选择器是配置项，不应被「未填 key / 未连接」禁用：
  // 没 key 只是不能发送，但仍要允许先选好要用的模型。
  const modelBtnDisabled = !profile || running;

  return (
    <div
      className={`relative flex flex-col gap-2 rounded-[var(--radius-box)] border bg-base-100 p-2.5 transition-colors ${
        dragOver ? "border-primary border-dashed bg-primary/[0.04]" : "border-base-300"
      }`}
      onDragOver={(e) => {
        if (disabled) return;
        if (Array.from(e.dataTransfer.types).includes("Files")) {
          e.preventDefault();
          setDragOver(true);
        }
      }}
      onDragLeave={(e) => {
        // 仅当离开整个容器时才取消高亮
        if (!e.currentTarget.contains(e.relatedTarget as Node)) setDragOver(false);
      }}
      onDrop={(e) => {
        if (disabled) return;
        const list = e.dataTransfer.files;
        if (list && list.length) {
          e.preventDefault();
          addFiles(Array.from(list));
        }
        setDragOver(false);
      }}
    >
      {dragOver && (
        <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center rounded-[var(--radius-box)] bg-primary/[0.04] text-[13px] font-medium text-primary">
          松开以添加附件
        </div>
      )}
      {previews.length > 0 && (
        <div className="flex flex-wrap gap-2 border-b border-base-300 pb-2">
          {previews.map((p, i) => (
            <div
              key={i}
              className="group relative flex items-center gap-1.5 rounded-[var(--radius-field)] border border-base-300 bg-base-200/50 pl-1.5 pr-7 py-1 text-[14px] text-base-content/90"
            >
              {p.mime.startsWith("image/") && p.url ? (
                <img
                  src={p.url}
                  alt={p.name}
                  className="h-7 w-7 rounded border border-base-300 object-cover"
                />
              ) : (
                <FileText className="h-3.5 w-3.5 text-base-content/90" />
              )}
              <span className="max-w-[160px] truncate">{p.name}</span>
              <button
                onClick={() => removeFile(i)}
                className="absolute right-1 top-1/2 -translate-y-1/2 rounded p-0.5 text-base-content/90 hover:bg-base-300 hover:text-base-content"
                aria-label="移除附件"
              >
                <X className="h-3 w-3" />
              </button>
            </div>
          ))}
        </div>
      )}

      {activeSkill && (
        <div className="flex items-center gap-1.5 text-[13px] text-base-content/90">
          <Sparkles className="h-3.5 w-3.5 shrink-0 text-primary" />
          <span className="shrink-0">使用技能</span>
          <code className="shrink-0 font-mono font-semibold text-base-content">
            {activeSkill.name}
          </code>
          <span className="truncate">— {activeSkill.description}</span>
        </div>
      )}

      <div className="relative flex items-end gap-1.5">
        {menuOpen && (
          <div className="absolute bottom-full left-0 z-30 mb-2 w-full max-w-md overflow-hidden rounded-[var(--radius-box)] border border-base-300 bg-base-100 shadow-lg">
            <div className="border-b border-base-300 px-2.5 py-1.5 text-[13px] text-base-content/90">
              选择技能（↑↓ 选择 · Enter 确认 · Esc 取消）
            </div>
            <ul className="max-h-64 overflow-y-auto py-1">
              {matched.map((s, i) => (
                <li key={s.name}>
                  <button
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={() => pickSkill(s.name)}
                    onMouseEnter={() => setMenuIndex(i)}
                    className={`flex w-full flex-col items-start gap-0.5 px-2.5 py-1.5 text-left ${
                      i === menuIndex ? "bg-primary/[0.10]" : "hover:bg-base-200"
                    }`}
                  >
                    <span className="flex items-center gap-1.5">
                      <Sparkles className="h-3 w-3 shrink-0 text-primary" />
                      <code className="font-mono text-[14px] font-semibold text-base-content">
                        {s.name}
                      </code>
                    </span>
                    <span className="line-clamp-2 text-[13px] leading-snug text-base-content/90">
                      {s.description || "（无描述）"}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}

        <button
          onClick={() => fileInputRef.current?.click()}
          disabled={running || disabled}
          className="btn btn-ghost btn-sm h-9 w-9 min-h-0 p-0"
          title="上传文件（PDF / Word / Excel / 图片）"
        >
          <Paperclip className="h-4 w-4" />
        </button>

        <textarea
          ref={taRef}
          value={text}
          onChange={(e) => {
            setText(e.target.value);
            setMenuDismissed(false);
            setMenuIndex(0);
          }}
          onKeyDown={handleKeyDown}
          onPaste={handlePaste}
          placeholder={
            disabled
              ? "请先在右上角设置中配置模型"
              : "问点什么，输入 / 使用技能…  (Enter 发送，Shift+Enter 换行)"
          }
          rows={1}
          disabled={running || disabled}
          className="textarea textarea-ghost min-h-0 flex-1 resize-none border-0 px-1 py-2 text-[15px] font-medium leading-relaxed text-base-content caret-base-content placeholder:text-base-content/70 focus:bg-transparent"
        />

        {/* ---------- 模型选择器 ---------- */}
        <div className="relative shrink-0" ref={modelMenuRef}>
          <button
            onClick={() => !modelBtnDisabled && setModelOpen((v) => !v)}
            disabled={modelBtnDisabled}
            className="btn btn-ghost btn-xs h-7 gap-1 px-2 text-base-content/90"
            title={selectedModel || "选择本次使用的模型"}
          >
            <Bot className="h-3.5 w-3.5" />
            <span className="max-w-[120px] truncate text-[13px]">
              {selectedModel || "—"}
            </span>
            <ChevronDown className="h-3 w-3" />
          </button>

          {modelOpen && (
            <div className="absolute bottom-full right-0 z-30 mb-2 w-72 overflow-hidden rounded-[var(--radius-box)] border border-base-300 bg-base-100 shadow-lg">
              <div className="flex items-center justify-between border-b border-base-300 px-2.5 py-1.5">
                <span className="text-[13px] font-medium text-base-content">选择模型</span>
              </div>

              {/* 仅搜索，自定义模型 ID 请在「设置」中录入 */}
              <div className="border-b border-base-300 px-2 py-1.5">
                <input
                  ref={modelInputRef}
                  value={modelQuery}
                  onChange={(e) => setModelQuery(e.target.value)}
                  placeholder="搜索模型"
                  className="input input-ghost input-xs h-7 w-full bg-base-200 px-2 text-[13px] text-base-content placeholder:text-base-content/70 focus:bg-base-200"
                />
              </div>

              <div className="max-h-60 overflow-y-auto py-1">
                {filteredModels.length === 0 && (
                  <div className="px-2.5 py-2 text-[13px] text-base-content/70">
                    {displayedModels.length === 0
                      ? "设置中暂无模型，请到「设置」添加"
                      : "无匹配模型"}
                  </div>
                )}
                {filteredModels.map((m) => (
                  <button
                    key={m}
                    onClick={() => chooseModel(m)}
                    className={`flex w-full flex-col items-start px-2.5 py-1.5 text-left hover:bg-base-200 ${
                      m === selectedModel ? "bg-primary/[0.08]" : ""
                    }`}
                  >
                    <span className="truncate font-mono text-[13px] font-medium text-base-content">
                      {m}
                    </span>
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* ---------- 上下文用量（悬停查看，进度环常驻） ---------- */}
        <div className="group relative flex shrink-0 items-center">
          <TokenRing pct={contextUsage.pct} />
          <div
            role="tooltip"
            className="pointer-events-none absolute bottom-full right-0 z-20 mb-2 hidden whitespace-nowrap rounded-[var(--radius-field)] border border-base-300 bg-base-100 px-2 py-1 text-[14px] text-base-content shadow-lg group-hover:block"
          >
            <div>{contextTip}</div>
            {usage && (
              <div className="mt-0.5 text-base-content/90">
                系统 {formatTokenCount(usage.breakdown.system)} · 会话{" "}
                {formatTokenCount(usage.breakdown.conversation)}
              </div>
            )}
          </div>
        </div>

        {running ? (
          <button
            onClick={onStop}
            className="btn btn-sm h-9 min-h-0 gap-1.5 border-error/40 bg-error/[0.08] text-error"
          >
            <span className="h-2 w-2 rounded-sm bg-error" />
            停止
          </button>
        ) : (
          <button
            onClick={handleSend}
            disabled={empty || disabled}
            className="btn btn-primary btn-sm h-9 min-h-0 gap-1.5"
          >
            <Send className="h-3.5 w-3.5" />
            发送
          </button>
        )}
      </div>

      <input
        ref={fileInputRef}
        type="file"
        multiple
        accept={ACCEPT}
        onChange={(e) => {
          const list = e.target.files;
          if (list) addFiles(Array.from(list));
          e.target.value = "";
        }}
        className="hidden"
      />
    </div>
  );
}
