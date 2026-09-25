"""LLM 提供商注册表。

内置常见国产与国际模型端点，切换提供商无需改代码。
"""

from __future__ import annotations

from typing import TypedDict


class ProviderSpec(TypedDict):
    label: str
    base_url: str
    models: list[str]
    doc: str


PROVIDERS: dict[str, ProviderSpec] = {
    "deepseek": {
        "label": "DeepSeek 深度求索",
        "base_url": "https://api.deepseek.com/v1",
        "models": ["deepseek-chat", "deepseek-reasoner"],
        "doc": "https://platform.deepseek.com",
    },
    "qwen": {
        "label": "通义千问（阿里云百炼）",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "models": ["qwen-plus", "qwen-max", "qwen-turbo", "qwen-long"],
        "doc": "https://bailian.console.aliyun.com",
    },
    "glm": {
        "label": "智谱 GLM",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "models": ["glm-4-plus", "glm-4-air", "glm-4-flash"],
        "doc": "https://open.bigmodel.cn",
    },
    "moonshot": {
        "label": "月之暗面 Kimi",
        "base_url": "https://api.moonshot.cn/v1",
        "models": ["moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k"],
        "doc": "https://platform.moonshot.cn",
    },
    "openai": {
        "label": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "models": ["gpt-4o", "gpt-4o-mini", "gpt-4.1"],
        "doc": "https://platform.openai.com",
    },
    "ollama": {
        "label": "Ollama 本地",
        "base_url": "http://127.0.0.1:11434/v1",
        "models": ["qwen2.5:7b", "qwen2.5:14b", "deepseek-r1:7b", "llama3.1:8b"],
        "doc": "https://ollama.com",
    },
    "custom": {
        "label": "自定义（OpenAI 兼容）",
        "base_url": "",
        "models": [],
        "doc": "",
    },
}

DEFAULT_PROVIDER = "deepseek"


def resolve_base(
    provider: str | None,
    base_url: str | None = None,
) -> tuple[str, str]:
    key = (provider or DEFAULT_PROVIDER).lower()
    spec = PROVIDERS.get(key)

    if spec is None:
        key = "custom"
        spec = PROVIDERS["custom"]

    if not base_url:
        if not spec["base_url"]:
            raise ValueError("自定义提供商必须填写 Base URL")
        base_url = spec["base_url"]

    return key, base_url.rstrip("/")


def resolve(
    provider: str | None,
    model: str | None,
    base_url: str | None = None,
) -> tuple[str, str, str]:
    key, base = resolve_base(provider, base_url)
    spec = PROVIDERS.get(key) or PROVIDERS["custom"]

    if not model:
        if not spec["models"]:
            raise ValueError("自定义提供商必须填写模型名称")
        model = spec["models"][0]

    return key, base, model


def catalog() -> dict:
    return {
        "default": DEFAULT_PROVIDER,
        "providers": [
            {
                "key": k,
                "label": v["label"],
                "base_url": v["base_url"],
                "models": v["models"],
                "doc": v["doc"],
            }
            for k, v in PROVIDERS.items()
        ],
    }
