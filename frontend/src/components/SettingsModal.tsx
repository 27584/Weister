"use client";

import { useState } from "react";
import { Bot, Settings2, Sparkles, Wrench, X } from "lucide-react";
import { SettingsPanel } from "./SettingsPanel";
import {
  CapabilitiesAgents,
  CapabilitiesSkills,
  CapabilitiesTools,
} from "./CapabilitiesPanel";
import type { LLMStore } from "@/lib/types";

interface Props {
  open: boolean;
  store: LLMStore;
  onChange: (store: LLMStore) => void;
  onClose: () => void;
}

type Tab = "model" | "skills" | "tools" | "agents";

const TABS: { key: Tab; label: string; icon: typeof Wrench }[] = [
  { key: "model", label: "模型配置", icon: Settings2 },
  { key: "skills", label: "技能", icon: Sparkles },
  { key: "tools", label: "工具", icon: Wrench },
  { key: "agents", label: "智能体", icon: Bot },
];

export function SettingsModal({ open, store, onChange, onClose }: Props) {
  const [tab, setTab] = useState<Tab>("model");
  if (!open) return null;

  return (
    <div className="modal modal-open" role="dialog" aria-modal="true">
      {/* 固定尺寸：切标签页时内容多少都不改变弹窗大小（内容区自己滚动） */}
      <div className="modal-box flex h-[85vh] max-w-3xl flex-col animate__animated animate__fadeIn animate__faster">
        <div className="mb-3 flex shrink-0 items-center justify-between">
          <h3 className="text-[14px] font-semibold text-base-content">设置</h3>
          <button
            onClick={onClose}
            className="btn btn-ghost btn-xs px-1.5 text-base-content/90"
            aria-label="关闭"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>

        <div role="tablist" className="tabs tabs-boxed mb-3 shrink-0">
          {TABS.map(({ key, label, icon: Icon }) => (
            <button
              key={key}
              role="tab"
              onClick={() => setTab(key)}
              className={`tab gap-1.5 ${tab === key ? "tab-active" : ""}`}
            >
              <Icon className="h-3.5 w-3.5" />
              {label}
            </button>
          ))}
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto pr-1">
          {tab === "model" && <SettingsPanel store={store} onChange={onChange} />}
          {tab === "skills" && <CapabilitiesSkills />}
          {tab === "tools" && <CapabilitiesTools />}
          {tab === "agents" && <CapabilitiesAgents />}
        </div>
      </div>

      <button
        className="modal-backdrop cursor-default"
        onClick={onClose}
        aria-label="关闭"
      />
    </div>
  );
}
