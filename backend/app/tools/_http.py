"""工具层共用的 HTTP 客户端。

统一处理两个环境问题：
    1. 系统代理（如 Clash）对境内站点可能返回 502 / ProxyError，
       而直连可用 —— 因此先按环境变量走代理，失败后关闭代理重试。
    2. 部分财经接口要求浏览器 User-Agent，缺失时返回空数据或风控页。
"""

from __future__ import annotations

import time
from typing import Any

import httpx

DEFAULT_TIMEOUT = 12.0
RETRY_BACKOFF = 0.35
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


def get(
    url: str,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    retries: int = 2,
) -> httpx.Response:
    """GET，代理失败自动降级直连，并对瞬时断连做有限重试。

    财经接口在高频访问下会直接断开连接而不返回响应，
    因此每轮（代理 / 直连）都会重试 retries 次。
    """
    merged = {"User-Agent": _UA, **(headers or {})}
    last: Exception | None = None
    for trust_env in (True, False):
        for attempt in range(max(1, retries)):
            try:
                with httpx.Client(
                    timeout=httpx.Timeout(timeout),
                    follow_redirects=True,
                    headers=merged,
                    trust_env=trust_env,
                ) as client:
                    resp = client.get(url, params=params)
                    resp.raise_for_status()
                    return resp
            except Exception as exc:  # noqa: BLE001 - 全部尝试失败才向上抛
                last = exc
                # 短暂退避：连续请求更容易被限流
                time.sleep(RETRY_BACKOFF * (attempt + 1))
    raise last  # type: ignore[misc]


def get_json(
    url: str,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> Any:
    """GET 并解析 JSON 响应体。"""
    return get(url, params=params, headers=headers, timeout=timeout).json()
