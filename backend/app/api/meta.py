"""元数据 / 配置 / 历史 CRUD 路由。"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import checkpoint, runlog, storage
from ..core.registry import registry
from ..models import ModelProbeError, list_models, probe_model
from ..providers import catalog, resolve_base
from .deps import Credentials, credentials

router = APIRouter()


@router.get("/api/health")
async def health() -> dict:
    return {"ok": True, "version": "0.3.1"}


@router.get("/api/providers")
async def providers() -> dict:
    return catalog()


@router.get("/api/registry")
async def registry_catalog() -> dict:
    return registry.catalog()


@router.get("/api/skills/{name}")
async def skill_detail(name: str) -> dict:
    """技能详情（含正文与「哪些专家持有它」），供前端展开查看。"""
    sk = registry.skills.get(name)
    if sk is None:
        raise HTTPException(status_code=404, detail=f"未加载的技能：{name}")
    owners = [
        {"key": a.key, "name": a.name} for a in registry.agents.values() if name in (a.skills or [])
    ]
    return {**sk.spec(), "body": sk.body, "agents": owners}


@router.get("/api/profiles")
async def get_profiles() -> dict:
    return storage.load_profiles()


class ProfilesPayload(BaseModel):
    profiles: list[dict] = []
    activeId: str = ""
    search: dict = {}


@router.put("/api/profiles")
async def put_profiles(payload: ProfilesPayload) -> dict:
    return storage.save_profiles(
        {
            "profiles": payload.profiles,
            "activeId": payload.activeId,
            "search": payload.search,
        }
    )


class SearchTestPayload(BaseModel):
    tavilyApiKey: str = ""
    bochaApiKey: str = ""
    searxngUrl: str = ""
    query: str = "贵州茅台 最新公告"


@router.post("/api/search/test")
async def test_search(payload: SearchTestPayload) -> dict:
    """用给定配置真跑一次搜索，返回实际命中的源与样例结果。

    设置面板用它验证 Key 是否可用 —— 只回「哪个源能用」比让用户猜强。
    """
    from ..searchcfg import bind as bind_search
    from ..tools import web as web_tools

    bind_search(
        {
            "tavily_api_key": payload.tavilyApiKey,
            "bocha_api_key": payload.bochaApiKey,
            "searxng_url": payload.searxngUrl,
        }
    )
    query = (payload.query or "").strip() or "贵州茅台 最新公告"
    try:
        res = await asyncio.to_thread(web_tools.web_search, query, 3)
    except Exception as exc:
        return {"ok": False, "provider": None, "error": str(exc)[:300]}
    results = res.get("results") or []
    return {
        "ok": len(results) > 0,
        "provider": res.get("provider"),
        "count": len(results),
        "sample": results[:1],
    }


@router.get("/api/samples")
async def list_samples() -> dict:
    return {"samples": storage.list_samples()}


class SamplePayload(BaseModel):
    name: str
    text: str


@router.post("/api/samples")
async def create_sample(payload: SamplePayload) -> dict:
    path = storage.write_sample(payload.name, payload.text)
    return {"ok": True, "filename": path.name}


@router.get("/api/runs")
async def list_runs(limit: int = 20) -> dict:
    return {"runs": checkpoint.list_runs(limit)}


@router.get("/api/runs/latest")
async def latest_run() -> dict:
    return {"checkpoint": checkpoint.latest()}


@router.get("/api/runs/{run_id}")
async def get_run(run_id: str) -> dict:
    data = checkpoint.load(run_id)
    if data is None:
        raise HTTPException(status_code=404, detail="检查点不存在")
    return {"checkpoint": data}


@router.delete("/api/runs/{run_id}")
async def delete_run(run_id: str) -> dict:
    checkpoint.clear(run_id)
    return {"ok": True}


@router.get("/api/logs")
async def list_logs(limit: int = 50) -> dict:
    return {"logs": runlog.list_run_logs(limit)}


@router.get("/api/logs/{run_id}")
async def get_log(run_id: str, limit: int = 500) -> dict:
    events = runlog.read_run_events(run_id, limit)
    if not events:
        raise HTTPException(status_code=404, detail="日志不存在")
    return {"run_id": run_id, "events": events}


@router.delete("/api/logs/{run_id}")
async def delete_log(run_id: str) -> dict:
    runlog.clear_run_log(run_id)
    return {"ok": True}


class ProbeRequest(BaseModel):
    provider: str = ""
    base_url: str = ""
    models: list[str] = []
    mode: str = "list"


@router.post("/api/models")
async def models(
    req: ProbeRequest,
    cred: Credentials = Depends(credentials),
) -> dict:
    # 优先用请求头里的 Key，其次用请求体的（兼容旧调用）
    api_key = cred.api_key or ""
    if not api_key:
        raise HTTPException(
            status_code=400, detail="未提供 API Key（请通过 X-LLM-Api-Key 请求头传递）"
        )

    provider = req.provider or cred.provider
    base_url = req.base_url or cred.base_url
    _, base = resolve_base(provider or None, base_url or None)

    if req.mode == "probe":
        results: list[dict] = []
        for m in req.models:
            try:
                results.append(probe_model(base, api_key, m))
            except ModelProbeError as exc:
                results.append({"model": m, "ok": False, "error": str(exc)})
        return {"base_url": base, "results": results}

    try:
        available = list_models(base, api_key)
    except ModelProbeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return {"base_url": base, "models": available}


__all__ = ["router"]
