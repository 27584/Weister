"""聊天形态（supervisor loop）SSE 流与路由。"""

from __future__ import annotations

import asyncio
import json
import queue
import shutil
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .. import interaction, runctx
from ..chat_supervisor import (
    _build_supervisor_messages,
    _summarize_documents,
    deserialize_messages,
    history_token_budget,
    run_chat,
)
from ..config import settings
from ..core.registry import registry
from ..events import EventType, NodeStatus
from ..llm import LLMError
from ..providers import resolve
from ..tokens import (
    OUTPUT_RESERVE_TOKENS,
    context_limit_for_model,
    count_messages_tokens,
)
from ..tools.parsing import detect_image_mime
from .deps import Credentials, bind_search_config, credentials
from .helpers import (
    build_attachments,
    build_user_message,
    skill_command_context,
    split_skill_command,
)
from .sse import sse
from .store import (
    conversation_title,
    load_chat_documents,
    load_chat_events,
    load_chat_history,
    load_chat_title,
    save_chat_documents,
    save_chat_events,
    save_chat_history,
)

router = APIRouter()


class ChatRequest(BaseModel):
    run_id: str = ""
    message: str = ""
    attachments: list[dict[str, Any]] = []


async def _chat_stream(
    req: ChatRequest,
    raw_files: dict[str, bytes],
    cred: Credentials,
) -> AsyncIterator[str]:
    run_id = req.run_id or uuid.uuid4().hex[:12]

    seq = 0
    collected: list[dict[str, Any]] = []  # 收集事件，跑完落盘供刷新后重建协作面板
    last_flush = time.monotonic()

    def wrap(event: dict) -> str:
        nonlocal seq, last_flush
        seq += 1
        last_flush = time.monotonic()
        event["seq"] = seq
        event.setdefault("run_id", run_id)
        collected.append(dict(event))
        return sse(event)

    try:
        pkey, pbase, pmodel = resolve(cred.provider, cred.model, cred.base_url or None)
        if not (cred.api_key or settings.llm_api_key):
            raise LLMError(
                "未提供 API Key：请通过 X-LLM-Api-Key 请求头传递，"
                "或在 backend/.env 中配置 LLM_API_KEY"
            )
    except Exception as exc:
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
        return

    # ---------- 事件流：线程池 + 队列，逐条实时推送 ----------
    #
    # run_chat 与附件解析（PyMuPDF 等）都是同步重活，多轮 LLM 调用可能跑几分钟。
    # 不能直接在协程里调用：
    #   1. 同步调用会阻塞整个 FastAPI 事件循环 —— 连 /api/health 都无响应
    #   2. 「先收集、跑完再统一 yield」的写法让前端在整轮结束前收不到任何事件，
    #      表现就是上传文件后永远停在「思考中」
    #
    # 正确姿势：worker 丢进线程池（asyncio.to_thread），emit 把事件压进线程安全的
    # queue.Queue，主协程轮询队列并逐条 yield SSE —— 前端能实时看到
    # supervisor 思考、专家调度、工具调用全过程。
    event_q: queue.Queue[dict[str, Any]] = queue.Queue()

    def emit(type_, *, status=None, message=None, payload=None, node_override=None):
        event_q.put(
            {
                "type": type_,
                "status": status,
                "message": message,
                "payload": payload or {},
                "node": node_override,
            }
        )

    def worker() -> dict[str, Any] | None:
        """重活全在这里跑：附件解析 + 历史加载 + supervisor loop。"""
        # 绑定运行上下文：交互类工具（ask_user / set_conversation_title）
        # 需要 run_id 与事件出口，而工具 handler 签名由模型参数决定，拿不到这两个值。
        runctx.bind(run_id, emit)
        try:
            new_docs = build_attachments(req.attachments, raw_files)
            # 累积本对话已上传的文档：追问时 agent 仍能读到完整正文
            prev_docs = load_chat_documents(run_id)
            documents = prev_docs + new_docs
            if new_docs:
                save_chat_documents(run_id, documents)

            history = load_chat_history(run_id)

            # 解析开头的 `/技能名` 命令：给模型看的 content 里把命令替换成
            # 一段「显式指定技能」的强提示；display_text 保留用户原文，
            # 否则用户只发 `/技能名` 时落盘为空串，前端渲染出空气泡，
            # 即聊天记录中丢失该条指令。
            skill_name, clean_text = split_skill_command(
                req.message,
                set(registry.skills.keys()),
            )
            # 只有技能命令、没有正文时，指令里要明确列出可行动作，
            # 否则主管会把命令当成一句通知，只回复「已收到技能指令」
            extra = (
                skill_command_context(skill_name, has_body=bool(clean_text)) if skill_name else ""
            )

            # 用户消息只引用「本次新上传」的附件（老附件在更早的消息里）
            user_msg = build_user_message(
                clean_text,
                req.attachments,
                new_docs,
                extra,
            )
            user_msg["display_text"] = (req.message or "").strip() or clean_text
            all_messages = history + [user_msg]

            emit(
                EventType.RUN_START,
                status=NodeStatus.RUNNING,
                message="开始聊天分析",
                payload={
                    "provider": pkey,
                    "model": pmodel,
                    "base_url": pbase,
                    "documents": [
                        {
                            "filename": d["filename"],
                            "kind": d["kind"],
                            "readable": d.get("readable", False),
                            "pages": (d.get("diagnostics") or {}).get("page_count"),
                            "chars": (d.get("diagnostics") or {}).get("chars", 0),
                        }
                        for d in new_docs
                    ],
                },
            )

            chat_state = {
                "run_id": run_id,
                "messages": all_messages,
                "provider": pkey,
                "model": pmodel,
                "fallback_models": cred.fallback_models,
                "base_url": pbase,
                "api_key": cred.api_key,
            }
            return run_chat(chat_state, documents, emit)
        except Exception as exc:
            emit(EventType.ERROR, status=NodeStatus.FAILED, message=str(exc))
            return None

    task = asyncio.create_task(asyncio.to_thread(worker))

    # 主循环：排空队列 → 没事件就小睡，直到 worker 结束
    try:
        while True:
            drained = False
            while not drained:
                try:
                    yield wrap(event_q.get_nowait())
                except queue.Empty:
                    drained = True
            if task.done():
                # worker 已结束，最后再捞一次队列（结束事件与完成之间可能有残留）
                try:
                    yield wrap(event_q.get_nowait())
                except queue.Empty:
                    pass
                break
            await asyncio.sleep(0.05)

            # 等待用户作答（或模型长考）时可能几十秒没有事件。
            # 发一个 SSE 注释保持连接活跃，避免中间层按空闲超时断开。
            if time.monotonic() - last_flush > 15:
                last_flush = time.monotonic()
                yield ": keep-alive\n\n"
    finally:
        # 客户端断开（刷新 / 关闭页面）时唤醒等待中的提问，
        # 否则 worker 线程会一直挂起到超时
        interaction.cancel_run(run_id)

    result = await task

    if result is None:
        # 失败也要把已产生的事件（含红色 run_end）落盘，
        # 否则刷新后这段过程会丢失，且面板会一直停在「进行中」
        run_end_event = {
            "type": EventType.RUN_END.value,
            "run_id": run_id,
            "node": None,
            "status": NodeStatus.FAILED.value,
            "message": "aborted",
            "payload": {},
        }
        run_end_sse = wrap(run_end_event)  # wrap 会把它也加入 collected
        save_chat_events(run_id, collected)
        yield run_end_sse
        return

    final_messages = result["messages"]
    save_chat_history(run_id, final_messages)

    result_event = {
        "type": EventType.RESULT.value,
        "run_id": run_id,
        "node": None,
        "status": NodeStatus.SUCCESS.value,
        "message": "完成",
        "payload": {
            "reply": result["reply"],
            "iterations": result["iterations"],
            "truncated": result["truncated"],
            "specialists_called": result["specialists_called"],
            "messages": final_messages,
        },
    }
    run_end_event = {
        "type": EventType.RUN_END.value,
        "run_id": run_id,
        "node": None,
        "status": NodeStatus.SUCCESS.value,
        "message": "done",
        "payload": {},
    }
    # 先 wrap（顺带进 collected），再落盘 —— 这样 events.jsonl 里有完整的
    # result + run_end，重放时 agent 相位才能正确落到「已完成」而不是卡在「进行中」
    result_sse = wrap(result_event)
    run_end_sse = wrap(run_end_event)

    # 落盘版去掉 result 里的完整 messages（messages.jsonl 已经存了，避免事件文件翻倍）
    for ev in collected:
        if ev.get("type") == EventType.RESULT.value and isinstance(ev.get("payload"), dict):
            ev["payload"] = {k: v for k, v in ev["payload"].items() if k != "messages"}

    save_chat_events(run_id, collected)

    yield result_sse
    yield run_end_sse


@router.post("/api/chat")
async def chat(
    message: str = Form(""),
    run_id: str = Form(""),
    attachments: str = Form("[]"),
    files: list[UploadFile] = File(default=[]),
    cred: Credentials = Depends(credentials),
) -> StreamingResponse:
    """聊天形态入口。multipart：message + run_id + attachments(JSON) + files。

    attachments 是 JSON 字符串，描述每个 file 的元信息（id, name, mime）。
    files 是真实的二进制（顺序与 attachments 一一对应）。
    """
    try:
        attachments_meta = json.loads(attachments) if attachments else []
        if not isinstance(attachments_meta, list):
            attachments_meta = []
    except json.JSONDecodeError:
        attachments_meta = []

    raw_files: dict[str, bytes] = {}
    cleaned_meta: list[dict[str, Any]] = []
    for idx, meta in enumerate(attachments_meta):
        if idx >= len(files):
            break
        raw = await files[idx].read()
        file_id = meta.get("id") or f"file-{idx}"
        guessed = detect_image_mime(meta.get("name", ""), raw)
        if not meta.get("mime") or meta["mime"] == "application/octet-stream":
            meta["mime"] = guessed
        raw_files[file_id] = raw
        cleaned_meta.append({**meta, "id": file_id})

    req = ChatRequest(
        run_id=run_id,
        message=message,
        attachments=cleaned_meta,
    )

    bind_search_config(cred)
    return StreamingResponse(
        _chat_stream(req, raw_files, cred),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


class ChatEstimateRequest(BaseModel):
    run_id: str = ""
    message: str = ""
    attachments: list[dict[str, Any]] = []
    model: str = ""


@router.post("/api/chat/estimate")
async def estimate_chat_tokens(
    req: ChatEstimateRequest,
    cred: Credentials = Depends(credentials),
) -> dict:
    """估算「主链路（supervisor）下一轮请求」的上下文占用。

    口径对齐主流 harness（Claude Code / Cline / Roo Code）：
        1. 只统计主链路真正发出的内容：系统提示词 + 文档摘要 + 历史 + 本轮输入（含图片）。
        2. 子智能体（specialist）是独立调用、独立上下文窗口，其 token **不计入**主上下文
           ——同 Claude Code：sidechain / Task 子 agent 不占主上下文。
        3. 预留输出空间：分子加 OUTPUT_RESERVE_TOKENS（对齐 Claude Code 的
           autocompact buffer / Cline 的输出预留），否则「已用 100%」时模型其实
           已经没有地方写回答了。
    """
    model = req.model or cred.model or ""

    history = load_chat_history(req.run_id) if req.run_id else []
    documents = load_chat_documents(req.run_id) if req.run_id else []

    # 本轮待发送附件：按 build_user_message 的真实形态构造（标签 / 图片）
    pending_docs: list[dict[str, Any]] = []
    for att in req.attachments or []:
        mime = att.get("mime") or ""
        text = att.get("text") if isinstance(att.get("text"), str) else ""
        pending_docs.append(
            {
                "filename": att.get("name") or "附件",
                "mime": mime,
                "kind": "image" if mime.startswith("image/") else "text",
                "image_b64": "",  # 尚未上传，按默认尺寸估算视觉 token
                "readable": bool(text) or not mime.startswith("application/"),
                "diagnostics": {"chars": len(text), "page_count": None},
            }
        )

    user_msg = build_user_message(req.message or "", [], pending_docs)
    # 预算函数接的是 InvestState 形态，这里只需要它读 model
    supervisor_state = {"model": model}
    supervisor_messages = _build_supervisor_messages(
        history + [user_msg],
        _summarize_documents(documents),
        called=None,
        # 估算要用真实的模型窗口，否则 1M 窗口的模型也会被默认预算低估
        max_history_tokens=history_token_budget(supervisor_state),
        model=model,
    )

    system_tokens = count_messages_tokens(
        [m for m in supervisor_messages if m.get("role") == "system"], model
    )
    conversation_tokens = count_messages_tokens(
        [m for m in supervisor_messages if m.get("role") != "system"], model
    )

    limit = context_limit_for_model(model)
    return {
        "tokens": system_tokens + conversation_tokens,
        "reserve": OUTPUT_RESERVE_TOKENS,
        "limit": limit,
        "model": model,
        "breakdown": {
            "system": system_tokens,
            "conversation": conversation_tokens,
        },
    }


class ChatAnswerPayload(BaseModel):
    qid: str = ""
    answers: list[dict[str, Any]] = []
    note: str = ""


@router.post("/api/chat/answer")
async def answer_question(payload: ChatAnswerPayload) -> dict:
    """把用户对 ask_user 的作答交回正在等待的工具。

    工具调用是同步阻塞的：worker 线程停在 interaction 模块的事件上，
    这里写入答案并唤醒它，ReAct 循环随即继续。
    """
    if not payload.qid:
        raise HTTPException(status_code=400, detail="缺少 qid")
    delivered = interaction.answer(
        payload.qid,
        {"answers": payload.answers, "note": payload.note},
    )
    if not delivered:
        raise HTTPException(status_code=404, detail="该提问已失效或超时")
    return {"ok": True, "qid": payload.qid}


@router.get("/api/chat/{run_id}")
async def get_chat_history(run_id: str) -> dict:
    """读取对话历史（用于刷新后可继续）。"""
    messages = load_chat_history(run_id)
    return {"run_id": run_id, "messages": messages, "title": load_chat_title(run_id)}


@router.get("/api/conversations/{run_id}/events")
async def get_conversation_events(run_id: str) -> dict:
    """读取某次对话的完整事件流（刷新/切换后重建协作面板）。"""
    events = load_chat_events(run_id)
    return {"run_id": run_id, "events": events}


@router.get("/api/conversations")
async def list_conversations() -> dict:
    """列出所有聊天形态对话（按最近更新时间倒序）。"""
    items: list[dict[str, Any]] = []
    runs_path = settings.runs_dir_path
    if runs_path.exists():
        for run_dir in runs_path.iterdir():
            msg_path = run_dir / "messages.jsonl"
            if not msg_path.exists():
                continue
            try:
                messages = deserialize_messages(msg_path.read_text(encoding="utf-8"))
                updated_at = int(msg_path.stat().st_mtime * 1000)
                items.append(
                    {
                        "run_id": run_dir.name,
                        "title": conversation_title(messages, run_dir.name),
                        "updated_at": updated_at,
                        "message_count": len(messages),
                    }
                )
            except Exception:
                continue
    items.sort(key=lambda x: x["updated_at"], reverse=True)
    return {"conversations": items}


@router.delete("/api/conversations/{run_id}")
async def delete_conversation(run_id: str) -> dict:
    """删除指定对话及其历史。"""
    run_dir = settings.runs_dir_path / run_id
    if run_dir.exists():
        shutil.rmtree(run_dir)
    return {"ok": True, "run_id": run_id}


__all__ = ["ChatRequest", "_chat_stream", "router"]
