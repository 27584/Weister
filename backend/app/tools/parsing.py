"""文档解析。

支持 PDF 与纯文本。对长文档会自动定位财务关键页，
避免把封面、目录等无关内容送给模型。

同时对「扫描件」做显式判定：没有文字层的 PDF 能被正常打开、
页数也正常，但抽出的文本几乎为 0。这类文档若继续往下走，
会把空字符串一路送进抽取与估值，最终产出一份「格式完整但没有依据」
的报告 —— 这是最危险的一类失败，因为它看起来是成功的。
"""

from __future__ import annotations

import io
import shutil
from typing import Any

import pymupdf

from ..core.registry import Tool, registry

# 单页可读文本低于此阈值，视为该页没有文字层
MIN_PAGE_CHARS = 20
# 整篇可读文本低于此阈值，视为文档不可读
MIN_DOC_CHARS = 50
# OCR 语言：中文简体 + 英文。需要 tesseract 及对应语言包
OCR_LANGUAGE = "chi_sim+eng"
OCR_DPI = 200

# 财务关键指标关键词，用于给页面打分
FINANCIAL_KEYWORDS = [
    "营业收入",
    "营业总收入",
    "归属于上市公司股东的净利润",
    "扣除非经常性损益",
    "经营活动产生的现金流量净额",
    "基本每股收益",
    "稀释每股收益",
    "总资产",
    "归属于上市公司股东的净资产",
    "加权平均净资产收益率",
    "毛利率",
    "资产负债率",
    "研发投入",
    "营业成本",
    "现金及现金等价物",
]


def ocr_available() -> bool:
    """是否存在可用 OCR 引擎（Tesseract 或 RapidOCR）。

    PyMuPDF 的 get_textpage_ocr 只对接系统 tesseract；
    RapidOCR 为 pip 可选依赖，走独立图像识别路径。
    """
    if shutil.which("tesseract") is not None:
        return True
    return _rapidocr_ready()


def _tesseract_ready() -> bool:
    return shutil.which("tesseract") is not None


_rapid_ocr = None
_rapid_checked = False


def _rapidocr_ready() -> bool:
    """是否已安装 rapidocr-onnxruntime（可选内置 OCR）。"""
    global _rapid_ocr, _rapid_checked
    if _rapid_checked:
        return _rapid_ocr is not None
    _rapid_checked = True
    try:
        from rapidocr_onnxruntime import RapidOCR  # type: ignore

        _rapid_ocr = RapidOCR()
    except Exception:
        _rapid_ocr = None
    return _rapid_ocr is not None


def _ocr_page_rapid(page: pymupdf.Page) -> str:
    """用 RapidOCR 识别单页（渲染为图像后送入）。"""
    if _rapid_ocr is None:
        return ""
    # 200 DPI 约 2480px 宽，对中文财报足够且不至于过大
    zoom = 200 / 72
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
    img = pix.tobytes("png")
    result, _elapse = _rapid_ocr(img)
    if not result:
        return ""
    # result: list of [box, text, score]
    lines = []
    for item in result:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            lines.append(str(item[1]))
    return "\n".join(lines)


def _read_page(page: pymupdf.Page, *, allow_ocr: bool) -> tuple[str, bool]:
    """读取单页文本，必要时回退到 OCR。

    返回 (文本, 是否使用了 OCR)。OCR 失败不抛出，静默回退到原生文本，
    由上层通过 assess_document 统一判定文档是否可用。

    OCR 优先级：系统 Tesseract（PyMuPDF）→ pip 内置 RapidOCR。
    """
    text = page.get_text("text") or ""
    if len(text.strip()) >= MIN_PAGE_CHARS or not allow_ocr:
        return text, False

    # 1) Tesseract via PyMuPDF
    if _tesseract_ready():
        try:
            textpage = page.get_textpage_ocr(language=OCR_LANGUAGE, dpi=OCR_DPI, full=True)
            ocr_text = page.get_text("text", textpage=textpage) or ""
            if len(ocr_text.strip()) > len(text.strip()):
                return ocr_text, True
        except Exception:
            pass

    # 2) RapidOCR（pip 内置，无需系统安装）
    if _rapidocr_ready():
        try:
            ocr_text = _ocr_page_rapid(page)
            if len(ocr_text.strip()) > len(text.strip()):
                return ocr_text, True
        except Exception:
            pass

    return text, False


def parse_pdf(raw: bytes) -> tuple[str, list[dict[str, Any]]]:
    doc = pymupdf.open(stream=io.BytesIO(raw), filetype="pdf")
    allow_ocr = ocr_available()

    pages: list[dict[str, Any]] = []
    for i, page in enumerate(doc, start=1):
        text, used_ocr = _read_page(page, allow_ocr=allow_ocr)
        pages.append(
            {
                "page": i,
                "text": text,
                "chars": len(text.strip()),
                "ocr": used_ocr,
            }
        )

    return "\n\n".join(p["text"] for p in pages), pages


def parse_text(raw: bytes) -> tuple[str, list[dict[str, Any]]]:
    text = raw.decode("utf-8", errors="ignore")
    return text, [{"page": 1, "text": text, "chars": len(text.strip()), "ocr": False}]


def parse_docx(raw: bytes) -> tuple[str, list[dict[str, Any]]]:
    """解析 Word 文档。依赖 python-docx（轻量、纯 Python）。"""
    try:
        from docx import Document  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "解析 .docx 需要安装 python-docx：在 backend/ 目录执行 "
            "`uv pip install python-docx` 或同等命令"
        ) from exc

    doc = Document(io.BytesIO(raw))
    pages: list[dict[str, Any]] = [{"page": 1, "text": "", "chars": 0, "ocr": False}]
    buffer: list[str] = []
    # 段落
    for para in doc.paragraphs:
        t = (para.text or "").strip()
        if t:
            buffer.append(t)
    # 表格：每个单元格一行，便于 LLM 读出表结构
    for tbl in doc.tables:
        for row in tbl.rows:
            cells = [c.text.strip() for c in row.cells]
            if any(cells):
                buffer.append(" | ".join(cells))
    text = "\n".join(buffer).strip()
    pages[0]["text"] = text
    pages[0]["chars"] = len(text)
    return text, pages


def parse_xlsx(raw: bytes) -> tuple[str, list[dict[str, Any]]]:
    """解析 Excel 工作簿。依赖 openpyxl（轻量、纯 Python）。

    每个 sheet 作为「一页」，文本格式：行号 + 每格 tab 分隔。
    只读 values，不带公式，便于 LLM 直接消费。
    """
    try:
        from openpyxl import load_workbook  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "解析 .xlsx 需要安装 openpyxl：在 backend/ 目录执行 "
            "`uv pip install openpyxl` 或同等命令"
        ) from exc

    wb = load_workbook(io.BytesIO(raw), data_only=True, read_only=True)
    pages: list[dict[str, Any]] = []
    all_text: list[str] = []

    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        lines: list[str] = [f"【{sheet_name}】"]
        for row_idx, row in enumerate(ws.iter_rows(values_only=True), start=1):
            cells = ["" if v is None else str(v).strip() for v in row]
            # 跳过整行全空
            if not any(cells):
                continue
            lines.append("\t".join(cells))
        sheet_text = "\n".join(lines).strip()
        if sheet_text:
            pages.append(
                {
                    "page": len(pages) + 1,
                    "text": sheet_text,
                    "chars": len(sheet_text),
                    "ocr": False,
                    "sheet": sheet_name,
                }
            )
            all_text.append(sheet_text)

    wb.close()
    text = "\n\n".join(all_text)
    if not pages:
        pages = [{"page": 1, "text": "", "chars": 0, "ocr": False}]
    return text, pages


def parse_pptx(raw: bytes) -> tuple[str, list[dict[str, Any]]]:
    """解析 PowerPoint。每张幻灯片作为一页，文本格式：标题 + 正文。"""
    try:
        from pptx import Presentation  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "解析 .pptx 需要安装 python-pptx：在 backend/ 目录执行 "
            "`uv pip install python-pptx` 或同等命令"
        ) from exc

    prs = Presentation(io.BytesIO(raw))
    pages: list[dict[str, Any]] = []
    all_text: list[str] = []

    for idx, slide in enumerate(prs.slides, start=1):
        chunks: list[str] = []
        for shape in slide.shapes:
            if shape.has_text_frame:
                for para in shape.text_frame.paragraphs:
                    t = "".join(run.text for run in para.runs).strip()
                    if t:
                        chunks.append(t)
        slide_text = "\n".join(chunks).strip()
        pages.append(
            {
                "page": idx,
                "text": slide_text,
                "chars": len(slide_text),
                "ocr": False,
            }
        )
        if slide_text:
            all_text.append(f"【第 {idx} 页】\n{slide_text}")

    text = "\n\n".join(all_text)
    if not pages:
        pages = [{"page": 1, "text": "", "chars": 0, "ocr": False}]
    return text, pages


def detect_image_mime(filename: str, raw: bytes) -> str:
    """根据文件头 magic bytes 判定图片 mime，避免被文件名欺骗。"""
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if raw[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if raw[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp"
    # 魔数未命中时按扩展名判定
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return {
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "gif": "image/gif",
        "webp": "image/webp",
    }.get(ext, "application/octet-stream")


def parse_any(raw: bytes, filename: str) -> dict[str, Any]:
    """统一入口：根据扩展名分发到对应解析器，返回完整结构。"""
    name = filename.lower()
    if name.endswith(".pdf"):
        text, pages = parse_pdf(raw)
    elif name.endswith(".docx"):
        text, pages = parse_docx(raw)
    elif name.endswith(".xlsx"):
        text, pages = parse_xlsx(raw)
    elif name.endswith(".pptx"):
        text, pages = parse_pptx(raw)
    else:
        text, pages = parse_text(raw)

    diagnostics = assess_document(text, pages)
    focus_pages = locate_financial_pages(pages)
    focus_text, focus_numbers = build_focus_text(focus_pages)

    return {
        "filename": filename,
        "kind": (
            "pdf"
            if name.endswith(".pdf")
            else "docx"
            if name.endswith(".docx")
            else "xlsx"
            if name.endswith(".xlsx")
            else "pptx"
            if name.endswith(".pptx")
            else "image"
            if detect_image_mime(filename, raw).startswith("image/")
            else "text"
        ),
        "document_text": text,
        "pages": pages,
        "chunks": chunk_text(text),
        "focus_text": focus_text,
        "focus_pages": focus_numbers,
        "diagnostics": diagnostics,
        "readable": not diagnostics["unreadable"],
    }


def assess_document(text: str, pages: list[dict[str, Any]]) -> dict[str, Any]:
    """判定文档是否真的读到了内容。

    扫描件的典型症状是「能打开、页数正常、文本几乎为 0」。
    把它显式判定出来交给调用方，是为了避免空文本被一路带到最后，
    产出一份看似成功、实则无依据的报告。
    """
    chars = len((text or "").strip())
    empty_pages = [p["page"] for p in pages if (p.get("chars") or 0) < MIN_PAGE_CHARS]
    ocred_pages = [p["page"] for p in pages if p.get("ocr")]

    return {
        "chars": chars,
        "page_count": len(pages),
        "empty_pages": empty_pages,
        "ocr_pages": ocred_pages,
        "ocr_available": ocr_available(),
        # 完全没有可读文本 → 不可用；有内容但部分页空白 → 可用但需告警
        "unreadable": bool(pages) and chars < MIN_DOC_CHARS,
    }


def unreadable_reason(stats: dict[str, Any], filename: str = "") -> str:
    """把 assess_document 的结果转成可执行的中文提示。"""
    name = f"「{filename}」" if filename else "该文件"
    empty = len(stats.get("empty_pages") or [])

    head = (
        f"无法从{name}提取任何可用文本："
        f"共 {stats.get('page_count', 0)} 页，其中 {empty} 页没有文字层，"
        f"全文可读字符仅 {stats.get('chars', 0)} 个。"
    )

    if stats.get("ocr_available"):
        hint = (
            "已尝试 OCR 但仍未取到文本，可能是扫描质量过低、分辨率不足，"
            "或中文模型未正确加载。可提高扫描 DPI 后重试。"
        )
    else:
        hint = (
            "该文件疑似扫描件或图片版 PDF，且本机当前没有可用 OCR 引擎。\n"
            "推荐：在 backend 目录安装内置 OCR（pip 可选依赖）：\n"
            "  .\\.venv\\Scripts\\python.exe -m pip install rapidocr-onnxruntime\n"
            "或安装系统 Tesseract 并加入 PATH（需 chi_sim+eng 语言包），"
            "安装后重启后端即可自动 OCR。\n"
            "也可先用其他工具对 PDF 做文字识别后再上传。"
        )

    return f"{head}{hint}"


def chunk_text(text: str, size: int = 1200, overlap: int = 150) -> list[str]:
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = start + size
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start = end - overlap
    return chunks


def locate_financial_pages(
    pages: list[dict[str, Any]],
    *,
    top_k: int = 10,
    min_hits: int = 2,
) -> list[dict[str, Any]]:
    """按财务关键词命中数定位关键页面。

    打分规则是页面命中多少个不同的关键词。
    同分时页码小的优先，因为核心财务摘要通常在前部。
    若没有任何页面达到 min_hits，退化为前 top_k 页。
    """
    scored: list[tuple[int, int, dict[str, Any]]] = []

    for p in pages:
        text = p.get("text") or ""
        hits = sum(1 for kw in FINANCIAL_KEYWORDS if kw in text)
        if hits >= min_hits:
            scored.append((hits, p["page"], p))

    if not scored:
        return pages[:top_k]

    scored.sort(key=lambda x: (-x[0], x[1]))
    selected = [p for _, _, p in scored[:top_k]]
    selected.sort(key=lambda p: p["page"])
    return selected


def build_focus_text(
    pages: list[dict[str, Any]],
    *,
    max_chars: int = 30000,
) -> tuple[str, list[int]]:
    """把选中的页面拼成带页码标记的文本。

    页码标记让模型可以生成 [p9] 形式的引用。
    返回 (文本, 页码列表)。
    """
    parts: list[str] = []
    numbers: list[int] = []
    total = 0

    for p in pages:
        text = (p.get("text") or "").strip()
        if not text:
            continue
        block = f"【第 {p['page']} 页】\n{text}"
        if total + len(block) > max_chars and parts:
            break
        parts.append(block)
        numbers.append(p["page"])
        total += len(block)

    return "\n\n".join(parts), numbers


def _tool_parse(raw: bytes, filename: str) -> dict[str, Any]:
    # 统一由 parse_any 分发，覆盖 pdf / 纯文本 / docx / xlsx / pptx 与图片识别。
    # 流水线形态仅使用 .pdf 与纯文本分支，此处保留其字段语义
    # （unreadable / focus_pages / readable 等），供 chat_supervisor 复用同一结构。
    result = parse_any(raw, filename)
    return {
        "document_text": result["document_text"],
        "pages": result["pages"],
        "chunks": result["chunks"],
        "focus_text": result["focus_text"],
        "focus_pages": result["focus_pages"],
        "diagnostics": result["diagnostics"],
        "readable": result["readable"],
        "kind": result["kind"],
        "filename": result["filename"],
    }


registry.add_tool(
    Tool(
        name="parse_document",
        description=(
            "解析 PDF 或纯文本财报，返回全文、分页引用、切片列表与财务关键页，"
            "并给出可读性诊断（unreadable 为真表示文档没有文字层，不应继续分析）"
        ),
        input_schema={"raw": "bytes", "filename": "str"},
        handler=_tool_parse,
        tags=["parsing", "io"],
    )
)
