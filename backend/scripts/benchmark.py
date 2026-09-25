"""固定样例端到端基准：统计多轮运行的稳定性。

不调用真实 LLM 时（--mock），验证管线与落盘；
指定 --profile 时会真实调用模型，用于竞赛「稳定性」数据表。

用法：
    python scripts/benchmark.py --mock --runs 3
    python scripts/benchmark.py --profile AIO --runs 5 --message "用一句话介绍贵州茅台"
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))

from _harness import isolate_data_dir

from app.api import chat as chat_mod
from app.api.chat import ChatRequest, _chat_stream
from app.api.deps import Credentials
from app.events import EventType


def fake_run_chat(state, documents, emit):
    emit(EventType.LOG, message="mock supervisor")
    return {
        "reply": "基准测试固定回复",
        "messages": list(state.get("messages") or [])
        + [{"role": "assistant", "content": "基准测试固定回复"}],
        "iterations": 1,
        "truncated": False,
        "specialists_called": ["financial_analyst"],
    }


async def one_run(message: str, cred: Credentials, run_id: str) -> dict:
    types: list[str] = []
    t0 = time.monotonic()
    async for chunk in _chat_stream(
        ChatRequest(run_id=run_id, message=message, attachments=[]), {}, cred
    ):
        if "data: " not in chunk:
            continue
        try:
            ev = json.loads(chunk.split("data: ", 1)[1].strip())
        except json.JSONDecodeError:
            continue
        types.append(str(ev.get("type")))
    elapsed = time.monotonic() - t0
    return {
        "run_id": run_id,
        "elapsed_s": round(elapsed, 2),
        "has_result": "result" in types,
        "has_run_end": "run_end" in types,
        "has_error": "error" in types,
        "event_count": len(types),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--message", default="用一句话介绍你自己")
    ap.add_argument("--mock", action="store_true")
    ap.add_argument("--profile", default="")
    ap.add_argument("--model", default="")
    ap.add_argument("--base", default="")
    ap.add_argument("--key", default="")
    args = ap.parse_args()

    isolate_data_dir()

    if args.mock:
        chat_mod.run_chat = fake_run_chat
        cred = Credentials(provider="deepseek", model="mock", api_key="x")
        label = "mock"
    else:
        if args.profile:
            path = Path(__file__).resolve().parents[1] / "data" / "profiles.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            prof = next(
                p
                for p in data.get("profiles") or []
                if p.get("id") == args.profile or p.get("name") == args.profile
            )
            cred = Credentials(
                provider=prof.get("provider") or "custom",
                model=args.model or prof.get("model") or "",
                api_key=prof.get("apiKey") or args.key,
                base_url=args.base or prof.get("baseUrl") or "",
            )
        else:
            cred = Credentials(
                provider="custom",
                model=args.model,
                api_key=args.key or "ollama",
                base_url=args.base or "http://127.0.0.1:11434/v1",
            )
        label = cred.model

    results = []
    for i in range(args.runs):
        rid = f"bench{i:02d}{int(time.time()) % 10000}"
        print(f"run {i + 1}/{args.runs} …", flush=True)
        results.append(asyncio.run(one_run(args.message, cred, rid)))

    ok = sum(1 for r in results if r["has_result"] and r["has_run_end"] and not r["has_error"])
    times = [r["elapsed_s"] for r in results]
    summary = {
        "label": label,
        "runs": args.runs,
        "success": ok,
        "success_rate": round(ok / max(args.runs, 1), 3),
        "elapsed_min": min(times) if times else None,
        "elapsed_max": max(times) if times else None,
        "elapsed_avg": round(sum(times) / len(times), 2) if times else None,
        "detail": results,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    out = Path(__file__).resolve().parents[1] / "data" / "benchmarks"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"bench_{label}_{int(time.time())}.json"
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("saved", path)


if __name__ == "__main__":
    main()
