"""分析流水线 SSE 流与路由。"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from .. import checkpoint, runlog, storage
from ..config import settings
from ..events import EventType, NodeStatus
from ..llm import LLMError
from ..orchestrator import graph
from ..providers import resolve
from .deps import DEFAULT_QUESTION, DEMO_QUESTION, Credentials, bind_search_config, credentials
from .sse import sse

router = APIRouter()
DEFAULT_SAMPLE = "annual_report"


async def _run_stream(
    run_id: str,
    filename: str,
    raw: bytes,
    question: str,
    cred: Credentials,
) -> AsyncIterator[str]:
    seq = 0
    logger = runlog.RunLogger(run_id)

    def wrap(event: dict) -> str:
        nonlocal seq
        seq += 1
        event["seq"] = seq
        logger.event(event)
        return sse(event)

    # resolve 失败时也要能用原始 provider/model 记录日志，因此先给回退值。
    # 这样 logger.start() 全程只调用一次，不会在事件流里留下重复的 run_start。
    pkey, pbase, pmodel = cred.provider, cred.base_url or "", cred.model
    cred_error: Exception | None = None
    try:
        pkey, pbase, pmodel = resolve(cred.provider, cred.model, cred.base_url or None)
        # 提前校验凭据，避免跑了一半才报错。
        # 这里按 LLMClient 的同一规则判定（请求头优先，回退 .env 的 LLM_API_KEY），
        # 但不为此构造一个用完即弃的客户端实例。
        if not (cred.api_key or settings.llm_api_key):
            raise LLMError(
                "未提供 API Key：请通过 X-LLM-Api-Key 请求头传递，"
                "或在 backend/.env 中配置 LLM_API_KEY"
            )
    except Exception as exc:
        cred_error = exc

    logger.start(filename, pkey, pmodel, question)

    if cred_error is not None:
        yield wrap(
            {
                "type": EventType.ERROR.value,
                "run_id": run_id,
                "node": None,
                "status": NodeStatus.FAILED.value,
                "message": str(cred_error),
                "payload": {},
            }
        )
        yield wrap(
            {
                "type": EventType.RUN_END.value,
                "run_id": run_id,
                "node": None,
                "status": NodeStatus.FAILED.value,
                "message": "aborted",
                "payload": {},
            }
        )
        logger.finish("failed")
        return

    yield wrap(
        {
            "type": EventType.RUN_START.value,
            "run_id": run_id,
            "node": None,
            "status": NodeStatus.RUNNING.value,
            "message": f"开始分析：{filename}",
            "payload": {"provider": pkey, "model": pmodel, "base_url": pbase},
        }
    )

    state = {
        "run_id": run_id,
        "filename": filename,
        "raw_bytes": raw,
        "question": question,
        "provider": pkey,
        "model": pmodel,
        "fallback_models": cred.fallback_models,
        "base_url": pbase,
        "api_key": cred.api_key,
    }

    final_state: dict = {}
    failed = False
    try:
        async for mode, chunk in graph.astream(state, stream_mode=["custom", "values"]):
            if mode == "custom":
                yield wrap(chunk)
            else:
                final_state = chunk
    except Exception as exc:
        failed = True
        yield wrap(
            {
                "type": EventType.ERROR.value,
                "run_id": run_id,
                "node": None,
                "status": NodeStatus.FAILED.value,
                "message": str(exc),
                "payload": {},
            }
        )

    if failed:
        yield wrap(
            {
                "type": EventType.RUN_END.value,
                "run_id": run_id,
                "node": None,
                "status": NodeStatus.FAILED.value,
                "message": "aborted",
                "payload": {},
            }
        )
        logger.finish("failed")
        return

    yield wrap(
        {
            "type": EventType.RESULT.value,
            "run_id": run_id,
            "node": None,
            "status": NodeStatus.SUCCESS.value,
            "message": "分析完成",
            "payload": {
                "extracted": final_state.get("extracted", {}),
                "metrics": final_state.get("metrics", {}),
                "assumptions": final_state.get("assumptions", {}),
                "dcf": final_state.get("dcf", {}),
                "relative": final_state.get("relative", {}),
                "sensitivity": final_state.get("sensitivity", {}),
                "valuation_summary": final_state.get("valuation_summary", {}),
                "analyses": {
                    k: {
                        "name": v.get("name"),
                        "role": v.get("role"),
                        "output": v.get("output"),
                        "steps": v.get("steps"),
                        "tools_used": v.get("tools_used"),
                        "elapsed_ms": v.get("elapsed_ms"),
                    }
                    for k, v in (final_state.get("analyses") or {}).items()
                },
                "expert_opinions": final_state.get("expert_opinions", []),
                "report_md": final_state.get("report_md", ""),
                "citations": final_state.get("citations", []),
                "trace": final_state.get("trace", []),
                "run_id": run_id,
            },
        }
    )

    yield wrap(
        {
            "type": EventType.RUN_END.value,
            "run_id": run_id,
            "node": None,
            "status": NodeStatus.SUCCESS.value,
            "message": "done",
            "payload": {},
        }
    )

    logger.finish("success")


def _init_checkpoint(run_id: str, filename: str, question: str) -> None:
    """创建初始检查点。

    必须把 question 一并写入：续跑时要用它恢复用户原本的提问。
    否则 /api/analyze/resume 将回退到默认问题重跑，
    同一份财报会因为问法不同而得出与首次不一致的结论。
    """
    checkpoint.save(
        run_id,
        {
            "run_id": run_id,
            "filename": filename,
            "question": question,
            "finished": False,
            "completed_nodes": [],
            "agents": {},
        },
    )


@router.get("/api/analyze/demo")
async def analyze_demo(
    sample: str = DEFAULT_SAMPLE,
    cred: Credentials = Depends(credentials),
) -> StreamingResponse:
    text = storage.read_sample(sample)
    if text is None:
        raise HTTPException(status_code=404, detail=f"样例不存在：{sample}")

    payload = text.encode("utf-8")
    base = sample.removesuffix(".txt")
    filename = f"{base}.txt"
    run_id = uuid.uuid4().hex[:12]
    _init_checkpoint(run_id, filename, DEMO_QUESTION)
    bind_search_config(cred)
    return StreamingResponse(
        _run_stream(run_id, filename, payload, DEMO_QUESTION, cred),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/api/analyze/resume")
async def analyze_resume(
    run_id: str,
    cred: Credentials = Depends(credentials),
) -> StreamingResponse:
    ckpt = checkpoint.load(run_id)
    if ckpt is None:
        raise HTTPException(status_code=404, detail="检查点不存在")

    raw = (ckpt.get("document_text") or "").encode("utf-8")
    filename = ckpt.get("filename") or "resume.txt"
    # 恢复用户首次运行时的问题，而不是套用默认问法
    question = ckpt.get("question") or DEFAULT_QUESTION

    bind_search_config(cred)
    return StreamingResponse(
        _run_stream(run_id, filename, raw, question, cred),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.post("/api/analyze")
async def analyze(
    file: UploadFile = File(...),
    question: str = Form(DEFAULT_QUESTION),
    cred: Credentials = Depends(credentials),
) -> StreamingResponse:
    raw = await file.read()
    filename = file.filename or "upload.bin"
    run_id = uuid.uuid4().hex[:12]
    _init_checkpoint(run_id, filename, question)
    bind_search_config(cred)
    return StreamingResponse(
        _run_stream(run_id, filename, raw, question, cred),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


__all__ = ["_init_checkpoint", "_run_stream", "router"]
