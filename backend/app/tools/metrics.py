"""派生指标计算。

纯确定性计算，不涉及模型判断。
"""

from __future__ import annotations

from typing import Any

from ..core.registry import Tool, registry


def compute_metrics(extracted: dict[str, Any]) -> dict[str, Any]:
    f = extracted.get("fields") or {}

    def n(key: str) -> float | None:
        v = f.get(key)
        return float(v) if isinstance(v, (int, float)) else None

    revenue = n("revenue")
    net_profit = n("net_profit")
    ocf = n("operating_cash_flow")
    assets = n("total_assets")
    liab = n("total_liabilities")

    metrics: dict[str, Any] = {}
    if revenue and net_profit is not None:
        metrics["net_margin"] = round(net_profit / revenue, 4)
    if revenue and ocf is not None:
        metrics["ocf_to_revenue"] = round(ocf / revenue, 4)
    if assets and liab is not None:
        metrics["debt_ratio"] = round(liab / assets, 4)
    if net_profit is not None and ocf is not None:
        metrics["profit_cash_gap"] = round(ocf - net_profit, 2)
        metrics["profit_cash_divergence"] = bool(
            net_profit > 0
            and ocf < 0
            or (net_profit and abs((ocf - net_profit) / net_profit) > 0.5)
        )
    return metrics


registry.add_tool(
    Tool(
        name="compute_metrics",
        description="从抽取字段计算派生指标：净利率、现金流质量、资产负债率、利润现金流背离",
        input_schema={"extracted": "dict"},
        handler=compute_metrics,
        tags=["metrics", "deterministic"],
    )
)
