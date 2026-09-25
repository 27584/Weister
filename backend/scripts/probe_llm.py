"""本地 / 云端模型连通性探测。

用法：
    python scripts/probe_llm.py --base http://127.0.0.1:11434/v1 --model qwen2.5:7b
    python scripts/probe_llm.py --profile AIO
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx


def load_profile(name: str) -> dict:
    path = Path(__file__).resolve().parents[1] / "data" / "profiles.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    for p in data.get("profiles") or []:
        if p.get("id") == name or p.get("name") == name:
            return p
    raise SystemExit(f"未找到配置档案：{name}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="")
    ap.add_argument("--model", default="")
    ap.add_argument("--key", default="")
    ap.add_argument("--profile", default="")
    args = ap.parse_args()

    base = args.base
    model = args.model
    key = args.key
    if args.profile:
        prof = load_profile(args.profile)
        base = base or (prof.get("baseUrl") or "")
        model = model or (prof.get("model") or "")
        key = key or (prof.get("apiKey") or "")

    if not base or not model:
        raise SystemExit("需要 --base 与 --model，或 --profile")

    base = base.rstrip("/")
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"

    print(f"base={base}\nmodel={model}")
    with httpx.Client(timeout=30.0) as c:
        try:
            r = c.get(f"{base}/models", headers=headers)
            print("GET /models", r.status_code)
            if r.status_code == 200:
                ids = [m.get("id") for m in (r.json().get("data") or [])][:15]
                print("models:", ids)
        except Exception as e:
            print("GET /models ERR", type(e).__name__, e)

        r = c.post(
            f"{base}/chat/completions",
            headers=headers,
            json={
                "model": model,
                "messages": [{"role": "user", "content": "只回复两个字：可用"}],
                "temperature": 0.2,
                "stream": False,
            },
        )
        print("POST chat", r.status_code)
        try:
            msg = r.json()["choices"][0]["message"]
            print("content:", (msg.get("content") or "")[:120])
            print("keys:", list(msg.keys()))
        except Exception:
            print(r.text[:300])
            raise SystemExit(1)
    print("PROBE OK")


if __name__ == "__main__":
    main()
