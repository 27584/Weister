/**
 * 桌面客户端能力探测 —— preload 注入的 window.WEISTER 桥的唯一读取入口。
 *
 * 浏览器（next dev / 直接访问）下桥不存在，返回 null：
 * 顶栏不加拖动区、不渲染窗口三按钮，页面表现与 Web 版完全一致。
 */

"use client";

import { useSyncExternalStore } from "react";

export interface WeisterBridge {
  API_BASE: string;
  IS_DESKTOP: true;
  VERSION: string;
  minimize(): void;
  maximize(): void;
  close(): void;
  /** 订阅最大化状态，返回取消订阅函数 */
  onMaximizeState(cb: (isMaximized: boolean) => void): () => void;
}

declare global {
  interface Window {
    WEISTER?: WeisterBridge;
  }
}

export function getDesktopBridge(): WeisterBridge | null {
  if (typeof window === "undefined") return null;
  return window.WEISTER?.IS_DESKTOP ? window.WEISTER : null;
}

/** 桥由 preload 一次性注入、引用稳定，无需真正订阅 */
const subscribeNoop = () => () => {};

/**
 * 组件内读取桥。首屏与服务端一律 null，因此不会造成 hydration 结构错位：
 * 桌面端在客户端挂载后才出现拖动区与窗口按钮。
 */
export function useDesktopBridge(): WeisterBridge | null {
  return useSyncExternalStore(subscribeNoop, getDesktopBridge, () => null);
}
