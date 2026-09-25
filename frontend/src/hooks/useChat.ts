"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { AgentEvent, AskAnswer, PendingAsk } from "@/lib/types";
import {
  ChatMessage,
  answerQuestion,
  chat as chatApi,
  ChatAttachmentMeta,
  filesToPreviews,
} from "@/lib/api";
import { formatDetail } from "@/hooks/useAgentTimeline";

/** 工具入参 / 返回值 → 可展示文本。超长截断，避免把整份财报结果塞进 DOM。 */
function stringifyDetail(value: unknown): string | undefined {
  const { text } = formatDetail(value);
  return text || undefined;
}

interface UseChatOptions {
  llm: () => { provider: string; model: string; apiKey: string; baseUrl: string; fallbackModels?: string[] } | null;
  /**
   * Secondary sink for raw events. UI 的 chat 流已经通过 handleEvent 处理过，
   * 这里再暴露一份给比如 AgentStage 这种观察面板。
   */
  onEvent?: (event: AgentEvent) => void;
}

function extractTextContent(content: unknown): string {
  if (typeof content === "string") return content;
  if (Array.isArray(content)) {
    return content
      .map((p) => (typeof p === "object" && p && "text" in p ? String((p as { text?: unknown }).text || "") : ""))
      .filter(Boolean)
      .join(" ");
  }
  return "";
}

/** 从多模态 content 数组里抽出图片（后端消息不带 images 字段） */
function extractImagesFromContent(content: unknown) {
  if (!Array.isArray(content)) return undefined;
  const imgs = content
    .filter(
      (p) => typeof p === "object" && p !== null &&
        (p as { type?: string }).type === "image_url",
    )
    .map((p) => {
      const url = (p as { image_url?: { url?: string } }).image_url?.url;
      return { url: String(url || ""), mime: "", name: "" };
    })
    .filter((i) => i.url);
  return imgs.length ? imgs : undefined;
}

/** 后端落盘的是 OpenAI 风格消息，缺 id/createdAt/by 等 UI 字段；切对话时补全 */
function normalizeMessages(raw: unknown[], prefix: string): ChatMessage[] {
  let counter = 0;
  return raw
    // internal 消息是系统写给模型看的（如「主管回复只有确认，请重新决策」的重决策
    // 指令），不是用户说过的话，不能在聊天流里渲染出来
    .filter((m: unknown) => !(m as { internal?: boolean } | null)?.internal)
    .map((m: unknown) => {
      const msg = (m || {}) as Partial<ChatMessage> & {
        content?: unknown;
        display_text?: unknown;
      };
      counter += 1;
      const role = msg.role || "system";
      // 后端把「给模型看的 content」和「给人看的 display_text」分开存：
      // 展示优先用 display_text，避免把注入的文档正文当作消息正文显示出来
      const display =
        typeof msg.display_text === "string"
          ? msg.display_text
          : extractTextContent(msg.content);
      return {
        id: msg.id || `${prefix}${counter}`,
        role,
        content: display,
        by: msg.by,
        images: msg.images ?? extractImagesFromContent(msg.content),
        attachments: msg.attachments,
        createdAt: msg.createdAt || 0,
      } as ChatMessage;
    });
}

export function useChat(opts: UseChatOptions) {
  const sinkEvent = opts.onEvent;
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [runId, setRunId] = useState<string>("");
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeAgent, setActiveAgent] = useState<string | null>(null);
  const [truncated, setTruncated] = useState(false);
  const [iterations, setIterations] = useState(0);
  const [specialistsCalled, setSpecialistsCalled] = useState<string[]>([]);
  /** 模型推理过程（thinking/reasoning 流），实时累积用于展示 */
  const [thinking, setThinking] = useState<string>("");
  /** 运行中超过阈值没有收到任何事件 —— 用于提示"仍在等待模型" */
  const [stalled, setStalled] = useState(false);
  /** 智能体发出的待答问题（ask_user）；非空时聊天区展示选项卡片并阻塞输入框 */
  const [pendingAsk, setPendingAsk] = useState<PendingAsk | null>(null);
  /** 智能体为对话设置的标题（title 事件），同步到侧边栏 */
  const [title, setTitle] = useState<string>("");
  const lastEventAtRef = useRef(0);
  const pendingAskRef = useRef<PendingAsk | null>(null);
  pendingAskRef.current = pendingAsk;

  const abortRef = useRef<AbortController | null>(null);
  const idCounterRef = useRef(0);

  const nextId = useCallback(() => {
    idCounterRef.current += 1;
    return `m${idCounterRef.current}`;
  }, []);

  // 运行期间若长时间收不到任何事件，标记 stalled，让 UI 明确提示"仍在等待"。
  // 等待用户作答期间后端本就阻塞在提问上，此时不应提示「无响应」。
  useEffect(() => {
    if (!running) {
      setStalled(false);
      return;
    }
    lastEventAtRef.current = Date.now();
    const timer = setInterval(() => {
      if (pendingAskRef.current) return;
      if (Date.now() - lastEventAtRef.current > 20000) setStalled(true);
    }, 2000);
    return () => clearInterval(timer);
  }, [running]);

  /** 把一条新消息追加到末尾，保留之前的引用（无变化时）以减少重渲染 */
  const appendMessage = useCallback((msg: ChatMessage) => {
    setMessages((prev) => [...prev, msg]);
  }, []);

  /** 流式更新最后一条 assistant 消息（追加内容） */
  const appendTokenToLast = useCallback((token: string) => {
    setMessages((prev) => {
      if (prev.length === 0) return prev;
      const next = prev.slice();
      const last = next[next.length - 1];
      if (last.role !== "assistant") {
        next.push({
          id: nextId(),
          role: "assistant",
          content: token,
          createdAt: Date.now(),
          streaming: true,
        });
        return next;
      }
      next[next.length - 1] = { ...last, content: last.content + token, streaming: true };
      return next;
    });
  }, [nextId]);

  /** 标记最后一条 assistant 消息流式结束 */
  const sealLastAssistant = useCallback(() => {
    setMessages((prev) => {
      if (prev.length === 0) return prev;
      const next = prev.slice();
      const last = next[next.length - 1];
      if (last.role !== "assistant") return prev;
      next[next.length - 1] = { ...last, streaming: false };
      return next;
    });
  }, []);

  const handleEvent = useCallback(
    (event: AgentEvent) => {
      const payload = event.payload ?? {};
      const message = event.message ?? "";
      lastEventAtRef.current = Date.now();
      setStalled(false);

      switch (event.type) {
        case "run_start": {
          if (event.run_id) setRunId(event.run_id);
          setTruncated(false);
          setIterations(0);
          setSpecialistsCalled([]);
          setThinking("");
          setError(null);
          setPendingAsk(null);
          break;
        }
        case "agent_start": {
          const agent = typeof payload.agent === "string" ? payload.agent : null;
          if (agent) setActiveAgent(agent);
          // 换 agent 就重新开始收集思考过程，展示当前这一步的推理
          setThinking("");
          // supervisor（coordinator）的输出是内部决策 JSON，不占聊天流
          if (agent === "coordinator") break;
          // 在聊天流中插入一个空 assistant 消息，用于接收 token。
          // 仅复用「仍在流式中」的占位消息；已 seal 的上一轮气泡不复用，
          // 否则第二位专家会把内容追加到第一位专家的气泡里。
          setMessages((prev) => {
            const last = prev[prev.length - 1];
            if (last && last.role === "assistant" && last.streaming) {
              return prev;
            }
            if (last && last.role === "assistant" && !last.content.trim()) {
              // 空气泡（未产出内容）直接复用，避免留下空气泡
              return prev;
            }
            const name = typeof payload.name === "string" ? payload.name : agent ?? "智能体";
            return [
              ...prev,
              {
                id: nextId(),
                role: "assistant",
                content: "",
                by: name,
                createdAt: Date.now(),
                streaming: true,
              },
            ];
          });
          break;
        }
        case "agent_end": {
          const agent = typeof payload.agent === "string" ? payload.agent : null;
          if (agent !== "coordinator") sealLastAssistant();
          setActiveAgent(null);
          break;
        }
        case "token": {
          // supervisor 的 token 是决策 JSON，不进聊天流
          const tokenAgent = typeof payload.agent === "string" ? payload.agent : null;
          if (tokenAgent === "coordinator") break;
          appendTokenToLast(message);
          break;
        }
        case "thinking": {
          // 累积模型推理过程，用于在界面上实时展示"思考内容"
          if (message) setThinking((prev) => prev + message);
          break;
        }
        case "log": {
          // 系统日志：可选择性显示（如"主管调度：估值专家"）
          if (message && message.length < 200) {
            appendMessage({
              id: nextId(),
              role: "system",
              content: message,
              createdAt: Date.now(),
            });
          }
          break;
        }
        case "tool_call": {
          // 工具调用合并为一条 system 消息，入参放进折叠区
          const tool = message.replace(/^tool:\s*/, "");
          appendMessage({
            id: nextId(),
            role: "tool",
            content: tool,
            toolDetail: stringifyDetail(payload.input),
            createdAt: Date.now(),
          });
          break;
        }
        case "tool_result": {
          const ok = payload.ok !== false;
          const tool = typeof payload.tool === "string" ? payload.tool : "";
          appendMessage({
            id: nextId(),
            role: "tool",
            content: `${tool} · ${ok ? "完成" : "失败"}`,
            toolOk: ok,
            // 失败时 result 恒为 null，原因在 error 字段
            toolDetail: stringifyDetail(ok ? payload.result : payload.error),
            createdAt: Date.now(),
          });
          break;
        }
        case "ask_user": {
          const qid = typeof payload.qid === "string" ? payload.qid : "";
          const questions = payload.questions;
          if (!qid || !Array.isArray(questions) || questions.length === 0) break;
          setPendingAsk({
            qid,
            title: typeof payload.title === "string" ? payload.title : "需要确认几个问题",
            total: questions.length,
            questions: questions as PendingAsk["questions"],
          });
          break;
        }
        case "title": {
          const next =
            typeof payload.title === "string" ? payload.title : message;
          if (next) setTitle(next);
          break;
        }
        case "error": {
          setError(message || "运行失败");
          break;
        }
        case "result": {
          const result = payload as {
            reply?: string;
            iterations?: number;
            truncated?: boolean;
            specialists_called?: string[];
            messages?: ChatMessage[];
          };
          if (typeof result.iterations === "number") setIterations(result.iterations);
          if (typeof result.truncated === "boolean") setTruncated(result.truncated);
          if (Array.isArray(result.specialists_called))
            setSpecialistsCalled(result.specialists_called);
          // 用后端最终 messages 覆盖前端构造的中间流（补全 UI 字段）
          if (Array.isArray(result.messages)) {
            setMessages(normalizeMessages(result.messages, "m"));
          }
          break;
        }
        default:
          break;
      }
      sinkEvent?.(event);
    },
    [appendMessage, appendTokenToLast, sealLastAssistant, nextId, sinkEvent],
  );

  const send = useCallback(
    async (text: string, files: File[], modelOverride?: string) => {
    const cfg = opts.llm();
    if (!cfg) {
      setError("请先在设置中配置模型");
      return;
    }

      // 若用户在输入区切换了模型，本次发送用覆盖后的配置
      const llm = modelOverride ? { ...cfg, model: modelOverride } : cfg;

      // 先把 user 消息插入到流中（带附件预览）
      const id = nextId();
      const previews = await filesToPreviews(files);
      const userMsg: ChatMessage = {
        id,
        role: "user",
        content: text,
        images: previews.filter((p) => p.mime.startsWith("image/") && p.url),
        attachments: previews
          .filter((p) => !p.mime.startsWith("image/"))
          .map((p) => ({ name: p.name, mime: p.mime })),
        createdAt: Date.now(),
      };
      appendMessage(userMsg);

      const meta: ChatAttachmentMeta[] = previews.map((p, i) => ({
        id: `f${i}`,
        name: p.name,
        mime: p.mime,
      }));

      setRunning(true);
      setError(null);
      abortRef.current = new AbortController();

      try {
        await chatApi({
          message: text,
          attachments: meta,
          files,
          runId,
          llm,
          signal: abortRef.current.signal,
          onEvent: handleEvent,
        });
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        if (!msg.toLowerCase().includes("abort")) setError(msg);
      } finally {
        setRunning(false);
        setActiveAgent(null);
      }
    },
    [opts, runId, handleEvent, appendMessage, nextId],
  );

  /** 提交作答：写回后端唤醒阻塞中的智能体，并清空卡片 */
  const submitAnswer = useCallback(
    async (answers: AskAnswer[], note = "") => {
      const ask = pendingAskRef.current;
      if (!ask) return;
      setPendingAsk(null);
      try {
        await answerQuestion(ask.qid, answers, note);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    },
    [],
  );

  /** 跳过作答：交回「无选择」，由智能体自行采用默认口径继续 */
  const skipAsk = useCallback(async () => {
    const ask = pendingAskRef.current;
    if (!ask) return;
    const note = "用户跳过本次询问，请自行采用最合理的默认口径并说明假设。";
    const blank: AskAnswer[] = ask.questions.map(() => ({
      selected: [],
      other: "",
    }));
    await submitAnswer(blank, note);
  }, [submitAnswer]);

  const abort = useCallback(() => {
    abortRef.current?.abort();
    setPendingAsk(null);
  }, []);

  /** 清空当前对话状态。可传入一个预生成的 runId（新建对话时用，
      这样前端能立刻把它显示在对话列表里，不必等后端返回）。 */
  const reset = useCallback((nextRunId: string = "") => {
    abortRef.current?.abort();
    setMessages([]);
    setRunId(nextRunId);
    setRunning(false);
    setError(null);
    setActiveAgent(null);
    setTruncated(false);
    setIterations(0);
    setSpecialistsCalled([]);
    setThinking("");
    setPendingAsk(null);
    setTitle("");
    idCounterRef.current = 0;
  }, []);

  /** 外部切到指定对话：重置运行态并灌入历史消息（含从事件流还原的元信息） */
  const loadConversation = useCallback(
    (
      runId: string,
      history: ChatMessage[],
      meta?: {
        thinking?: string;
        specialistsCalled?: string[];
        iterations?: number;
        truncated?: boolean;
        title?: string;
      },
    ) => {
    abortRef.current?.abort();
    setRunId(runId);
    const normalized = normalizeMessages(history, "h");
    setMessages(normalized);
    setRunning(false);
    setError(null);
    setActiveAgent(null);
    setTruncated(meta?.truncated ?? false);
    setIterations(meta?.iterations ?? 0);
    setSpecialistsCalled(meta?.specialistsCalled ?? []);
    setThinking(meta?.thinking ?? "");
    setPendingAsk(null);
    setTitle(meta?.title ?? "");
    const maxId = normalized.reduce((m, msg) => {
      const n = parseInt(String(msg.id).replace(/^[mh]/, ""), 10);
      return Number.isNaN(n) ? m : Math.max(m, n);
    }, 0);
    idCounterRef.current = maxId;
  }, []);

  /** 外部切换对话后同步 runId */
  const setRunIdExternal = useCallback((runId: string) => {
    setRunId(runId);
  }, []);

  return {
    messages,
    runId,
    running,
    error,
    activeAgent,
    truncated,
    iterations,
    specialistsCalled,
    thinking,
    stalled,
    pendingAsk,
    title,
    send,
    abort,
    reset,
    loadConversation,
    submitAnswer,
    skipAsk,
    setRunId: setRunIdExternal,
  };
}