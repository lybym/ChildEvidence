# ANNOTATION_GUIDE.md — 人工标注标准与分歧处理

> 状态：**DRAFT v1.1（CE-01R）** — 2026-10-13 依据跨文件一致性审计修订（逐条意见见
> [docs/governance/CE-01R-REVIEW.md](docs/governance/CE-01R-REVIEW.md)）。
> **仍待人工审核，未生效**：Agent 不得将本文件当作生效准则执行（见 AGENTS.md 科研治理节）；
> 人工批准以 [docs/governance/CE-01R-CHECKLIST.md](docs/governance/CE-01R-CHECKLIST.md) 为准。
> 上位文件：RESEARCH_METHODOLOGY.md；直接服务对象：CE-02（A2 80 项复核）及后续标注任务。

## 1. 适用范围与标注物

- CE-02：`datasets/asreview-human-review-queue-blinded.csv`（A2，80 项，含 54 项历史拒收）。
- 后续：任何进入证据评价的人工判定任务。

标注物为"文献判定"，输入是**标题 + 摘要**（必要时全文），输出是结构化决策记录。

**双轨判定语义（v1.1，RESEARCH_METHODOLOGY §5）**：

- A2 复核历史拒收属**轨道 A（catalog 层）**：判定"该文献是否值得馆藏"，
  decision 用 §3 的 `relevant / boundary / not_relevant / undecided`，回写后对应
  catalog 值域（ingested/rejected/pending），**不是**任何 RQ 的 included/excluded；
- 轨道 B 的 RQ 级判定：判定"该文献对该 RQ 的证据资格"，decision 记录必须携带
  `rq_id` + RQ 版本，回写后对应 review 值域（included/excluded/pending）；
- 两类判定不得混填同一记录字段（契约：
  [docs/governance/contracts/CE-01R-decision-scope.contract.json](docs/governance/contracts/CE-01R-decision-scope.contract.json)）。

## 2. 盲法要求（降低锚定偏差）

1. 标注使用**盲法版** `asreview-human-review-queue-blinded.csv`：不含
   `historical_label`（原 record_status）、不含抽样层（stratum）、不含任何模型排名。
2. 标注环境不得显示 ASReview/其他模型的排序位置或评分。
3. 解盲只发生在**复核/审计阶段**：先完成标注并固定，再与历史标签对照做偏差分析
   （错误审计）；顺序不可颠倒。
4. 抽样层信息（stratum）保存在带键版本中，仅用于事后分层统计，不进入标注视图。

## 3. 标注任务定义

每项输出：

| 字段 | 取值 |
|---|---|
| decision | `relevant` / `boundary` / `not_relevant` / `undecided` |
| reason_code | 见 §5 代码表（与 SCREENING_PROTOCOL §4 对齐） |
| reason_text | 一句话理由（必填） |
| confidence | high / medium / low |
| track | `catalog`（轨道 A）/ `review`（轨道 B；另附 `rq_id` + RQ 版本） |
| label_tier | 按 §8 判定本记录的标签层级（proxy/silver/provisional/gold） |
| reviewer_id / reviewed_at | 审计字段 |
| notes | 可选（争议点、待补信息） |

`undecided` 是合法状态：证据不足或确实无法判断时**不得强判**。

## 4. 判定标准

- 以 RESEARCH_METHODOLOGY §5（双轨）与 SCREENING_PROTOCOL §3–§4（I/E 标准）为唯一依据；
- **三级判定分离（v1.1）**：先判相关性（是否离题），再判全文资格（是否可评）；
  研究方法质量属 appraisal（L6），**不进入本任务 decision**——方法差不是排除理由，
  也不得写成 R 系列代码；方法学疑虑写入 notes 供 L6 参考；
- `boundary` 的定义：主题相关但存在明确限制（人群不符但有概念迁移价值、研究设计
  特殊、适用边界不清等），需要在理由中写明限制内容；
- 判定只针对"该文献对 ChildEvidence 研究范围（或该 RQ）的价值"，不评价其学术声望。

## 5. 理由代码表

- 纳入：A01 实证研究、A02 理论/综述、A03 实践指南；
- 排除：R01 主题不符、R02 人群不符、R03 无可检验内容、R04 重复、R05 来源不可信、
  R06 标识不可核验且关键内容缺失（先穷尽 ISBN/报告编号/馆藏记录渠道，SCREENING_PROTOCOL §4）；
- 边界：B01 人群边界、B02 设计边界、B03 适用范围边界；
- 其他：P01 待定、U01 无法判断。
- **无"方法质量低"代码**：该维度属 appraisal，不属于筛选排除。

## 6. 特殊类别的保护条款（POC-A 实测风险）

可操作定义见 SCREENING_PROTOCOL §6.4（中文条目/经典理论/负面结果/争议研究）。

1. **经典理论文献**：出版年代不得作为排除或降级理由（实测老文献被排序器沉底）。
2. **中文研究**：语言不得作为质量理由（实测中文正例被排序器系统性压后）。
3. **负面/无显著结果研究**：不得因结果方向不利而排除。
4. **争议研究**：记录争议点；可标 `undecided`，不得静默丢弃。

## 7. 分歧处理流程

1. 双人独立盲标（同一盲法数据）→ 比对；
2. 分歧条目进入**分歧登记表**（条目 id、双方决策与理由）；
3. 裁决方式：第三人独立标注，或双人协商后由知识负责人确认；裁决记录必须保留
   双方原始意见（不覆盖）；
4. 无法达成一致的条目保留 `undecided` 并进入待定池（P01）；
5. 暂无双人的情况（CE-02 起点）：**单人标注 + 事后抽样复核 + 全程记录审核者身份与
   方法**；必须在标注包 README 中声明"单人标注，未经第二人独立验证"；此类标签
   层级封顶 `provisional`（§8、RESEARCH_METHODOLOGY §7）。

## 8. 标签层级与 Gold 资格（v1.1 新增）

四级标签（proxy / silver / provisional / gold）的定义、来源与资格边界以
RESEARCH_METHODOLOGY §7 为准；机器可校验契约：
[docs/governance/contracts/CE-01R-label-tiers.contract.json](docs/governance/contracts/CE-01R-label-tiers.contract.json)。

标注执行规则：

1. 每条人工决策默认 `label_tier=provisional`；达到 Gold 资格流程（独立复核一致或
   裁决完成 + 知识负责人签署）后才可标 `gold` 并记录签署人/日期；
2. 模型辅助（预填要点、排序建议）产出只能标 `silver`（`ai_assisted=true` + 模型版本），
   人工采纳时**重标为人工 provisional/gold**，silver 本身不得转正；
3. **禁止模型生成并自我确认 Gold Label**；多模型一致投票不等同专家共识；
4. 无法独立复核时（单人标注），封顶 provisional 并显式声明（§7.5），不得支撑知识包
   发布门禁（KNOWLEDGE_GOVERNANCE §4）；
5. 历史标签一律 `proxy`：A2 复核对象的历史 `record_status` 仅作对照，不得自动转成
   任何人工层级。

## 9. 审计与数据安全

1. 标注记录只追加、可追溯（reviewer、时间、理由、track、label_tier），
   与 `ingestion_notes` 体系一致；
2. PDF/摘要不出本地；不得提交给外部模型（AGENTS #6、POC 网络边界）；
3. 模型辅助必须标记 `ai_assisted=true` 且不改变 decision 的最终人工属性。

## 10. 统计与外推限制

- A2 为富集样本（刻意包含 54 项历史拒收），适合**错误审计**；
- 估计全库 393 项的误拒率必须按抽样层加权校正，并报告不确定区间；
- 不得用 A2 直接宣称"历史误拒率 = X%"。

## 11. 变更记录

| 版本 | 日期 | 说明 |
|---|---|---|
| DRAFT v1.0 | 2026-10-13 | Codex 起草（CE-01）；待人工审核确认 |
| DRAFT v1.1 | 2026-10-13 | CE-01R 一致性审计修订：双轨判定语义与 track 字段、三级判定分离（方法质量不进筛选）、标签层级与 Gold 资格流程、单人标注封顶 provisional、保护层可操作定义引用；**仍待人工审核，未生效** |
