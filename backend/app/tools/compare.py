"""多标的横向对比：把多家公司的核心指标排成可对比表。"""

from __future__ import annotations

from typing import Any

from ..core.registry import Tool, registry

_COMPARE_KEYS = [
    "revenue",
    "net_profit",
    "operating_cash_flow",
    "total_assets",
    "total_liabilities",
    "gross_margin",
    "net_margin",
    "roe",
    "debt_ratio",
    "ocf_to_net_profit",
]


def _pick(d: dict[str, Any], key: str) -> Any:
    if key in d and d[key] is not None:
        return d[key]
    fields = d.get("fields")
    if isinstance(fields, dict) and key in fields:
        return fields[key]
    metrics = d.get("metrics")
    if isinstance(metrics, dict) and key in metrics:
        return metrics[key]
    return None


def peer_comparison(
    companies: list[dict[str, Any]],
    keys: list[str] | None = None,
) -> dict[str, Any]:
    """companies: [{"name":"贵州茅台","fields":{...},"metrics":{...}}, ...]

    输出 markdown 表与 JSON 行，便于专家直接写进报告。
    """
    if not companies or len(companies) < 2:
        raise ValueError("至少需要 2 家公司的数据才能对比")
    use_keys = [k for k in (keys or _COMPARE_KEYS) if k]
    rows: list[dict[str, Any]] = []
    for c in companies[:8]:
        name = str(c.get("name") or c.get("company") or "未命名")
        row: dict[str, Any] = {"name": name}
        for k in use_keys:
            row[k] = _pick(c, k)
        rows.append(row)

    # Markdown 表
    header = "| 公司 | " + " | ".join(use_keys) + " |"
    sep = "| --- | " + " | ".join(["---"] * len(use_keys)) + " |"
    lines = [header, sep]
    for r in rows:
        cells = []
        for k in use_keys:
            v = r.get(k)
            if isinstance(v, float):
                cells.append(f"{v:.4g}" if abs(v) < 1 else f"{v:,.2f}")
            else:
                cells.append("" if v is None else str(v))
        lines.append(f"| {r['name']} | " + " | ".join(cells) + " |")
    return {"keys": use_keys, "rows": rows, "markdown_table": "\n".join(lines)}


registry.add_tool(
    Tool(
        name="peer_comparison",
        description=(
            "把 2~8 家公司的核心财务指标排成对比表（JSON + Markdown）。"
            "每项可为 fields 或 metrics 中的键；缺失显示为空，禁止编造。"
        ),
        input_schema={
            "companies": "list，每项 {'name':str,'fields':dict,'metrics':dict 可选}",
            "keys": "list 可选，自定义对比字段",
        },
        handler=peer_comparison,
        tags=["compare", "peer", "deterministic"],
    )
)
