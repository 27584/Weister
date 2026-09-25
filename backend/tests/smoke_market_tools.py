"""回归测试：市场数据与计算工具的注册、可用性与安全边界。

网络相关断言依赖公网接口，全部接口均为免 Key 的公开数据源。
公网接口偶发超时或限流，因此网络调用统一包一层重试，
避免把临时网络波动误判为功能缺陷。
计算部分的断言不依赖网络，用于守护受限执行环境的拦截规则。
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.agents import bootstrap as bootstrap_agents
from app.core.registry import registry

bootstrap_agents()


def retry(fn, label: str, times: int = 3):
    """网络调用重试：连续失败判定为数据源不可用。"""
    last: Exception | None = None
    for _ in range(times):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - 捕获后继续重试
            last = exc
            time.sleep(0.8)
    raise AssertionError(f"{label} 连续 {times} 次失败：{last}") from last


print("=== 注册检查 ===")
for name in ("stock_quote", "stock_history", "financial_history", "python_calc"):
    assert registry.tool(name) is not None, f"工具未注册：{name}"
    print(f"  tool  {name} ✓")
assert registry.skills.get("market_data") is not None, "技能未注册：market_data"
print("  skill market_data ✓")
assert registry.agents.get("market_analyst") is not None, "智能体未注册：market_analyst"
print("  agent market_analyst ✓")

print("\n=== 行情工具（腾讯 → 东方财富 → 新浪 降级） ===")
quote = retry(lambda: registry.tool("stock_quote").handler("600519"), "stock_quote")
assert quote["price"] is not None, "行情未取到价格"
print(
    f"  {quote['name']}({quote['code']}) 价 {quote['price']} "
    f"涨跌 {quote['change_pct']}% PE {quote['pe_ttm']} "
    f"市值 {quote['market_cap']} [源 {quote['source']}]"
)

hist = retry(
    lambda: registry.tool("stock_history").handler("600519", "week", 8),
    "stock_history",
)
assert hist["count"] > 0, "K 线为空"
assert hist["stats"], "K 线统计为空"
print(
    f"  K线 {hist['count']} 条 {hist['stats']['start']}~{hist['stats']['end']} "
    f"区间 {hist['stats']['period_return_pct']}% [源 {hist['source']}]"
)

fin = retry(
    lambda: registry.tool("financial_history").handler("600519", 3),
    "financial_history",
)
assert fin["count"] > 0, "财报为空"
first = fin["records"][0]
assert "营业收入" in first and "归母净利润" in first, f"财报字段缺失：{list(first)}"
print(
    f"  财报 {fin['count']} 期，最新 {first['报告期']} "
    f"营收 {first['营业收入']} 净利 {first['归母净利润']}"
)

print("\n=== 名称解析 ===")
by_name = retry(lambda: registry.tool("stock_quote").handler("宁德时代"), "简称解析")
assert by_name["code"] == "300750", f"简称解析错误：{by_name['code']}"
print(f"  简称 宁德时代 → {by_name['code']} {by_name['name']}")

print("\n=== 计算沙箱：功能 ===")
calc = registry.tool("python_calc").handler
assert round(calc("(1 + 0.15) ** 5")["result"], 4) == 2.0114
assert calc("cagr = (520 / 300) ** (1 / 5) - 1; round(cagr * 100, 2)")["result"] == 11.63
assert calc("[round(x, 2) for x in [1, 2, 3]]")["result"] == [1, 2, 3]
assert calc("math.sqrt(144)")["result"] == 12.0
assert round(calc("math.log(2.5)")["result"], 4) == 0.9163
assert round(calc("statistics.stdev([1,2,3,4,5])")["result"], 4) == 1.5811
print("  算术 / 多行 / 推导 / math / statistics 均通过")

print("\n=== 计算沙箱：安全边界 ===")
BLOCKED = [
    "import os",
    "().__class__",
    "(1,).__class__.__bases__[0].__subclasses__()",
    "__import__('os')",
    "math.__class__",
    "open('x')",
    "eval('1+1')",
    "exec('x=1')",
    "globals()",
]
for code in BLOCKED:
    try:
        calc(code)
    except Exception:  # noqa: BLE001 - 期望被拦截，任何异常都算通过
        print(f"  已拦截 {code}")
        continue
    raise AssertionError(f"未拦截危险代码：{code}")

print("\nRESULT: ALL PASS（市场数据与计算工具）")
