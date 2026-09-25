"""回归测试（两个 bug）：

1. 上传 PDF 后，对话里那条「文件」不能被转成一大段截断文本
   → _build_user_message 的 content 里不能含文档正文，且要带 display_text / attachments
2. 几百页的 PDF 不能被砍成几百字
   → parse_any 能读到全部页；_build_user_message 只做「元信息」，不塞正文
"""

import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.api import helpers as helpers_mod
from app.api import store as store_mod
from app.tools.parsing import parse_any


def make_big_pdf(pages: int = 300) -> bytes:
    import pymupdf

    doc = pymupdf.open()
    for i in range(pages):
        page = doc.new_page()
        page.insert_text(
            (72, 72),
            f"第 {i + 1} 页  营业收入 1,234,567 万元  净利润 89,000 万元  "
            f"经营活动现金流 45,000 万元  资产负债率 42.1%",
        )
    return doc.tobytes()


def main():
    ok = True

    # ---- 1. 解析：300 页 PDF 应读到 300 页、且字符量可观 ----
    data = make_big_pdf(300)
    parsed = parse_any(data, "big_report.pdf")
    pages = parsed["diagnostics"]["page_count"]
    chars = parsed["diagnostics"]["chars"]
    print(f"[解析] 页数={pages} 提取字数={chars} readable={parsed['readable']}")
    assert pages == 300, f"应解析出 300 页，实际 {pages}"
    assert chars > 5000, f"300 页应有大量文本，实际仅 {chars} 字"
    assert parsed["readable"] is True

    doc = {**parsed, "mime": "application/pdf"}

    # ---- 2. 消息构造：正文不得进入 content ----
    msg = helpers_mod.build_user_message("帮我分析这份年报", [], [doc])
    content = msg["content"]
    print(f"\n[消息] content 长度={len(content)}")
    print(f"[消息] content 预览={content[:160]!r}")
    assert "📎" in content, "content 里应有附件标记"
    assert "300 页" in content, "content 里应显示页数"
    assert len(content) < 400, f"content 不应包含文档正文（当前 {len(content)} 字）"
    assert msg["display_text"] == "帮我分析这份年报"
    att = msg["attachments"][0]
    assert att["pages"] == 300 and att["chars"] == chars
    print(f"[消息] display_text={msg['display_text']!r}")
    print(f"[消息] attachments={att}")

    # ---- 3. 文档持久化：追问时还能拿到正文 ----
    tmp = tempfile.mkdtemp(prefix="weister_doc_")

    class FakeSettings:
        runs_dir = tmp

    real_settings = store_mod.settings
    store_mod.settings = FakeSettings()
    try:
        store_mod.save_chat_documents("run-x", [doc])
        loaded = store_mod.load_chat_documents("run-x")
        assert len(loaded) == 1 and loaded[0]["document_text"] == parsed["document_text"]
        print(
            f"\n[持久化] 回读文档 {loaded[0]['filename']}，正文 {len(loaded[0]['document_text'])} 字 OK"
        )
    finally:
        store_mod.settings = real_settings
        shutil.rmtree(tmp, ignore_errors=True)

    print("\nALL PASS: 消息不再塞正文；300 页 PDF 完整解析且可跨轮复用")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
