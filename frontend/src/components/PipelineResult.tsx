"use client";

import { useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { FlaskConical } from "lucide-react";
import type { AnalyzeResultPayload } from "@/hooks/useAnalyzeRun";
import { extractReportMd } from "@/lib/md";

type TabKey = "report" | "valuation" | "data" | "experts";

const TABS: { key: TabKey; label: string }[] = [
  { key: "report", label: "研究报告" },
  { key: "valuation", label: "估值建模" },
  { key: "data", label: "结构化数据" },
  { key: "experts", label: "专家意见" },
];

function fmtNum(v: unknown): string {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "number") {
    return Math.abs(v) >= 1000
      ? v.toLocaleString(undefined, { maximumFractionDigits: 2 })
      : String(Math.round(v * 10000) / 10000);
  }
  return String(v);
}

function ValuationCards({ result }: { result: AnalyzeResultPayload }) {
  const summary = (result.valuation_summary || {}) as {
    low?: number;
    mid?: number;
    high?: number;
    methods?: Record<string, number | number[]>;
  };
  const dcf = (result.dcf || {}) as Record<string, unknown>;
  const relative = (result.relative || {}) as Record<string, unknown>;
  const sens = (result.sensitivity || null) as {
    wacc?: number[];
    growth?: number[];
    /** WACC ≤ 永续增长率时该格为 null，fmtNum 会渲染成「—」 */
    grid?: (number | null)[][];
  } | null;

  return (
    <div className="space-y-3">
      {(summary.low !== undefined || summary.mid !== undefined) && (
        <div className="grid gap-2 sm:grid-cols-3">
          {[
            { label: "区间下沿", value: summary.low },
            { label: "中位数", value: summary.mid },
            { label: "区间上沿", value: summary.high },
          ].map((c) => (
            <div
              key={c.label}
              className="rounded-[var(--radius-box)] border border-base-300 bg-base-200/40 px-3 py-2"
            >
              <p className="text-[14px] text-base-content/85">{c.label}</p>
              <p className="tnum font-mono text-lg font-semibold text-base-content">
                {fmtNum(c.value)}
              </p>
            </div>
          ))}
        </div>
      )}

      {summary.methods && Object.keys(summary.methods).length > 0 && (
        <div className="rounded-[var(--radius-field)] border border-base-300 bg-base-100 p-2.5">
          <p className="mb-1 text-[14px] font-medium text-base-content">分方法估值</p>
          <ul className="space-y-0.5 font-mono text-[14px]">
            {Object.entries(summary.methods).map(([k, v]) => (
              <li key={k} className="flex justify-between gap-2">
                <span className="text-base-content/85">{k}</span>
                <span>{Array.isArray(v) ? v.map(fmtNum).join(" ~ ") : fmtNum(v)}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {Object.keys(dcf).length > 0 && (
        <div className="rounded-[var(--radius-field)] border border-base-300 bg-base-100 p-2.5">
          <p className="mb-1 text-[14px] font-medium text-base-content">DCF 关键值</p>
          <div className="grid gap-x-4 gap-y-0.5 sm:grid-cols-2 font-mono text-[14px]">
            {(
              [
                ["企业价值", dcf.enterprise_value],
                ["权益价值", dcf.equity_value],
                ["终值现值", dcf.pv_terminal],
                ["每股价值", dcf.equity_value_per_share],
                ["净债务", dcf.net_debt],
                ["WACC 对应终值占比", dcf.terminal_share],
              ] as const
            ).map(([k, v]) => (
              <div key={k} className="flex justify-between gap-2">
                <span className="text-base-content/85">{k}</span>
                <span>{fmtNum(v)}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {Object.keys(relative).length > 0 && (
        <div className="rounded-[var(--radius-field)] border border-base-300 bg-base-100 p-2.5">
          <p className="mb-1 text-[14px] font-medium text-base-content">相对估值</p>
          <pre className="max-h-48 overflow-auto font-mono text-[14px] text-base-content/90">
            {JSON.stringify(relative, null, 2)}
          </pre>
        </div>
      )}

      {sens?.grid && (
        <div className="overflow-x-auto rounded-[var(--radius-field)] border border-base-300 bg-base-100 p-2.5">
          <p className="mb-1 text-[14px] font-medium text-base-content">敏感性（WACC × 永续增长）</p>
          <table className="tnum font-mono text-[14px]">
            <thead>
              <tr>
                <th className="pr-2 text-left">WACC\g</th>
                {(sens.growth || []).map((g, i) => (
                  <th key={i} className="px-1 text-right">
                    {fmtNum(g)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {(sens.wacc || []).map((w, ri) => (
                <tr key={ri}>
                  <td className="pr-2 text-left">{fmtNum(w)}</td>
                  {(sens.grid?.[ri] || []).map((cell, ci) => (
                    <td key={ci} className="px-1 text-right">
                      {fmtNum(cell)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {summary.low === undefined && !Object.keys(dcf).length && (
        <p className="text-[14px] text-base-content/85">本次运行未产出估值区间。</p>
      )}
    </div>
  );
}

function DataTab({ result }: { result: AnalyzeResultPayload }) {
  const extracted = (result.extracted || {}) as {
    company?: string;
    period?: string;
    unit?: string;
    fields?: Record<string, unknown>;
  };
  const metrics = (result.metrics || {}) as Record<string, unknown>;
  const fieldEntries = Object.entries(extracted.fields || {});

  return (
    <div className="space-y-3">
      {(extracted.company || extracted.period) && (
        <p className="text-[14px] text-base-content/90">
          <span className="font-medium">{extracted.company || "—"}</span>
          {extracted.period ? ` · ${extracted.period}` : ""}
          {extracted.unit ? ` · 单位：${extracted.unit}` : ""}
        </p>
      )}
      {fieldEntries.length > 0 && (
        <div className="rounded-[var(--radius-field)] border border-base-300 bg-base-100 p-2.5">
          <p className="mb-1 text-[14px] font-medium">财务字段</p>
          <div className="grid gap-x-4 gap-y-0.5 sm:grid-cols-2 font-mono text-[14px]">
            {fieldEntries.map(([k, v]) => (
              <div key={k} className="flex justify-between gap-2 border-b border-base-300/40 py-0.5">
                <span className="text-base-content/85">{k}</span>
                <span>{v === null || v === "" ? "—" : String(v)}</span>
              </div>
            ))}
          </div>
        </div>
      )}
      {Object.keys(metrics).length > 0 && (
        <div className="rounded-[var(--radius-field)] border border-base-300 bg-base-100 p-2.5">
          <p className="mb-1 text-[14px] font-medium">派生指标</p>
          <div className="grid gap-x-4 gap-y-0.5 sm:grid-cols-2 font-mono text-[14px]">
            {Object.entries(metrics).map(([k, v]) => (
              <div key={k} className="flex justify-between gap-2">
                <span className="text-base-content/85">{k}</span>
                <span>{fmtNum(v)}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function ExpertsTab({ result }: { result: AnalyzeResultPayload }) {
  const analyses = (result.analyses || {}) as Record<
    string,
    { name?: string; role?: string; output?: string }
  >;
  const opinions = (result.expert_opinions || []) as {
    name?: string;
    agent?: string;
    role?: string;
    opinion?: string;
    output?: string;
  }[];

  const cards: { title: string; body: string }[] = [];
  for (const a of Object.values(analyses)) {
    const body = (a.output || "").trim();
    if (body) cards.push({ title: `${a.name || "专家"}${a.role ? `（${a.role}）` : ""}`, body });
  }
  for (const o of opinions) {
    const body = (o.opinion || o.output || "").trim();
    if (body) cards.push({ title: `${o.name || o.agent || "专家"}${o.role ? `（${o.role}）` : ""}`, body });
  }

  if (!cards.length) {
    return <p className="text-[14px] text-base-content/85">本次运行没有专家长文输出。</p>;
  }
  return (
    <div className="space-y-3">
      {cards.map((c, i) => (
        <div key={i} className="rounded-[var(--radius-box)] border border-base-300 bg-base-100 p-3">
          <p className="mb-1.5 text-[14px] font-semibold text-base-content">{c.title}</p>
          <article className="prose-report text-[14px]">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{c.body}</ReactMarkdown>
          </article>
        </div>
      ))}
    </div>
  );
}

export interface PipelineResultViewProps {
  reply: string;
  result: AnalyzeResultPayload | null;
  running: boolean;
  error: string | null;
}

export function PipelineResultView({ reply, result, running, error }: PipelineResultViewProps) {
  const [tab, setTab] = useState<TabKey>("report");
  const reportText = useMemo(() => extractReportMd(result).trim() || reply.trim(), [result, reply]);

  if (error) {
    return (
      <p className="alert alert-error alert-soft py-1.5 text-[14px]">{error}</p>
    );
  }

  if (!reportText && !result && !running) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 text-center text-base-content/90">
        <FlaskConical className="h-8 w-8" />
        <p className="text-[14px] font-medium">一键估值建模</p>
        <p className="max-w-[360px] text-[14px]">
          上传财报或运行内置样例，将依次执行：文档解析 → 数据提取 → 主管调度 →
          分析组 → 评审组 → 报告撰写。完成后此处渲染 Markdown 研究报告与估值结果。
        </p>
      </div>
    );
  }

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-3">
      {result && (
        <div role="tablist" className="tabs tabs-boxed w-fit">
          {TABS.map((t) => (
            <button
              key={t.key}
              role="tab"
              type="button"
              aria-selected={tab === t.key}
              className={`tab ${tab === t.key ? "tab-active" : ""}`}
              onClick={() => setTab(t.key)}
            >
              {t.label}
            </button>
          ))}
        </div>
      )}

      {(!result || tab === "report") && (
        <article className="prose-report rounded-[var(--radius-box)] border border-base-300 bg-base-100 px-4 py-3">
          {reportText ? (
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{reportText}</ReactMarkdown>
          ) : running ? (
            <p className="text-[14px] text-base-content/85">报告生成中…</p>
          ) : (
            <p className="text-[14px] text-base-content/85">无报告正文。</p>
          )}
        </article>
      )}

      {result && tab === "valuation" && <ValuationCards result={result} />}
      {result && tab === "data" && <DataTab result={result} />}
      {result && tab === "experts" && <ExpertsTab result={result} />}
    </div>
  );
}
