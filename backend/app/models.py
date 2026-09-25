"""模型探测。

提供两个能力：
    list_models()  拉取提供商支持的模型列表
    probe_model()  对单个模型发最小请求验证连通性
"""

from __future__ import annotations

from typing import Any

import httpx

PROBE_TIMEOUT = 60.0
TEST_TIMEOUT = 90.0


class ModelProbeError(RuntimeError):
    pass


def list_models(base_url: str, api_key: str) -> list[str]:
    url = f"{base_url.rstrip('/')}/models"
    try:
        resp = httpx.get(
            url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=PROBE_TIMEOUT,
        )
    except httpx.HTTPError as exc:
        raise ModelProbeError(f"网络请求失败：{exc}") from exc

    if resp.status_code >= 400:
        raise ModelProbeError(f"HTTP {resp.status_code}: {resp.text[:300]}")

    data = resp.json()
    items = data.get("data") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise ModelProbeError("响应格式不含 data 列表")

    models: list[str] = []
    for it in items:
        if isinstance(it, dict):
            mid = it.get("id") or it.get("name")
            if isinstance(mid, str):
                models.append(mid)
    return sorted(set(models))


def probe_model(base_url: str, api_key: str, model: str) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 4,
        "temperature": 0,
    }
    try:
        resp = httpx.post(
            url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=TEST_TIMEOUT,
        )
    except httpx.TimeoutException as exc:
        raise ModelProbeError("请求超时") from exc
    except httpx.HTTPError as exc:
        raise ModelProbeError(f"网络请求失败：{exc}") from exc

    if resp.status_code >= 400:
        raise ModelProbeError(f"HTTP {resp.status_code}: {resp.text[:200]}")

    return {"model": model, "ok": True}
