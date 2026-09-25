"""图编排。

执行流程：
    ingest -> extract -> coordinator -> analysis -> review -> report

coordinator 制定计划；analysis 与 review 各自并行调度多位专家；
report 汇总所有意见成文。所有节点通过 get_stream_writer() 推送事件。
"""

from __future__ import annotations

import queue
import time
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from typing import Any

from langgraph.config import get_stream_writer

from . import checkpoint
from .agents import AgentRunner, registry
from .core.registry import AgentSpec
from .events import EventType, NodeStatus
from .llm import LLMClient
from .state import InvestState
from .tools.metrics import compute_metrics
from .tools.parsing import (
    assess_document,
    build_focus_text,
    chunk_text,
    locate_financial_pages,
    parse_pdf,
    parse_text,
    unreadable_reason,
)

EmitFn = Callable[..., None]

COORDINATOR_PLAN = [
    {
        "key": "financial_analyst",
        "node": "analysis",
        "task": "分析财报的盈利质量、现金流健康度与资产负债结构。",
    },
    {
        "key": "valuation_expert",
        "node": "analysis",
        "task": "为标的公司建立估值模型，给出估值区间与假设依据。",
    },
]

REVIEW_PLAN = [
    {
        "key": "risk_reviewer",
        "node": "review",
        "task": "审视财务分析与估值结论，识别风险并给出反向验证条件。",
    },
    {
        "key": "devils_advocate",
        "node": "review",
        "task": "从对立面质疑财务分析与估值结论，指出可能的假设错误与被忽略的风险。",
    },
]


def _make_emitter(node: str, run_id: str) -> EmitFn:
    writer = get_stream_writer()

    def emit(
        type_: EventType,
        *,
        status: NodeStatus | None = None,
        message: str | None = None,
        payload: dict[str, Any] | None = None,
        node_override: str | None = None,
    ) -> None:
        writer(
            {
                "type": type_.value,
                "run_id": run_id,
                "node": node_override or node,
                "status": status.value if status else None,
                "message": message,
                "payload": payload or {},
            }
        )

    return emit


def _trace(node: str, elapsed_ms: int, detail: dict[str, Any]) -> dict[str, Any]:
    return {"node": node, "elapsed_ms": elapsed_ms, **detail}


def build_client(state: InvestState, emit: EmitFn) -> LLMClient:
    def on_retry(attempt: int, wait: float, reason: str) -> None:
        emit(
            EventType.LOG,
            status=NodeStatus.RUNNING,
            message=f"第 {attempt} 次重试（{reason}），{wait:.1f}s 后重发",
            payload={"attempt": attempt, "wait": wait, "reason": reason},
        )

    def on_switch(old: str, new: str) -> None:
        emit(
            EventType.LOG,
            status=NodeStatus.RUNNING,
            message=f"模型持续失败，切换至备用模型：{new}",
            payload={"from": old, "to": new},
        )

    return LLMClient(
        base_url=state.get("base_url") or None,
        api_key=state.get("api_key") or None,
        model=state.get("model") or None,
        fallback_models=list(state.get("fallback_models") or []),
        on_retry=on_retry,
        on_switch=on_switch,
    )


def _load_ckpt(state: InvestState) -> dict[str, Any]:
    run_id = state.get("run_id") or ""
    if not run_id:
        return {}
    return checkpoint.load(run_id) or {}


def _save_ckpt(state: InvestState, patch: dict[str, Any]) -> None:
    run_id = state.get("run_id") or ""
    if not run_id:
        return
    data = checkpoint.load(run_id) or {
        "run_id": run_id,
        "filename": state.get("filename"),
        "finished": False,
        "completed_nodes": [],
        "agents": {},
    }
    data.update(patch)
    checkpoint.save(run_id, data)


def _mark_node(state: InvestState, node: str) -> None:
    data = _load_ckpt(state)
    done = list(data.get("completed_nodes") or [])
    if node not in done:
        done.append(node)
    _save_ckpt(state, {"completed_nodes": done, "stage": node})


def ingest(state: InvestState) -> dict[str, Any]:
    node = "ingest"
    run_id = state["run_id"]
    emit = _make_emitter(node, run_id)
    t0 = time.perf_counter()

    ckpt = _load_ckpt(state)
    if node in (ckpt.get("completed_nodes") or []) and ckpt.get("document_text"):
        emit(EventType.NODE_START, status=NodeStatus.RUNNING, message="从检查点恢复文档解析")
        emit(
            EventType.NODE_END,
            status=NodeStatus.SUCCESS,
            message=f"已恢复：{len(ckpt['document_text'])} 字",
            payload={"resumed": True},
        )
        return {
            "document_text": ckpt["document_text"],
            "chunks": ckpt.get("chunks") or [],
            "citations": ckpt.get("citations") or [],
            "trace": [_trace(node, 0, {"resumed": True})],
        }

    emit(EventType.NODE_START, status=NodeStatus.RUNNING, message="读取并解析文档")

    raw = state.get("raw_bytes") or b""
    name = (state.get("filename") or "").lower()
    text, pages = parse_pdf(raw) if name.endswith(".pdf") else parse_text(raw)

    # 可读性闸门：扫描件没有文字层，抽出的文本几乎为 0。
    # 若放行，空文本会被一路带到抽取与估值，最后产出一份
    # 「结构完整、但没有依据」的报告 —— 这类静默失败最危险。
    stats = assess_document(text, pages)
    if stats["unreadable"]:
        reason = unreadable_reason(stats, state.get("filename") or "")
        emit(
            EventType.LOG, status=NodeStatus.FAILED, message=reason, payload={"diagnostics": stats}
        )
        raise RuntimeError(reason)

    if stats["empty_pages"]:
        emit(
            EventType.LOG,
            status=NodeStatus.RUNNING,
            message=(
                f"有 {len(stats['empty_pages'])} 页没有文字层，已跳过"
                f"（页码 {stats['empty_pages']}）"
            ),
            payload={"diagnostics": stats},
        )

    chunks = chunk_text(text)

    # 长文档定位财务关键页，避免把封面目录送给模型
    focus_pages = locate_financial_pages(pages)
    focus_text, focus_numbers = build_focus_text(focus_pages)
    elapsed = int((time.perf_counter() - t0) * 1000)

    citations = [{"page": p["page"], "excerpt": p["text"][:200]} for p in pages]

    emit(
        EventType.NODE_END,
        status=NodeStatus.SUCCESS,
        message=(
            f"解析完成：{len(pages)} 页，{len(chunks)} 个片段；"
            f"定位财务关键页 {len(focus_numbers)} 页"
            + (f"；{len(stats['ocr_pages'])} 页经 OCR 识别" if stats["ocr_pages"] else "")
        ),
        payload={
            "chars": len(text),
            "pages": len(pages),
            "chunks": len(chunks),
            "focus_pages": focus_numbers,
            "diagnostics": stats,
        },
    )

    _save_ckpt(
        state,
        {
            "document_text": text,
            "chunks": chunks,
            "citations": citations,
            "focus_text": focus_text,
            "focus_pages": focus_numbers,
            "diagnostics": stats,
        },
    )
    _mark_node(state, node)

    return {
        "document_text": text,
        "chunks": chunks,
        "citations": citations,
        "focus_text": focus_text,
        "focus_pages": focus_numbers,
        "trace": [
            _trace(
                node,
                elapsed,
                {
                    "chars": len(text),
                    "chunks": len(chunks),
                    "focus_pages": focus_numbers,
                },
            )
        ],
    }


def extract(state: InvestState) -> dict[str, Any]:
    node = "extract"
    run_id = state["run_id"]
    emit = _make_emitter(node, run_id)
    t0 = time.perf_counter()

    ckpt = _load_ckpt(state)
    if ckpt.get("extracted") and ckpt.get("metrics"):
        emit(EventType.NODE_START, status=NodeStatus.RUNNING, message="从检查点恢复财务数据")
        extracted = ckpt["extracted"]
        metrics = ckpt["metrics"]
        emit(
            EventType.NODE_END,
            status=NodeStatus.SUCCESS,
            message=f"已恢复：{len(metrics)} 个指标",
            payload={"resumed": True},
        )
        return {
            "extracted": extracted,
            "metrics": metrics,
            "trace": [_trace(node, 0, {"resumed": True})],
        }

    emit(EventType.NODE_START, status=NodeStatus.RUNNING, message="抽取财务字段并计算指标")
    client = build_client(state, emit)

    from .tools.extraction import extract_fields

    def on_delta(delta):
        if delta.reasoning:
            emit(
                EventType.THINKING,
                status=NodeStatus.RUNNING,
                message=delta.reasoning,
                payload={"agent": "extractor"},
            )
        if delta.content:
            emit(
                EventType.TOKEN,
                status=NodeStatus.RUNNING,
                message=delta.content,
                payload={"agent": "extractor"},
            )

    emit(
        EventType.AGENT_START,
        status=NodeStatus.RUNNING,
        message="数据提取员开始工作",
        payload={"agent": "extractor", "name": "数据提取员", "role": "字段抽取与指标计算"},
    )

    emit(
        EventType.TOOL_CALL,
        status=NodeStatus.RUNNING,
        message="tool: extract_fields",
        payload={"agent": "extractor"},
    )

    # 优先用定位出的财务关键页，避免把封面目录送给模型
    focus = state.get("focus_text") or ""
    source_text = focus if focus else state.get("document_text", "")

    extracted = extract_fields(
        source_text,
        client,
        max_chars=40000,
        on_delta=on_delta,
    )
    metrics = compute_metrics(extracted)

    got = sum(1 for v in (extracted.get("fields") or {}).values() if v is not None)

    emit(
        EventType.TOOL_RESULT,
        status=NodeStatus.SUCCESS,
        message=f"抽取 {got} 字段（来源 {len(source_text)} 字）",
        payload={
            "agent": "extractor",
            "tool": "extract_fields",
            "ok": True,
            "result": extracted,
            "source_chars": len(source_text),
            "focus_pages": state.get("focus_pages") or [],
        },
    )

    elapsed = int((time.perf_counter() - t0) * 1000)

    emit(
        EventType.AGENT_END,
        status=NodeStatus.SUCCESS,
        message=f"数据提取员完成（{got} 字段）",
        payload={
            "agent": "extractor",
            "name": "数据提取员",
            "role": "字段抽取与指标计算",
            "opinion": f"已抽取 {got} 个字段，计算 {len(metrics)} 个指标",
            "elapsed_ms": elapsed,
            "steps": 1,
            "tools_used": ["extract_fields"],
        },
    )

    emit(
        EventType.NODE_END,
        status=NodeStatus.SUCCESS,
        message=f"财务数据就绪：{len(metrics)} 个指标",
        payload={"extracted": extracted, "metrics": metrics},
    )

    _save_ckpt(state, {"extracted": extracted, "metrics": metrics})
    _mark_node(state, node)

    return {
        "extracted": extracted,
        "metrics": metrics,
        "trace": [_trace(node, elapsed, {"metrics": list(metrics.keys())})],
    }


def coordinator(state: InvestState) -> dict[str, Any]:
    node = "coordinator"
    run_id = state["run_id"]
    emit = _make_emitter(node, run_id)
    t0 = time.perf_counter()
    emit(EventType.NODE_START, status=NodeStatus.RUNNING, message="投研主管制定分析计划")

    spec = registry.agents["coordinator"]
    plan = COORDINATOR_PLAN + REVIEW_PLAN

    emit(
        EventType.LOG,
        status=NodeStatus.RUNNING,
        message=f"计划：{len(plan)} 位专家参与，分两组执行",
        payload={"plan": plan},
    )

    elapsed = int((time.perf_counter() - t0) * 1000)
    emit(
        EventType.NODE_END,
        status=NodeStatus.SUCCESS,
        message=f"计划就绪：{len(plan)} 位专家",
        payload={"coordinator": spec.name, "plan": plan},
    )

    _mark_node(state, node)

    return {"trace": [_trace(node, elapsed, {"experts": [p["key"] for p in plan]})]}


def _build_task(base: str, state: InvestState, extra: str = "") -> str:
    # 优先用定位出的财务关键页；没有则退回全文
    focus = state.get("focus_text") or ""
    text = focus if focus else state.get("document_text", "")

    extracted = state.get("extracted") or {}
    metrics = state.get("metrics") or {}
    question = state.get("question") or ""
    focus_pages = state.get("focus_pages") or []

    parts = [base]
    if question:
        parts.append(f"研究问题：{question}")
    if extracted:
        parts.append(f"已抽取的财务字段：{extracted.get('fields')}")
    if metrics:
        parts.append(f"已计算的派生指标：{metrics}")
    if extra:
        parts.append(extra)
    if focus_pages:
        parts.append(f"以下为财报关键页（页码 {focus_pages}）：")
    parts.append(f"财报原文：\n{text[:20000]}")
    return "\n\n".join(parts)


def _run_agent(
    spec: AgentSpec,
    task: str,
    state: InvestState,
    node: str,
    event_queue: queue.Queue[dict[str, Any]],
    cached: dict[str, Any] | None = None,
) -> dict[str, Any]:
    run_id = state["run_id"]

    def put(
        type_: EventType,
        *,
        status: NodeStatus | None = None,
        message: str | None = None,
        payload: dict[str, Any] | None = None,
        node_override: str | None = None,
    ) -> None:
        event_queue.put(
            {
                "type": type_.value,
                "run_id": run_id,
                "node": node_override or node,
                "status": status.value if status else None,
                "message": message,
                "payload": payload or {},
            }
        )

    if cached and cached.get("output"):
        put(
            EventType.AGENT_START,
            status=NodeStatus.RUNNING,
            message=f"{spec.name} 从检查点恢复",
            payload={"agent": spec.key, "name": spec.name, "role": spec.role, "resumed": True},
        )
        put(
            EventType.AGENT_END,
            status=NodeStatus.SUCCESS,
            message=f"{spec.name} 已恢复（{len(cached['output'])} 字）",
            payload={**cached, "resumed": True},
        )
        return cached

    put(
        EventType.AGENT_START,
        status=NodeStatus.RUNNING,
        message=f"{spec.name} 开始工作",
        payload={"agent": spec.key, "name": spec.name, "role": spec.role},
    )

    client = build_client(state, put)
    runner = AgentRunner(spec)
    shared: dict[str, Any] = {}

    result = runner.run(task, client, put, node, shared=shared)

    payload = {
        "agent": spec.key,
        "name": spec.name,
        "role": spec.role,
        "opinion": result["output"],
        "steps": result["steps"],
        "tools_used": result["tools_used"],
        "elapsed_ms": result["elapsed_ms"],
        "trace": result["trace"],
        # 技能不是运行时按需加载的，而是在 build_system_prompt 里整体内联进
        # system prompt。所以这里如实上报 spec.skills（真正进了 prompt 的那些），
        # 而不是去追踪 load_skill 调用 —— 6 个智能体的工具白名单里都没有
        # load_skill，追踪它永远只会得到空数组。
        "loaded_skills": list(spec.skills),
        # 触顶截断时如实上报，避免前端把不完整的结论当成正常完成
        "truncated": result.get("truncated", False),
    }

    put(
        EventType.AGENT_END,
        status=NodeStatus.SUCCESS,
        message=f"{spec.name} 完成（{len(result['output'])} 字）",
        payload=payload,
    )

    return {**result, **payload}


def _drain(emit: EmitFn, event_queue: queue.Queue[dict[str, Any]]) -> None:
    while True:
        try:
            raw = event_queue.get_nowait()
        except queue.Empty:
            return
        emit(
            EventType(raw["type"]),
            status=NodeStatus(raw["status"]) if raw["status"] else None,
            message=raw["message"],
            payload=raw["payload"],
            node_override=raw["node"],
        )


def _run_group(
    plan: list[dict[str, str]],
    state: InvestState,
    emit: EmitFn,
    extra: str = "",
) -> list[dict[str, Any]]:
    if not plan:
        return []

    ckpt = _load_ckpt(state)
    saved: dict[str, Any] = ckpt.get("agents") or {}

    event_queue: queue.Queue[dict[str, Any]] = queue.Queue()
    results: list[dict[str, Any]] = []

    with ThreadPoolExecutor(max_workers=len(plan)) as pool:
        futures = {}
        for item in plan:
            spec = registry.agents[item["key"]]
            task = _build_task(item["task"], state, extra)
            cached = saved.get(item["key"])
            futures[
                pool.submit(_run_agent, spec, task, state, item["node"], event_queue, cached)
            ] = item["key"]

        pending = set(futures)
        while pending:
            done, pending = wait(pending, timeout=0.08, return_when=FIRST_COMPLETED)
            _drain(emit, event_queue)
            for fut in done:
                result = fut.result()
                results.append(result)
                saved[result["agent"]] = result
                _save_ckpt(state, {"agents": saved})
        _drain(emit, event_queue)

    order = {item["key"]: i for i, item in enumerate(plan)}
    results.sort(key=lambda r: order.get(r["agent"], 99))
    return results


def analysis_group(state: InvestState) -> dict[str, Any]:
    node = "analysis"
    run_id = state["run_id"]
    emit = _make_emitter(node, run_id)
    t0 = time.perf_counter()
    emit(EventType.NODE_START, status=NodeStatus.RUNNING, message="财务分析师与估值专家并行工作")

    results = _run_group(COORDINATOR_PLAN, state, emit)

    analyses: dict[str, Any] = {r["agent"]: r for r in results}
    elapsed = int((time.perf_counter() - t0) * 1000)

    patch: dict[str, Any] = {
        "analyses": analyses,
        "trace": [_trace(node, elapsed, {"agents": [r["agent"] for r in results]})],
    }

    valuation_artifacts: dict[str, Any] = {}
    for r in results:
        for key, value in (r.get("artifacts") or {}).items():
            if isinstance(value, dict):
                valuation_artifacts[key] = value

    if "build_assumptions" in valuation_artifacts:
        patch["assumptions"] = valuation_artifacts["build_assumptions"]
    if "dcf_valuation" in valuation_artifacts:
        patch["dcf"] = valuation_artifacts["dcf_valuation"]
    if "relative_valuation" in valuation_artifacts:
        patch["relative"] = valuation_artifacts["relative_valuation"]
    if "sensitivity_grid" in valuation_artifacts:
        patch["sensitivity"] = valuation_artifacts["sensitivity_grid"]

    has_summary = "summarize_valuation" in valuation_artifacts
    has_dcf = "dcf_valuation" in valuation_artifacts
    has_relative = "relative_valuation" in valuation_artifacts

    if has_summary:
        patch["valuation_summary"] = valuation_artifacts["summarize_valuation"]
    elif has_dcf:
        from .tools.valuation import relative_valuation, summarize_valuation

        if not has_relative:
            fields = (state.get("extracted") or {}).get("fields") or {}
            revenue = fields.get("revenue")
            net_profit = fields.get("net_profit")
            patch["relative"] = relative_valuation(
                float(net_profit) if isinstance(net_profit, (int, float)) else None,
                float(revenue) if isinstance(revenue, (int, float)) else None,
            )
            has_relative = True

        patch["valuation_summary"] = summarize_valuation(
            valuation_artifacts["dcf_valuation"],
            patch.get("relative") or {},
        )

    for r in results:
        extracted = (r.get("artifacts") or {}).get("extract_fields")
        if isinstance(extracted, dict) and extracted.get("fields"):
            patch["extracted"] = extracted
            patch["metrics"] = compute_metrics(extracted)
            break

    emit(
        EventType.NODE_END,
        status=NodeStatus.SUCCESS,
        message=f"分析组完成：{len(results)} 位专家",
        payload={
            "analyses": {k: v.get("output", "") for k, v in analyses.items()},
            "valuation_summary": patch.get("valuation_summary", {}),
        },
    )

    _save_ckpt(
        state,
        {
            "assumptions": patch.get("assumptions"),
            "dcf": patch.get("dcf"),
            "relative": patch.get("relative"),
            "sensitivity": patch.get("sensitivity"),
            "valuation_summary": patch.get("valuation_summary"),
            "extracted": patch.get("extracted"),
            "metrics": patch.get("metrics"),
        },
    )
    _mark_node(state, node)

    return patch


def review_group(state: InvestState) -> dict[str, Any]:
    node = "review"
    run_id = state["run_id"]
    emit = _make_emitter(node, run_id)
    t0 = time.perf_counter()
    emit(EventType.NODE_START, status=NodeStatus.RUNNING, message="风险审查员与反方质疑者并行评估")

    analyses = state.get("analyses") or {}
    prior = "\n\n".join(
        f"【{v.get('name')}】\n{(v.get('output') or '')[:2000]}" for v in analyses.values()
    )
    extra = f"前置分析结论：\n{prior}" if prior else ""

    results = _run_group(REVIEW_PLAN, state, emit, extra=extra)
    elapsed = int((time.perf_counter() - t0) * 1000)

    emit(
        EventType.NODE_END,
        status=NodeStatus.SUCCESS,
        message=f"评审组完成：{len(results)} 位专家",
        payload={"opinions": [r["agent"] for r in results]},
    )

    _mark_node(state, node)

    return {
        "expert_opinions": results,
        "trace": [_trace(node, elapsed, {"agents": [r["agent"] for r in results]})],
    }


def _strip_md_fence(md: str) -> str:
    """去掉模型输出的 ```markdown / ``` 围栏，便于前端直接渲染。"""
    text = (md or "").strip()
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    # 丢掉首行围栏
    body = lines[1:]
    # 丢掉末尾围栏
    while body and body[-1].strip() in ("```", ""):
        if body[-1].strip() == "```":
            body = body[:-1]
        else:
            body = body[:-1]
    return "\n".join(body).strip()


def report(state: InvestState) -> dict[str, Any]:
    node = "report"
    run_id = state["run_id"]
    emit = _make_emitter(node, run_id)
    t0 = time.perf_counter()

    ckpt = _load_ckpt(state)
    if ckpt.get("report_md"):
        emit(EventType.NODE_START, status=NodeStatus.RUNNING, message="从检查点恢复报告")
        md = _strip_md_fence(ckpt["report_md"])
        emit(
            EventType.TOOL_RESULT,
            status=NodeStatus.SUCCESS,
            message=f"报告 {len(md)} 字",
            payload={"report_md": md, "resumed": True},
        )
        emit(EventType.NODE_END, status=NodeStatus.SUCCESS, message=f"已恢复报告（{len(md)} 字）")
        return {"report_md": md, "trace": [_trace(node, 0, {"resumed": True})]}

    emit(EventType.NODE_START, status=NodeStatus.RUNNING, message="报告撰写人整合输出")

    spec = registry.agents["report_writer"]
    analyses = state.get("analyses") or {}
    opinions = state.get("expert_opinions") or []
    question = state.get("question") or "请分析该公司本期经营与财务表现。"

    blocks: list[str] = []
    for r in list(analyses.values()) + opinions:
        output = (r.get("output") or "").strip()
        if not output:
            continue
        name = r.get("name") or r.get("agent") or "专家"
        role = r.get("role") or ""
        blocks.append(f"【{name}（{role}）】\n{output[:1200]}")

    if not blocks:
        raise RuntimeError("没有可用的专家意见，无法生成报告")

    task = (
        f"研究问题：{question}\n\n"
        f"原始财报节选：\n{state.get('document_text', '')[:1200]}\n\n"
        f"专家意见：\n" + "\n\n".join(blocks)
    )

    emit(
        EventType.AGENT_START,
        status=NodeStatus.RUNNING,
        message=f"{spec.name} 开始撰写",
        payload={"agent": spec.key, "name": spec.name, "role": spec.role},
    )

    runner = AgentRunner(spec)
    client = build_client(state, emit)
    shared: dict[str, Any] = {}

    result = runner.run(task, client, emit, node, shared=shared)
    md = _strip_md_fence(result["output"])

    if not md.strip():
        emit(
            EventType.AGENT_END,
            status=NodeStatus.FAILED,
            message="报告撰写人未能生成正文",
            payload={
                "agent": spec.key,
                "name": spec.name,
                "role": spec.role,
                "opinion": "",
                "elapsed_ms": 0,
            },
        )
        raise RuntimeError("报告撰写人未能生成正文")

    elapsed = int((time.perf_counter() - t0) * 1000)

    emit(
        EventType.AGENT_END,
        status=NodeStatus.SUCCESS,
        message=f"{spec.name} 完成（{len(md)} 字）",
        payload={
            "agent": spec.key,
            "name": spec.name,
            "role": spec.role,
            "opinion": md,
            "steps": result.get("steps", 0),
            "tools_used": result.get("tools_used", []),
            "elapsed_ms": elapsed,
            # 同 _run_agent：技能是内联进 prompt 的，如实上报白名单
            "loaded_skills": list(spec.skills),
        },
    )

    emit(
        EventType.TOOL_RESULT,
        status=NodeStatus.SUCCESS,
        message=f"报告 {len(md)} 字",
        payload={"report_md": md},
    )
    emit(EventType.NODE_END, status=NodeStatus.SUCCESS, message=f"报告生成完成（{len(md)} 字）")

    _save_ckpt(state, {"report_md": md})
    _mark_node(state, node)
    checkpoint.mark_finished(run_id)

    return {
        "report_md": md,
        # 技能是内联进 system prompt 的，trace 里同样如实记 spec.skills，
        # 而不是去读那个永远为空的 shared["loaded_skills"]
        "trace": [_trace(node, elapsed, {"chars": len(md), "skills": list(spec.skills)})],
    }


NODES = [
    ("ingest", ingest),
    ("extract", extract),
    ("coordinator", coordinator),
    ("analysis", analysis_group),
    ("review", review_group),
    ("report", report),
]


def build_graph():
    from langgraph.graph import END, START, StateGraph

    g = StateGraph(InvestState)
    for name, fn in NODES:
        g.add_node(name, fn)

    g.add_edge(START, NODES[0][0])
    for i in range(len(NODES) - 1):
        g.add_edge(NODES[i][0], NODES[i + 1][0])
    g.add_edge(NODES[-1][0], END)
    return g.compile()


graph = build_graph()
