"use client";

import { useEffect, useState } from "react";
import {
  Settings2,
  KeyRound,
  Cpu,
  Link2,
  Check,
  X,
  Plus,
  Trash2,
  Pencil,
  RefreshCw,
  ListChecks,
  Loader2,
  Shuffle,
} from "lucide-react";
import { getProviders, listModels, probeModels } from "@/lib/api";
import type { ProbeResult } from "@/lib/api";
import type { LLMProfile, LLMStore, ProviderCatalog, ProviderInfo } from "@/lib/types";
import { createProfile } from "@/lib/llmStore";
import { FieldLabel } from "@/components/settings/FieldLabel";
import { SearchApiCard } from "@/components/settings/SearchApiCard";

interface Props {
  store: LLMStore;
  onChange: (store: LLMStore) => void;
}


export function SettingsPanel({ store, onChange }: Props) {
  const [catalog, setCatalog] = useState<ProviderCatalog | null>(null);
  const [open, setOpen] = useState(false);
  const [showKey, setShowKey] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [renaming, setRenaming] = useState(false);

  const [loading, setLoading] = useState(false);
  const [available, setAvailable] = useState<string[]>([]);
  const [probed, setProbed] = useState<ProbeResult[]>([]);
  const [probeError, setProbeError] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const [customId, setCustomId] = useState("");

  useEffect(() => {
    getProviders()
      .then(setCatalog)
      .catch((e) => setError(String(e)));
  }, []);

  const active =
    store.profiles.find((p) => p.id === store.activeId) ?? store.profiles[0];
  const current: ProviderInfo | undefined = catalog?.providers.find(
    (p) => p.key === active?.provider,
  );

  useEffect(() => {
    setAvailable(active?.models ?? []);
    setProbed([]);
    setProbeError(null);
    setFilter("");
    setCustomId("");
  }, [active?.id]);

  const updateProfile = (patch: Partial<LLMProfile>) => {
    onChange({
      ...store,
      profiles: store.profiles.map((p) =>
        p.id === active.id ? { ...p, ...patch } : p,
      ),
    });
  };

  const selectProvider = (key: string) => {
    const p = catalog?.providers.find((x) => x.key === key);
    updateProfile({
      provider: key,
      model: p?.models[0] ?? "",
      baseUrl: key === "custom" ? active.baseUrl : p?.base_url ?? "",
    });
  };

  const addProfile = () => {
    const profile = createProfile({ name: `配置 ${store.profiles.length + 1}` });
    onChange({ profiles: [...store.profiles, profile], activeId: profile.id });
    setRenaming(true);
  };

  const removeProfile = (id: string) => {
    if (store.profiles.length <= 1) return;
    const profiles = store.profiles.filter((p) => p.id !== id);
    const activeId = store.activeId === id ? profiles[0].id : store.activeId;
    onChange({ profiles, activeId });
  };

  const detectModels = async () => {
    setLoading(true);
    setProbeError(null);
    setAvailable([]);
    setProbed([]);
    try {
      const res = await listModels({
        provider: active.provider,
        baseUrl: active.baseUrl,
        apiKey: active.apiKey,
      });
      setAvailable(res.models);
      updateProfile({ models: res.models });
      if (res.models.length === 0) {
        setProbeError("提供商返回的模型列表为空");
      }
    } catch (e) {
      setProbeError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  // 手动录入模型 ID：自建/代理/未开放 /models 接口的模型走这里
  const addCustomModel = () => {
    const m = customId.trim();
    if (!m) return;
    if (!available.includes(m)) setAvailable((prev) => [...prev, m]);
    if (!(active.models || []).includes(m)) {
      updateProfile({ models: [...(active.models || []), m] });
    }
    setCustomId("");
  };

  const addFallback = (m: string) => {
    if (m === active.model) return;
    if (active.fallbackModels.includes(m)) return;
    updateProfile({ fallbackModels: [...active.fallbackModels, m] });
  };

  const removeFallback = (m: string) => {
    updateProfile({
      fallbackModels: active.fallbackModels.filter((x) => x !== m),
    });
  };

  const testModels = async (models: string[]) => {
    if (models.length === 0) return;
    setLoading(true);
    setProbeError(null);
    try {
      const res = await probeModels(
        { provider: active.provider, baseUrl: active.baseUrl, apiKey: active.apiKey },
        models,
      );
      setProbed(res.results);
    } catch (e) {
      setProbeError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  const connected = Boolean(active?.apiKey?.trim());

  const visibleModels = available.filter((m) =>
    filter ? m.toLowerCase().includes(filter.toLowerCase()) : true,
  );

  const okSet = new Set(probed.filter((r) => r.ok).map((r) => r.model));
  const failSet = new Set(probed.filter((r) => !r.ok).map((r) => r.model));

  return (
    <div className="space-y-3">
      <div className="collapse collapse-arrow card-border border-base-300 bg-base-100">
        <input
          type="checkbox"
          checked={open}
          onChange={() => setOpen((v) => !v)}
          aria-label="展开模型设置"
        />
      <div className="collapse-title flex min-h-0 items-center gap-2 py-2.5 pr-9 pl-3">
        <Settings2 className="h-3.5 w-3.5 shrink-0 text-base-content/90" />
        <span className="text-sm font-semibold tracking-wide text-base-content/90">
          模型设置
        </span>
        <span className="ml-auto flex items-center gap-2">
          {active?.name && (
            <span className="max-w-[72px] truncate text-[14px] text-base-content/90">
              {active.name}
            </span>
          )}
          <span
            className={`badge badge-sm gap-1 ${
              connected ? "badge-success badge-outline" : "badge-ghost"
            }`}
          >
            {connected ? (
              <Check className="h-2.5 w-2.5" strokeWidth={3} />
            ) : (
              <X className="h-2.5 w-2.5" strokeWidth={3} />
            )}
            {connected ? "已配置" : "未配置"}
          </span>
        </span>
      </div>

      {open && (
        <div className="collapse-content space-y-3 px-3">
          {error && (
            <p className="alert alert-error alert-soft py-1.5 text-[14px]">
              {error}
            </p>
          )}

          <div>
            <div className="mb-1 flex items-center justify-between">
              <FieldLabel>配置档案</FieldLabel>
              <button
                onClick={addProfile}
                className="btn btn-xs btn-ghost gap-0.5 px-1.5 text-primary"
              >
                <Plus className="h-3 w-3" />
                新增
              </button>
            </div>
            <div className="space-y-1">
              {store.profiles.map((p) => {
                const isActive = p.id === active.id;
                return (
                  <div
                    key={p.id}
                    className={`flex items-center gap-1 rounded-[var(--radius-field)] border px-2 py-1.5 ${
                      isActive
                        ? "border-primary/45 bg-primary/[0.05]"
                        : "border-base-300 bg-base-200/50"
                    }`}
                  >
                    <button
                      onClick={() => onChange({ ...store, activeId: p.id })}
                      className="min-w-0 flex-1 text-left"
                    >
                      <p className="truncate text-[14px] text-base-content">
                        {p.name}
                      </p>
                      <p className="truncate font-mono text-[14px] text-base-content/90">
                        {p.model || "未设置模型"}
                      </p>
                    </button>
                    {isActive && store.profiles.length > 1 && (
                      <button
                        onClick={() => removeProfile(p.id)}
                        className="btn btn-ghost btn-xs px-1 text-base-content/90 hover:text-error"
                        title="删除"
                      >
                        <Trash2 className="h-3 w-3" />
                      </button>
                    )}
                  </div>
                );
              })}
            </div>
          </div>

          <div>
            <div className="mb-1 flex items-center justify-between">
              <FieldLabel>名称</FieldLabel>
              <button
                onClick={() => setRenaming((v) => !v)}
                className="btn btn-xs btn-ghost gap-0.5 px-1.5 text-primary"
              >
                <Pencil className="h-2.5 w-2.5" />
                {renaming ? "完成" : "重命名"}
              </button>
            </div>
            {renaming ? (
              <input
                autoFocus
                value={active.name}
                onChange={(e) => updateProfile({ name: e.target.value })}
                onKeyDown={(e) => e.key === "Enter" && setRenaming(false)}
                className="input input-sm w-full border-primary/50"
              />
            ) : (
              <p className="rounded-[var(--radius-field)] border border-base-300 bg-base-200/50 px-2.5 py-1.5 text-[14px] text-base-content/90">
                {active.name}
              </p>
            )}
          </div>

          <div>
            <FieldLabel icon={Cpu}>提供商</FieldLabel>
            <select
              value={active.provider}
              onChange={(e) => selectProvider(e.target.value)}
              className="select select-sm w-full"
            >
              {catalog?.providers.map((p) => (
                <option key={p.key} value={p.key}>
                  {p.label}
                </option>
              ))}
            </select>
          </div>

          {(active.provider === "custom" || !current?.models?.length) && (
            <div>
              <FieldLabel icon={Link2}>Base URL</FieldLabel>
              <input
                value={active.baseUrl}
                onChange={(e) => updateProfile({ baseUrl: e.target.value })}
                placeholder="https://your-endpoint/v1"
                className="input input-sm w-full font-mono text-[14px]"
              />
            </div>
          )}

          <div>
            <FieldLabel icon={KeyRound}>API Key</FieldLabel>
            <div className="flex gap-1.5">
              <input
                type={showKey ? "text" : "password"}
                value={active.apiKey}
                onChange={(e) => updateProfile({ apiKey: e.target.value })}
                placeholder="sk-..."
                className="input input-sm min-w-0 flex-1 font-mono text-[14px]"
              />
              <button
                onClick={() => setShowKey((v) => !v)}
                className="btn btn-sm shrink-0 border-base-300 bg-base-100 font-normal text-base-content/90"
              >
                {showKey ? "隐藏" : "显示"}
              </button>
            </div>
          </div>

          <div className="rounded-[var(--radius-field)] border border-base-300 bg-base-200/40 p-2.5">
            <div className="mb-2 flex items-center justify-between gap-2">
              <FieldLabel icon={ListChecks}>可选模型</FieldLabel>
              <div className="flex gap-1">
                <button
                  onClick={detectModels}
                  disabled={loading || !active.apiKey}
                  className="btn btn-xs gap-1 border-base-300 bg-base-100 font-normal text-base-content/90"
                >
                  {loading ? (
                    <Loader2 className="h-2.5 w-2.5 animate-spin" />
                  ) : (
                    <RefreshCw className="h-2.5 w-2.5" />
                  )}
                  检测
                </button>
                {available.length > 0 && (
                  <button
                    onClick={() => testModels(visibleModels.slice(0, 20))}
                    disabled={loading}
                    className="btn btn-xs border-base-300 bg-base-100 font-normal text-base-content/90"
                  >
                    连通性测试
                  </button>
                )}
              </div>
            </div>

            {probeError && (
              <p className="alert alert-error alert-soft mb-2 py-1 text-[14px]">
                {probeError}
              </p>
            )}

            <div className="mb-2 flex gap-1">
              <input
                value={customId}
                onChange={(e) => setCustomId(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    addCustomModel();
                  }
                }}
                placeholder="输入自定义模型 ID"
                className="input input-xs min-w-0 flex-1 font-mono text-[14px]"
              />
              <button
                onClick={addCustomModel}
                disabled={!customId.trim()}
                className="btn btn-xs shrink-0 border-base-300 bg-base-100 font-normal text-base-content/90"
              >
                添加
              </button>
            </div>

            {available.length > 0 && (
              <>
                <input
                  value={filter}
                  onChange={(e) => setFilter(e.target.value)}
                  placeholder="筛选模型…"
                  className="input input-xs mb-2 w-full"
                />
                <div className="max-h-48 space-y-0.5 overflow-y-auto">
                  {visibleModels.map((m) => {
                    const isActive = m === active.model;
                    const ok = okSet.has(m);
                    const fail = failSet.has(m);
                    return (
                      <div
                        key={m}
                        className={`flex items-center gap-1 rounded-[3px] px-1 ${
                          isActive ? "bg-primary/10" : "hover:bg-base-200"
                        }`}
                      >
                        <button
                          onClick={() => updateProfile({ model: m })}
                          className={`flex min-w-0 flex-1 items-center justify-between gap-2 px-1 py-1 text-left ${
                            isActive ? "text-primary" : "text-base-content/90"
                          }`}
                        >
                          <span className="truncate font-mono text-[14px]">
                            {m}
                          </span>
                          {ok && (
                            <Check
                              className="h-3 w-3 shrink-0 text-success"
                              strokeWidth={3}
                            />
                          )}
                          {fail && (
                            <X
                              className="h-3 w-3 shrink-0 text-error"
                              strokeWidth={3}
                            />
                          )}
                        </button>
                        {!isActive && (
                          <button
                            onClick={() => addFallback(m)}
                            disabled={active.fallbackModels.includes(m)}
                            title="加入备用链"
                            className="btn btn-ghost btn-xs shrink-0 px-1 text-base-content/90"
                          >
                            +
                          </button>
                        )}
                      </div>
                    );
                  })}
                  {visibleModels.length === 0 && (
                    <p className="px-2 py-1 text-[14px] text-base-content/90">
                      无匹配模型
                    </p>
                  )}
                </div>
              </>
            )}

            {available.length === 0 && !probeError && (
              <p className="text-[14px] text-base-content/90">
                点击「检测」拉取可用模型，或在上方手动添加模型 ID
              </p>
            )}
          </div>

          <div className="rounded-[var(--radius-field)] border border-base-300 bg-base-200/40 p-2.5">
            <FieldLabel icon={Shuffle}>备用模型链</FieldLabel>
            {active.fallbackModels.length === 0 ? (
              <p className="text-[14px] leading-relaxed text-base-content/90">
                主模型连续失败 3 次后自动切换；在模型列表中点击 + 添加
              </p>
            ) : (
              <ol className="space-y-0.5">
                {active.fallbackModels.map((m, i) => (
                  <li
                    key={m}
                    className="flex items-center gap-1.5 rounded-[3px] bg-base-100 px-2 py-1"
                  >
                    <span className="tnum font-mono text-[14px] text-base-content/90">
                      {i + 1}
                    </span>
                    <span className="min-w-0 flex-1 truncate font-mono text-[14px] text-base-content/90">
                      {m}
                    </span>
                    <button
                      onClick={() => removeFallback(m)}
                      className="btn btn-ghost btn-xs px-1 text-base-content/90 hover:text-error"
                    >
                      <X className="h-3 w-3" />
                    </button>
                  </li>
                ))}
              </ol>
            )}
          </div>

          {current?.doc && (
            <a
              href={current.doc}
              target="_blank"
              rel="noopener noreferrer"
              className="link link-primary block text-[14px]"
            >
              获取 {current.label} API Key →
            </a>
          )}
        </div>
      )}
      </div>

      <SearchApiCard store={store} onChange={onChange} />
    </div>
  );
}
