/**
 * 后端 API 基地址的唯一解析入口。
 *
 * 优先级：
 *   1. 桌面客户端：preload 注入的 window.WEISTER.API_BASE（主进程
 *      findFreePort 选出的真实端口，端口冲突无需重新构建前端）
 *   2. 浏览器开发模式：NEXT_PUBLIC_API_BASE
 *   3. 回退默认端口（仅 next dev 用，桌面端永远不会走到这里）
 *
 * 全前端只在这里出现一次端口常量，其余模块一律 import { API_BASE }。
 */

export function resolveApiBase(): string {
  if (typeof window !== "undefined") {
    const injected = (window as { WEISTER?: { API_BASE?: string } }).WEISTER
      ?.API_BASE;
    if (injected) return injected;
  }
  return process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:8000";
}

export const API_BASE: string = resolveApiBase();
