import { EMPTY_SEARCH, type LLMProfile, type LLMStore, type SearchConfig } from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000";
const CACHE_KEY = "weister.llm.store.cache";

export function newId(): string {
  return Math.random().toString(36).slice(2, 10);
}

export function createProfile(partial?: Partial<LLMProfile>): LLMProfile {
  return {
    id: newId(),
    name: partial?.name ?? "新配置",
    provider: partial?.provider ?? "deepseek",
    model: partial?.model ?? "deepseek-chat",
    fallbackModels: partial?.fallbackModels ?? [],
    models: partial?.models ?? [],
    apiKey: partial?.apiKey ?? "",
    baseUrl: partial?.baseUrl ?? "",
  };
}

export function defaultStore(): LLMStore {
  const profile = createProfile({ name: "DeepSeek" });
  return { profiles: [profile], activeId: profile.id, search: { ...EMPTY_SEARCH } };
}

function normalizeSearch(raw: unknown): SearchConfig {
  const src = (raw && typeof raw === "object" ? raw : {}) as Partial<SearchConfig>;
  return {
    tavilyApiKey: typeof src.tavilyApiKey === "string" ? src.tavilyApiKey : "",
    bochaApiKey: typeof src.bochaApiKey === "string" ? src.bochaApiKey : "",
    searxngUrl: typeof src.searxngUrl === "string" ? src.searxngUrl : "",
  };
}

function normalize(raw: unknown): LLMStore | null {
  if (!raw || typeof raw !== "object") return null;
  const data = raw as { profiles?: unknown; activeId?: unknown; search?: unknown };
  if (!Array.isArray(data.profiles) || data.profiles.length === 0) return null;

  const profiles: LLMProfile[] = data.profiles
    .filter((p): p is Record<string, unknown> => !!p && typeof p === "object")
    .map((p) => ({
      id: typeof p.id === "string" ? p.id : newId(),
      name: typeof p.name === "string" ? p.name : "未命名",
      provider: typeof p.provider === "string" ? p.provider : "deepseek",
      model: typeof p.model === "string" ? p.model : "",
      fallbackModels: Array.isArray(p.fallbackModels)
        ? (p.fallbackModels as string[])
        : [],
      models: Array.isArray(p.models) ? (p.models as string[]) : [],
      apiKey: typeof p.apiKey === "string" ? p.apiKey : "",
      baseUrl: typeof p.baseUrl === "string" ? p.baseUrl : "",
    }));

  if (profiles.length === 0) return null;

  const activeId =
    typeof data.activeId === "string" &&
    profiles.some((p) => p.id === data.activeId)
      ? data.activeId
      : profiles[0].id;

  return {
    profiles,
    activeId,
    search: normalizeSearch(data.search),
  };
}

function readCache(): LLMStore | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(CACHE_KEY);
    return raw ? normalize(JSON.parse(raw)) : null;
  } catch {
    return null;
  }
}

function writeCache(store: LLMStore): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(CACHE_KEY, JSON.stringify(store));
  } catch {
    /* ignore */
  }
}

export async function loadStore(): Promise<LLMStore> {
  try {
    const resp = await fetch(`${API_BASE}/api/profiles`);
    if (resp.ok) {
      const store = normalize(await resp.json());
      if (store) {
        writeCache(store);
        return store;
      }
    }
  } catch {
    /* 后端不可用，退回缓存 */
  }
  return readCache() ?? defaultStore();
}

export async function saveStore(store: LLMStore): Promise<void> {
  writeCache(store);
  try {
    await fetch(`${API_BASE}/api/profiles`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(store),
    });
  } catch {
    /* 后端不可用，仅本地缓存 */
  }
}

export function activeProfile(store: LLMStore): LLMProfile {
  return (
    store.profiles.find((p) => p.id === store.activeId) ?? store.profiles[0]
  );
}
