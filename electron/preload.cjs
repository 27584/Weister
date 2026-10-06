/**
 * Weister 桌面客户端 — 预加载脚本
 *
 * 只做两件事：
 *   1. 注入运行时常量（API_BASE 由主进程动态分配端口后传入）
 *   2. 暴露窗口控制 IPC（最小化 / 最大化 / 关闭 + 最大化状态订阅）
 *
 * 不再注入任何标题栏 DOM 与 CSS。无边框窗口的标题栏就是前端页面自己的顶栏
 * （frontend/src/app/page.tsx 的 <header>：整条可拖动，最右侧是最小化/最大化/关闭），
 * 拖动区与按钮由 lib/desktop.ts + components/WindowControls.tsx 驱动。
 *
 * 因此这里也不再给根节点补 padding-top —— 页面高度天然等于视口，
 * 不会出现「两条导航栏叠在一起」和多出来的滚动条。
 */

const { contextBridge, ipcRenderer } = require("electron");

const apiBase =
  process.env.WEISTER_API_BASE || `http://127.0.0.1:${process.env.WEISTER_BACKEND_PORT || 8000}`;

contextBridge.exposeInMainWorld("WEISTER", {
  API_BASE: apiBase,
  IS_DESKTOP: true,
  VERSION: process.env.npm_package_version || "0.3.1",
  minimize: () => ipcRenderer.send("wt:minimize"),
  maximize: () => ipcRenderer.send("wt:maximize"),
  close: () => ipcRenderer.send("wt:close"),
  /**
   * 订阅最大化状态，供顶栏按钮在「最大化 / 还原」图标间切换。
   * 返回取消订阅的函数，组件卸载时调用。
   */
  onMaximizeState: (cb) => {
    const listener = (_e, isMax) => cb(Boolean(isMax));
    ipcRenderer.on("wt:maximized", listener);
    return () => ipcRenderer.removeListener("wt:maximized", listener);
  },
});
