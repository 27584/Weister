"""联网工具：搜索、网页抓取、当前时间。

让专家智能体能够获取训练数据之外的时效性信息（新闻 / 公告 / 政策 / 行情动态），
并对资料标注来源与时间。

搜索源按优先级自动降级（配置见 backend/.env 或设置面板）：
    1. Tavily      —— TAVILY_API_KEY，LLM 生态最常用
    2. 博查 Bocha  —— BOCHA_API_KEY，国内可用性最好
    3. SearXNG     —— SEARXNG_URL，自建元搜索
    4. 百度        —— 无需 Key 的降级源（中文财经与公司信息相关度更好）
    5. 必应中国    —— 无需 Key 的降级源，结果页解析受页面结构影响

全部走 httpx 同步客户端（AgentRunner 的工具 handler 为同步调用），
超时 12s，跟随重定向，信任系统代理环境变量。
"""

from __future__ import annotations

import base64
import html as html_mod
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from ..config import settings
from ._http import get as http_get

_TIMEOUT = httpx.Timeout(12.0)


def _conf(key: str) -> str:
    """读搜索源配置：请求头 / 前端存档优先，缺失再回落到 backend/.env。"""
    from ..searchcfg import get as _get_cfg

    v = (_get_cfg().get(key) or "").strip()
    if v:
        return v
    return str(getattr(settings, key, "") or "").strip()


_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

_SEARCH_HINT = (
    "（可用搜索源均失败。可在「设置 → 搜索 API」填写 Tavily / 博查 / SearXNG，"
    "或在 backend/.env 配置 TAVILY_API_KEY / BOCHA_API_KEY / SEARXNG_URL）"
)


def _client() -> httpx.Client:
    return httpx.Client(timeout=_TIMEOUT, follow_redirects=True, headers={"User-Agent": _UA})


def _search_tavily(query: str, max_results: int) -> list[dict[str, Any]]:
    key = _conf("tavily_api_key").strip()
    if not key:
        return []
    resp = httpx.post(
        "https://api.tavily.com/search",
        headers={"Authorization": f"Bearer {key}"},
        json={"query": query, "max_results": max_results, "search_depth": "basic"},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    out = []
    for item in resp.json().get("results", [])[:max_results]:
        out.append(
            {
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "snippet": (item.get("content") or "")[:400],
            }
        )
    return out


def _search_bocha(query: str, max_results: int) -> list[dict[str, Any]]:
    key = _conf("bocha_api_key").strip()
    if not key:
        return []
    resp = httpx.post(
        "https://api.bochaai.com/v1/web-search",
        headers={"Authorization": f"Bearer {key}"},
        json={"query": query, "count": max_results, "summary": True},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    pages = ((resp.json().get("data") or {}).get("webPages") or {}).get("value") or []
    out = []
    for item in pages[:max_results]:
        out.append(
            {
                "title": item.get("name", ""),
                "url": item.get("url", ""),
                "snippet": (item.get("summary") or item.get("snippet") or "")[:400],
            }
        )
    return out


def _search_searxng(query: str, max_results: int) -> list[dict[str, Any]]:
    base = _conf("searxng_url").strip().rstrip("/")
    if not base:
        return []
    resp = httpx.get(
        f"{base}/search",
        params={"q": query, "format": "json"},
        timeout=_TIMEOUT,
        headers={"User-Agent": _UA},
    )
    resp.raise_for_status()
    out = []
    for item in resp.json().get("results", [])[:max_results]:
        out.append(
            {
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "snippet": (item.get("content") or "")[:400],
            }
        )
    return out


_TAG_RE = re.compile(r"<[^>]+>")
_BING_REDIRECT_RE = re.compile(r"[?&]u=a1([A-Za-z0-9_\-]+)")


def _decode_bing_redirect(url: str) -> str:
    """cn.bing.com 的结果链接是 /ck/a?...&u=a1<base64> 跳转，还原真实 URL。"""
    m = _BING_REDIRECT_RE.search(url)
    if not m:
        return url
    raw = m.group(1)
    raw += "=" * (-len(raw) % 4)
    try:
        return base64.urlsafe_b64decode(raw).decode("utf-8", "ignore")
    except Exception:  # noqa: BLE001
        return url


def _get(url: str, params: dict[str, str] | None = None) -> httpx.Response:
    """GET，代理失败时自动降级为直连（实现见 tools._http）。"""
    return http_get(url, params=params)


def _search_baidu(query: str, max_results: int) -> list[dict[str, Any]]:
    """抓百度结果页：无需 Key 的降级源，中文财务与公司信息相关度最好。

    结果链接为 baidu.com/link?url=... 跳转链，fetch_url 可跟随解析到原文。
    命中风控页时解析结果为空，抛错后由上层降级到下一个源。
    """
    resp = _get("https://www.baidu.com/s", {"wd": query, "rn": str(max_results)})
    resp.raise_for_status()
    page = resp.text

    items = re.findall(
        r'<h3[^>]*class="[^"]*c-title[^"]*"[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
        page,
        re.DOTALL,
    )
    out: list[dict[str, Any]] = []
    for url, title in items[:max_results]:
        title = html_mod.unescape(_TAG_RE.sub("", title)).strip()
        if not title:
            continue
        out.append(
            {
                "title": title,
                "url": html_mod.unescape(url),
                "snippet": "",  # 百度摘要结构多变且常被 JS 填充，标题已足够定位
            }
        )
    if not out:
        raise RuntimeError("百度结果页解析为空（可能触发风控页）")
    return out


def _search_bing_cn(query: str, max_results: int) -> list[dict[str, Any]]:
    """抓 cn.bing.com 结果页：无需 Key 的降级源，国内可直连。

    页面结构变化或命中风控时抛错，由上层降级到下一个源。
    """
    resp = _get(
        "https://cn.bing.com/search", {"q": query, "count": str(max_results), "setlang": "zh-hans"}
    )
    resp.raise_for_status()
    page = resp.text

    blocks = re.findall(r'<li class="b_algo".*?</li>', page, re.DOTALL)
    out: list[dict[str, Any]] = []
    for block in blocks[:max_results]:
        m = re.search(r'<h2[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', block, re.DOTALL)
        if not m:
            continue
        url = html_mod.unescape(m.group(1))
        title = _TAG_RE.sub("", m.group(2)).strip()
        sm = re.search(r"<p[^>]*>(.*?)</p>", block, re.DOTALL)
        snippet = _TAG_RE.sub("", sm.group(1)).strip() if sm else ""
        out.append(
            {
                "title": html_mod.unescape(title),
                "url": _decode_bing_redirect(url),
                "snippet": html_mod.unescape(snippet)[:400],
            }
        )
    if not out:
        raise RuntimeError("必应结果页解析为空（页面结构变化或触发风控）")
    return out


def web_search(query: str, max_results: int = 8) -> dict[str, Any]:
    """联网搜索：按配置的源依次尝试，返回带来源的结果列表。"""
    query = (query or "").strip()
    if not query:
        raise ValueError("query 不能为空")
    max_results = max(1, min(int(max_results or 8), 10))

    providers: list[tuple[str, Any]] = [
        ("tavily", _search_tavily),
        ("bocha", _search_bocha),
        ("searxng", _search_searxng),
        ("baidu", _search_baidu),
        ("bing_cn", _search_bing_cn),
    ]
    errors: list[str] = []
    for name, fn in providers:
        try:
            results = fn(query, max_results)
        except Exception as exc:  # noqa: BLE001
            # 未配置的源静默跳过；配置了但失败的记录原因
            if _provider_configured(name):
                errors.append(f"{name}: {exc}")
            continue
        if results:
            return {
                "query": query,
                "provider": name,
                "results": results,
                "note": "请在结论中标注来源 URL 与信息时间；不同来源有出入时如实指出。",
            }
        errors.append(f"{name}: 无结果")
    raise RuntimeError("; ".join(errors) + " " + _SEARCH_HINT)


def _provider_configured(name: str) -> bool:
    if name == "tavily":
        return bool(_conf("tavily_api_key"))
    if name == "bocha":
        return bool(_conf("bocha_api_key"))
    if name == "searxng":
        return bool(_conf("searxng_url"))
    return True


def fetch_url(url: str, max_chars: int = 8000) -> dict[str, Any]:
    """抓取网页并提取正文文本（去 script/style/标签），供智能体阅读。"""
    url = (url or "").strip()
    if not url.lower().startswith(("http://", "https://")):
        raise ValueError(f"仅支持 http/https URL：{url!r}")
    max_chars = max(200, min(int(max_chars or 8000), 20000))

    resp = _get(url)
    resp.raise_for_status()
    content_type = resp.headers.get("content-type", "")
    if "html" not in content_type.lower():
        text = resp.text[:max_chars]
        return {
            "url": str(resp.url),
            "status": resp.status_code,
            "content_type": content_type,
            "text": text,
            "truncated": len(resp.text) > max_chars,
        }

    page = resp.text
    page = re.sub(
        r"<(script|style|noscript)[^>]*>.*?</\1>", " ", page, flags=re.DOTALL | re.IGNORECASE
    )
    page = re.sub(r"<!--.*?-->", " ", page, flags=re.DOTALL)
    # 块级标签转换行，避免正文粘连
    page = re.sub(
        r"</(p|div|li|tr|h[1-6]|section|article|blockquote)>", "\n", page, flags=re.IGNORECASE
    )
    page = re.sub(r"<(br|hr)\s*/?>", "\n", page, flags=re.IGNORECASE)
    text = _TAG_RE.sub("", page)
    text = html_mod.unescape(text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text).strip()

    title = ""
    tm = re.search(r"<title[^>]*>(.*?)</title>", resp.text, re.DOTALL | re.IGNORECASE)
    if tm:
        title = html_mod.unescape(_TAG_RE.sub("", tm.group(1))).strip()

    return {
        "url": str(resp.url),
        "status": resp.status_code,
        "content_type": content_type,
        "title": title[:200],
        "text": text[:max_chars],
        "truncated": len(text) > max_chars,
    }


def current_datetime() -> dict[str, Any]:
    """当前北京时间。智能体判断资料时效性、生成日期标注前先调用。

    用固定 UTC+8 偏移而不是 ZoneInfo：Windows 环境缺少 tzdata 包时，
    ZoneInfo("Asia/Shanghai") 会抛出 ZoneInfoNotFoundError。
    """
    now = datetime.now(timezone(timedelta(hours=8)))
    weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    return {
        "datetime": now.strftime("%Y-%m-%d %H:%M:%S"),
        "date": now.strftime("%Y-%m-%d"),
        "weekday": weekdays[now.weekday()],
        "timezone": "Asia/Shanghai (UTC+8)",
        "unix": int(now.timestamp()),
    }


registry_tools = [
    {
        "name": "web_search",
        "description": (
            "联网搜索最新公开信息（新闻 / 公告 / 政策 / 市场动态），"
            "返回带来源 URL 的结果列表。结论中必须标注来源。"
        ),
        "input_schema": {
            "query": "str",
            "max_results": "int（可选，默认 8，上限 10）",
        },
        "handler": web_search,
    },
    {
        "name": "fetch_url",
        "description": (
            "抓取指定网页并提取正文文本（自动去除脚本与标签）。"
            "用于阅读 web_search 结果里的关键页面。"
        ),
        "input_schema": {
            "url": "str",
            "max_chars": "int（可选，默认 8000，上限 20000）",
        },
        "handler": fetch_url,
    },
    {
        "name": "current_datetime",
        "description": (
            "获取当前北京时间。判断资料时效性、标注报告日期前先调用它，不要凭记忆猜测今天日期。"
        ),
        "input_schema": {},
        "handler": current_datetime,
    },
]


def register() -> None:
    from ..core.registry import Tool, registry

    for spec in registry_tools:
        registry.add_tool(
            Tool(
                name=spec["name"],
                description=spec["description"],
                input_schema=spec["input_schema"],
                handler=spec["handler"],
                tags=["web"],
            )
        )


# 导入即注册（与 skills.py 同一模式：tools/__init__ import 副作用）
register()
