"""Token counting utilities.

Goals:
    - Give the frontend an *actual* token count instead of a rough char/3.5 guess.
    - Count the messages array (history + pending user message) as it will be
      sent to the LLM.
    - For images, use model-specific vision heuristics: still an approximation,
      because exact vision token counts depend on the provider's image encoder.

The heavy lifting for text is done by tiktoken when available.  DeepSeek-V3,
GPT-4 series and many OpenAI-compatible models use the cl100k_base / o200k_base
encodings.  For models that tiktoken does not know, we fall back to a character
based estimate so the UI never breaks.
"""

from __future__ import annotations

import base64
import logging
import math
from typing import Any

try:  # pragma: no cover - optional dependency guard
    import tiktoken
except Exception:  # noqa: BLE001
    tiktoken = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


TOKEN_FLOOR = 4  # per-message role/name/separator overhead used by most APIs

# 模型得留地方写回答：口径对齐主流 harness（Claude Code 的 auto-compact buffer、
# Cline/Roo 的输出预留），显示占用率时把这部分一并算进分子。
OUTPUT_RESERVE_TOKENS = 4096


def _encoding_for_model(model: str) -> Any | None:
    """Return a tiktoken encoding for known model families.

    未知模型（自建/改名部署，如 dots3-note-prev）默认用 cl100k_base 近似：
    DeepSeek 官方也推荐它做 token 估算，对中文略高估——上下文占用宁可
    略高估也不能低估，否则「已用 60%」时模型其实已经爆窗了。
    """
    if tiktoken is None:
        return None
    m = (model or "").lower()
    try:
        if "gpt-4o" in m or "o1-" in m or "o3-" in m:
            return tiktoken.get_encoding("o200k_base")
        # deepseek-v3 / deepseek-chat, qwen, legacy GPT-4, claude-ish fallback
        if "deepseek" in m or "qwen" in m or "gpt-4" in m or "gpt-3.5" in m or "claude" in m:
            return tiktoken.get_encoding("cl100k_base")
        try:
            return tiktoken.encoding_for_model(model)
        except Exception:  # noqa: BLE001 - unknown model name
            return tiktoken.get_encoding("cl100k_base")
    except Exception:  # noqa: BLE001 - tiktoken unavailable / no cache
        return None


def _char_estimate(text: str) -> int:
    """CJK 感知的字符估算（tiktoken 不可用时的降级估算）。

    中文实际约 1.4~1.8 字/token（即 0.55~0.7 token/字），
    英文约 4 字符/token；统一按 length/3.5 折算会显著低估中文。
    分桶计：CJK（含全角标点）× 0.7 + 其余 ÷ 4。
    """
    cjk = 0
    for ch in text:
        code = ord(ch)
        if (
            0x4E00 <= code <= 0x9FFF  # CJK 统一表意文字
            or 0x3400 <= code <= 0x4DBF  # 扩展 A
            or 0x3000 <= code <= 0x303F  # CJK 标点
            or 0xFF00 <= code <= 0xFFEF  # 全角形式
        ):
            cjk += 1
    other = len(text) - cjk
    return max(1, round(cjk * 0.7 + other / 4))


def count_text_tokens(text: str, model: str = "") -> int:
    """Count tokens in a plain text string."""
    if not text:
        return 0
    enc = _encoding_for_model(model)
    if enc is None:
        return _char_estimate(text)
    try:
        return len(enc.encode(text))
    except Exception:  # noqa: BLE001
        return _char_estimate(text)


def _extract_b64(url: str) -> str:
    if not url or "," not in url:
        return ""
    return url.split(",", 1)[1]


def image_size(raw: bytes) -> tuple[int, int] | None:
    """从图像字节里解析出 (width, height)。纯 stdlib，覆盖 PNG/JPEG/GIF/BMP/WEBP。"""
    if not raw or len(raw) < 24:
        return None
    try:
        if raw[:8] == b"\x89PNG\r\n\x1a\n" and raw[12:16] == b"IHDR":
            return int.from_bytes(raw[16:20], "big"), int.from_bytes(raw[20:24], "big")
        if raw[:2] == b"\xff\xd8":
            return _jpeg_size(raw)
        if raw[:6] in (b"GIF87a", b"GIF89a"):
            return int.from_bytes(raw[6:8], "little"), int.from_bytes(raw[8:10], "little")
        if raw[:2] == b"BM":
            return int.from_bytes(raw[18:22], "little"), int.from_bytes(raw[22:26], "little")
        if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
            return _webp_size(raw)
    except Exception:  # noqa: BLE001
        return None
    return None


def _jpeg_size(raw: bytes) -> tuple[int, int] | None:
    """扫 JPEG 段找 SOF 标记读出尺寸。"""
    pos = 2
    while pos + 9 < len(raw):
        if raw[pos] != 0xFF:
            return None
        marker = raw[pos + 1]
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            pos += 2
            continue
        seg_len = int.from_bytes(raw[pos + 2 : pos + 4], "big")
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            return (
                int.from_bytes(raw[pos + 7 : pos + 9], "big"),
                int.from_bytes(raw[pos + 5 : pos + 7], "big"),
            )
        if seg_len <= 0:
            return None
        pos += 2 + seg_len
    return None


def _webp_size(raw: bytes) -> tuple[int, int] | None:
    """WEBP：VP8X 容器头最简单；有损 VP8 走帧头。"""
    if raw[12:16] == b"VP8X":
        w = int.from_bytes(raw[24:27], "little") & 0xFFFFFF
        h = int.from_bytes(raw[27:30], "little") & 0xFFFFFF
        return (w + 1, h + 1) if w and h else None
    if raw[12:16] == b"VP8 ":
        return (
            int.from_bytes(raw[26:28], "little") & 0x3FFF,
            int.from_bytes(raw[28:30], "little") & 0x3FFF,
        )
    return None


def _openai_image_tokens(width: int, height: int, model: str) -> int:
    """OpenAI 视觉计费：缩到 2048² 内 → 短边压到 768 → 铺 512 tile。

    base / per-tile 取各家公布值：gpt-4o、gpt-4.1 = 85/170；
    gpt-4o-mini、gpt-4.1-mini/nano = 2833/5667；o1/o3 = 75/150；gpt-5 = 70/140。
    """
    m = (model or "").lower()
    scale = min(1.0, 2048 / width, 2048 / height)
    w = max(1, int(width * scale))
    h = max(1, int(height * scale))
    if min(w, h) > 768:
        s = 768 / min(w, h)
        w = max(1, int(w * s))
        h = max(1, int(h * s))
    tiles = math.ceil(w / 512) * math.ceil(h / 512)

    if "gpt-4o-mini" in m or "gpt-4.1-mini" in m or "gpt-4.1-nano" in m:
        base, per_tile = 2833, 5667
    elif "o1" in m or "o3" in m:
        base, per_tile = 75, 150
    elif "gpt-5" in m:
        base, per_tile = 70, 140
    else:
        base, per_tile = 85, 170
    return base + per_tile * tiles


def _claude_image_tokens(width: int, height: int) -> int:
    """Anthropic：tokens ≈ (w × h) / 750，长边超 1568px 时先等比缩小。

    官方示例 1092×1092 ≈ 1590 tokens，即未触发缩放时等于裸面积 / 750，
    因此仅按长边 1568 等比缩放；额外施加「1.15MP」上限会导致结果偏低。
    """
    long_edge_cap = 1568
    if max(width, height) > long_edge_cap:
        scale = long_edge_cap / max(width, height)
        width = max(1, int(width * scale))
        height = max(1, int(height * scale))
    return max(1, round(width * height / 750))


def count_image_tokens(width: int, height: int, model: str = "") -> int:
    """按模型所属厂商的视觉 token 公式估算一张图。尺寸未知时按 1024² 计算。"""
    if not width or not height or width <= 0 or height <= 0:
        width, height = 1024, 1024
    if "claude" in (model or "").lower():
        return _claude_image_tokens(width, height)
    return _openai_image_tokens(width, height, model)


def _count_image_tokens(doc: dict[str, Any], model: str = "") -> int:
    """Count vision tokens for one image document (from its stored bytes)."""
    if doc.get("kind") != "image":
        return 0
    b64 = doc.get("image_b64", "")
    if not b64:
        # 还没上传字节（前端刚选的图）：按默认尺寸估，数量级不会错。
        return count_image_tokens(0, 0, model)
    try:
        raw = base64.b64decode(b64)
    except Exception:  # noqa: BLE001
        return count_image_tokens(0, 0, model)
    size = image_size(raw)
    if size is None:
        return count_image_tokens(0, 0, model)
    return count_image_tokens(size[0], size[1], model)


def count_messages_tokens(messages: list[dict[str, Any]], model: str = "") -> int:
    """Count tokens for a list of OpenAI-style messages.

    Handles:
        - string content
        - multimodal content arrays (text / image_url)
        - attachment metadata labels
        - per-message overhead
    """
    total = 0
    for m in messages:
        content = m.get("content")
        if isinstance(content, str):
            total += count_text_tokens(content, model)
        elif isinstance(content, list):
            for part in content:
                if not isinstance(part, dict):
                    continue
                ptype = part.get("type")
                if ptype == "text":
                    total += count_text_tokens(str(part.get("text", "")), model)
                elif ptype == "image_url":
                    url = part.get("image_url", {}).get("url", "")
                    total += _count_image_tokens(
                        {"kind": "image", "image_b64": _extract_b64(url)},
                        model,
                    )

        for att in m.get("attachments", []) or []:
            label = f"{att.get('name', '')} {att.get('pages', 0)}页 {att.get('chars', 0)}字"
            total += count_text_tokens(label, model)

        total += TOKEN_FLOOR

    return total


# 上下文窗口表：顺序 = 从具体到宽泛，命中即返回。
# 该表由后端统一维护，前端通过 /api/chat/estimate 获取上限，不另行存放副本。
_MODEL_CONTEXT_LIMITS: tuple[tuple[str, int], ...] = (
    # OpenAI：新版大窗，老 gpt-4 基线其实只有 8K
    ("gpt-4.1", 1_047_576),
    ("gpt-4o-mini", 128_000),
    ("gpt-4o", 128_000),
    ("gpt-4-turbo", 128_000),
    ("gpt-4-32k", 32_768),
    ("gpt-4", 8_192),
    ("gpt-3.5-turbo-16k", 16_384),
    ("gpt-3.5", 16_384),
    ("o1", 200_000),
    ("o3", 200_000),
    ("gpt-5", 400_000),
    # Anthropic：Claude 3 及以后都是 200K，只有 Claude 2 是 100K
    ("claude-2", 100_000),
    ("claude-3", 200_000),
    ("claude", 200_000),
    # DeepSeek：chat / reasoner 都是 64K
    ("deepseek", 64_000),
    # 阿里通义
    ("qwen-long", 1_000_000),
    ("qwen-max", 32_768),
    ("qwen-plus", 131_072),
    ("qwen-turbo", 131_072),
    ("qwen", 32_768),
    # 智谱 / Kimi / 豆包 / 文心
    ("glm-4", 128_000),
    ("moonshot", 128_000),
    ("doubao", 256_000),
    ("ernie", 128_000),
)


def context_limit_for_model(model: str) -> int:
    """Return the context-window limit for the model name. 未知模型按 64K 计。"""
    m = (model or "").lower()
    for key, limit in _MODEL_CONTEXT_LIMITS:
        if key in m:
            return limit
    return 64_000
