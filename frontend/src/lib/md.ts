/** 去掉模型输出的 markdown 代码围栏，便于渲染器当正文而不是代码块。 */
export function stripMarkdownFence(text: string | null | undefined): string {
  const raw = (text || "").trim();
  if (!raw.startsWith("```")) return raw;
  const lines = raw.split(/\r?\n/);
  let body = lines.slice(1);
  while (body.length && body[body.length - 1].trim() === "") body.pop();
  if (body.length && body[body.length - 1].trim() === "```") body.pop();
  return body.join("\n").trim();
}

/** 从建模 result payload 抽出可展示的报告正文。 */
export function extractReportMd(payload: {
  report_md?: string;
  reply?: string;
} | null): string {
  if (!payload) return "";
  return stripMarkdownFence(payload.report_md || payload.reply || "");
}
