"""派生指标确定性单测。"""

from __future__ import annotations

from app.tools.metrics import compute_metrics


def test_net_margin_and_debt_ratio():
    m = compute_metrics(
        {
            "fields": {
                "revenue": 1000,
                "net_profit": 100,
                "operating_cash_flow": 30,
                "total_assets": 2000,
                "total_liabilities": 800,
            }
        }
    )
    assert m["net_margin"] == 0.1
    assert m["ocf_to_revenue"] == 0.03
    assert m["debt_ratio"] == 0.4
    assert m["profit_cash_gap"] == -70
    assert m["profit_cash_divergence"] is True  # |gap|/profit = 0.7 > 0.5


def test_no_divergence_when_close():
    m = compute_metrics(
        {
            "fields": {
                "revenue": 1000,
                "net_profit": 100,
                "operating_cash_flow": 95,
            }
        }
    )
    assert m["profit_cash_divergence"] is False


def test_empty_fields():
    assert compute_metrics({"fields": {}}) == {}
    assert compute_metrics({}) == {}
