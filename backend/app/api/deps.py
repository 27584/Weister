"""HTTP 依赖：凭据解析与搜索配置绑定。"""

from __future__ import annotations

from fastapi import Header
from pydantic import BaseModel

from .. import storage
from ..config import settings

# 默认研究问题：上传文件与续跑都以此为默认值
DEFAULT_QUESTION = "请分析该公司本期经营与财务表现，并给出估值区间。"
# 内置样例使用的问题（样例是通用年报，问法略作收敛）
DEMO_QUESTION = "分析盈利质量、现金流风险并给出估值区间。"


class Credentials(BaseModel):
    provider: str = "deepseek"
    model: str = ""
    fallback_models: list[str] = []
    api_key: str = ""
    base_url: str = ""
    # 搜索源：走请求头时优先于 profiles.json 里保存的配置
    tavily_api_key: str = ""
    bocha_api_key: str = ""
    searxng_url: str = ""


def credentials(
    x_llm_provider: str = Header(default="deepseek", alias="X-LLM-Provider"),
    x_llm_model: str = Header(default="", alias="X-LLM-Model"),
    x_llm_fallback_models: str = Header(default="", alias="X-LLM-Fallback-Models"),
    x_llm_api_key: str = Header(default="", alias="X-LLM-Api-Key"),
    x_llm_base_url: str = Header(default="", alias="X-LLM-Base-Url"),
    x_search_tavily_key: str = Header(default="", alias="X-Search-Tavily-Key"),
    x_search_bocha_key: str = Header(default="", alias="X-Search-Bocha-Key"),
    x_search_searxng_url: str = Header(default="", alias="X-Search-Searxng-Url"),
) -> Credentials:
    """从请求头提取模型凭据。

    FastAPI 的 Header 依赖会自动处理大小写与连字符/下划线转换。
    """
    fallbacks = [m.strip() for m in x_llm_fallback_models.split(",") if m.strip()]
    return Credentials(
        provider=x_llm_provider or "deepseek",
        model=x_llm_model,
        fallback_models=fallbacks,
        api_key=x_llm_api_key,
        base_url=x_llm_base_url,
        tavily_api_key=x_search_tavily_key,
        bocha_api_key=x_search_bocha_key,
        searxng_url=x_search_searxng_url,
    )


def bind_search_config(cred: Credentials) -> None:
    """把本次请求生效的搜索配置绑定到当前 context。

    取值优先级：请求头 > profiles.json 存档 > backend/.env。
    必须在 asyncio.to_thread 之前调用 —— to_thread 会复制 context，
    这样 worker 线程里的 web_search 才能读到本请求的 Key。
    """
    from ..searchcfg import bind

    stored = storage.load_profiles().get("search") or {}

    def pick(name: str, header_val: str) -> str:
        hv = (header_val or "").strip()
        return hv or str(stored.get(name) or "").strip()

    bind(
        {
            "tavily_api_key": pick("tavilyApiKey", cred.tavily_api_key),
            "bocha_api_key": pick("bochaApiKey", cred.bocha_api_key),
            "searxng_url": pick("searxngUrl", cred.searxng_url),
        }
    )


__all__ = [
    "DEFAULT_QUESTION",
    "DEMO_QUESTION",
    "Credentials",
    "bind_search_config",
    "credentials",
    "settings",
]
