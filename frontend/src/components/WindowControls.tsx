"use client";

import { useEffect, useState } from "react";
import { useDesktopBridge } from "@/lib/desktop";

/**
 * 窗口控制按钮（最小化 / 最大化·还原 / 关闭）。
 *
 * 只存在于页面顶栏的右端 —— 无边框窗口的标题栏就是顶栏本身，
 * Electron 不再额外注入一条。Web / dev 模式下桥不存在，整块不渲染。
 */
export function WindowControls() {
  const bridge = useDesktopBridge();
  const [isMaximized, setIsMaximized] = useState(false);

  // 最大化状态由主进程推送（maximize/unmaximize 事件），用于切换按钮图标
  useEffect(() => {
    if (!bridge) return;
    return bridge.onMaximizeState(setIsMaximized);
  }, [bridge]);

  if (!bridge) return null;

  const cls =
    "app-no-drag flex h-[26px] w-[34px] shrink-0 items-center justify-center rounded-[var(--radius-field)] border-0 bg-transparent text-base-content/70 transition-colors hover:bg-base-200 hover:text-base-content";

  return (
    <div className="app-no-drag flex shrink-0 items-center">
      <button
        type="button"
        className={cls}
        title="最小化"
        onClick={() => bridge.minimize()}
      >
        <svg viewBox="0 0 12 12" className="h-3 w-3">
          <rect x="1.5" y="5.5" width="9" height="1" fill="currentColor" />
        </svg>
      </button>

      <button
        type="button"
        className={cls}
        title={isMaximized ? "还原" : "最大化"}
        onClick={() => bridge.maximize()}
      >
        {isMaximized ? (
          <svg viewBox="0 0 12 12" className="h-3 w-3">
            <rect
              x="1.5"
              y="3.5"
              width="7"
              height="7"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.1"
            />
            <path
              d="M3.5 3.5 V1.5 H10.5 V8.5 H8.5"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.1"
            />
          </svg>
        ) : (
          <svg viewBox="0 0 12 12" className="h-3 w-3">
            <rect
              x="1.5"
              y="1.5"
              width="9"
              height="9"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.1"
            />
          </svg>
        )}
      </button>

      <button
        type="button"
        className={cls + " hover:bg-error hover:text-error-content"}
        title="关闭"
        onClick={() => bridge.close()}
      >
        <svg viewBox="0 0 12 12" className="h-3 w-3">
          <path
            d="M2.5 2.5 L9.5 9.5 M9.5 2.5 L2.5 9.5"
            stroke="currentColor"
            strokeWidth="1.1"
            fill="none"
          />
        </svg>
      </button>
    </div>
  );
}
