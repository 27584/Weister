---
name: peer_benchmark
description: 可比公司对标：选择 2~4 家同业，用 peer_comparison 生成指标对比表，并解释估值与经营差异。
tags:
  - peer
  - valuation
  - compare
tools:
  - peer_comparison
  - financial_ratio_suite
  - yoy_compare
  - web_search
  - python_calc
---

# 同业对标技能

## 适用场景

- 需要「和同行比贵不贵 / 经营好不好」时
- 相对估值需要可比 PE/PS 时
- 用户点名「对比茅台和五粮液」时

## 工作流程

1. **选样**：同行业 2~4 家，优先业务可比、体量接近；在结论中说明选样理由。
2. **统一口径**：同一报告期；利润用归母口径；写明单位与币种。
3. **生成表**：调用 `peer_comparison`，不要手写数字。
4. **解读差异**：至少覆盖盈利质量（净利率/现金流匹配）、杠杆、成长（yoy）。

## 输出结构

1. 选样说明（为何这几家）
2. 对比表（工具生成的 markdown_table）
3. 2~3 条关键差异结论（带指标）
4. 对估值的含义（相对高估/低估的依据，禁止只给结论不给数）

## 红线

- 未取到的数据保持空，不编造对标数字
- 美股/港股同业在 A 股行情工具不可用时，改用 `web_search` 并标注来源
