---
name: earnings_quality
description: 盈利质量深度核查：利润与现金流匹配、应收存货异常、一次性损益、应计项目方向，输出「利润含金量」判断。
tags:
  - quality
  - earnings
  - cashflow
tools:
  - extract_fields
  - compute_metrics
  - financial_ratio_suite
  - yoy_compare
  - locate_evidence
  - python_calc
---

# 盈利质量技能

## 核心问题

报表利润是否「真金白银」？重点看：

1. **利润与经营现金流匹配**：`ocf_to_net_profit`、`profit_cash_gap`
2. **应收与存货**：增速是否显著快于收入
3. **一次性损益**：扣非前后差异、政府补助、资产处置
4. **应计方向**：长期 OCF < 净利润 需警惕

## 工作流程

1. `extract_fields` → `financial_ratio_suite`
2. 有上期数据时 `yoy_compare` 看恶化/改善方向
3. 对异常数字 `locate_evidence` 回原文
4. 给出结论等级：**高 / 中 / 低**，并写清触发该等级的指标阈值

## 判定参考（可按行业微调，但须写明）

| 信号 | 含义 |
| --- | --- |
| OCF/净利润 < 0.5 持续 2 期 | 含金量偏低 |
| 应收增速 > 收入增速 20pct+ | 回款压力 |
| 扣非净利远低于归母 | 利润依赖非经常项目 |

## 红线

- 不得用「看起来不错」代替数字
- 等级判断必须列出所依据的指标与数值
