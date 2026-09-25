"""LLM 客户端。

统一走 OpenAI 兼容协议，支持：
    - 原生 messages 数组（保留多轮角色信息）
    - SSE 流式输出，同时提取 content 与 reasoning_content
    - 指数退避重试 + 备用模型链自动切换
"""

from __future__ import annotations

import json
import random
import time
from collections.abc import Callable, Iterator
from typing import Any

import httpx

from .config import settings

RETRY_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}
MAX_ATTEMPTS = 8
BACKOFF_BASE = 2.0
BACKOFF_CAP = 60.0
FALLBACK_AFTER = 3


class LLMError(RuntimeError):
    pass


class Delta:
    """一次流式增量。

    content    正文片段
    reasoning  推理片段（推理模型的思考过程）
    tool_call  工具调用增量，形如
               {"index": 0, "id": "call_xxx", "name": "dcf_valuation",
                "arguments": "{\"base_revenue\": 100}"}
               arguments 是分片累积的，调用方需按 index 拼接。
    """

    __slots__ = ("content", "reasoning", "tool_call")

    def __init__(
        self,
        content: str = "",
        reasoning: str = "",
        tool_call: dict[str, Any] | None = None,
    ) -> None:
        self.content = content
        self.reasoning = reasoning
        self.tool_call = tool_call


class LLMClient:
    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        fallback_models: list[str] | None = None,
        timeout: float = 300.0,
        max_attempts: int = MAX_ATTEMPTS,
        on_retry: Callable[[int, float, str], None] | None = None,
        on_switch: Callable[[str, str], None] | None = None,
    ) -> None:
        self.base_url = (base_url or settings.llm_base_url).rstrip("/")
        self.api_key = api_key or settings.llm_api_key
        self.model = model or settings.llm_model
        self.fallback_models = [m for m in (fallback_models or []) if m and m != self.model]
        self.timeout = timeout
        self.max_attempts = max_attempts
        self.on_retry = on_retry
        self.on_switch = on_switch
        self._active_model = self.model
        self._model_failures = 0

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    @property
    def active_model(self) -> str:
        return self._active_model

    def require_configured(self) -> None:
        if not self.api_key:
            raise LLMError("未提供 API Key")

    @staticmethod
    def _backoff(attempt: int) -> float:
        base = min(BACKOFF_BASE**attempt, BACKOFF_CAP)
        return base * (0.7 + random.random() * 0.6)

    def _notify_retry(self, attempt: int, wait: float, reason: str) -> None:
        if self.on_retry:
            self.on_retry(attempt, wait, reason)

    def _switch_model(self) -> bool:
        if not self.fallback_models:
            return False
        previous = self._active_model
        self._active_model = self.fallback_models.pop(0)
        self._model_failures = 0
        if self.on_switch:
            self.on_switch(previous, self._active_model)
        return True

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def stream_messages(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str = "auto",
    ) -> Iterator[Delta]:
        """流式调用。

        max_tokens 默认 None，即不限制——推理模型的 reasoning 与 content
        共享该预算，限制它会挤压正文空间。

        tools 传入 OpenAI 格式的工具声明时，模型会返回结构化的 tool_calls，
        无需解析文本。这是推荐的使用方式。
        """
        self.require_configured()
        url = f"{self.base_url}/chat/completions"
        headers = self._headers()

        attempt = 0
        last_error: Exception | None = None

        while attempt < self.max_attempts:
            attempt += 1
            payload: dict[str, Any] = {
                "model": self._active_model,
                "temperature": settings.llm_temperature if temperature is None else temperature,
                "stream": True,
                "messages": messages,
            }
            # 仅在显式指定时才传，默认让模型自行决定输出长度
            if max_tokens is not None and max_tokens > 0:
                payload["max_tokens"] = max_tokens
            if tools:
                payload["tools"] = tools
                payload["tool_choice"] = tool_choice

            try:
                with httpx.stream(
                    "POST", url, headers=headers, json=payload, timeout=self.timeout
                ) as resp:
                    if resp.status_code in RETRY_STATUS:
                        resp.read()
                        self._model_failures += 1
                        if self._model_failures >= FALLBACK_AFTER and self._switch_model():
                            attempt = 0
                            continue
                        if attempt < self.max_attempts:
                            wait = self._backoff(attempt)
                            self._notify_retry(attempt, wait, f"HTTP {resp.status_code}")
                            time.sleep(wait)
                            continue
                        raise LLMError(f"LLM {resp.status_code}: {resp.text[:500]}")

                    if resp.status_code >= 400:
                        resp.read()
                        raise LLMError(f"LLM {resp.status_code}: {resp.text[:500]}")

                    yield from self._iter_deltas(resp)
                    return
            except httpx.TimeoutException as exc:
                last_error = LLMError(f"请求超时（{self.timeout:.0f}s）")
                self._model_failures += 1
                if self._model_failures >= FALLBACK_AFTER and self._switch_model():
                    attempt = 0
                    continue
                if attempt < self.max_attempts:
                    wait = self._backoff(attempt)
                    self._notify_retry(attempt, wait, "timeout")
                    time.sleep(wait)
                    continue
                raise last_error from exc
            except httpx.HTTPError as exc:
                last_error = LLMError(f"网络请求失败：{exc}")
                self._model_failures += 1
                if self._model_failures >= FALLBACK_AFTER and self._switch_model():
                    attempt = 0
                    continue
                if attempt < self.max_attempts:
                    wait = self._backoff(attempt)
                    self._notify_retry(attempt, wait, "network")
                    time.sleep(wait)
                    continue
                raise last_error from exc

        raise last_error or LLMError("LLM 调用失败")

    @staticmethod
    def _iter_deltas(resp: httpx.Response) -> Iterator[Delta]:
        for line in resp.iter_lines():
            if not line or not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                chunk = json.loads(data)
            except json.JSONDecodeError:
                continue

            choices = chunk.get("choices") or []
            if not choices:
                continue

            delta = choices[0].get("delta") or {}
            content = delta.get("content") or ""
            reasoning = delta.get("reasoning_content") or delta.get("reasoning") or ""
            tool_calls = delta.get("tool_calls") or []

            if content or reasoning:
                yield Delta(content=content, reasoning=reasoning)

            for tc in tool_calls:
                fn = tc.get("function") or {}
                yield Delta(
                    tool_call={
                        "index": tc.get("index", 0),
                        "id": tc.get("id") or "",
                        "name": fn.get("name") or "",
                        "arguments": fn.get("arguments") or "",
                    }
                )

    def stream(
        self,
        system: str,
        user: str,
        *,
        temperature: float | None = None,
    ) -> Iterator[Delta]:
        yield from self.stream_messages(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=temperature,
        )

    def chat(self, system: str, user: str, *, temperature: float | None = None) -> str:
        parts: list[str] = []
        for delta in self.stream(system, user, temperature=temperature):
            if delta.content:
                parts.append(delta.content)
        return "".join(parts)

    def chat_json(self, system: str, user: str, *, temperature: float | None = None) -> Any:
        raw = self.chat(
            system + "\n只输出 JSON，不要任何解释或 Markdown 代码块围栏。",
            user,
            temperature=temperature,
        )
        return parse_json_loose(raw)


def parse_json_loose(raw: str) -> Any:
    """宽松解析 JSON：容忍无围栏、```json 围栏、前后夹说明文字三种形态。

    与 chat_supervisor._parse_decision 的容错逻辑对齐，避免模型输出稍微
    不规范（如缺闭合围栏、前面带一句"这是结果："）就直接抛 JSONDecodeError。
    """
    text = (raw or "").strip()
    if not text:
        raise ValueError("empty LLM output, cannot parse JSON")

    # 1) 直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 2) 去 ```json ... ``` 围栏
    fence = chr(96) * 3
    body = text
    if body.startswith(fence):
        body = body[len(fence) :]
        body = body.removeprefix("json")
        if fence in body:
            body = body.split(fence)[0]
        body = body.strip()
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            pass

    # 3) 退化：取第一个 { 到最后一个 } 之间的内容
    first = text.find("{")
    last = text.rfind("}")
    if first >= 0 and last > first:
        candidate = text[first : last + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError as exc:
            raise ValueError(f"无法解析 JSON：{exc}") from exc

    raise ValueError("响应中找不到合法的 JSON 对象")


llm = LLMClient()
