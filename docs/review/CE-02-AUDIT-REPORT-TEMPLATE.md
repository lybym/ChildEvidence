# CE-02 解盲审计报告模板（人工阶段填充）

> 本模板是 `review audit` 输出 `audit-report.md` 的 tracked 模板；
> 真实审计结果默认生成于 `data/review/audit/`（gitignored），是否收录 Git 须
> 按许可与隐私审查另行决定（AGENTS #8）。
> 规程依据为 **DRAFT v1.1**（ANNOTATION_GUIDE §2/§9–§10、SCREENING_PROTOCOL §6、
> RESEARCH_METHODOLOGY §7），未经人工批准前仅作流程载体，不作生效准则（AGENTS #23）。

## 报告头（工具自动生成部分）

- 生成时间、样本（A2 80 项，54 项历史拒收）、人工标签层级声明
  （单人标注封顶 provisional，"单人标注，未经第二人独立验证"）。

## 1. 总体对照（历史 proxy vs 人工 provisional）

| 关系 | 定义 | 计数 |
|---|---|---|
| consistent | 人工与历史同向（relevant↔ingested 或 not_relevant↔rejected） | 由工具统计 |
| inconsistent | 人工与历史异向（**原决策保留，仅登记**） | 由工具统计 |
| human_undecided_or_boundary | 人工 undecided/boundary | 由工具统计 |

不一致条目清单：逐条列出 queue_id、双方决策与理由（含 reviewer），作为人工
复核/回写讨论的输入。**禁止**根据本表自动翻转任何主库记录。

## 2. 保护层近似分层（SCREENING_PROTOCOL §6.4 的机械近似）

| 层 | 近似规则（工具口径） | 一致 | 不一致 | undecided/boundary |
|---|---|---|---|---|
| chinese | language/stratum 含 zh | | | |
| classic_pre2000 | 出版年 ≤ 2000 | | | |
| negative_result | 标题/摘要命中负面结果关键词 | | | |
| general | 其余 | | | |

> 声明：该分层是可操作定义的**机械近似**（如"经典理论"的原典属性、"争议研究"
> 无法由关键词判定），供人工修正与重点复核排序。

## 3. 统计外推边界（默认：不得外推）

- A2 为富集样本（54/80 历史拒收），本报告只描述 A2 样本本身；
- 如需推断全库 393 项误拒率，必须在此由**人工**补充：抽样概率（各 stratum 入样率）、
  分层加权方法、置信区间与假设；
- 未提供上述内容时，报告维持"仅 A2 样本结果，不外推总体"。

> 外推说明（人工填写）：＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿

## 4. ASReview proxy 性能补充分析边界

- 本工具不训练、不回训任何模型；
- 基于历史 proxy 的性能指标（召回/WSS 等）只能作为排序效率指标（CE-01R-ERRATA
  口径），不构成筛选停止性证明；
- 任何性能补充分析须**单独报告人工 Gold 子样本**；禁止用人工复核数据回训模型后
  再在同批条目上报告无偏性能。

## 5. 后续人工动作

- [ ] 不一致条目逐条人工复议（可发起第二轮独立标注或裁决）；
- [ ] undecided 条目全文补读或保持 P01/U01；
- [ ] 满足 Gold 资格的条目走 `record-signoff`（签署文件留档）；
- [ ] 人工按 CATALOG_MAPPING 决定主库回写（另行变更流程，本工具不写主库）。
