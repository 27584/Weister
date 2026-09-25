"""DCF / 相对估值 / 敏感性 / 汇总的确定性单测。"""

from __future__ import annotations

import pytest

from app.tools.valuation import (
    dcf_valuation,
    relative_valuation,
    sensitivity_grid,
    summarize_valuation,
)

BASE_ASSUMPTIONS = {
    "wacc": 0.10,
    "terminal_growth": 0.025,
    "forecast_years": 3,
    "growth_rates": [0.10, 0.08, 0.06],
    "fcf_margin": 0.10,
}


def test_dcf_basic_identity():
    """企业价值 = 明确预测期现值 + 终值现值；权益价值 = EV - 净债务。"""
    out = dcf_valuation(1000.0, BASE_ASSUMPTIONS, net_debt=200.0)
    assert out["enterprise_value"] == pytest.approx(
        out["pv_explicit"] + out["pv_terminal"], rel=1e-6
    )
    assert out["equity_value"] == pytest.approx(out["enterprise_value"] - 200.0, rel=1e-6)
    assert len(out["rows"]) == 3


def test_dcf_rejects_wacc_le_growth():
    bad = {**BASE_ASSUMPTIONS, "wacc": 0.02, "terminal_growth": 0.03}
    with pytest.raises(ValueError, match="必须大于"):
        dcf_valuation(1000.0, bad)


def test_dcf_per_share():
    out = dcf_valuation(1000.0, BASE_ASSUMPTIONS, net_debt=0.0, shares_outstanding=100.0)
    assert out["equity_value_per_share"] == pytest.approx(out["equity_value"] / 100.0, rel=1e-4)


def test_dcf_deterministic():
    a = dcf_valuation(1000.0, BASE_ASSUMPTIONS, net_debt=100.0)
    b = dcf_valuation(1000.0, BASE_ASSUMPTIONS, net_debt=100.0)
    assert a == b


def test_relative_valuation_pe_ps():
    out = relative_valuation(100.0, 800.0, pe_range=(10, 20), ps_range=(1, 2))
    assert out["pe"]["equity_value"] == [1000.0, 2000.0]
    assert out["ps"]["equity_value"] == [800.0, 1600.0]


def test_summarize_valuation_range():
    dcf = {"equity_value": 1000.0}
    relative = {
        "pe": {"equity_value": [900.0, 1100.0]},
        "ps": {"equity_value": [950.0]},
    }
    s = summarize_valuation(dcf, relative)
    assert s["low"] == 900.0
    assert s["high"] == 1100.0
    assert s["methods"]["dcf"] == 1000.0


def test_sensitivity_grid_shape_and_invalid_cells():
    grid = sensitivity_grid(
        1000.0,
        BASE_ASSUMPTIONS,
        net_debt=0.0,
        wacc_range=[0.08, 0.12],
        growth_range=[0.02, 0.10],
    )
    assert len(grid["grid"]) == 2
    assert len(grid["grid"][0]) == 2
    # wacc <= growth 时终值发散，该格为 None（前端渲染为「—」），
    # 不再假装成一个 0 的估值结果
    assert grid["grid"][0][1] is None  # wacc=0.08, growth=0.10
    assert grid["grid"][1][0] > 0  # wacc=0.12, growth=0.02
