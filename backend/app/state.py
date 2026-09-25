"""LangGraph 全局状态。

所有节点读写同一个 TypedDict。列表型字段用 operator.add 归约，
使并行的专家节点可以各自追加而不互相覆盖。
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


class InvestState(TypedDict, total=False):
    run_id: str
    filename: str
    raw_bytes: bytes
    question: str

    provider: str
    model: str
    fallback_models: list[str]
    api_key: str
    base_url: str

    document_text: str
    chunks: list[str]
    focus_text: str
    focus_pages: list[int]
    extracted: dict[str, Any]
    metrics: dict[str, Any]

    assumptions: dict[str, Any]
    dcf: dict[str, Any]
    relative: dict[str, Any]
    sensitivity: dict[str, Any]
    valuation_summary: dict[str, Any]

    analyses: dict[str, Any]
    expert_opinions: list[dict[str, Any]]
    report_md: str
    citations: list[dict[str, Any]]

    trace: Annotated[list[dict[str, Any]], operator.add]
    errors: Annotated[list[str], operator.add]
