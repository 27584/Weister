"""聊天消息构造：附件解析、技能命令、用户消息组装。"""

from __future__ import annotations

import base64
from typing import Any

from ..core.registry import registry
from ..tools.parsing import parse_any


def build_attachments(
    files_meta: list[dict[str, Any]],
    raw_files: dict[str, bytes],
) -> list[dict[str, Any]]:
    """把上传的文件解析为 documents 结构（保留 binary 以备 image_url 用）。"""
    documents: list[dict[str, Any]] = []
    for meta in files_meta:
        file_id = meta.get("id", "")
        filename = meta.get("name", file_id)
        mime = meta.get("mime") or "application/octet-stream"
        raw = raw_files.get(file_id, b"")

        # 图片走 image_url，不解析文本
        if mime.startswith("image/"):
            documents.append(
                {
                    "filename": filename,
                    "kind": "image",
                    "mime": mime,
                    "image_b64": base64.b64encode(raw).decode("ascii"),
                    "document_text": "",
                    "pages": [],
                    "chunks": [],
                    "focus_text": "",
                    "focus_pages": [],
                    "diagnostics": {
                        "chars": 0,
                        "empty_pages": [],
                        "ocr_pages": [],
                        "ocr_available": False,
                        "unreadable": False,
                    },
                    "readable": True,
                }
            )
            continue

        try:
            parsed = parse_any(raw, filename)
        except Exception as exc:
            documents.append(
                {
                    "filename": filename,
                    "kind": "error",
                    "mime": mime,
                    "error": f"{type(exc).__name__}: {exc}",
                    "document_text": "",
                    "pages": [],
                    "chunks": [],
                    "focus_text": "",
                    "focus_pages": [],
                    "diagnostics": {
                        "chars": 0,
                        "empty_pages": [],
                        "ocr_pages": [],
                        "ocr_available": False,
                        "unreadable": True,
                    },
                    "readable": False,
                }
            )
            continue

        documents.append(
            {
                **parsed,
                "mime": mime,
            }
        )
    return documents


def doc_label(doc: dict[str, Any]) -> str:
    """给附件生成一句人话描述：类型 / 页数 / 提取字数 / 扫描件告警。"""
    name = doc.get("filename", "附件")
    kind = doc.get("kind", "text")
    diag = doc.get("diagnostics") or {}
    pages = diag.get("page_count") or len(doc.get("pages") or [])
    chars = diag.get("chars") or 0
    segs = [str(kind)]
    if pages:
        segs.append(f"{pages} 页")
    segs.append(f"提取 {chars} 字")
    if doc.get("error"):
        return f"📎 {name}（{kind}，解析失败：{doc['error']}）"
    if not doc.get("readable", True):
        return (
            f"📎 {name}（{', '.join(segs)}）\n"
            "⚠️ 未提取到可读文本：该文件可能是扫描件（无文字层）。"
            "请改用带文字层的 PDF，或先把扫描件做 OCR 再上传。"
        )
    return f"📎 {name}（{', '.join(segs)}）"


def split_skill_command(text: str, known: set[str]) -> tuple[str | None, str]:
    """解析开头的 `/技能名` 命令。

    返回 (skill_name, 去掉命令后的正文)。不是已知技能时原样返回。
    """
    s = (text or "").lstrip()
    if not s.startswith("/"):
        return None, text
    head, _, rest = s[1:].partition(" ")
    name = head.strip()
    if name and name in known:
        return name, rest.strip()
    return None, text


def skill_command_context(name: str, has_body: bool = True) -> str:
    """把「用户显式指定的技能」转成一段给模型的指令。

    `has_body` 区分两种用法，二者的行动要求不同：
        - 命令 + 正文：围绕该技能处理正文里的请求
        - 只有命令：用户没提问题，必须给出明确的可行动作（调度或询问），
          否则模型会把它当成一句通知，只回复「已收到技能指令」这类空话
    """
    sk = registry.skills.get(name)
    if sk is None:
        return f"【未知技能命令 /{name}】这不是已注册技能，请忽略该命令，按用户正文正常处理。\n\n"

    owners = [a.name for a in registry.agents.values() if name in (a.skills or [])]
    owner_txt = f"（可由{'、'.join(owners)}执行）" if owners else ""

    if has_body:
        return (
            f"【用户指定技能：{sk.name}】{sk.description}{owner_txt}\n"
            f"请围绕该技能处理用户请求：需要专业分析时 delegate 给对应专家，"
            f"不要只确认收到技能指令。\n\n"
        )

    tools = list(getattr(sk, "tools", None) or [])
    tool_txt = f"该技能可用工具：{'、'.join(tools)}。" if tools else ""
    return (
        f"【用户执行了技能命令 /{name}，但没有提出具体问题】\n"
        f"技能：{sk.name} —— {sk.description}{owner_txt}\n"
        f"{tool_txt}\n"
        f"你必须采取以下之一的实际动作，禁止只回答「已收到 / 已激活 / 明白」"
        f"这类没有信息量的确认：\n"
        f"1. 若对话中已有可分析的材料、标的或上文 → 用 delegate 交给对应专家，"
        f"让专家基于已有信息直接开展工作；\n"
        f"2. 若尚无可分析的内容 → 用 ask 询问用户想做什么，"
        f"选项从该技能的典型用法中给出。\n\n"
    )


def build_user_message(
    text: str,
    attachments: list[dict[str, Any]],
    documents: list[dict[str, Any]],
    extra_context: str = "",
) -> dict[str, Any]:
    """把 user 输入 + 附件清单组合成一条 message。

    **不把文档正文塞进消息** —— 否则对话记录里那条「文件」会变成一大段被截断的
    文本（用户看到的就是「文件记录被自动转成了文字」）。文档正文通过 documents
    参数单独传给 agent；这里只保留用户输入 + 附件元信息。

    额外的 `display_text` / `attachments` 是给前端渲染用的：前端优先展示
    display_text + 附件卡片，而不是把 content 原样当正文显示。

    图片走 OpenAI 多模态格式（content 是 list，每项 type=text|image_url）。
    """
    att_meta: list[dict[str, Any]] = []
    for doc in documents:
        diag = doc.get("diagnostics") or {}
        att_meta.append(
            {
                "name": doc.get("filename", "附件"),
                "mime": doc.get("mime", ""),
                "kind": doc.get("kind", "text"),
                "pages": diag.get("page_count") or len(doc.get("pages") or []) or None,
                "chars": diag.get("chars", 0),
                "readable": doc.get("readable", True),
            }
        )

    has_image = any(d.get("kind") == "image" for d in documents)
    if not has_image:
        parts: list[str] = []
        if text:
            parts.append(text)
        for doc in documents:
            if doc.get("kind") == "image":
                continue
            parts.append(doc_label(doc))
        body = "\n\n".join(parts).strip() or (
            # 只有 /技能命令、没有其他文字时，给模型一句明确说明
            # （比含混的「(空消息)」更不容易让轻量模型困惑）
            "（用户没有输入其他文字，意图见上方技能指令）" if extra_context.strip() else "(空消息)"
        )
        return {
            "role": "user",
            "content": (extra_context + body).strip(),
            "display_text": text,
            "attachments": att_meta,
        }

    # 有图片：用多模态 content 数组
    content_parts: list[dict[str, Any]] = []
    image_names: list[str] = []
    for doc in documents:
        if doc.get("kind") != "image":
            continue
        image_names.append(doc.get("filename", "图片"))
        content_parts.append(
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:{doc['mime']};base64,{doc.get('image_b64', '')}",
                },
            }
        )
    text_part = text or ""
    if image_names:
        text_part = (text_part + f"\n\n📎 图片：{'、'.join(image_names)}").strip()
    content_parts.insert(0, {"type": "text", "text": extra_context + (text_part or "(空消息)")})
    return {
        "role": "user",
        "content": content_parts,
        "display_text": text,
        "attachments": att_meta,
    }


__all__ = [
    "build_attachments",
    "build_user_message",
    "doc_label",
    "skill_command_context",
    "split_skill_command",
]
