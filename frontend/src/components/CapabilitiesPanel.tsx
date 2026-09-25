"use client";

import { useEffect, useState } from "react";
import { ChevronDown, ChevronRight, Loader2 } from "lucide-react";
import {
  AgentSpecInfo,
  RegistryCatalog,
  SkillSpec,
  ToolSpec,
  getRegistry,
  getSkill,
} from "@/lib/api";

/** 能力目录数据（技能 / 工具 / 智能体），各列表共用一次拉取 */
function useRegistry() {
  const [catalog, setCatalog] = useState<RegistryCatalog | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    void getRegistry()
      .then((c) => alive && setCatalog(c))
      .catch((e) => alive && setError(e instanceof Error ? e.message : String(e)));
    return () => {
      alive = false;
    };
  }, []);

  return { catalog, error };
}

function Status({ error, empty }: { error: string | null; empty: boolean }) {
  if (error) {
    return (
      <p className="rounded-[var(--radius-field)] border border-error/30 bg-error/[0.05] px-3 py-2 text-[14px] text-base-content">
        {error}
      </p>
    );
  }
  if (empty) {
    return (
      <p className="flex items-center gap-2 py-6 text-[14px] text-base-content/90">
        <Loader2 className="h-4 w-4 animate-spin" />
        正在读取能力目录…
      </p>
    );
  }
  return null;
}

function Tags({ items }: { items: string[] }) {
  if (items.length === 0) return null;
  return (
    <span className="flex flex-wrap gap-1">
      {items.map((t) => (
        <span key={t} className="badge badge-sm badge-ghost font-mono text-[12px]">
          {t}
        </span>
      ))}
    </span>
  );
}

/* ---------- 技能 ---------- */

function SkillRow({ skill }: { skill: SkillSpec }) {
  const [open, setOpen] = useState(false);
  const [body, setBody] = useState<string | null>(null);
  const [owners, setOwners] = useState<{ key: string; name: string }[]>([]);
  const [loading, setLoading] = useState(false);

  const toggle = async () => {
    const next = !open;
    setOpen(next);
    if (next && body === null) {
      setLoading(true);
      const detail = await getSkill(skill.name);
      setBody(detail?.body ?? "（无法加载正文）");
      setOwners(detail?.agents ?? []);
      setLoading(false);
    }
  };

  return (
    <div className="rounded-[var(--radius-box)] border border-base-300 bg-base-100">
      <button
        onClick={toggle}
        className="flex w-full items-start gap-2 px-3 py-2.5 text-left hover:bg-base-200/60"
      >
        {open ? (
          <ChevronDown className="mt-0.5 h-3.5 w-3.5 shrink-0 text-base-content/90" />
        ) : (
          <ChevronRight className="mt-0.5 h-3.5 w-3.5 shrink-0 text-base-content/90" />
        )}
        <span className="flex min-w-0 flex-1 flex-col gap-1">
          <span className="flex flex-wrap items-center gap-2">
            <code className="rounded bg-base-200 px-1.5 py-0.5 font-mono text-[14px] font-semibold text-base-content">
              {skill.name}
            </code>
            <Tags items={skill.tags} />
          </span>
          <span className="text-[14px] leading-relaxed text-base-content/90">
            {skill.description || "（无描述）"}
          </span>
          {skill.tools.length > 0 && (
            <span className="flex flex-wrap items-center gap-1 text-[13px] text-base-content/90">
              <span>用到工具：</span>
              {skill.tools.map((t) => (
                <code key={t} className="font-mono">
                  {t}
                </code>
              ))}
            </span>
          )}
        </span>
      </button>

      {open && (
        <div className="border-t border-base-300 px-3 py-2">
          {loading ? (
            <span className="flex items-center gap-1.5 text-[14px] text-base-content/90">
              <Loader2 className="h-3 w-3 animate-spin" />
              加载中…
            </span>
          ) : (
            <>
              {owners.length > 0 && (
                <p className="mb-2 flex flex-wrap items-center gap-1.5 text-[14px] text-base-content/90">
                  <span>持有该技能的专家：</span>
                  {owners.map((a) => (
                    <span key={a.key} className="badge badge-sm badge-outline">
                      {a.name}
                    </span>
                  ))}
                  <span>
                    （对话里输入 <code className="font-mono">/{skill.name}</code> 可直接指定）
                  </span>
                </p>
              )}
              <pre className="prose-report max-h-72 overflow-auto rounded-[var(--radius-field)] bg-base-200/60 p-2.5 font-mono text-[13px] whitespace-pre-wrap text-base-content">
                {body}
              </pre>
            </>
          )}
        </div>
      )}
    </div>
  );
}

export function CapabilitiesSkills() {
  const { catalog, error } = useRegistry();
  if (!catalog) return <Status error={error} empty />;
  return (
    <div className="flex flex-col gap-2">
      <p className="text-[13px] text-base-content/90">
        在输入框输入 <code className="font-mono">/</code> 可以直接选择技能，例如{" "}
        <code className="font-mono">/valuation_modeling 给这家公司估值</code>
      </p>
      {catalog.skills.map((s) => (
        <SkillRow key={s.name} skill={s} />
      ))}
    </div>
  );
}

/* ---------- 工具 ---------- */

function ToolRow({ tool }: { tool: ToolSpec }) {
  const params = Object.entries(tool.input_schema ?? {});
  return (
    <div className="rounded-[var(--radius-box)] border border-base-300 bg-base-100 px-3 py-2.5">
      <div className="flex flex-wrap items-center gap-2">
        <code className="rounded bg-base-200 px-1.5 py-0.5 font-mono text-[14px] font-semibold text-base-content">
          {tool.name}
        </code>
        <Tags items={tool.tags} />
      </div>
      <p className="mt-1 text-[14px] leading-relaxed text-base-content/90">
        {tool.description || "（无描述）"}
      </p>
      {params.length > 0 && (
        <ul className="mt-1.5 flex flex-col gap-0.5">
          {params.map(([k, v]) => (
            <li key={k} className="font-mono text-[13px] text-base-content/90">
              <span className="font-semibold text-base-content">{k}</span>
              <span> · {v}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function CapabilitiesTools() {
  const { catalog, error } = useRegistry();
  if (!catalog) return <Status error={error} empty />;
  return (
    <div className="flex flex-col gap-2">
      {catalog.tools.map((t) => (
        <ToolRow key={t.name} tool={t} />
      ))}
    </div>
  );
}

/* ---------- 智能体 ---------- */

function AgentRow({ agent }: { agent: AgentSpecInfo }) {
  return (
    <div className="rounded-[var(--radius-box)] border border-base-300 bg-base-100 px-3 py-2.5">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[14px] font-semibold text-base-content">
          {agent.name}
        </span>
        <code className="font-mono text-[13px] text-base-content/90">
          {agent.key}
        </code>
        <span className="badge badge-sm badge-ghost font-mono text-[12px]">
          上限 {agent.max_steps} 步
        </span>
      </div>
      <p className="mt-1 text-[14px] text-base-content/90">{agent.role}</p>
      <div className="mt-1.5 flex flex-col gap-0.5 text-[13px] text-base-content/90">
        {agent.tools.length > 0 && (
          <span>
            <span>工具：</span>
            <span className="font-mono">{agent.tools.join("、")}</span>
          </span>
        )}
        {agent.skills.length > 0 && (
          <span>
            <span>技能：</span>
            <span className="font-mono">{agent.skills.join("、")}</span>
          </span>
        )}
      </div>
    </div>
  );
}

export function CapabilitiesAgents() {
  const { catalog, error } = useRegistry();
  if (!catalog) return <Status error={error} empty />;
  return (
    <div className="flex flex-col gap-2">
      {catalog.agents.map((a) => (
        <AgentRow key={a.key} agent={a} />
      ))}
    </div>
  );
}
