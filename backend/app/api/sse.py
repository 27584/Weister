"""SSE 帧编码。"""

from __future__ import annotations

import json


def sse(event: dict) -> str:
    return f"event: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"


__all__ = ["sse"]
