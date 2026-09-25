"use client";

import { Globe } from "lucide-react";
import { useState } from "react";
import { FlaskConical, Loader2 } from "lucide-react";
import { testSearch } from "@/lib/api";
import type { SearchTestResult } from "@/lib/api";
import type { LLMStore, SearchConfig } from "@/lib/types";
import { EMPTY_SEARCH } from "@/lib/types";

const SEARCH_PROVIDERS: Record<string, string> = {
  tavily: "Tavily",
  bocha: "博查 Bocha",
  searxng: "SearXNG",
  baidu: "百度",
  bing_cn: "必应中国",
};

interface Props {
  store: LLMStore;
  onChange: (store: LLMStore) => void;
}

/** 联网搜索源配置：填 Key 走稳定源，不填则自动降级到百度 / 必应 */
export function SearchApiCard({ store, onChange }: Props) {
  const [open, setOpen] = useState(false);
  const [showKey, setShowKey] = useState(false);
  const [testing, setTesting] = useState(false);
  const [result, setResult] = useState<SearchTestResult | null>(null);

  const cfg: SearchConfig = store.search ?? EMPTY_SEARCH;

  const patch = (next: Partial<SearchConfig>) => {
    onChange({ ...store, search: { ...cfg, ...next } });
    setResult(null);
  };

  const configured = [cfg.tavilyApiKey, cfg.bochaApiKey, cfg.searxngUrl].filter(
    (v) => v.trim(),
  ).length;

  const runTest = async () => {
    setTesting(true);
    setResult(null);
    try {
      setResult(await testSearch(cfg));
    } catch (e) {
      setResult({
        ok: false,
        provider: null,
        count: 0,
        error: e instanceof Error ? e.message : String(e),
      });
    } finally {
      setTesting(false);
    }
  };

  return (
    <div className="collapse collapse-arrow card-border border-base-300 bg-base-100">
      <input
        type="checkbox"
        checked={open}
        onChange={() => setOpen((v) => !v)}
        aria-label="展开搜索 API 设置"
      />
      <div className="collapse-title flex min-h-0 items-center gap-2 py-2.5 pr-9 pl-3">
        <Globe className="h-3.5 w-3.5 shrink-0 text-base-content/90" />
        <span className="text-sm font-semibold tracking-wide text-base-content/90">
          搜索 API
        </span>
        <span className="ml-auto">
          <span
            className={`badge badge-sm gap-1 ${
              configured > 0 ? "badge-success badge-outline" : "badge-ghost"
            }`}
          >
            {configured > 0 ? `已配置 ${configured}` : "未配置"}
          </span>
        </span>
      </div>
      {open && (
        <div className="collapse-content space-y-3 pt-0">
          <p className="text-[13px] leading-relaxed text-base-content/70">
            填入任一稳定源的 Key 后，智能体联网检索会优先使用；全部留空时自动降级到
            百度 / 必应中国。
          </p>

          <label className="form-control">
            <span className="mb-1 text-[14px] text-base-content/90">Tavily API Key</span>
            <div className="join">
              <input
                type={showKey ? "text" : "password"}
                className="input input-bordered join-item input-sm flex-1 font-mono"
                placeholder="tvly-..."
                value={cfg.tavilyApiKey}
                onChange={(e) => patch({ tavilyApiKey: e.target.value })}
              />
            </div>
          </label>

          <label className="form-control">
            <span className="mb-1 text-[14px] text-base-content/90">博查 Bocha Key</span>
            <input
              type={showKey ? "text" : "password"}
              className="input input-bordered input-sm font-mono"
              placeholder="sk-..."
              value={cfg.bochaApiKey}
              onChange={(e) => patch({ bochaApiKey: e.target.value })}
            />
          </label>

          <label className="form-control">
            <span className="mb-1 text-[14px] text-base-content/90">
              自建 SearXNG 地址
            </span>
            <input
              className="input input-bordered input-sm font-mono"
              placeholder="https://searx.example.com"
              value={cfg.searxngUrl}
              onChange={(e) => patch({ searxngUrl: e.target.value })}
            />
          </label>

          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              className="btn btn-xs gap-1"
              onClick={() => setShowKey((v) => !v)}
            >
              {showKey ? "隐藏 Key" : "显示 Key"}
            </button>
            <button
              type="button"
              className="btn btn-xs gap-1 border-base-300 bg-base-200"
              onClick={runTest}
              disabled={testing}
            >
              {testing ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                <FlaskConical className="h-3 w-3" />
              )}
              测试连通性
            </button>
            <span className="text-[13px] text-base-content/50">
              可用源：{Object.values(SEARCH_PROVIDERS).join(" / ")}
            </span>
          </div>

          {result && (
            <div
              className={`rounded-[var(--radius-field)] border px-2.5 py-2 text-[13px] ${
                result.ok
                  ? "border-success/40 bg-success/10 text-base-content"
                  : "border-error/40 bg-error/10 text-base-content"
              }`}
            >
              {result.ok ? (
                <span className="break-words">
                  成功 · 源：{result.provider} · 命中 {result.count} 条
                  {result.sample?.[0]?.title ? `（例：${result.sample[0].title}）` : ""}
                </span>
              ) : (
                <span className="break-words">
                  失败：{result.error ?? "所有搜索源均无结果"}
                </span>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
