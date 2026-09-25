"""python_calc 沙箱与结果清洗的确定性单测。"""

from __future__ import annotations

import pytest

from app.tools.compute import _clean, python_calc


def test_basic_expression():
    assert python_calc("1 + 2")["result"] == 3


def test_multi_statement_last_expr():
    out = python_calc("x = 10\ny = x * 2\nx + y")
    assert out["result"] == 30


def test_math_module_allowed():
    out = python_calc("math.sqrt(16)")
    assert out["result"] == 4.0


def test_cagr_style():
    out = python_calc("(200 / 100) ** (1 / 3) - 1")
    # _clean 会 round 到 6 位小数
    assert abs(out["result"] - 0.259921) < 1e-6


@pytest.mark.parametrize(
    "code",
    [
        "import os",
        "__import__('os')",
        "open('/etc/passwd')",
        "(1).__class__",
        "eval('1')",
    ],
)
def test_sandbox_rejects_dangerous(code: str):
    with pytest.raises(ValueError):
        python_calc(code)


def test_divide_by_zero_message():
    with pytest.raises(ValueError, match="除以零"):
        python_calc("1 / 0")


def test_clean_rounds_floats():
    assert _clean(1.23456789) == 1.234568


def test_clean_handles_nan_inf():
    assert _clean(float("nan")) == "nan"
    assert _clean(float("inf")) == "inf"


def test_clean_nested():
    assert _clean({"a": [1, 2.5]}) == {"a": [1, 2.5]}