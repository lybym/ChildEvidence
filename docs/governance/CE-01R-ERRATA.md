# CE-01R-ERRATA.md — POC 评估指标权威更正索引

> 性质：**权威更正索引（Errata Index）**。它不修改任何原始记录——原始数据与
> v1 报告文本全部保留；本索引只声明"哪些数字已作废、以什么为最新值"。
> 机器可读指针：[contracts/CE-01R-poc-metrics-latest.json](contracts/CE-01R-poc-metrics-latest.json)
> （由 `tests/test_governance_contracts.py` 与 `results/` 原始 CSV 逐值校验）。
> 适用对象：`docs/assessment/2026-10-13-poc-tech-evaluation/` 全部材料及其引用。

## E1 WSS@95 口径更正（supersedes v1）

- **作废（superseded）**：FINAL_RECOMMENDATION §8.3 表格的 WSS@95
  （svm 0.118 / nb 0.152 / logistic 0.146 / tfidf_sim 0.075 / random 0.067）为
  **v1 未调整口径**（现更名 `wss@95_unadjusted`，仅留痕，不再用于任何结论）。
- **现行口径（v2）**：`WSS@95 = 0.95 − B95/N`，从原始排序重算。
  最新值（`results/asreview-metrics-v2-summary.csv`，5 种子均值）：
  svm 0.068 / nb 0.102 / logistic 0.096 / tfidf_sim 0.025 / random 0.017。
- **禁止用法**：不得把 §8.3 v1 数字写入新文档、结论或代码注释；不得把任一口径的
  WSS@95 当作"真实可停止性"证据（SCREENING_PROTOCOL v1.1 §6.2）。

## E2 Missed@50 口径更正（supersedes v1）

- **作废（superseded）**：FINAL_RECOMMENDATION §8.3 的"bottom-50% 漏筛（去重）
  59 / 68 / 71 / 127 / 136"是 v1 跨种子并集数字，方法学上混淆了 run 与种子，
  已作废（§9.4 同此结论）。
- **现行口径（v2）**：逐 run `missed_at_50` 的跨种子均值。
  最新值：svm 42.6 / nb 47.2 / logistic 45.2 / tfidf_sim 61.0 / random 72.4
  （±std 见 CSV 与机器指针文件）。
- **禁止用法**：不得引用 59–136 区间作为当前结论。

## E3 运行次数澄清（无数字变更）

"25 runs" = 20 次 ASReview Simulate（含官方 Random querier）+ 5 次自建 tfidf_sim。
`results/asreview-runs.json` 为准。

## E4 原始记录保留声明

1. `FINAL_RECOMMENDATION.md` §8.3 的 v1 数字**保留原文不改写**；其效力仅由本索引
   与 §9.4 修订记录覆盖（文件顶部已加勘误指针）。
2. `results/asreview-metrics.csv`（v1）保留；`results/asreview-metrics-v2.csv|jsonl`
   与 `asreview-metrics-v2-summary.csv` 为现行重算记录。
3. 一致性测试 `results/asreview-consistency-tests.json`（25/25 通过）与回归测试
   （test_16 固化）继续有效；重算可从 `results/asreview-ranking.jsonl` 复现。
4. 任何自动消费者**必须**以
   `docs/governance/contracts/CE-01R-poc-metrics-latest.json` 为最新指标入口；
   该 JSON 声明 `supersedes` 关系，并包含每项指标指向的原始记录路径。

## E5 与规程的联动

- RESEARCH_METHODOLOGY M9（可复现）：历史指标修正以本索引为权威指针。
- SCREENING_PROTOCOL §6.2：模拟口径 WSS@95（含 v2）不构成筛选停止证明。
- AGENTS.md #21：宣称 95% 召回前必须完成独立评估与人工批准。
