"use client";

import { useCallback, useRef, useState } from "react";
import type {
  AgentEvent,
  AgentRun,
  AskAnswer,
  FinalResult,
  ProviderCatalog,
  SearchConfig,
} from "./types";

/**
 * 后端 API 基地址。
 *
 * 桌面客户端下由 preload 注入 window.WEISTER.API_BASE（主进程动态分配端口后
 * 在运行时设置）——端口冲突时无需重新构建前端。
 * 浏览器开发模式下回退到 NEXT_PUBLIC_API_BASE 或默认 8000 端口。
 */
const API_BASE: string =
  (typeof window !== "undefined" && (window as { WEISTER?: { API_BASE?: string } }).WEISTER?.API_BASE) ||
  process.env.NEXT_PUBLIC_API_BASE ||
  "http://127.0.0.1:8000";

export interface LLMConfig {
  provider: string;
  model: string;
  fallbackModels?: string[];
  apiKey: string;
  baseUrl: string;
  /** 搜索源配置：随请求头发给后端，后端优先于 .env 使用 */
  search?: SearchConfig;
}

function credentialHeaders(llm: LLMConfig): Record<string, string> {
  const headers: Record<string, string> = {
    "X-LLM-Provider": llm.provider || "deepseek",
  };
  if (llm.model) headers["X-LLM-Model"] = llm.model;
  if (llm.fallbackModels?.length) {
    headers["X-LLM-Fallback-Models"] = llm.fallbackModels.join(",");
  }
  if (llm.apiKey) headers["X-LLM-Api-Key"] = llm.apiKey;
  if (llm.baseUrl) headers["X-LLM-Base-Url"] = llm.baseUrl;

  const s = llm.search;
  if (s?.tavilyApiKey) headers["X-Search-Tavily-Key"] = s.tavilyApiKey;
  if (s?.bochaApiKey) headers["X-Search-Bocha-Key"] = s.bochaApiKey;
  if (s?.searxngUrl) headers["X-Search-Searxng-Url"] = s.searxngUrl;
  return headers;
}

async function consumeStream(
  body: ReadableStream<Uint8Array>,
  onEvent: (event: AgentEvent) => void,
): Promise<void> {
  const reader = body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let idx: number;
    while ((idx = buffer.indexOf("\n\n")) !== -1) {
      const frame = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      const dataLine = frame.split("\n").find((l) => l.startsWith("data: "));
      if (!dataLine) continue;
      try {
        onEvent(JSON.parse(dataLine.slice(6)) as AgentEvent);
      } catch {
        /* ignore */
      }
    }
  }
}

export interface AnalyzeOptions {
  file?: File;
  question?: string;
  demo?: boolean;
  llm: LLMConfig;
  signal?: AbortSignal;
  onEvent: (event: AgentEvent) => void;
}

export async function analyze({
  file,
  question,
  demo,
  llm,
  signal,
  onEvent,
}: AnalyzeOptions): Promise<void> {
  const headers = credentialHeaders(llm);
  let url: string;
  let init: RequestInit;

  if (demo) {
    url = `${API_BASE}/api/analyze/demo`;
    init = { method: "GET", headers, signal };
  } else {
    url = `${API_BASE}/api/analyze`;
    const form = new FormData();
    if (file) form.append("file", file);
    form.append(
      "question",
      question ?? "请分析该公司本期经营与财务表现，并给出估值区间。",
    );
    init = { method: "POST", headers, body: form, signal };
  }

  const resp = await fetch(url, init);
  if (!resp.ok || !resp.body) {
    throw new Error(`请求失败：${resp.status} ${resp.statusText}`);
  }
  await consumeStream(resp.body, onEvent);
}

export interface ProbeParams {
  provider: string;
  baseUrl: string;
  apiKey: string;
}

export interface ProbeResult {
  model: string;
  ok: boolean;
  error?: string;
}

export async function listModels({
  provider,
  baseUrl,
  apiKey,
}: ProbeParams): Promise<{ base_url: string; models: string[] }> {
  const resp = await fetch(`${API_BASE}/api/models`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-LLM-Provider": provider || "deepseek",
      "X-LLM-Api-Key": apiKey,
      ...(baseUrl ? { "X-LLM-Base-Url": baseUrl } : {}),
    },
    body: JSON.stringify({ provider, base_url: baseUrl, mode: "list" }),
  });
  if (!resp.ok) {
    const detail = await resp.text();
    throw new Error(detail.slice(0, 300) || `HTTP ${resp.status}`);
  }
  return resp.json();
}

export async function probeModels(
  params: ProbeParams,
  models: string[],
): Promise<{ base_url: string; results: ProbeResult[] }> {
  const resp = await fetch(`${API_BASE}/api/models`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-LLM-Provider": params.provider || "deepseek",
      "X-LLM-Api-Key": params.apiKey,
      ...(params.baseUrl ? { "X-LLM-Base-Url": params.baseUrl } : {}),
    },
    body: JSON.stringify({
      provider: params.provider,
      base_url: params.baseUrl,
      models,
      mode: "probe",
    }),
  });
  if (!resp.ok) {
    const detail = await resp.text();
    throw new Error(detail.slice(0, 300) || `HTTP ${resp.status}`);
  }
  return resp.json();
}

export interface RunSummary {
  run_id: string;
  filename: string;
  finished: boolean;
  stage: string | null;
  completed_nodes: string[];
  updated_at: number;
}

export async function listRuns(limit = 20): Promise<{ runs: RunSummary[] }> {
  const resp = await fetch(`${API_BASE}/api/runs?limit=${limit}`);
  if (!resp.ok) throw new Error("获取运行列表失败");
  return resp.json();
}

export async function latestRun(): Promise<{ checkpoint: unknown | null }> {
  const resp = await fetch(`${API_BASE}/api/runs/latest`);
  if (!resp.ok) throw new Error("获取最新检查点失败");
  return resp.json();
}

export async function deleteRun(runId: string): Promise<void> {
  await fetch(`${API_BASE}/api/runs/${runId}`, { method: "DELETE" });
}

export async function analyzeResume(
  runId: string,
  llm: LLMConfig,
  signal: AbortSignal | undefined,
  onEvent: (event: AgentEvent) => void,
): Promise<void> {
  const resp = await fetch(
    `${API_BASE}/api/analyze/resume?run_id=${encodeURIComponent(runId)}`,
    {
      method: "GET",
      headers: credentialHeaders(llm),
      signal,
    },
  );
  if (!resp.ok || !resp.body) {
    throw new Error(`恢复失败：${resp.status} ${resp.statusText}`);
  }
  await consumeStream(resp.body, onEvent);
}

export async function getProviders(): Promise<ProviderCatalog> {
  const resp = await fetch(`${API_BASE}/api/providers`);
  if (!resp.ok) throw new Error("获取提供商列表失败");
  return resp.json();
}

export interface SearchTestResult {
  ok: boolean;
  provider: string | null;
  count: number;
  error?: string;
  sample?: { title: string; url: string; snippet: string }[];
}

/** 用给定配置真跑一次搜索，验证 Key 能不能用 */
export async function testSearch(
  cfg: SearchConfig,
  query = "贵州茅台 最新公告",
): Promise<SearchTestResult> {
  const resp = await fetch(`${API_BASE}/api/search/test`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...cfg, query }),
  });
  if (!resp.ok) {
    throw new Error((await resp.text()).slice(0, 200) || `HTTP ${resp.status}`);
  }
  return resp.json();
}

export async function health(): Promise<{ ok: boolean; version: string }> {
  const resp = await fetch(`${API_BASE}/api/health`);
  if (!resp.ok) throw new Error("健康检查失败");
  return resp.json();
}

/* ---------------- 聊天形态 ---------------- */

export interface ChatAttachmentMeta {
  id: string;
  name: string;
  mime: string;
  /** 文本类附件的正文（发送前供后端精确计入上下文；PDF/Word 等无法在浏览器端解析则不传） */
  text?: string;
}

export interface ChatOptions {
  message: string;
  attachments: ChatAttachmentMeta[];
  files: File[];
  runId: string;
  llm: LLMConfig;
  signal?: AbortSignal;
  onEvent: (event: AgentEvent) => void;
}

/** 调用 /api/chat 流式接口 */
export async function chat({
  message,
  attachments,
  files,
  runId,
  llm,
  signal,
  onEvent,
}: ChatOptions): Promise<void> {
  const form = new FormData();
  form.append("message", message);
  form.append("run_id", runId);
  form.append("attachments", JSON.stringify(attachments));
  for (const f of files) form.append("files", f);

  const resp = await fetch(`${API_BASE}/api/chat`, {
    method: "POST",
    headers: credentialHeaders(llm),
    body: form,
    signal,
  });
  if (!resp.ok || !resp.body) {
    const detail = await resp.text();
    throw new Error(detail.slice(0, 300) || `请求失败：${resp.status}`);
  }
  await consumeStream(resp.body, onEvent);
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "tool" | "system";
  /** 文本内容（assistant 与 user 用） */
  content: string;
  /** 多模态 image_url 列表（user message 用） */
  images?: { url: string; mime: string; name: string }[];
  /** 附件列表（user message 用） */
  attachments?: {
    name: string;
    mime: string;
    kind?: string;
    pages?: number | null;
    chars?: number;
    readable?: boolean;
  }[];
  /** assistant 消息：被调度的专家名（用于渲染"由 xxx 给出"的来源标注） */
  by?: string;
  /** 完整元信息（specialist 输出/工具调用记录） */
  meta?: Record<string, unknown>;
  /** 工具消息：完整入参 / 返回值，供折叠面板展开查看 */
  toolDetail?: string;
  /** 工具消息：调用是否成功（tool_result 用） */
  toolOk?: boolean;
  /** 流式输出是否仍在进行 */
  streaming?: boolean;
  createdAt: number;
}

export interface ChatEstimateOptions {
  runId: string;
  message: string;
  attachments: ChatAttachmentMeta[];
  llm: LLMConfig;
}

export interface ChatEstimateResult {
  tokens: number;
  /** 给模型写回答预留的 token，占用率分子要算进去 */
  reserve: number;
  /** 上下文上限由后端统一给出，前端不另存模型表 */
  limit: number;
  model: string;
  /** 主链路占用拆分：系统提示词（含文档摘要） / 会话（历史 + 本轮输入） */
  breakdown: { system: number; conversation: number };
}

/** 让后端用 tiktoken 精确计算当前对话 + 待发送内容的 token 数。 */
export async function estimateChatTokens({
  runId,
  message,
  attachments,
  llm,
}: ChatEstimateOptions): Promise<ChatEstimateResult> {
  const resp = await fetch(`${API_BASE}/api/chat/estimate`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...credentialHeaders(llm),
    },
    body: JSON.stringify({
      run_id: runId,
      message,
      attachments,
      model: llm.model,
    }),
  });
  if (!resp.ok) {
    const detail = await resp.text();
    throw new Error(detail.slice(0, 300) || `HTTP ${resp.status}`);
  }
  return resp.json();
}

/* ---------------- 人机交互 ---------------- */

/** 把用户对 ask_user 的作答交回后端，唤醒阻塞中的智能体。 */
export async function answerQuestion(
  qid: string,
  answers: AskAnswer[],
  note = "",
): Promise<void> {
  const resp = await fetch(`${API_BASE}/api/chat/answer`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ qid, answers, note }),
  });
  if (!resp.ok) {
    const detail = await resp.text();
    throw new Error(detail.slice(0, 200) || `提交失败：${resp.status}`);
  }
}

export async function getChatHistory(runId: string): Promise<{
  messages: ChatMessage[];
  /** 智能体显式设置的标题（set_conversation_title），未设置时为空串 */
  title: string;
}> {
  const resp = await fetch(`${API_BASE}/api/chat/${encodeURIComponent(runId)}`);
  if (!resp.ok) return { messages: [], title: "" };
  const data = await resp.json();
  return { messages: data.messages ?? [], title: data.title ?? "" };
}

/** 读取某次对话的完整事件流（刷新/切换后重建协作面板） */
export async function getConversationEvents(
  runId: string,
): Promise<{ events: AgentEvent[] }> {
  const resp = await fetch(
    `${API_BASE}/api/conversations/${encodeURIComponent(runId)}/events`,
  );
  if (!resp.ok) return { events: [] };
  return resp.json();
}

/* ---------------- 能力目录（工具 / 技能 / 智能体） ---------------- */

export interface ToolSpec {
  name: string;
  description: string;
  input_schema: Record<string, string>;
  tags: string[];
  inject: string[];
}

export interface SkillSpec {
  name: string;
  description: string;
  tools: string[];
  tags: string[];
  path: string;
}

export interface AgentSpecInfo {
  key: string;
  name: string;
  role: string;
  tools: string[];
  skills: string[];
  max_steps: number;
}

export interface RegistryCatalog {
  tools: ToolSpec[];
  skills: SkillSpec[];
  agents: AgentSpecInfo[];
}

export interface SkillDetail extends SkillSpec {
  body: string;
  agents: { key: string; name: string }[];
}

export async function getRegistry(): Promise<RegistryCatalog> {
  const resp = await fetch(`${API_BASE}/api/registry`);
  if (!resp.ok) throw new Error("获取能力目录失败");
  return resp.json();
}

export async function getSkill(name: string): Promise<SkillDetail | null> {
  const resp = await fetch(`${API_BASE}/api/skills/${encodeURIComponent(name)}`);
  if (!resp.ok) return null;
  return resp.json();
}

/* ---------------- 多对话管理 ---------------- */

export interface ConversationSummary {
  run_id: string;
  title: string;
  updated_at: number;
  message_count: number;
}

export async function listConversations(): Promise<{
  conversations: ConversationSummary[];
}> {
  const resp = await fetch(`${API_BASE}/api/conversations`);
  if (!resp.ok) throw new Error("获取对话列表失败");
  return resp.json();
}

export async function deleteConversation(runId: string): Promise<void> {
  const resp = await fetch(`${API_BASE}/api/conversations/${encodeURIComponent(runId)}`, {
    method: "DELETE",
  });
  if (!resp.ok) throw new Error("删除对话失败");
}

/** 把 File 列表转成 dataURL（用于本地预览）。仅在用户上传时调用一次。 */
export async function filesToPreviews(files: File[]): Promise<
  { url: string; mime: string; name: string }[]
> {
  return Promise.all(
    files.map(
      (f) =>
        new Promise<{ url: string; mime: string; name: string }>((resolve) => {
          const reader = new FileReader();
          reader.onload = () =>
            resolve({ url: String(reader.result), mime: f.type, name: f.name });
          reader.onerror = () =>
            resolve({ url: "", mime: f.type, name: f.name });
          reader.readAsDataURL(f);
        }),
    ),
  );
}