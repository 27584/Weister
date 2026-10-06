/**
 * Weister 桌面客户端 — 预加载脚本
 *
 * 1. 注入运行时常量（API_BASE 由主进程动态分配端口后传入）
 * 2. 注入自定义标题栏（无边框窗口的可拖动栏 + 最小化/最大化/关闭按钮）
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
});

// ---- 自定义标题栏 ----
//
// 关键：不能给 body 加 padding（会把页面根的 h-screen/100vh 撑出滚动条）。
// 改为给应用根节点设 box-sizing: border-box + height: 100vh + padding-top，
// 这样标题栏高度被算进 100vh 内，总高恰好等于视口，不产生滚动条。
const TITLEBAR_CSS = `
  #weister-titlebar {
    position: fixed; top: 0; left: 0; right: 0; height: 34px;
    display: flex; align-items: center; justify-content: space-between;
    background: #ffffff; border-bottom: 1px solid #e3e6ec;
    -webkit-app-region: drag; user-select: none; z-index: 2147483647;
    font-family: -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif;
  }
  #weister-titlebar .wt-title {
    font-size: 12px; color: #5b6474; padding-left: 12px; letter-spacing: 0.2px;
  }
  #weister-titlebar .wt-btns { display: flex; -webkit-app-region: no-drag; height: 100%; }
  #weister-titlebar .wt-btn {
    width: 46px; height: 100%; border: 0; background: transparent; cursor: default;
    display: flex; align-items: center; justify-content: center;
    color: #1a1f2b; transition: background 0.12s;
  }
  #weister-titlebar .wt-btn:hover { background: #f5f6f8; }
  #weister-titlebar .wt-btn.wt-close:hover { background: #e81123; color: #ffffff; }
  #weister-titlebar .wt-btn svg { width: 11px; height: 11px; }

  /* 清零默认外边距：body 默认 8px margin 会把 100vh 内容推出视口产生滚动条 */
  html, body { margin: 0 !important; padding: 0 !important; overflow: hidden !important; }
`;

/**
 * 给应用根节点补偿标题栏高度。
 *
 * 不能给 body 加 padding（页面根用 h-screen/100vh，会被撑出滚动条）。
 * 改为直接给根节点设 box-sizing + height:100vh + padding-top:34px，
 * 标题栏高度算进 100vh 内，总高恰好等于视口。
 */
function applyRootOffset() {
  const bar = document.getElementById("weister-titlebar");
  const roots = Array.from(document.body.children).filter((el) => el !== bar);
  for (const el of roots) {
    if (el.tagName === "SCRIPT" || el.tagName === "STYLE") continue;
    // 跳过空的 portal/占位容器（无子节点、无文本），它们不需要补偿
    if (!el.children.length && !(el.textContent || "").trim()) continue;
    el.style.boxSizing = "border-box";
    el.style.height = "100vh";
    el.style.paddingTop = "34px";
    el.style.margin = "0";
    el.style.overflow = "hidden";
  }
}

function injectTitlebar() {
  // loading.html 自带标题栏，跳过注入
  if (document.getElementById("weister-titlebar") || document.getElementById("b-close")) return;

  const style = document.createElement("style");
  style.textContent = TITLEBAR_CSS;
  document.head.appendChild(style);

  const bar = document.createElement("div");
  bar.id = "weister-titlebar";
  bar.innerHTML = `
    <div class="wt-title">Weister</div>
    <div class="wt-btns">
      <button class="wt-btn" id="wt-min" title="最小化">
        <svg viewBox="0 0 12 12"><rect x="1" y="5.5" width="10" height="1" fill="currentColor"/></svg>
      </button>
      <button class="wt-btn" id="wt-max" title="最大化">
        <svg viewBox="0 0 12 12"><rect x="1.5" y="1.5" width="9" height="9" fill="none" stroke="currentColor" stroke-width="1.2"/></svg>
      </button>
      <button class="wt-btn wt-close" id="wt-close" title="关闭">
        <svg viewBox="0 0 12 12"><path d="M2 2 L10 10 M10 2 L2 10" stroke="currentColor" stroke-width="1.2"/></svg>
      </button>
    </div>
  `;
  document.body.appendChild(bar);
  applyRootOffset();

  // React 可能随后重挂根节点，观察 body 子节点变化重新补偿
  const mo = new MutationObserver(() => applyRootOffset());
  mo.observe(document.body, { childList: true });

  document.getElementById("wt-min").addEventListener("click", () => ipcRenderer.send("wt:minimize"));
  document.getElementById("wt-max").addEventListener("click", () => ipcRenderer.send("wt:maximize"));
  document.getElementById("wt-close").addEventListener("click", () => ipcRenderer.send("wt:close"));

  // 最大化状态同步按钮图标
  ipcRenderer.on("wt:maximized", (_e, isMax) => {
    const btn = document.getElementById("wt-max");
    if (!btn) return;
    btn.innerHTML = isMax
      ? `<svg viewBox="0 0 12 12"><rect x="1.5" y="3.5" width="7" height="7" fill="none" stroke="currentColor" stroke-width="1.2"/><path d="M3.5 3.5 V1.5 H10.5 V8.5 H8.5" fill="none" stroke="currentColor" stroke-width="1.2"/></svg>`
      : `<svg viewBox="0 0 12 12"><rect x="1.5" y="1.5" width="9" height="9" fill="none" stroke="currentColor" stroke-width="1.2"/></svg>`;
    btn.title = isMax ? "还原" : "最大化";
  });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", injectTitlebar);
} else {
  injectTitlebar();
}
