"""估值建模工具。

包含假设生成、DCF 折现、相对估值、敏感性分析与区间汇总。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..core.registry import Tool, registry
from ..llm import LLMClient

DeltaHandler = Callable[[Any], None]

ASSUMPTION_SYSTEM = """你是估值分析师。基于给定的财务数据，给出 DCF 估值所需的核心假设。
输出严格 JSON，每个假设必须在 rationale 中写明依据。"""

ASSUMPTION_HINT = """输出结构：
{
  "wacc": 0.10,
  "terminal_growth": 0.025,
  "forecast_years": 5,
  "growth_rates": [0.15, 0.12, 0.10, 0.08, 0.06],
  "fcf_margin": 0.08,
  "rationale": {
    "wacc": "依据",
    "terminal_growth": "依据",
    "growth_rates": "依据",
    "fcf_margin": "依据"
  }
}"""


def build_assumptions(
    extracted: dict[str, Any],
    metrics: dict[str, Any],
    client: LLMClient,
    on_delta: DeltaHandler | None = None,
) -> dict[str, Any]:
    client.require_configured()
    user = f"{ASSUMPTION_HINT}\n\n财务数据：{extracted.get('fields')}\n\n派生指标：{metrics}"
    if on_delta is None:
        raw = client.chat(
            ASSUMPTION_SYSTEM + "\n只输出 JSON，不要任何解释或 Markdown 代码块围栏。",
            user,
        )
        return _parse_assumptions(raw)

    parts: list[str] = []
    for delta in client.stream_messages(
        [
            {
                "role": "system",
                "content": ASSUMPTION_SYSTEM
                + "\n只输出 JSON，不要任何解释或 Markdown 代码块围栏。",
            },
            {"role": "user", "content": user},
        ],
    ):
        on_delta(delta)
        if delta.content:
            parts.append(delta.content)

    raw = "".join(parts).strip()
    if not raw:
        raise RuntimeError("模型未返回可解析的假设 JSON")

    return _parse_assumptions(raw)


def _parse_assumptions(raw: str) -> dict[str, Any]:
    """解析假设 JSON，缺字段时补默认值。

    DCF 需要四个核心参数。若模型输出不完整（截断或漏字段），
    用保守默认值补齐，保证估值流程不中断。
    """
    from .extraction import _parse_json_safe

    data = _parse_json_safe(raw)
    if not isinstance(data, dict):
        raise RuntimeError(f"假设输出不是 JSON 对象：{type(data).__name__}")

    defaults = {
        "wacc": 0.10,
        "terminal_growth": 0.025,
        "forecast_years": 5,
        "growth_rates": [0.12, 0.10, 0.08, 0.06, 0.05],
        "fcf_margin": 0.08,
    }

    filled = dict(data)
    for key, value in defaults.items():
        if key not in filled or filled[key] is None:
            filled[key] = value

    # 类型与边界校验
    filled["wacc"] = float(filled["wacc"])
    filled["terminal_growth"] = float(filled["terminal_growth"])
    filled["forecast_years"] = int(filled["forecast_years"])
    filled["fcf_margin"] = float(filled["fcf_margin"])

    rates = filled.get("growth_rates")
    if not isinstance(rates, list) or len(rates) < filled["forecast_years"]:
        base = list(defaults["growth_rates"])
        while len(base) < filled["forecast_years"]:
            base.append(base[-1])
        filled["growth_rates"] = base[: filled["forecast_years"]]
    else:
        filled["growth_rates"] = [float(r) for r in rates[: filled["forecast_years"]]]

    if filled["wacc"] <= filled["terminal_growth"]:
        filled["wacc"] = filled["terminal_growth"] + 0.05

    if not isinstance(filled.get("rationale"), dict):
        filled["rationale"] = {}

    return filled


def dcf_valuation(
    base_revenue: float,
    assumptions: dict[str, Any],
    net_debt: float = 0.0,
    shares_outstanding: float | None = None,
) -> dict[str, Any]:
    wacc = float(assumptions["wacc"])
    g_term = float(assumptions["terminal_growth"])
    years = int(assumptions["forecast_years"])
    growth_rates = list(assumptions["growth_rates"])[:years]
    fcf_margin = float(assumptions["fcf_margin"])

    if wacc <= g_term:
        raise ValueError(f"WACC ({wacc}) 必须大于永续增长率 ({g_term})")

    rows: list[dict[str, Any]] = []
    revenue = base_revenue
    pv_sum = 0.0
    for i in range(years):
        revenue = revenue * (1 + float(growth_rates[i]))
        fcf = revenue * fcf_margin
        pv = fcf / (1 + wacc) ** (i + 1)
        pv_sum += pv
        rows.append(
            {
                "year": i + 1,
                "growth": round(float(growth_rates[i]), 4),
                "revenue": round(revenue, 2),
                "fcf": round(fcf, 2),
                "pv": round(pv, 2),
            }
        )

    terminal_value = rows[-1]["fcf"] * (1 + g_term) / (wacc - g_term)
    pv_terminal = terminal_value / (1 + wacc) ** years
    enterprise_value = pv_sum + pv_terminal
    equity_value = enterprise_value - net_debt

    # 若提供了总股本，直接算好每股价值，避免模型自行换算时出错。
    # 优先用显式参数，其次查 assumptions。
    shares = shares_outstanding
    if shares is None:
        shares = assumptions.get("shares_outstanding")
    per_share: float | None = None
    if isinstance(shares, (int, float)) and shares > 0:
        per_share = round(equity_value / shares, 4)

    return {
        "rows": rows,
        "pv_explicit": round(pv_sum, 2),
        "terminal_value": round(terminal_value, 2),
        "pv_terminal": round(pv_terminal, 2),
        "terminal_share": round(pv_terminal / enterprise_value, 4) if enterprise_value else None,
        "enterprise_value": round(enterprise_value, 2),
        "equity_value": round(equity_value, 2),
        "equity_value_per_share": per_share,
        "shares_outstanding": shares,
        "net_debt": round(net_debt, 2),
    }


def sensitivity_grid(
    base_revenue: float,
    assumptions: dict[str, Any],
    net_debt: float,
    wacc_range: list[float],
    growth_range: list[float],
) -> dict[str, Any]:
    # 格子里可能出现 None（WACC ≤ 永续增长率时终值发散，无法计算）
    grid: list[list[float | None]] = []
    for w in wacc_range:
        row: list[float | None] = []
        for g in growth_range:
            if w <= g:
                # WACC 不高于永续增长率时终值数学上发散，不是「估值为 0」。
                # 填 None 让前端渲染为「— / N/A」，避免被误读成一个真实的计算结果。
                row.append(None)
                continue
            a = {**assumptions, "wacc": w, "terminal_growth": g}
            row.append(dcf_valuation(base_revenue, a, net_debt)["equity_value"])
        grid.append(row)
    return {
        "wacc": [round(w, 4) for w in wacc_range],
        "growth": [round(g, 4) for g in growth_range],
        "grid": grid,
    }


def relative_valuation(
    net_profit: float | None,
    revenue: float | None,
    pe_range: tuple[float, float] = (15.0, 25.0),
    ps_range: tuple[float, float] = (2.0, 4.0),
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if net_profit:
        out["pe"] = {
            "multiple": [pe_range[0], pe_range[1]],
            "equity_value": [
                round(net_profit * pe_range[0], 2),
                round(net_profit * pe_range[1], 2),
            ],
        }
    if revenue:
        out["ps"] = {
            "multiple": [ps_range[0], ps_range[1]],
            "equity_value": [round(revenue * ps_range[0], 2), round(revenue * ps_range[1], 2)],
        }
    return out


def summarize_valuation(dcf: dict[str, Any], relative: dict[str, Any]) -> dict[str, Any]:
    points: list[float] = [dcf["equity_value"]]
    for key in ("pe", "ps"):
        block = relative.get(key)
        if block:
            points.extend(block["equity_value"])
    points = [p for p in points if p > 0]
    if not points:
        return {"low": 0.0, "mid": 0.0, "high": 0.0, "methods": {}}
    return {
        "low": round(min(points), 2),
        "mid": round(sum(points) / len(points), 2),
        "high": round(max(points), 2),
        "methods": {
            "dcf": dcf["equity_value"],
            **{k: v["equity_value"] for k, v in relative.items()},
        },
    }


registry.add_tool(
    Tool(
        name="build_assumptions",
        description="基于财务数据生成 DCF 核心假设（WACC、永续增长率、增速序列、FCF 利润率）",
        input_schema={"extracted": "dict", "metrics": "dict"},
        handler=build_assumptions,
        tags=["valuation", "llm"],
        inject=["client", "on_delta"],
    )
)

registry.add_tool(
    Tool(
        name="dcf_valuation",
        description=(
            "两阶段 DCF：显式预测期现金流折现 + 永续增长终值。"
            "传入 shares_outstanding 可直接得到每股价值，避免手工换算。"
        ),
        input_schema={
            "base_revenue": "float",
            "assumptions": "dict",
            "net_debt": "float",
            "shares_outstanding": "float（可选）",
        },
        handler=dcf_valuation,
        tags=["valuation", "deterministic"],
    )
)

registry.add_tool(
    Tool(
        name="sensitivity_grid",
        description="WACC × 永续增长率 二维敏感性分析矩阵",
        input_schema={
            "base_revenue": "float",
            "assumptions": "dict",
            "net_debt": "float",
            "wacc_range": "list[float]",
            "growth_range": "list[float]",
        },
        handler=sensitivity_grid,
        tags=["valuation", "deterministic"],
    )
)

registry.add_tool(
    Tool(
        name="relative_valuation",
        description="相对估值：给定 PE / PS 倍数区间输出隐含市值区间",
        input_schema={"net_profit": "float", "revenue": "float"},
        handler=relative_valuation,
        tags=["valuation", "deterministic"],
    )
)

registry.add_tool(
    Tool(
        name="summarize_valuation",
        description="汇总 DCF 与相对估值得出综合估值区间",
        input_schema={"dcf": "dict", "relative": "dict"},
        handler=summarize_valuation,
        tags=["valuation", "deterministic"],
    )
)
