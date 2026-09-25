"""工具集。

导入本包会触发所有工具的注册，注册后可通过 registry.tool(name) 获取。
"""

from . import compare as _compare  # noqa: F401
from . import compute as _compute  # noqa: F401
from . import interact as _interact  # noqa: F401
from . import market as _market  # noqa: F401
from . import ratios as _ratios  # noqa: F401
from . import skills as _skills  # noqa: F401
from . import source_trace as _source_trace  # noqa: F401
from . import web as _web  # noqa: F401
from .extraction import extract_fields
from .metrics import compute_metrics
from .parsing import (
    assess_document,
    chunk_text,
    ocr_available,
    parse_pdf,
    parse_text,
    unreadable_reason,
)
from .valuation import (
    build_assumptions,
    dcf_valuation,
    relative_valuation,
    sensitivity_grid,
    summarize_valuation,
)

__all__ = [
    "assess_document",
    "build_assumptions",
    "chunk_text",
    "compute_metrics",
    "dcf_valuation",
    "extract_fields",
    "ocr_available",
    "parse_pdf",
    "parse_text",
    "relative_valuation",
    "sensitivity_grid",
    "summarize_valuation",
    "unreadable_reason",
]
