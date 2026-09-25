"""原文溯源：在文档中定位关键句与页码，支撑可验证引用。"""

from __future__ import annotations

import re
from typing import Any

from ..core.registry import Tool, registry


def _normalize(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def locate_evidence(
    document_text: str | None = None,
    pages: list[dict[str, Any]] | None = None,
    quote: str = "",
    keywords: list[str] | None = None,
    max_hits: int = 8,
) -> dict[str, Any]:
    """在全文或分页结构中定位 quote / keywords。

    - pages: [{"page": 1, "text": "..."}]（parse_pdf 产物）
    - document_text: 连续正文（无页码时 page=null）
    返回命中片段（前后文）与页码，供报告标注 [pN]。
    """
    needle = (quote or "").strip()
    kws = [k.strip() for k in (keywords or []) if str(k).strip()]
    if not needle and not kws:
        raise ValueError("必须提供 quote 或 keywords")

    candidates: list[tuple[int | None, str]] = []
    if pages:
        for p in pages:
            pg = p.get("page")
            text = p.get("text") or p.get("document_text") or ""
            candidates.append((int(pg) if isinstance(pg, (int, float)) else None, str(text)))
    elif document_text:
        candidates.append((None, str(document_text)))
    else:
        raise ValueError("必须提供 document_text 或 pages")

    hits: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add_hit(page: int | None, snippet: str, matched: str) -> None:
        key = f"{page}:{_normalize(snippet)[:80]}"
        if key in seen:
            return
        seen.add(key)
        hits.append({"page": page, "snippet": snippet, "matched": matched})

    for page, text in candidates:
        if not text:
            continue
        flat = _normalize(text)
        if needle:
            nflat = _normalize(needle)
            if nflat and nflat in flat:
                # 在原文中找近似位置（忽略空白差异时用前缀探测）
                idx = text.find(needle[:20]) if len(needle) > 8 else text.find(needle)
                if idx < 0:
                    # 退化：按前 8 字找
                    probe = re.sub(r"\s+", "", needle)[:8]
                    for m in re.finditer(re.escape(probe), flat):
                        # 无法精确映射回原文索引时给页首片段
                        idx = 0
                        break
                start = max(0, (idx or 0) - 60)
                end = min(len(text), (idx or 0) + len(needle) + 80)
                add_hit(page, text[start:end].strip(), needle)
        for kw in kws:
            if kw and kw in text:
                i = text.find(kw)
                start = max(0, i - 50)
                end = min(len(text), i + len(kw) + 80)
                add_hit(page, text[start:end].strip(), kw)
        if len(hits) >= max_hits:
            break

    return {
        "hits": hits[:max_hits],
        "count": len(hits[:max_hits]),
        "pages_searched": len(candidates),
    }


def build_citation_snippets(
    hits: list[dict[str, Any]] | None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """把 locate_evidence 的命中整理成报告可用的引用卡片。"""
    out: list[dict[str, Any]] = []
    for h in (hits or [])[:limit]:
        snip = re.sub(r"\s+", " ", str(h.get("snippet") or "")).strip()
        if len(snip) > 200:
            snip = snip[:200] + "…"
        out.append({"page": h.get("page"), "excerpt": snip, "matched": h.get("matched")})
    return out


registry.add_tool(
    Tool(
        name="locate_evidence",
        description=(
            "在财报原文中定位关键句与页码，用于给结论标注 [pN] 来源。"
            "传入 pages（parse_pdf 分页结果）或 document_text，以及 quote 或 keywords。"
            "返回命中的原文片段与页码，禁止编造页码。"
        ),
        input_schema={
            "document_text": "str 可选，连续正文",
            "pages": "list 可选，[{'page':int,'text':str}]",
            "quote": "str 要定位的原文片段",
            "keywords": "list 可选，关键词列表",
        },
        handler=locate_evidence,
        tags=["citation", "traceability", "deterministic"],
    )
)
