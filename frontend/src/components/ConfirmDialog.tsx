"use client";

import { useEffect, useState } from "react";

export interface ConfirmOptions {
  title: string;
  message?: string;
  confirmText?: string;
  cancelText?: string;
  /** 危险操作（删除等）用红色确认按钮 */
  danger?: boolean;
}

interface ConfirmState extends ConfirmOptions {
  resolve: (ok: boolean) => void;
}

let openConfirm: ((opts: ConfirmOptions) => Promise<boolean>) | null = null;

/**
 * 显示一个与主界面风格一致的自定义确认框（替代原生 window.confirm）。
 *
 * 用法：
 *   const ok = await confirmDialog({ title: "删除对话？", danger: true });
 */
export function confirmDialog(opts: ConfirmOptions): Promise<boolean> {
  if (!openConfirm) {
    // 组件尚未挂载时的兜底（极少发生）
    return Promise.resolve(window.confirm(`${opts.title}\n${opts.message ?? ""}`));
  }
  return openConfirm(opts);
}

/** 挂载一次即可（放在页面根部） */
export function ConfirmHost() {
  const [state, setState] = useState<ConfirmState | null>(null);

  useEffect(() => {
    openConfirm = (opts) =>
      new Promise<boolean>((resolve) => {
        setState({ ...opts, resolve });
      });
    return () => {
      openConfirm = null;
    };
  }, []);

  useEffect(() => {
    if (!state) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        state.resolve(false);
        setState(null);
      } else if (e.key === "Enter") {
        state.resolve(true);
        setState(null);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [state]);

  if (!state) return null;

  const close = (ok: boolean) => {
    state.resolve(ok);
    setState(null);
  };

  return (
    <div className="fixed inset-0 z-[9999] flex items-center justify-center">
      <button
        className="absolute inset-0 cursor-default bg-black/40"
        onClick={() => close(false)}
        aria-label="取消"
      />
      <div className="relative z-10 w-[380px] max-w-[90vw] rounded-[var(--radius-box)] border border-base-300 bg-base-100 p-5 shadow-xl">
        <h3 className="mb-2 text-[15px] font-semibold text-base-content">{state.title}</h3>
        {state.message ? (
          <p className="mb-5 whitespace-pre-line text-[13px] leading-relaxed text-base-content/80">
            {state.message}
          </p>
        ) : (
          <div className="mb-3" />
        )}
        <div className="flex justify-end gap-2">
          <button
            onClick={() => close(false)}
            className="btn btn-sm border-base-300 bg-base-100 text-base-content/90"
          >
            {state.cancelText || "取消"}
          </button>
          <button
            onClick={() => close(true)}
            className={`btn btn-sm ${
              state.danger
                ? "border-error bg-error text-error-content hover:bg-error/90"
                : "btn-primary"
            }`}
          >
            {state.confirmText || "确定"}
          </button>
        </div>
      </div>
    </div>
  );
}
