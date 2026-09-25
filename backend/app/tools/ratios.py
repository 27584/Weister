"""财务比率套件。

在 compute_metrics（净利率/负债率等基础指标）之上，给出更完整的
偿债、盈利、营运与现金流质量比率，全部为确定性计算。
"""

from __future__ import annotations

from typing import Any

from ..core.registry import Tool, registry


def _n(fields: dict[str, Any], *keys: str) -> float | None:
    for k in keys:
        v = fields.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return float(v)
    return None


def _ratio(num: float | None, den: float | None, *, scale: float = 1.0) -> float | None:
    if num is None or den is None or den == 0:
        return None
    return round(num / den * scale, 4)


def financial_ratio_suite(extracted: dict[str, Any]) -> dict[str, Any]:
    """输入 extract_fields 的结果或 {"fields": {...}}，输出分组比率。

    缺失字段不会臆造，对应比率返回 null。
    """
    fields = extracted.get("fields") if isinstance(extracted.get("fields"), dict) else extracted
    fields = fields or {}

    revenue = _n(fields, "revenue", "operating_revenue")
    net_profit = _n(fields, "net_profit", "net_income")
    operating_profit = _n(fields, "operating_profit")
    gross_profit = _n(fields, "gross_profit")
    ocf = _n(fields, "operating_cash_flow")
    capex = _n(fields, "capex", "capital_expenditure")
    current_assets = _n(fields, "current_assets")
    current_liab = _n(fields, "current_liabilities")
    inventory = _n(fields, "inventory")
    receivables = _n(fields, "accounts_receivable")
    cash = _n(fields, "cash_and_equivalents")
    total_assets = _n(fields, "total_assets")
    total_liab = _n(fields, "total_liabilities")
    equity = _n(fields, "shareholders_equity", "total_equity")
    interest_expense = _n(fields, "interest_expense")
    ebit = operating_profit

    fcf = None
    if ocf is not None:
        fcf = round(ocf - (capex or 0.0), 2)

    out: dict[str, Any] = {
        "profitability": {
            "gross_margin": _ratio(gross_profit, revenue),
            "operating_margin": _ratio(operating_profit, revenue),
            "net_margin": _ratio(net_profit, revenue),
            "roe": _ratio(net_profit, equity),
            "roa": _ratio(net_profit, total_assets),
        },
        "liquidity": {
            "current_ratio": _ratio(current_assets, current_liab),
            "quick_ratio": (
                _ratio((current_assets - (inventory or 0.0)), current_liab)
                if current_assets is not None and current_liab is not None
                else None
            ),
            "cash_ratio": _ratio(cash, current_liab),
        },
        "solvency": {
            "debt_ratio": _ratio(total_liab, total_assets),
            "debt_to_equity": _ratio(total_liab, equity),
            "interest_coverage": _ratio(ebit, interest_expense),
        },
        "efficiency": {
            "asset_turnover": _ratio(revenue, total_assets),
            "receivable_turnover": _ratio(revenue, receivables),
            "inventory_turnover": _ratio(
                (revenue - (gross_profit or 0.0)) if revenue is not None else None,
                inventory,
            ),
        },
        "cash_quality": {
            "ocf_to_net_profit": _ratio(ocf, net_profit),
            "ocf_to_revenue": _ratio(ocf, revenue),
            "fcf": fcf,
            "fcf_margin": _ratio(fcf, revenue),
        },
    }
    # 可算出的比率数量，便于模型判断数据是否足够
    total = 0
    filled = 0
    for group in out.values():
        for v in group.values():
            total += 1
            if v is not None:
                filled += 1
    out["_coverage"] = {"filled": filled, "total": total, "ratio": round(filled / total, 3)}
    return out


def yoy_compare(current: dict[str, Any], prior: dict[str, Any]) -> dict[str, Any]:
    """同比/环比：对两期字段做增速与变动分析。

    current / prior 均可为 extract_fields 结果或扁平 fields dict。
    """
    def fields_of(d: dict[str, Any]) -> dict[str, Any]:
        f = d.get("fields") if isinstance(d.get("fields"), dict) else d
        return f or {}

    cur = fields_of(current)
    pre = fields_of(prior)
    keys = sorted(set(cur) | set(pre))
    rows: list[dict[str, Any]] = []
    for k in keys:
        c, p = _n(cur, k), _n(pre, k)
        if c is None and p is None:
            continue
        yoy = None
        if c is not None and p not in (None, 0):
            yoy = round((c - p) / abs(p), 4)
        rows.append(
            {
                "field": k,
                "current": c,
                "prior": p,
                "change": (None if c is None or p is None else round(c - p, 4)),
                "yoy": yoy,
            }
        )
    return {"rows": rows, "fields_compared": len(rows)}


registry.add_tool(
    Tool(
        name="financial_ratio_suite",
        description=(
            "计算完整财务比率套件：毛利率/净利率/ROE/ROA、流动比率/速动比率、"
            "资产负债率/利息保障倍数、周转率、经营现金流/净利润等。"
            "输入 extract_fields 的 fields；缺字段对应比率为 null，不要补造数字。"
        ),
        input_schema={"extracted": "dict，含 fields 或扁平财务字段"},
        handler=financial_ratio_suite,
        tags=["metrics", "deterministic", "ratios"],
    )
)

registry.add_tool(
    Tool(
        name="yoy_compare",
        description=(
            "两期财务字段同比/环比：对每项字段给出当期值、上期值、变动额与同比增速。"
            "用于营收利润增速、费用率变化等对比分析。"
        ),
        input_schema={"current": "dict 当期字段", "prior": "dict 上期字段"},
        handler=yoy_compare,
        tags=["metrics", "deterministic", "compare"],
    )
)
