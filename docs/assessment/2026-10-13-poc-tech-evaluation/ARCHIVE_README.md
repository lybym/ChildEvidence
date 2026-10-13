# POC 技术评估归档（2026-10-13）

本目录是 **ChildEvidence 三项开源技术 POC 的独立技术评估归档**（用户判定：工程执行可验收、
数据保护通过、技术路线方向明确；评测有效性修正已完成）。POC 结论仅作决策依据，
不构成本仓库的生产代码，不随本仓库运行。

## 内容

- `UPSTREAM_AUDIT.md` — 五个上游项目（ASReview 3.0.8 / Docling 2.138.0 / GROBID 0.9.1 /
  PaperQA2 2026.8.12 / SciFact @68b98a5）的版本、SHA、许可证与源码级审查。
- `EXPERIMENT_PROTOCOL.md` — 统一实验协议（含 CE-01 指标口径 v2 修订）。
- `FINAL_RECOMMENDATION.md` — 技术选型（含 §9 决策修订 v1.1：Docling ADOPT（受控）、
  ASReview PILOT（禁止自动终局拒收）、GROBID DEFER、PaperQA2 REFERENCE、
  SciFact ADOPT Benchmark）。
- `reports/` — POC-A（ASReview 筛选）、POC-B（PDF 解析对比）、POC-C（证据检索与主张验证）。
- `results/` — 原始指标与记录；`asreview-ranking.jsonl` 是 25 次模拟运行的完整筛选顺序，
  全部指标可由它重算并通过一致性测试（`asreview-consistency-tests.json`，25/25）。
- `figures/` — Recall 曲线与解析器对比图。
- `datasets/` — 样本清单与标注包（`asreview-human-review-queue-blinded.csv` 为 CE-02
  盲法标注视图；`asreview-human-review-queue.csv` 含抽样层与历史标签键，仅供解盲审计）。

## 有意排除（不在归档中）

- `library.sqlite` 快照与任何数据库数据（遵守 AGENTS #8）；
- PDF 原件副本（保留在本地 POC 工作区 `C:\CODE\ChildEvidence-POC\datasets\pdf-sample\`）；
- 上游克隆、虚拟环境、模型缓存、解析全文输出（体积与版权原因）。

## 与本仓库的关系

1. WSS@95 等 ASReview 指标的 v2 口径（0.95 − B95/N）与"指标必须可从原始记录重算"
   已纳入 `RESEARCH_METHODOLOGY.md`（M9）与 AGENTS #21；
2. ASReview 使用边界（只排序、禁自动拒收）已纳入 `SCREENING_PROTOCOL.md` §6 与 AGENTS #17；
3. Docling 解析工程（v0.2 CE-03）与 Evidence/Claim 模型（v0.3 CE-05）按
   FINAL_RECOMMENDATION §9.5 关键路径独立立项。
