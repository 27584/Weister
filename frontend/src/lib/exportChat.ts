import type { ChatMessage } from "@/lib/api";

/** 把聊天消息导出为 Markdown 文本。 */
export function messagesToMarkdown(
  messages: ChatMessage[],
  title = "Weister 对话",
): string {
  const lines: string[] = [`# ${title}`, ""];
  for (const m of messages) {
    const content = (m.content || "").trim();
    if (!content) continue;
    if (m.role === "user") {
      lines.push("## 用户", "", content, "");
    } else if (m.role === "assistant") {
      const who = m.by ? `（${m.by}）` : "";
      lines.push(`## 助手${who}`, "", content, "");
    }
  }
  lines.push(
    "",
    "---",
    "",
    `导出自 Weister · ${new Date().toISOString().slice(0, 19).replace("T", " ")}`,
  );
  return lines.join("\n");
}

export function downloadMarkdown(filename: string, text: string) {
  const blob = new Blob([text], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}
