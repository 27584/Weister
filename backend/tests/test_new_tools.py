"""新增比率 / 同比 / 同业 / 溯源工具单测。"""

from __future__ import annotations

import pytest

from app.tools.compare import peer_comparison
from app.tools.ratios import financial_ratio_suite, yoy_compare
from app.tools.source_trace import locate_evidence

FIELDS = {
    "revenue": 1000.0,
    "net_profit": 100.0,
    "operating_profit": 120.0,
    "gross_profit": 400.0,
    "operating_cash_flow": 90.0,
    "capex": 30.0,
    "current_assets": 500.0,
    "current_liabilities": 250.0,
    "inventory": 100.0,
    "cash": 80.0,
    "total_assets": 2000.0,
    "total_liabilities": 800.0,
    "shareholders_equity": 1200.0,
}


def test_ratio_suite_core():
    out = financial_ratio_suite({"fields": FIELDS})
    assert out["profitability"]["net_margin"] == 0.1
    assert out["liquidity"]["current_ratio"] == 2.0
    assert out["solvency"]["debt_ratio"] == 0.4
    assert out["cash_quality"]["fcf"] == 60.0
    assert out["_coverage"]["filled"] > 0


def test_ratio_suite_missing_fields_null():
    out = financial_ratio_suite({"fields": {"revenue": 10}})
    assert out["profitability"]["net_margin"] is None
    assert out["liquidity"]["current_ratio"] is None


def test_yoy_compare():
    out = yoy_compare({"fields": {"revenue": 120, "net_profit": 15}}, {"fields": {"revenue": 100, "net_profit": 10}})
    by = {r["field"]: r for r in out["rows"]}
    assert by["revenue"]["yoy"] == 0.2
    assert by["net_profit"]["yoy"] == 0.5


def test_peer_comparison_table():
    out = peer_comparison(
        [
            {"name": "A", "fields": {"revenue": 100, "net_profit": 10}},
            {"name": "B", "fields": {"revenue": 200, "net_profit": 30}},
        ],
        keys=["revenue", "net_profit"],
    )
    assert len(out["rows"]) == 2
    assert "| A |" in out["markdown_table"]
    assert "revenue" in out["markdown_table"]


def test_peer_comparison_requires_two():
    with pytest.raises(ValueError):
        peer_comparison([{"name": "A", "fields": {}}])


def test_locate_evidence_quote():
    pages = [
        {"page": 1, "text": "公司名称示例。"},
        {"page": 2, "text": "报告期内营业收入为 100 亿元，同比增长 12%。"},
    ]
    out = locate_evidence(pages=pages, quote="营业收入为 100 亿元")
    assert out["count"] >= 1
    assert out["hits"][0]["page"] == 2
    assert "营业收入" in out["hits"][0]["snippet"]


def test_locate_evidence_keywords():
    out = locate_evidence(
        document_text="前言\n\n资产负债率上升至 45%。\n\n后记",
        keywords=["资产负债率"],
    )
    assert out["count"] >= 1
