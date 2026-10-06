/**
 * Weister 桌面客户端 — 预加载脚本
 *
 * 最小化设计：不暴露 Node API，仅注入客户端所需的常量。
 * 渲染进程通过 window.WEISTER 访问配置。
 */

const { contextBridge } = require("electron");

contextBridge.exposeInMainWorld("WEISTER", {
  /** 后端 API 地址（与前端 .env.production 一致） */
  API_BASE: "http://127.0.0.1:8000",
  /** 标识运行在桌面客户端中 */
  IS_DESKTOP: true,
  /** 应用版本 */
  VERSION: process.env.npm_package_version || "0.3.1",
});
