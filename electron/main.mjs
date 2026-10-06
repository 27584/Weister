/**
 * Weister 桌面客户端 — Electron 主进程
 *
 * 职责：
 * 1. 启动内嵌 Python 后端（backend.exe）和前端 standalone server
 * 2. 管理两个子进程的生命周期（退出时一并终止）
 * 3. 创建 BrowserWindow 加载前端页面
 *
 * 数据目录：%APPDATA%/Weister/data
 * 后端端口：8000
 * 前端端口：3000
 */

import { app, BrowserWindow, shell, ipcMain } from "electron";
import { spawn, exec } from "node:child_process";
import { createRequire } from "node:module";
import { existsSync, mkdirSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import http from "node:http";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const require = createRequire(import.meta.url);

// 资源路径：开发模式 vs 打包模式
// 开发模式：从 electron/ 目录上溯到项目根
// 打包模式：extraResources 放在 process.resourcesPath 下
const isDev = !app.isPackaged;
const ROOT = isDev ? join(__dirname, "..") : process.resourcesPath;

// 后端 Python 解释器路径
// 开发模式：用 backend/.venv 的 Python
// 打包模式：用嵌入的 python/python/ 目录下的 python.exe
const BACKEND_PYTHON = isDev
  ? join(ROOT, "backend", ".venv", "Scripts", "python.exe")
  : join(ROOT, "backend", "python", "python.exe");

const BACKEND_CWD = join(ROOT, "backend");
// 用 `-m app`（app/__main__.py 会读 HOST/PORT 环境变量），
// 不要直接用 `-m uvicorn`——uvicorn 只认命令行参数，不读 PORT 环境变量，
// 会静默退回默认 8000 端口，导致与 findFreePort 选出的端口不一致。
const BACKEND_ARGS = ["-m", "app"];

// 前端 standalone server 路径
const FRONTEND_SERVER = isDev
  ? join(ROOT, "frontend", ".next", "standalone", "server.js")
  : join(ROOT, "frontend", "server.js");

// 用户数据目录
const USER_DATA_DIR = join(app.getPath("userData"), "data");

// 运行时选定的端口（启动时动态分配，避免占用冲突）
let BACKEND_PORT = 8000;
let FRONTEND_PORT = 3000;

let backendProcess = null;
let frontendProcess = null;
let mainWindow = null;
let loadingWindow = null;

/**
 * 查找可用端口：从 preferred 开始，被占用则 +1 递增（最多试 20 个）
 */
function findFreePort(preferred) {
  const net = require("node:net");
  return new Promise((resolve, reject) => {
    let port = preferred;
    const tries = 20;

    const attempt = (p, left) => {
      const server = net.createServer();
      server.once("error", (err) => {
        if (err.code === "EADDRINUSE" && left > 0) {
          attempt(p + 1, left - 1);
        } else {
          reject(err);
        }
      });
      server.once("listening", () => {
        server.close(() => resolve(p));
      });
      server.listen(p, "127.0.0.1");
    };

    attempt(port, tries);
  });
}

/**
 * 确保数据目录存在
 */
function ensureDataDir() {
  if (!existsSync(USER_DATA_DIR)) {
    mkdirSync(USER_DATA_DIR, { recursive: true });
  }
}

/**
 * 杀掉占用指定端口的进程（Windows）
 */
function killPort(port) {
  return new Promise((resolve) => {
    exec(
      `powershell -Command "Get-NetTCPConnection -LocalPort ${port} -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"`,
      () => resolve(),
    );
  });
}

/**
 * 启动后端进程
 */
function startBackend() {
  ensureDataDir();

  const env = {
    ...process.env,
    DATA_DIR: USER_DATA_DIR,
    PORT: String(BACKEND_PORT),
    HOST: "127.0.0.1",
    CORS_ORIGINS: `http://localhost:${FRONTEND_PORT},http://127.0.0.1:${FRONTEND_PORT}`,
  };

  console.log(`[main] Starting backend: ${BACKEND_PYTHON} ${BACKEND_ARGS.join(" ")}`);
  console.log(`[main] DATA_DIR=${USER_DATA_DIR}`);

  backendProcess = spawn(BACKEND_PYTHON, BACKEND_ARGS, {
    cwd: BACKEND_CWD,
    env,
    windowsHide: false,
  });

  backendProcess.stdout?.on("data", (data) => {
    console.log(`[backend] ${data.toString().trim()}`);
  });

  backendProcess.stderr?.on("data", (data) => {
    console.error(`[backend] ${data.toString().trim()}`);
  });

  backendProcess.on("exit", (code) => {
    console.log(`[backend] exited with code ${code}`);
    backendProcess = null;
  });
}

/**
 * 启动前端 standalone server
 */
function startFrontend() {
  const env = {
    ...process.env,
    PORT: String(FRONTEND_PORT),
    NODE_ENV: "production",
  };

  console.log(`[main] Starting frontend via Electron Node runtime: ${FRONTEND_SERVER}`);

  // 用 Electron 自带的 Node 运行时启动前端，不依赖系统安装 Node.js。
  // ELECTRON_RUN_AS_NODE=1 让 electron.exe 以纯 Node 模式运行。
  frontendProcess = spawn(process.execPath, [FRONTEND_SERVER], {
    cwd: dirname(FRONTEND_SERVER),
    env: {
      ...env,
      ELECTRON_RUN_AS_NODE: "1",
    },
    windowsHide: false,
  });

  frontendProcess.stdout?.on("data", (data) => {
    console.log(`[frontend] ${data.toString().trim()}`);
  });

  frontendProcess.stderr?.on("data", (data) => {
    console.error(`[frontend] ${data.toString().trim()}`);
  });

  frontendProcess.on("exit", (code) => {
    console.log(`[frontend] exited with code ${code}`);
    frontendProcess = null;
  });
}

/**
 * 轮询等待服务就绪
 */
function waitForService(name, port, maxAttempts = 30, intervalMs = 1000) {
  return new Promise((resolve, reject) => {
    let attempts = 0;

    const check = () => {
      attempts++;
      const req = http.get(
        `http://127.0.0.1:${port}/api/health`,
        (res) => {
          if (res.statusCode === 200) {
            console.log(`[main] ${name} ready (port ${port})`);
            resolve();
          } else if (attempts < maxAttempts) {
            setTimeout(check, intervalMs);
          } else {
            reject(new Error(`${name} health check failed after ${maxAttempts}s`));
          }
          res.destroy();
        },
      );

      req.on("error", () => {
        if (attempts < maxAttempts) {
          setTimeout(check, intervalMs);
        } else {
          reject(new Error(`${name} not responding after ${maxAttempts}s`));
        }
      });

      req.setTimeout(2000, () => {
        req.destroy();
        if (attempts < maxAttempts) {
          setTimeout(check, intervalMs);
        } else {
          reject(new Error(`${name} timeout after ${maxAttempts}s`));
        }
      });
    };

    check();
  });
}

/**
 * 创建主窗口
 */
/**
 * 创建加载窗口：启动后立即显示，避免用户对着空白窗口等待
 */
function createLoadingWindow() {
  loadingWindow = new BrowserWindow({
    width: 460,
    height: 340,
    frame: false,
    resizable: false,
    center: true,
    show: true,
    backgroundColor: "#ffffff",
    title: "Weister",
    icon: join(__dirname, "build", "icon.ico"),
    webPreferences: {
      preload: join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  loadingWindow.loadFile(join(__dirname, "loading.html"));
  loadingWindow.on("closed", () => {
    loadingWindow = null;
  });
}

/**
 * 向加载窗口推送进度
 */
function reportProgress(pct, text) {
  if (!loadingWindow || loadingWindow.isDestroyed()) return;
  loadingWindow.webContents.executeJavaScript(
    `window.__weisterOnProgress && window.__weisterOnProgress(${pct}, ${JSON.stringify(text)})`,
  );
}

function reportError(msg) {
  if (!loadingWindow || loadingWindow.isDestroyed()) return;
  loadingWindow.webContents.executeJavaScript(
    `window.__weisterOnError && window.__weisterOnError(${JSON.stringify(msg)})`,
  );
}

/**
 * 轮询等待前端 HTTP 服务可用
 */
function waitForHttp(url, maxAttempts = 40, intervalMs = 500) {
  return new Promise((resolve, reject) => {
    let attempts = 0;
    const check = () => {
      attempts++;
      const req = http.get(url, (res) => {
        res.resume();
        resolve();
      });
      req.on("error", () => {
        if (attempts < maxAttempts) setTimeout(check, intervalMs);
        else reject(new Error(`timeout: ${url}`));
      });
      req.setTimeout(2000, () => {
        req.destroy();
        if (attempts < maxAttempts) setTimeout(check, intervalMs);
        else reject(new Error(`timeout: ${url}`));
      });
    };
    check();
  });
}

/**
 * 统一的标题栏窗口控制 IPC 注册。
 *
 * 必须在 app.whenReady 时注册（而不是在 createWindow 内），
 * 否则加载窗口阶段的关闭/最小化按钮点击无人响应（handler 尚未注册）。
 * 操作目标是「当前活跃窗口」——优先 mainWindow，否则 loadingWindow。
 */
function registerWindowIpc() {
  const active = () => mainWindow || loadingWindow || BrowserWindow.getFocusedWindow();

  ipcMain.on("wt:minimize", () => {
    const w = active();
    if (w && !w.isDestroyed()) w.minimize();
  });

  ipcMain.on("wt:maximize", () => {
    const w = active();
    if (!w || w.isDestroyed()) return;
    if (w.isMaximized()) w.unmaximize();
    else w.maximize();
  });

  ipcMain.on("wt:close", () => {
    // 加载阶段关窗 → 直接退出整个应用；主界面阶段 → 关闭主窗口
    if (!mainWindow || mainWindow.isDestroyed()) {
      app.quit();
      return;
    }
    if (!mainWindow.isDestroyed()) mainWindow.close();
  });
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 1024,
    minHeight: 700,
    title: "Weister",
    icon: join(__dirname, "build", "icon.ico"),
    frame: false, // 无边框：用页面内的自定义标题栏（可拖动 + 三按钮）
    backgroundColor: "#ffffff",
    webPreferences: {
      preload: join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  // 自定义标题栏按钮的 IPC 处理在 app 启动时统一注册（见 registerWindowIpc）

  // 同步最大化状态给渲染进程（切换按钮图标）
  mainWindow.on("maximize", () => mainWindow?.webContents.send("wt:maximized", true));
  mainWindow.on("unmaximize", () => mainWindow?.webContents.send("wt:maximized", false));

  // 开发模式打开 DevTools
  if (isDev) {
    mainWindow.webContents.openDevTools();
  }

  // 外部链接在系统浏览器打开
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: "deny" };
  });

  mainWindow.loadURL(`http://localhost:${FRONTEND_PORT}`);

  mainWindow.on("closed", () => {
    mainWindow = null;
  });
}

/**
 * 清理所有子进程
 */
function cleanup() {
  if (backendProcess) {
    console.log("[main] Killing backend process");
    backendProcess.kill();
    backendProcess = null;
  }
  if (frontendProcess) {
    console.log("[main] Killing frontend process");
    frontendProcess.kill();
    frontendProcess = null;
  }
}

// ======== 应用生命周期 ========

app.whenReady().then(async () => {
  console.log("[main] Weister desktop starting...");
  console.log(`[main] userData: ${app.getPath("userData")}`);
  console.log(`[main] isDev: ${isDev}`);

  // 标题栏窗口控制（加载窗口阶段就要可用，不能等到 createWindow）
  registerWindowIpc();

  // 立即显示加载窗口，不要让用户对着空白/无响应等待
  createLoadingWindow();
  reportProgress(8, "分配端口…");

  // 动态分配空闲端口，避免与其他应用冲突（不再强杀端口上的进程）
  BACKEND_PORT = await findFreePort(8000);
  FRONTEND_PORT = await findFreePort(3000);
  console.log(`[main] Selected ports: backend=${BACKEND_PORT} frontend=${FRONTEND_PORT}`);
  reportProgress(20, "启动后端服务…");

  // 通过环境变量把实际端口传给 preload（渲染进程读取）
  process.env.WEISTER_API_BASE = `http://127.0.0.1:${BACKEND_PORT}`;

  try {
    // 1. 启动后端
    startBackend();
    reportProgress(35, "等待后端就绪…");
    await waitForService("backend", BACKEND_PORT, 60, 1000);

    // 2. 启动前端
    reportProgress(65, "启动界面服务…");
    startFrontend();

    reportProgress(80, "等待界面就绪…");
    await waitForHttp(`http://127.0.0.1:${FRONTEND_PORT}/`, 60, 500);

    // 3. 服务就绪，切到主界面
    reportProgress(100, "加载应用…");
    createWindow();

    if (loadingWindow && !loadingWindow.isDestroyed()) {
      loadingWindow.close();
      loadingWindow = null;
    }
  } catch (err) {
    console.error("[main] Startup failed:", err);
    reportError(String(err && err.message ? err.message : err));
  }
});

app.on("window-all-closed", () => {
  cleanup();
  app.quit();
});

app.on("before-quit", () => {
  cleanup();
});

// 捕获未处理的退出信号
process.on("SIGINT", () => {
  cleanup();
  app.quit();
});

process.on("SIGTERM", () => {
  cleanup();
  app.quit();
});
