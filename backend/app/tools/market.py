"""A 股市场数据工具：实时行情、历史 K 线、历史财报主要指标。

数据源全部为公开接口，无需 API Key，覆盖沪深北交所。
网络访问复用 tools._http：系统代理失败时自动降级直连，请求自带重试。

行情与 K 线采用多源降级：
    行情  腾讯 qt.gtimg.cn（字段最全） → 东方财富 push2 → 新浪 hq.sinajs.cn
    K 线  腾讯 ifzq.gtimg.cn（前复权） → 东方财富 push2his
    财报  东方财富 datacenter-web（定期报告主要指标）

单一源在高频访问下会触发限流（东方财富 push2 会直接断开连接而不返回响应），
因此每个工具都必须有多个可用源，并在全部失败时给出明确错误。

标的解析支持三种输入：
    6 位代码（600519）、带市场前缀（sh600519 / SZ300750）、公司简称（贵州茅台）。
简称通过东方财富 suggest 接口匹配，取相关性最高的 A 股条目。
"""

from __future__ import annotations

import re
from typing import Any

from ._http import get as http_get
from ._http import get_json

_EM_QUOTE_URL = "https://push2.eastmoney.com/api/qt/stock/get"
_EM_KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
_EM_SUGGEST_URL = "https://searchapi.eastmoney.com/api/suggest/get"
_EM_FINANCE_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
_TX_QUOTE_URL = "https://qt.gtimg.cn/q="
_TX_KLINE_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
_SINA_QUOTE_URL = "https://hq.sinajs.cn/list="
_SINA_KLINE_URL = "https://quotes.sina.cn/cn/api/json_v2.php/CN_MarketDataService.getKLineData"

# 东方财富行情字段：价格 / 股本 / 市值 / 估值 / 涨跌
_EM_QUOTE_FIELDS = (
    "f43,f44,f45,f46,f47,f48,f57,f58,f59,f60,f84,f85,f116,f117,f162,f167,f168,f169,f170"
)

_EM_KLINE_PERIOD = {"day": "101", "week": "102", "month": "103"}
# 新浪 K 线周期参数（分钟数）：日 240 / 周 1200 / 月 7200
_SINA_KLINE_SCALE = {"day": "240", "week": "1200", "month": "7200"}

# 业绩报表字段 → 中文名
_FINANCE_FIELDS = {
    "SECURITY_NAME_ABBR": "证券简称",
    "REPORTDATE": "报告期",
    "TOTAL_OPERATE_INCOME": "营业收入",
    "PARENT_NETPROFIT": "归母净利润",
    "BASIC_EPS": "每股收益",
    "DEDUCT_BASIC_EPS": "扣非每股收益",
    "BPS": "每股净资产",
    "WEIGHTAVG_ROE": "加权净资产收益率",
    "XSMLL": "销售毛利率",
    "MGJYXJJE": "每股经营现金流",
    "ZXGXL": "股息率",
    "YSHZ": "营业收入同比",
    "SJLHZ": "净利润同比",
}


# ---------- 标的解析 ----------


def _market_id(code: str) -> str:
    """6 位 A 股代码 → 东方财富市场标识（沪市 1，深市与北交所 0）。"""
    if code.startswith(("60", "68", "9")):
        return "1"
    return "0"


def _exchange(code: str) -> str:
    """6 位 A 股代码 → 腾讯 / 新浪前缀（sh / sz / bj）。"""
    if code.startswith(("60", "68", "9")):
        return "sh"
    if code.startswith(("4", "8")):
        return "bj"
    return "sz"


def _digits(raw: str) -> str:
    m = re.search(r"(\d{6})", (raw or "").strip().upper())
    return m.group(1) if m else ""


def _resolve(query: str) -> dict[str, str]:
    """把用户输入解析为 {code, name, secid, symbol}。

    symbol 为带交易所前缀的代码（sh600519），供腾讯与新浪接口使用。
    输入已是 6 位代码时直接构造，省去一次网络请求。
    """
    q = (query or "").strip()
    if not q:
        raise ValueError("标的不能为空，请提供股票代码或公司简称")

    # 明显的非 A 股代码：直接说明能力边界，避免在 suggest 里空转
    upper = q.upper().replace(" ", "")
    if re.fullmatch(r"[A-Z]{1,5}", upper) or re.search(
        r"\b(AAPL|TSLA|MSFT|GOOGL|AMZN|NVDA)\b", upper
    ):
        raise ValueError(
            f"「{q}」看起来不是中国 A 股标的。本行情接口仅覆盖沪深北交所；"
            "美股/港股请改用 web_search 查询公开行情与财务摘要。"
        )

    code = _digits(q)
    if code:
        return {
            "code": code,
            "name": "",
            "secid": f"{_market_id(code)}.{code}",
            "symbol": f"{_exchange(code)}{code}",
        }

    data = get_json(
        _EM_SUGGEST_URL,
        params={
            "input": q,
            "type": "14",
            "token": "D43BF722C8E33BDC906FB84D85E326E8",
            "count": "10",
        },
    )
    items = ((data or {}).get("QuotationCodeTable") or {}).get("Data") or []
    astock = [i for i in items if i.get("Classify") == "AStock"]
    hit = astock[0] if astock else (items[0] if items else None)
    code = str((hit or {}).get("Code") or "")
    if not code:
        raise ValueError(
            f"未找到匹配的 A 股标的：{q}。"
            "若为美股/港股/其他市场，请改用 web_search 查询，不要继续调用 stock_quote。"
        )
    return {
        "code": code,
        "name": str((hit or {}).get("Name") or ""),
        "secid": f"{_market_id(code)}.{code}",
        "symbol": f"{_exchange(code)}{code}",
    }


def _num(value: Any) -> float | None:
    if value in (None, "", "-"):
        return None
    try:
        return round(float(value), 4)
    except (TypeError, ValueError):
        return None


def _ratio(value: Any) -> float | None:
    """东方财富的价格与比率字段为实际值 × 100。"""
    out = _num(value)
    return None if out is None else round(out / 100, 4)


# ---------- 实时行情 ----------


def _quote_tx(symbol: str) -> dict[str, Any] | None:
    """腾讯行情源：字段最全（含市值、市盈率、市净率、换手率）。"""
    resp = http_get(_TX_QUOTE_URL + symbol)
    body = resp.text
    if '="' not in body:
        return None
    p = body.split('="', 1)[1].rstrip('";\n').split("~")
    if len(p) < 47:
        return None

    def at(i: int) -> float | None:
        return _num(p[i]) if i < len(p) else None

    amount_wan = at(37)  # 成交额，万元
    float_cap_yi = at(44)  # 流通市值，亿元
    total_cap_yi = at(45)  # 总市值，亿元
    return {
        "code": p[2] if len(p) > 2 else "",
        "name": p[1] if len(p) > 1 else "",
        "price": at(3),
        "prev_close": at(4),
        "open": at(5),
        "high": at(33),
        "low": at(34),
        "change": at(31),
        "change_pct": at(32),
        "volume_lots": at(36),
        "turnover": amount_wan * 10000 if amount_wan is not None else None,
        "turnover_rate": at(38),
        "pe_ttm": at(39),
        "pb": at(46),
        "float_cap": float_cap_yi * 1e8 if float_cap_yi is not None else None,
        "market_cap": total_cap_yi * 1e8 if total_cap_yi is not None else None,
        "total_shares": None,
        "float_shares": None,
        "currency": "CNY",
        "source": "腾讯财经",
    }


def _quote_em(secid: str) -> dict[str, Any] | None:
    """东方财富行情源：提供股本数据，作为腾讯源的补充。"""
    data = get_json(_EM_QUOTE_URL, params={"secid": secid, "fields": _EM_QUOTE_FIELDS})
    d = (data or {}).get("data")
    if not d:
        return None
    # 价格字段按接口返回的小数位缩放（A 股通常为 2 位）
    div = 10 ** int(d.get("f59") or 2)

    def price(value: Any) -> float | None:
        raw = _num(value)
        return None if raw is None else round(raw / div, 4)

    return {
        "code": d.get("f57") or "",
        "name": d.get("f58") or "",
        "price": price(d.get("f43")),
        "prev_close": price(d.get("f60")),
        "open": price(d.get("f46")),
        "high": price(d.get("f44")),
        "low": price(d.get("f45")),
        "change": price(d.get("f169")),
        "change_pct": _ratio(d.get("f170")),
        "volume_lots": _num(d.get("f47")),
        "turnover": _num(d.get("f48")),
        "turnover_rate": _ratio(_num(d.get("f168"))),
        "pe_ttm": _ratio(d.get("f162")),
        "pb": _ratio(d.get("f167")),
        "float_cap": _num(d.get("f117")),
        "market_cap": _num(d.get("f116")),
        "total_shares": _num(d.get("f84")),
        "float_shares": _num(d.get("f85")),
        "currency": "CNY",
        "source": "东方财富",
    }


def _quote_sina(symbol: str) -> dict[str, Any] | None:
    """新浪行情源：仅价格与成交，作为末级降级。"""
    resp = http_get(
        _SINA_QUOTE_URL + symbol,
        headers={"Referer": "https://finance.sina.com.cn"},
    )
    body = resp.text
    if '="' not in body:
        return None
    p = body.split('="', 1)[1].rstrip('";\n').split(",")
    if len(p) < 10:
        return None
    return {
        "code": _digits(symbol),
        "name": p[0],
        "price": _num(p[3]),
        "prev_close": _num(p[2]),
        "open": _num(p[1]),
        "high": _num(p[4]),
        "low": _num(p[5]),
        "change": None,
        "change_pct": None,
        "volume_lots": None,
        "turnover": _num(p[9]),
        "turnover_rate": None,
        "pe_ttm": None,
        "pb": None,
        "float_cap": None,
        "market_cap": None,
        "total_shares": None,
        "float_shares": None,
        "currency": "CNY",
        "source": "新浪财经",
    }


def stock_quote(symbol: str) -> dict[str, Any]:
    """查询 A 股实时行情：价格、涨跌幅、总市值、市盈率、市净率、换手率。

    参数 symbol 支持 6 位代码、带市场前缀的代码或公司简称。
    盘中为实时快照，收盘后为当日收盘价。数据源按腾讯 → 东方财富 → 新浪降级。
    """
    target = _resolve(symbol)
    errors: list[str] = []
    for label, fn, arg in (
        ("腾讯", _quote_tx, target["symbol"]),
        ("东方财富", _quote_em, target["secid"]),
        ("新浪", _quote_sina, target["symbol"]),
    ):
        try:
            data = fn(arg)
        except Exception as exc:  # noqa: BLE001 - 单源失败即降级
            errors.append(f"{label}: {type(exc).__name__}")
            continue
        if data and data.get("price") is not None:
            data["note"] = (
                "行情快照。单位：价格 元、成交额 元、市值 元；"
                "涨跌幅 / 换手率 / 股息率为百分比数值。"
            )
            return data
        errors.append(f"{label}: 返回空数据")

    raise ValueError(f"所有行情源均不可用（{symbol}）：" + "；".join(errors))


# ---------- 历史 K 线 ----------


def _kline_tx(symbol: str, period: str, limit: int) -> list[dict[str, Any]]:
    """腾讯 K 线：返回 [日期, 开, 收, 高, 低, 成交量]。"""
    data = get_json(
        _TX_KLINE_URL,
        params={
            "param": f"{symbol},{period},,,{limit},qfq",
        },
    )
    node = ((data or {}).get("data") or {}).get(symbol) or {}
    rows = node.get("qfq" + period) or node.get(period) or []
    out = []
    for r in rows:
        if len(r) < 6:
            continue
        out.append(
            {
                "date": str(r[0])[:10],
                "open": _num(r[1]),
                "close": _num(r[2]),
                "high": _num(r[3]),
                "low": _num(r[4]),
                "volume": _num(r[5]),
            }
        )
    return out


def _kline_em(secid: str, period: str, limit: int) -> list[dict[str, Any]]:
    """东方财富 K 线：返回 日期,收盘,开盘,最高,最低,成交量,成交额。"""
    data = get_json(
        _EM_KLINE_URL,
        params={
            "secid": secid,
            "klt": _EM_KLINE_PERIOD[period],
            "fqt": "1",  # 前复权
            "beg": "19900101",
            "end": "20500101",
            "fields1": "f1,f2,f3",
            "fields2": "f51,f52,f53,f54,f55,f56,f57",
        },
    )
    d = (data or {}).get("data")
    if not d:
        return []
    out = []
    for line in d.get("klines") or []:
        parts = line.split(",")
        if len(parts) < 6:
            continue
        out.append(
            {
                "date": parts[0],
                "close": _num(parts[1]),
                "open": _num(parts[2]),
                "high": _num(parts[3]),
                "low": _num(parts[4]),
                "volume": _num(parts[5]),
            }
        )
    return out


def _kline_sina(symbol: str, period: str, limit: int) -> list[dict[str, Any]]:
    """新浪 K 线：返回 day / open / high / low / close / volume 对象数组。"""
    data = get_json(
        _SINA_KLINE_URL,
        params={
            "symbol": symbol,
            "scale": _SINA_KLINE_SCALE[period],
            "ma": "no",
            "datalen": str(limit),
        },
    )
    rows = data if isinstance(data, list) else []
    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        out.append(
            {
                "date": str(r.get("day") or "")[:10],
                "open": _num(r.get("open")),
                "high": _num(r.get("high")),
                "low": _num(r.get("low")),
                "close": _num(r.get("close")),
                "volume": _num(r.get("volume")),
            }
        )
    return out


def _stats(rows: list[dict[str, Any]], period: str) -> dict[str, Any]:
    closes = [r["close"] for r in rows if r.get("close") is not None]
    if len(closes) < 2:
        return {}
    first, last = closes[0], closes[-1]
    rets = [
        (closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes)) if closes[i - 1]
    ]
    out: dict[str, Any] = {
        "start": rows[0]["date"],
        "end": rows[-1]["date"],
        "first_close": first,
        "last_close": last,
        "period_return_pct": round((last - first) / first * 100, 2) if first else None,
        "max_close": max(closes),
        "min_close": min(closes),
    }
    if rets:
        mean = sum(rets) / len(rets)
        var = sum((r - mean) ** 2 for r in rets) / len(rets)
        annualize = {"day": 252, "week": 52, "month": 12}[period]
        out["volatility_annual_pct"] = round((var**0.5) * (annualize**0.5) * 100, 2)
    return out


def stock_history(symbol: str, period: str = "day", limit: int = 60) -> dict[str, Any]:
    """查询历史 K 线（前复权），返回时间序列与区间统计。

    period: day / week / month。limit 为返回条数（上限 500）。
    统计项包含区间涨跌幅、最高最低与年化波动率，用于趋势判断与风险度量。
    """
    key = (period or "day").lower()
    if key not in _EM_KLINE_PERIOD:
        raise ValueError(f"period 只能是 day / week / month，收到：{period}")
    size = max(1, min(int(limit or 60), 500))

    target = _resolve(symbol)
    errors: list[str] = []
    rows: list[dict[str, Any]] = []
    source = ""
    for label, fn, arg in (
        ("腾讯", _kline_tx, (target["symbol"], key, size)),
        ("东方财富", _kline_em, (target["secid"], key, size)),
        ("新浪", _kline_sina, (target["symbol"], key, size)),
    ):
        try:
            rows = fn(*arg)
        except Exception as exc:  # noqa: BLE001 - 单源失败即降级
            errors.append(f"{label}: {type(exc).__name__}")
            continue
        if rows:
            source = label
            break
        errors.append(f"{label}: 返回空数据")

    if not rows:
        raise ValueError(f"所有 K 线数据源均不可用（{symbol}）：" + "；".join(errors))

    return {
        "code": target["code"],
        "name": target["name"],
        "period": key,
        "source": source,
        "count": len(rows),
        "stats": _stats(rows, key),
        "series": rows,
        "note": "前复权价格；波动率为简单收益率的年化标准差，仅作风险参考。",
    }


# ---------- 历史财报 ----------


def financial_history(symbol: str, periods: int = 8) -> dict[str, Any]:
    """查询历史定期报告的主要财务指标。

    返回最近 periods 期，按报告期倒序。金额单位为元，比率字段为百分比数值。
    用于建立盈利趋势、计算增长率，或核对从文档中抽取出的财务数据。
    """
    target = _resolve(symbol)
    data = get_json(
        _EM_FINANCE_URL,
        params={
            "reportName": "RPT_LICO_FN_CPD",
            "columns": ",".join(_FINANCE_FIELDS),
            "filter": f'(SECURITY_CODE="{target["code"]}")',
            "pageSize": str(max(1, min(int(periods or 8), 30))),
            "sortColumns": "REPORTDATE",
            "sortTypes": "-1",
            "source": "WEB",
            "client": "WEB",
        },
    )
    rows = ((data or {}).get("result") or {}).get("data") or []
    if not rows:
        raise ValueError(f"未取到财报数据：{symbol}（可能尚未上市或非 A 股）")

    records = []
    for r in rows:
        item: dict[str, Any] = {}
        for key, label in _FINANCE_FIELDS.items():
            value = r.get(key)
            if isinstance(value, str) and "00:00:00" in value:
                item[label] = value.split(" ")[0]
            elif isinstance(value, (int, float)):
                item[label] = round(float(value), 4)
            else:
                item[label] = value
        records.append(item)

    return {
        "code": target["code"],
        "name": str(records[0].get("证券简称") or target["name"]),
        "count": len(records),
        "records": records,
        "note": "金额单位为元，比率字段为百分比数值；数据来自上市公司定期报告。",
    }


registry_tools = [
    {
        "name": "stock_quote",
        "description": (
            "查询 A 股实时行情：最新价、涨跌幅、总市值、市盈率 TTM、市净率、"
            "换手率与成交额。估值建模与市值核对时先用它取当前价格与股本，"
            "不要凭记忆猜测股价。参数支持 6 位代码或公司简称。"
        ),
        "input_schema": {"symbol": "股票代码或公司简称，如 600519 / 贵州茅台"},
        "handler": stock_quote,
    },
    {
        "name": "stock_history",
        "description": (
            "查询 A 股历史 K 线（日 / 周 / 月，前复权），返回收盘价序列与"
            "区间统计：区间涨跌幅、最高最低、年化波动率。用于判断价格趋势、"
            "估算波动率与计算历史估值区间。"
        ),
        "input_schema": {
            "symbol": "股票代码或公司简称",
            "period": "day / week / month，默认 day",
            "limit": "返回条数，默认 60，上限 500",
        },
        "handler": stock_history,
    },
    {
        "name": "financial_history",
        "description": (
            "查询 A 股历史定期报告的主要财务指标：营业收入、归母净利润、"
            "每股收益、加权 ROE、销售毛利率、每股经营现金流、营收与净利同比。"
            "用于建立盈利趋势、计算增长率，或核对文档抽取出的财务数据。"
        ),
        "input_schema": {
            "symbol": "股票代码或公司简称",
            "periods": "返回期数，默认 8，上限 30",
        },
        "handler": financial_history,
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
                tags=["market", "data"],
            )
        )


register()
