/** Token / 模型展示工具函数。
 *
 * 上下文 token 数本身改由后端 `/api/chat/estimate` 用 tiktoken 精确计算，
 * 这里只保留 UI 所需的格式化。
 * 模型一律显示原始 ID（不猜测显示名）。
 */

/** 把 token 数格式化成 "1.2K" / "1.5M" / "123" 这样。 */
export function formatTokenCount(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

/** 把 token 数格式化成 WorkBuddy 风格的 "1000.0K"。 */
export function formatTokenCountFixed(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return `${n}.0`;
}

export interface ContextUsage {
  used: number;
  limit: number;
  /** 占用率 0~1，含输出预留（对齐主流 harness：分子 = prompt + 预留） */
  pct: number;
  /** 给模型写回答预留的 token（Claude Code 的 autocompact buffer / Cline 输出预留同思路） */
  reserve?: number;
}

/** 格式化为："12.3% · 30.1K / 64.0K 上下文已使用（含 4.0K 输出预留）"。
 * 若 used 未知，返回占位。
 */
export function formatContextUsage(usage: ContextUsage | null): string {
  if (!usage || usage.used < 0) return "— / — 上下文已使用";
  const pct = `${(Math.min(1, usage.pct) * 100).toFixed(1)}%`;
  const base = `${pct} · ${formatTokenCount(usage.used)} / ${formatTokenCountFixed(
    usage.limit,
  )} 上下文已使用`;
  return usage.reserve
    ? `${base}（含 ${formatTokenCount(usage.reserve)} 输出预留）`
    : base;
}
