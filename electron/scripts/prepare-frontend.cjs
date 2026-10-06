/**
 * electron-builder 打包前置：把 Next.js 的静态资源同步进 standalone 目录。
 *
 * 背景：Next.js `output: "standalone"` 生成的 server.js 会从
 * `__dirname/.next/static` 读取静态资源，但 standalone 输出**不含** static/public。
 * 若 electron-builder 用两个独立 extraResources 源分别复制 standalone 与 static，
 * 一旦两者来自不同次构建（BUILD_ID 不一致），页面引用的 chunk 名就对不上，
 * 全部 404 → React 无法 hydrate → 所有按钮失效（白屏/点击无反应）。
 *
 * 解决：打包前把 static/public 复制进 standalone，使二者同源，
 * electron-builder 只需复制 standalone 一个目录即可。
 */

const { existsSync, cpSync, rmSync, mkdirSync } = require("node:fs");
const { join } = require("node:path");

const FE = join(__dirname, "..", "..", "frontend");
const NEXT = join(FE, ".next");
const STANDALONE = join(NEXT, "standalone");

function sync(src, dest, label) {
  if (!existsSync(src)) {
    console.log(`[prepare-frontend] skip ${label}: ${src} not found`);
    return;
  }
  rmSync(dest, { recursive: true, force: true });
  mkdirSync(join(dest, ".."), { recursive: true });
  cpSync(src, dest, { recursive: true });
  console.log(`[prepare-frontend] synced ${label} -> ${dest}`);
}

if (!existsSync(STANDALONE)) {
  console.error(
    `[prepare-frontend] ERROR: ${STANDALONE} not found.\n` +
      `  Run "pnpm build" in frontend/ first.`,
  );
  process.exit(1);
}

// 静态资源必须与 standalone 内的 BUILD_ID 同源
sync(join(NEXT, "static"), join(STANDALONE, ".next", "static"), ".next/static");
sync(join(FE, "public"), join(STANDALONE, "public"), "public");

// 校验 BUILD_ID 存在（同源标志）
const bid = join(STANDALONE, ".next", "BUILD_ID");
if (existsSync(bid)) {
  console.log(`[prepare-frontend] BUILD_ID present: ${require("node:fs").readFileSync(bid, "utf8").trim()}`);
} else {
  console.error("[prepare-frontend] WARN: standalone/.next/BUILD_ID missing");
}
