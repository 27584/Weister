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

const {
  existsSync,
  cpSync,
  rmSync,
  mkdirSync,
  renameSync,
  lstatSync,
  readdirSync,
} = require("node:fs");
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

/**
 * 实体化 standalone/node_modules 下的符号链接。
 *
 * pnpm 项目里 Next.js standalone 会把依赖写成 junction，其 target 是**构建机上的
 * 绝对路径**（例如 D:\...\frontend\node_modules\.pnpm\next@16.3.4...\node_modules\next）。
 * 这种链接一旦离开构建机就是死的：
 *   1. 别人机器上那个绝对路径根本不存在；
 *   2. zip / 7z 等归档格式默认不保留 junction，解压后变成空目录。
 * 结果 server.js 启动即 `Cannot find module 'next'` 并以退出码 1 结束。
 *
 * 所以打包前把 node_modules 整棵子树 dereference 一遍，产物只含真实文件。
 */
function materializeLinks(root, rel) {
  const target = join(root, rel);
  if (!existsSync(target)) {
    console.log(`[prepare-frontend] skip materialize: ${target} not found`);
    return;
  }
  const tmp = `${target}.__deref__`;
  rmSync(tmp, { recursive: true, force: true });
  cpSync(target, tmp, { recursive: true, dereference: true });
  rmSync(target, { recursive: true, force: true });
  try {
    renameSync(tmp, target);
  } catch {
    // 同盘 rename 偶尔会被杀软/索引器短暂锁住（EPERM），退化为复制回填
    cpSync(tmp, target, { recursive: true });
    rmSync(tmp, { recursive: true, force: true });
  }
}

/** 快速探测子树内是否存在符号链接（pnpm 默认的 isolated 布局会留 junction）。 */
function containsLinks(root, depth = 6) {
  let entries;
  try {
    entries = readdirSync(root, { withFileTypes: true });
  } catch {
    return false;
  }
  for (const e of entries) {
    if (e.isSymbolicLink()) return true;
    if (depth > 0 && e.isDirectory() && containsLinks(join(root, e.name), depth - 1)) {
      return true;
    }
  }
  return false;
}

// 断链自检：这些路径必须是真实目录，否则说明 dereference 没生效
const nm = join(STANDALONE, "node_modules");
if (existsSync(nm) && containsLinks(nm)) {
  console.log("[prepare-frontend] symlinked (isolated) node_modules detected - materializing links");
  materializeLinks(STANDALONE, "node_modules");
} else {
  console.log("[prepare-frontend] hoisted node_modules (no symlinks) - nothing to materialize");
}
for (const name of ["next", "react", "react-dom"]) {
  const p = join(nm, name);
  if (!existsSync(p)) {
    console.error(`[prepare-frontend] ERROR: ${p} missing after materialize`);
    process.exit(1);
  }
  if (lstatSync(p).isSymbolicLink()) {
    console.error(`[prepare-frontend] ERROR: ${p} is still a link after materialize`);
    process.exit(1);
  }
}
console.log("[prepare-frontend] materialized node_modules links (next/react/react-dom are real dirs)");

// 校验 BUILD_ID 存在（同源标志）
const bid = join(STANDALONE, ".next", "BUILD_ID");
if (existsSync(bid)) {
  console.log(`[prepare-frontend] BUILD_ID present: ${require("node:fs").readFileSync(bid, "utf8").trim()}`);
} else {
  console.error("[prepare-frontend] WARN: standalone/.next/BUILD_ID missing");
}

/**
 * 把 standalone 铺到不含隐藏目录段的路径，供 electron-builder 复制。
 *
 * electron-builder 复制 extraResources 时会对 from 做 glob 展开，而 glob 默认
 * 跳过以 "." 开头的目录。standalone 的路径里含 .next，展开结果为空，于是
 * electron-builder 只打印一行 "file source doesn't exist" 就把整项跳过 ——
 * 产物中根本没有 resources/frontend，客户端启动前端必然失败。
 *
 * 因此先在 electron/build/frontend（路径无隐藏段）放一份，extraResources 指向它。
 */
const STAGE = join(__dirname, "..", "build", "frontend");
rmSync(STAGE, { recursive: true, force: true });
mkdirSync(join(STAGE, ".."), { recursive: true });
cpSync(STANDALONE, STAGE, { recursive: true });
console.log(`[prepare-frontend] staged for electron-builder -> ${STAGE}`);
