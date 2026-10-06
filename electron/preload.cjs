/**
 * Weister 桌面客户端 — 预加载脚本
 *
 * 最小化设计：不暴露 Node API，仅注入客户端所需的运行时常量。
 *
 * API_BASE 由主进程在启动时动态分配后端端口并注入（WEISTER_API_BASE 环境变量），
 * 渲染进程通过 window.WEISTER.API_BASE 读取——这样端口冲突时无需重新构建前端。
 */

const { contextBridge } = require("electron");

const apiBase =
  process.env.WEISTER_API_BASE || `http://127.0.0.1:${process.env.WEISTER_BACKEND_PORT || 8000}`;

contextBridge.exposeInMainWorld("WEISTER", {
  /** 后端 API 地址（主进程动态分配，运行时注入） */
  API_BASE: apiBase,
  /** 标识运行在桌面客户端中 */
  IS_DESKTOP: true,
  /** 应用版本 */
  VERSION: process.env.npm_package_version || "0.3.1",
});