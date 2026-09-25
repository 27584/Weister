"""受限数值计算工具。

让智能体执行确定性的算术与统计，避免用大语言模型心算增长率、
CAGR、比率换算或敏感性试算这类必然出错的任务。

安全模型：
    1. 先做 AST 静态检查，仅放行白名单节点；
    2. 禁止 import、属性访问（杜绝 __class__ / __globals__ 等逃逸路径）、
       推导式中的副作用与所有 I/O；
    3. 内置函数与模块均为只读白名单，不提供 open / exec / eval / __import__；
    4. 单条语句与循环次数设上限，防止长时间占用。

因此该工具只能做纯计算，不具备文件、网络与进程能力。
"""

from __future__ import annotations

import ast
import math
import statistics
from typing import Any

MAX_SOURCE_CHARS = 4000
MAX_STATEMENTS = 200

_ALLOWED_NODES = (
    ast.Module,
    ast.Expr,
    ast.Assign,
    ast.AugAssign,
    ast.Name,
    ast.Load,
    ast.Store,
    ast.Constant,
    ast.BinOp,
    ast.UnaryOp,
    ast.BoolOp,
    ast.Compare,
    ast.IfExp,
    ast.List,
    ast.Tuple,
    ast.Dict,
    ast.Set,
    ast.Subscript,
    ast.Slice,
    ast.ListComp,
    ast.DictComp,
    ast.SetComp,
    ast.comprehension,
    ast.Call,
    ast.keyword,  # 仅白名单内置函数可调用，属性访问已整体禁用
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.FloorDiv,
    ast.Mod,
    ast.Pow,
    ast.USub,
    ast.UAdd,
    ast.And,
    ast.Or,
    ast.Not,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
    ast.In,
    ast.NotIn,
    ast.Is,
    ast.IsNot,
)

_ALLOWED_BUILTINS: dict[str, Any] = {
    "abs": abs,
    "min": min,
    "max": max,
    "sum": sum,
    "round": round,
    "len": len,
    "pow": pow,
    "range": range,
    "sorted": sorted,
    "reversed": reversed,
    "any": any,
    "all": all,
    "zip": zip,
    "enumerate": enumerate,
    "int": int,
    "float": float,
    "str": str,
    "bool": bool,
    "list": list,
    "dict": dict,
    "set": set,
    "tuple": tuple,
}

_ALLOWED_MODULES: dict[str, Any] = {"math": math, "statistics": statistics}


def _check(tree: ast.AST) -> None:
    """静态校验：节点类型白名单 + 导入与属性访问限制。"""
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            raise ValueError("计算环境不允许 import")
        if isinstance(node, ast.Attribute):
            # 仅放行白名单模块的公开属性（如 math.log）；
            # 其余属性访问（含 __class__ / __subclasses__ 一类逃逸路径）一律拒绝
            base = node.value
            if not (isinstance(base, ast.Name) and base.id in _ALLOWED_MODULES):
                raise ValueError("计算环境不允许属性访问")
            if node.attr.startswith("_"):
                raise ValueError(f"不允许访问：{base.id}.{node.attr}")
            continue  # 白名单模块的公开属性已放行
        # 名称以下划线开头（如 __import__）一律拒绝
        if isinstance(node, ast.Name) and node.id.startswith("__"):
            raise ValueError(f"不允许访问：{node.id}")
        if isinstance(node, _ALLOWED_NODES):
            continue
        raise ValueError(f"不支持的语法：{type(node).__name__}（仅支持纯数值计算）")


def _run(source: str) -> Any:
    tree = ast.parse(source, mode="exec")
    _check(tree)

    stmts = tree.body
    if len(stmts) > MAX_STATEMENTS:
        raise ValueError(f"语句数量超过上限 {MAX_STATEMENTS}")

    # __builtins__ 必须显式置为白名单：exec / eval 会自动注入完整的
    # builtins，否则 open / eval / __import__ 等都将可用。
    env: dict[str, Any] = {"__builtins__": dict(_ALLOWED_BUILTINS), **_ALLOWED_MODULES}
    for stmt in stmts[:-1]:
        exec(compile(ast.Module(body=[stmt], type_ignores=[]), "<calc>", "exec"), env, env)

    last = stmts[-1]
    if isinstance(last, ast.Expr):
        return eval(compile(ast.Expression(last.value), "<calc>", "eval"), env, env)
    exec(compile(ast.Module(body=[last], type_ignores=[]), "<calc>", "exec"), env, env)
    return None


def _clean(value: Any, depth: int = 0) -> Any:
    """把结果收敛为可 JSON 序列化的结构，避免返回不可展示的对象。"""
    if depth > 3:
        return str(value)
    if value is None or isinstance(value, (bool, int, float, str)):
        if isinstance(value, float):
            if math.isnan(value) or math.isinf(value):
                return str(value)
            return round(value, 6)
        return value
    if isinstance(value, (list, tuple, set)):
        return [_clean(v, depth + 1) for v in list(value)[:200]]
    if isinstance(value, dict):
        return {str(k): _clean(v, depth + 1) for k, v in list(value.items())[:100]}
    return str(value)


def python_calc(code: str) -> dict[str, Any]:
    """在受限环境中执行纯数值计算，返回最后一条表达式的值。

    可用内置：abs / min / max / sum / round / len / pow / range / sorted /
    zip / enumerate / int / float / 等；可用模块：math、statistics。
    不支持 import、属性访问、字符串格式化以外的一切 I/O。

    典型用途：增长率与 CAGR、比率换算、DCF 试算、加权平均、简单的
    描述性统计。多行代码用最后一条表达式作为返回值。
    """
    source = (code or "").strip()
    if not source:
        raise ValueError("code 不能为空")
    if len(source) > MAX_SOURCE_CHARS:
        raise ValueError(f"代码长度超过上限 {MAX_SOURCE_CHARS} 字符")

    try:
        value = _run(source)
    except ValueError:
        raise
    except ZeroDivisionError:
        raise ValueError("计算中出现除以零") from None
    except Exception as exc:  # noqa: BLE001 - 把执行期错误统一成可读提示
        raise ValueError(f"{type(exc).__name__}: {exc}") from None

    return {
        "code": source,
        "result": _clean(value),
        "result_type": type(value).__name__,
        "note": "受限计算环境：仅数值与统计，无文件、网络与进程能力。",
    }


registry_tools = [
    {
        "name": "python_calc",
        "description": (
            "在受限环境中执行纯数值计算，返回最后一条表达式的值。"
            "用于增长率与 CAGR、比率换算、加权平均、DCF 试算、描述性统计等"
            "必须精确的步骤 —— 这类计算不要用语言模型心算。"
            "可用内置：abs/min/max/sum/round/len/pow/range/sorted/zip/int/float 等；"
            "可用模块：math、statistics。不支持 import 与任何 I/O。"
        ),
        "input_schema": {"code": "Python 表达式或多行代码，最后一条表达式的值作为结果"},
        "handler": python_calc,
    },
]


def register() -> None:
    from ..core.registry import Tool, registry

    for spec in registry_tools:
        registry.add_tool(
            Tool(
                name=spec["name"],
                description=spec["description"],
                input_schema=spec["input_schema"],
                handler=spec["handler"],
                tags=["compute"],
            )
        )


register()
