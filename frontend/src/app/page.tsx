"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Bot,
  FlaskConical,
  MessageSquarePlus,
  MessagesSquare,
  PanelLeftClose,
  PanelLeftOpen,
  PanelRightClose,
  PanelRightOpen,
  Play,
  Settings as SettingsIcon,
  Upload,
} from "lucide-react";
import {
  activeProfile,
  defaultStore,
  loadStore,
  saveStore,
} from "@/lib/llmStore";
import {
  ConversationSummary,
  SkillSpec,
  deleteConversation,
  getChatHistory,
  getConversationEvents,
  getRegistry,
  listConversations,
} from "@/lib/api";
import type { AgentEvent, AskAnswer, LLMProfile } from "@/lib/types";
import { EMPTY_SEARCH } from "@/lib/types";
import { useChat } from "@/hooks/useChat";
import { SYSTEM_KEY, useAgentTimeline } from "@/hooks/useAgentTimeline";
import { AGENT_ORDER, deriveRunMeta, genRunId } from "@/lib/runMeta";
import { useAnalyzeRun } from "@/hooks/useAnalyzeRun";
import { PipelineProgress } from "@/components/PipelineProgress";
import { PipelineResultView } from "@/components/PipelineResult";
import { ChatPanel } from "@/components/ChatPanel";
import { ChatComposer } from "@/components/ChatComposer";
import { AgentStage } from "@/components/AgentStage";
import { ConversationSidebar } from "@/components/ConversationSidebar";
import { SettingsModal } from "@/components/SettingsModal";
import { WindowControls } from "@/components/WindowControls";
import { ConfirmHost } from "@/components/ConfirmDialog";
import { useDesktopBridge } from "@/lib/desktop";

type AppMode = "chat" | "pipeline";

export default function Home() {
  const [store, setStore] = useState(defaultStore);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [skills, setSkills] = useState<SkillSpec[]>([]);
  const [stageOpen, setStageOpen] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [stageWidth, setStageWidth] = useState(420);
  const [zoomKey, setZoomKey] = useState<string | null>(null);
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [activeRunId, setActiveRunId] = useState<string>("");
  /** 刚新建、尚未产生任何消息的对话（前端先占位显示在列表顶部） */
  const [pendingRunId, setPendingRunId] = useState<string | null>(null);
  const [appMode, setAppMode] = useState<AppMode>("chat");
  const [pipeFile, setPipeFile] = useState<File | null>(null);
  const [pipeDragOver, setPipeDragOver] = useState(false);
  const pipeFileRef = useRef<HTMLInputElement>(null);

  const timeline = useAgentTimeline();
  const analyzeRun = useAnalyzeRun();
  const profile = activeProfile(store);
  const connected = Boolean(profile?.apiKey?.trim());
  /** 桌面客户端（Electron）下顶栏同时充当窗口标题栏，Web 下为 null */
  const bridge = useDesktopBridge();

  useEffect(() => {
    void loadStore().then(setStore);
  }, []);

  // 拉一次能力目录：技能列表用于输入框的 `/` 命令提示
  useEffect(() => {
    void getRegistry()
      .then((c) => setSkills(c.skills))
      .catch(() => {});
  }, []);

  const updateStore = useCallback((next: typeof store) => {
    setStore(next);
    void saveStore(next);
  }, []);

  // 选中模型：以设置 store 为唯一真相源。
  // 模型属于哪个档案就激活哪个档案（连同它的 baseUrl/Key 一起生效）；
  // 全新模型归入当前档案。保证「设置 → 模型列表」与对话框下拉永远同一份。
  const selectModel = useCallback(
    (model: string) => {
      const m = model.trim();
      if (!m) return;
      const owns = (p: LLMProfile) =>
        p.model === m ||
        (p.fallbackModels || []).includes(m) ||
        (p.models || []).includes(m);
      const active = store.profiles.find((p) => p.id === store.activeId);
      // 1) 当前档案已拥有 → 仅把当前档案的 model 指过去
      if (active && owns(active)) {
        if (active.model !== m) {
          updateStore({
            ...store,
            profiles: store.profiles.map((p) =>
              p.id === active.id ? { ...p, model: m } : p,
            ),
          });
        }
        return;
      }
      // 2) 其他档案拥有 → 切换激活档案
      const owner = store.profiles.find((p) => p.id !== store.activeId && owns(p));
      if (owner) {
        updateStore({
          ...store,
          activeId: owner.id,
          profiles: store.profiles.map((p) =>
            p.id === owner.id ? { ...p, model: m } : p,
          ),
        });
      }
    },
    [store, updateStore],
  );

  const refreshConversations = useCallback(async () => {
    try {
      const data = await listConversations();
      setConversations(data.conversations);
    } catch {
      // silent
    }
  }, []);

  useEffect(() => {
    void refreshConversations();
  }, [refreshConversations]);

  const llmCfg = useCallback(() => {
    if (!profile) return null;
    return {
      provider: profile.provider,
      model: profile.model,
      apiKey: profile.apiKey,
      baseUrl: profile.baseUrl,
      fallbackModels: profile.fallbackModels,
      search: store.search ?? { ...EMPTY_SEARCH },
    };
  }, [profile, store.search]);

  const chat = useChat({
    llm: llmCfg,
    onEvent: timeline.push,
  });

  /** 进入建模模式。
   *  - 已有建模结果/过程 → 只切模式，不 reset，避免来回切换清空
   *  - 尚无建模状态 → 新开独立会话占位
   */
  const enterPipelineMode = useCallback(() => {
    const hasPipeline =
      Boolean(analyzeRun.result) ||
      Object.keys(analyzeRun.nodes).length > 0 ||
      Boolean(analyzeRun.runId) ||
      analyzeRun.running;

    setAppMode("pipeline");
    setStageOpen(true);
    setZoomKey(null);

    if (hasPipeline) {
      // 恢复到该次建模的 run_id，协作面板继续显示过程
      if (analyzeRun.runId) {
        setActiveRunId(analyzeRun.runId);
        setPendingRunId(analyzeRun.runId);
      }
      return;
    }

    const newId = genRunId();
    chat.reset(newId);
    setActiveRunId(newId);
    setPendingRunId(newId);
  }, [analyzeRun, chat]);

  const enterChatMode = useCallback(() => {
    setAppMode("chat");
    // 保留建模状态；协作面板切回当前聊天 run（若有）
    setZoomKey(null);
    if (chat.runId) {
      setActiveRunId(chat.runId);
    }
  }, [chat.runId]);

  /** 建模事件：推进流水线进度 + 写入协作面板；首事件绑定 run_id 为当前会话 */
  const onAnalyzeEvent = useCallback(
    (ev: AgentEvent) => {
      timeline.push(ev);
      if (ev.run_id && ev.run_id !== activeRunId) {
        // 后端生成的 run_id 与侧栏占位对齐，协作面板才能显示该次过程
        setActiveRunId(ev.run_id);
        setPendingRunId(ev.run_id);
      }
    },
    [activeRunId, timeline],
  );

  const runPipelineDemo = useCallback(() => {
    const llm = llmCfg();
    if (!llm) {
      setSettingsOpen(true);
      return;
    }
    setStageOpen(true);
    setAppMode("pipeline");
    void analyzeRun.run({
      demo: true,
      llm,
      onEvent: onAnalyzeEvent,
    });
  }, [analyzeRun, llmCfg, onAnalyzeEvent]);

  const runPipelineFile = useCallback(() => {
    const llm = llmCfg();
    if (!llm) {
      setSettingsOpen(true);
      return;
    }
    if (!pipeFile) return;
    setStageOpen(true);
    setAppMode("pipeline");
    void analyzeRun.run({
      file: pipeFile,
      llm,
      onEvent: onAnalyzeEvent,
    });
  }, [analyzeRun, llmCfg, onAnalyzeEvent, pipeFile]);

  // 仅在聊天模式下把 chat.runId 同步到页面级 activeRunId，
  // 避免建模运行时被聊天 hook 的 id 覆盖协作面板分桶。
  useEffect(() => {
    if (appMode === "chat" && chat.runId) {
      setActiveRunId(chat.runId);
    }
  }, [appMode, chat.runId]);

  // 建模运行结束后刷新侧栏（若后端写了 checkpoint/runs）
  useEffect(() => {
    if (!analyzeRun.running && analyzeRun.result) {
      void refreshConversations();
    }
  }, [analyzeRun.running, analyzeRun.result, refreshConversations]);

  const handleSend = useCallback(
    async (text: string, files: File[], model: string) => {
      // 注意：不要在这里 reset timeline —— 同一对话内多轮应累积显示，
      // 只有「新对话 / 切换对话」才 reset（见 handleNewConversation / handleSelectConversation）
      await chat.send(text, files, model);
      // 新对话首次发送会拿到 run_id；刷新列表让标题/时间更新
      void refreshConversations();
    },
    [chat, refreshConversations],
  );

  const handleAbort = useCallback(() => {
    chat.abort();
  }, [chat]);

  const handleAnswer = useCallback(
    (answers: AskAnswer[]) => {
      void chat.submitAnswer(answers);
    },
    [chat],
  );

  const handleSkipAsk = useCallback(() => {
    void chat.skipAsk();
  }, [chat]);

  const handleNewConversation = useCallback(() => {
    setAppMode("chat");
    const newId = genRunId();
    // 预生成 runId：新建后立刻出现在列表里，首条消息直接用这个 id 落盘
    chat.reset(newId);
    // 不清 timeline：其他对话的协作面板数据要保留，切换回去还能看到
    setActiveRunId(newId);
    setPendingRunId(newId);
    setZoomKey(null);
  }, [chat]);

  const handleSelectConversation = useCallback(
    async (runId: string) => {
      // 点侧栏会话一律进入对话形态（建模用独立入口，不与会话混用）
      setAppMode("chat");
      if (runId === activeRunId && chat.runId === runId) {
        setZoomKey(null);
        return;
      }
      // 离开未使用的草稿对话 → 丢弃占位
      setPendingRunId((prev) => (prev && prev !== runId ? null : prev));

      const { messages, title } = await getChatHistory(runId);
      // 事件流始终拉取：既用于还原思考/轮数等元信息，也用于重建协作面板
      const { events } = await getConversationEvents(runId);
      const meta = deriveRunMeta(events);

      chat.loadConversation(runId, messages, { ...meta, title });
      setActiveRunId(runId);
      setZoomKey(null);

      // 本地还没有该对话的协作事件（如刷新过页面）→ 回放重建协作面板
      if (!timeline.store[runId]) {
        for (const ev of events) timeline.push(ev);
        // 历史对话已结束：统一收敛残留的「进行中」相位
        timeline.finalize(runId);
      }
    },
    [activeRunId, chat, timeline],
  );

  const handleDeleteConversation = useCallback(
    async (runId: string) => {
      await deleteConversation(runId);
      timeline.reset(runId); // 该对话已删除，清掉它那份协作数据
      setPendingRunId((prev) => (prev === runId ? null : prev));
      if (runId === activeRunId || runId === chat.runId) {
        chat.reset();
        setActiveRunId("");
      }
      await refreshConversations();
    },
    [activeRunId, chat, refreshConversations, timeline],
  );

  /** 右侧协作面板拖拽调宽 */
  const handleStageDragStart = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      const startX = e.clientX;
      const startW = stageWidth;
      const prevSelect = document.body.style.userSelect;
      const prevCursor = document.body.style.cursor;
      document.body.style.userSelect = "none";
      document.body.style.cursor = "col-resize";
      const onMove = (ev: MouseEvent) => {
        const delta = startX - ev.clientX; // 向左拖 → 变宽
        const max = Math.max(360, window.innerWidth - 520);
        setStageWidth(Math.min(Math.max(startW + delta, 300), max));
      };
      const onUp = () => {
        document.body.style.userSelect = prevSelect;
        document.body.style.cursor = prevCursor;
        window.removeEventListener("mousemove", onMove);
        window.removeEventListener("mouseup", onUp);
      };
      window.addEventListener("mousemove", onMove);
      window.addEventListener("mouseup", onUp);
    },
    [stageWidth],
  );

  // 当前对话对应的协作面板数据（按 run_id 分桶）
  const activeAgents = timeline.store[activeRunId] ?? {};

  // 列表 = 服务端对话 + 尚未落盘的「新对话/建模」占位。
  // 智能体在对话过程中调用 set_conversation_title 时，title 事件先于列表刷新到达，
  // 这里用实时标题覆盖列表项，避免侧边栏要等本轮跑完才改名。
  const displayConversations = useMemo<ConversationSummary[]>(() => {
    const applyLiveTitle = (list: ConversationSummary[]) =>
      chat.title && appMode === "chat"
        ? list.map((c) =>
            c.run_id === activeRunId ? { ...c, title: chat.title } : c,
          )
        : list;

    if (pendingRunId && !conversations.some((c) => c.run_id === pendingRunId)) {
      return applyLiveTitle([
        {
          run_id: pendingRunId,
          title:
            appMode === "pipeline" || analyzeRun.running
              ? "一键建模"
              : "新对话",
          updated_at: Date.now(),
          message_count: 0,
        },
        ...conversations,
      ]);
    }
    return applyLiveTitle(conversations);
  }, [
    conversations,
    pendingRunId,
    chat.title,
    activeRunId,
    appMode,
    analyzeRun.running,
  ]);

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-base-200">
      <ConfirmHost />
      {/* ---------- 顶栏（桌面端同时也是窗口标题栏：整条可拖动） ---------- */}
      <header
        className={[
          bridge ? "app-drag" : "",
          "flex shrink-0 items-center justify-between gap-3 border-b border-base-300 bg-base-100 px-3 py-2",
        ]
          .filter(Boolean)
          .join(" ")}
      >
        <div className="flex min-w-0 items-center gap-2.5">
          <button
            onClick={() => setSidebarOpen((v) => !v)}
            className="app-no-drag btn btn-ghost btn-xs h-7 w-7 min-h-0 shrink-0 p-0"
            title={sidebarOpen ? "收起对话列表" : "展开对话列表"}
          >
            {sidebarOpen ? (
              <PanelLeftClose className="h-4 w-4" />
            ) : (
              <PanelLeftOpen className="h-4 w-4" />
            )}
          </button>

          <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-[var(--radius-field)] border border-base-300 bg-base-200 text-[14px] font-bold text-base-content/90">
            W
          </span>
          <div className="min-w-0 leading-tight">
            <h1 className="truncate text-[14px] font-semibold tracking-tight text-base-content">
              Weister
            </h1>
          </div>
        </div>

        <div className="flex shrink-0 items-center gap-1.5">
          {connected ? (
            <span className="badge badge-sm badge-outline hidden max-w-[240px] gap-1.5 md:inline-flex">
              <span className="truncate">{profile!.name}</span>
              <span className="truncate font-mono text-base-content/90">
                {profile!.model || "—"}
              </span>
            </span>
          ) : (
            <button
              onClick={() => setSettingsOpen(true)}
              className="btn btn-xs gap-1 border-warning/40 bg-warning/[0.08] text-warning"
            >
              未配置模型，点击设置
            </button>
          )}

          <button
            onClick={handleNewConversation}
            disabled={chat.running}
            className="btn btn-xs gap-1 border-base-300 bg-base-100 text-base-content/90"
            title="新对话"
          >
            <MessageSquarePlus className="h-3 w-3" />
            新对话
          </button>

          <button
            onClick={() => setStageOpen((v) => !v)}
            className={`btn btn-xs gap-1 border-base-300 ${
              stageOpen ? "bg-base-200 text-base-content" : "bg-base-100 text-base-content/90"
            }`}
            title="智能体协作详情"
          >
            {stageOpen ? (
              <PanelRightClose className="h-3 w-3" />
            ) : (
              <PanelRightOpen className="h-3 w-3" />
            )}
            协作
            {Object.keys(activeAgents).length > 0 && (
              <span className="badge badge-sm badge-primary badge-outline">
                {Object.keys(activeAgents).length}
              </span>
            )}
          </button>

          <button
            onClick={() => setSettingsOpen(true)}
            className="btn btn-xs gap-1 border-base-300 bg-base-100 text-base-content/90"
            title="设置"
          >
            <SettingsIcon className="h-3 w-3" />
            设置
          </button>

          <div className="join ml-1">
            <button
              type="button"
              onClick={enterChatMode}
              className={`btn btn-xs join-item gap-1 border-base-300 ${
                appMode === "chat" ? "bg-primary text-primary-content" : "bg-base-100 text-base-content/90"
              }`}
              title="自由对话（主管调度专家）"
            >
              <MessagesSquare className="h-3 w-3" />
              对话
            </button>
            <button
              type="button"
              onClick={() => {
                if (appMode !== "pipeline") enterPipelineMode();
              }}
              className={`btn btn-xs join-item gap-1 border-base-300 ${
                appMode === "pipeline"
                  ? "bg-primary text-primary-content"
                  : "bg-base-100 text-base-content/90"
              }`}
              title="一键建模流水线（六节点 DAG，独立会话）"
            >
              <FlaskConical className="h-3 w-3" />
              建模
            </button>
          </div>

          <span
            className={`badge badge-sm gap-1.5 ${
              chat.running || analyzeRun.running
                ? "badge-primary badge-outline"
                : "badge-ghost"
            }`}
          >
            <span
              className={`status status-xs ${
                chat.running || analyzeRun.running
                  ? "status-primary animate-pulse"
                  : "status-neutral"
              }`}
            />
            {appMode === "pipeline"
              ? analyzeRun.running
                ? "流水线执行中"
                : "就绪"
              : chat.running
                ? chat.pendingAsk
                  ? "等待选择"
                  : chat.activeAgent
                    ? `${chat.activeAgent} 处理中`
                    : "运行中"
                : "就绪"}
          </span>

          {/* 窗口三按钮嵌在顶栏右端，与设置等控件同一条栏 */}
          <WindowControls />
        </div>
      </header>

      {/* ---------- 主区 ---------- */}
      <div className="flex min-h-0 min-w-0 flex-1 overflow-hidden">
        {sidebarOpen && (
          <ConversationSidebar
            conversations={displayConversations}
            activeId={activeRunId}
            onSelect={handleSelectConversation}
            onNew={handleNewConversation}
            onDelete={handleDeleteConversation}
          />
        )}

        <div className="flex min-h-0 min-w-0 flex-1 flex-col gap-2.5 p-2.5">
          {appMode === "pipeline" ? (
            <div
              className={`relative flex min-h-0 flex-1 flex-col overflow-hidden rounded-[var(--radius-box)] border bg-base-100 transition-colors ${
                pipeDragOver ? "border-primary border-dashed bg-primary/[0.04]" : "border-base-300"
              }`}
              onDragOver={(e) => {
                if (analyzeRun.running) return;
                if (Array.from(e.dataTransfer.types).includes("Files")) {
                  e.preventDefault();
                  setPipeDragOver(true);
                }
              }}
              onDragLeave={(e) => {
                if (!e.currentTarget.contains(e.relatedTarget as Node)) setPipeDragOver(false);
              }}
              onDrop={(e) => {
                if (analyzeRun.running) return;
                const f = e.dataTransfer.files?.[0];
                if (f) {
                  e.preventDefault();
                  setPipeFile(f);
                }
                setPipeDragOver(false);
              }}
            >
              {pipeDragOver && (
                <div className="pointer-events-none absolute inset-0 z-20 flex items-center justify-center bg-primary/[0.04] text-[13px] font-medium text-primary">
                  松开以上传财报文件（PDF / TXT / MD）
                </div>
              )}
              <PipelineProgress nodes={analyzeRun.nodes} running={analyzeRun.running} />
              <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-base-300 px-3 py-2">
                <input
                  ref={pipeFileRef}
                  type="file"
                  accept=".pdf,.txt,.md"
                  className="hidden"
                  onChange={(e) => setPipeFile(e.target.files?.[0] ?? null)}
                />
                <button
                  type="button"
                  onClick={() => pipeFileRef.current?.click()}
                  className="btn btn-xs gap-1 border-base-300 bg-base-200"
                  disabled={analyzeRun.running}
                >
                  <Upload className="h-3 w-3" />
                  {pipeFile ? pipeFile.name : "选择财报 PDF/TXT"}
                </button>
                <button
                  type="button"
                  onClick={runPipelineFile}
                  disabled={!pipeFile || analyzeRun.running || !connected}
                  className="btn btn-xs gap-1"
                >
                  <Play className="h-3 w-3" />
                  上传分析
                </button>
                <button
                  type="button"
                  onClick={runPipelineDemo}
                  disabled={analyzeRun.running || !connected}
                  className="btn btn-xs gap-1 border-base-300 bg-base-100"
                >
                  运行内置样例
                </button>
                {!connected && (
                  <span className="text-[14px] text-warning">请先配置模型 API Key</span>
                )}
              </div>
              <div className="min-h-0 flex-1 overflow-y-auto px-3 py-3">
                <PipelineResultView
                  reply={analyzeRun.reply}
                  result={analyzeRun.result}
                  running={analyzeRun.running}
                  error={analyzeRun.error}
                />
              </div>
            </div>
          ) : (
            <>
              <div className="min-h-0 flex-1">
                <ChatPanel
                  messages={chat.messages}
                  running={chat.running}
                  activeAgent={chat.activeAgent}
                  error={chat.error}
                  truncated={chat.truncated}
                  iterations={chat.iterations}
                  onAbort={handleAbort}
                  thinking={chat.thinking}
                  stalled={chat.stalled}
                  pendingAsk={chat.pendingAsk}
                  onAnswer={handleAnswer}
                  onSkipAsk={handleSkipAsk}
                />
              </div>
              <ChatComposer
                running={chat.running}
                onSend={handleSend}
                onStop={handleAbort}
                disabled={!profile || Boolean(chat.pendingAsk)}
                skills={skills}
                messages={chat.messages}
                profile={profile}
                profiles={store.profiles}
                onSelectModel={selectModel}
                runId={chat.runId}
              />
            </>
          )}
        </div>

        {stageOpen && (
          <div
            onMouseDown={handleStageDragStart}
            className="w-1.5 shrink-0 cursor-col-resize self-stretch transition-colors hover:bg-primary/40"
            title="拖动调整协作面板宽度"
          />
        )}
        {stageOpen && (
          <aside
            style={{ width: stageWidth }}
            className="mr-2.5 flex shrink-0 flex-col overflow-hidden rounded-[var(--radius-box)] border border-base-300 bg-base-100"
          >
            <div className="flex shrink-0 items-center justify-between gap-2 border-b border-base-300 px-3 py-2">
              <div className="flex items-center gap-1.5">
                <Bot className="h-3 w-3 text-base-content/90" />
                <h2 className="text-[14px] font-semibold tracking-wide text-base-content/90">
                  {appMode === "pipeline" ? "建模协作" : "智能体协作"}
                </h2>
                {chat.specialistsCalled.length > 0 && appMode === "chat" && (
                  <span className="font-mono text-[14px] text-base-content/90">
                    本轮调度 {chat.specialistsCalled.length} 位专家
                  </span>
                )}
                {appMode === "pipeline" && analyzeRun.runId && (
                  <span className="font-mono text-[14px] text-base-content/85">
                    run {analyzeRun.runId.slice(0, 8)}
                  </span>
                )}
              </div>
            </div>
            <div className="min-h-0 flex-1">
              <AgentStage
                agents={activeAgents}
                order={AGENT_ORDER}
                zoomKey={zoomKey}
                onZoom={setZoomKey}
              />
            </div>
          </aside>
        )}
      </div>

      <SettingsModal
        open={settingsOpen}
        store={store}
        onChange={updateStore}
        onClose={() => setSettingsOpen(false)}
      />
    </div>
  );
}