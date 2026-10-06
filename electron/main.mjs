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

import { app, BrowserWindow, shell } from "electron";
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
const BACKEND_ARGS = ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"];

// 前端 standalone server 路径
const FRONTEND_SERVER = isDev
  ? join(ROOT, "frontend", ".next", "standalone", "server.js")
  : join(ROOT, "frontend", "server.js");

// 用户数据目录
const USER_DATA_DIR = join(app.getPath("userData"), "data");
const BACKEND_PORT = 8000;
const FRONTEND_PORT = 3000;

let backendProcess = null;
let frontendProcess = null;
let mainWindow = null;

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

  console.log(`[main] Starting frontend: node ${FRONTEND_SERVER}`);

  frontendProcess = spawn("node", [FRONTEND_SERVER], {
    cwd: dirname(FRONTEND_SERVER),
    env,
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
function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 1024,
    minHeight: 700,
    title: "Weister",
    icon: join(__dirname, "build", "icon.ico"),
    webPreferences: {
      preload: join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

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

  // 清理可能残留的端口占用
  await killPort(BACKEND_PORT);
  await killPort(FRONTEND_PORT);

  try {
    // 1. 启动后端
    startBackend();
    await waitForService("backend", BACKEND_PORT, 30, 1000);

    // 2. 启动前端
    startFrontend();
    // Next.js standalone server 没有 /api/health 端点，等待 3 秒让它启动
    console.log("[main] Waiting 3s for frontend to start...");
    await new Promise((r) => setTimeout(r, 3000));

    // 3. 创建窗口
    createWindow();
  } catch (err) {
    console.error("[main] Startup failed:", err);
    // 即使失败也创建窗口，让用户看到错误
    createWindow();
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
