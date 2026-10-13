# CE-02 标注计划 — A2 80 篇盲法人工复核、历史误拒审计与审核流水线

> Issue：[#2](https://github.com/lybym/ChildEvidence/issues/2)（[CE-02][P0]）
> 状态：**HUMAN_REVIEW_PENDING** —— 本计划与工具是 AI 交付的**离线载体**；
> 实际 80 项人工判定、独立复核、锁定、解盲审计、签署均属**人工阶段**，
> 当前**无一完成**，完成前 Issue 不得因本 PR 关闭为"已标注"。
> 依据规程（**DRAFT v1.1，未经人工批准不生效**，AGENTS #23）：
> `ANNOTATION_GUIDE.md`、`SCREENING_PROTOCOL.md`、`RESEARCH_METHODOLOGY.md`、
> `KNOWLEDGE_GOVERNANCE.md`。规程批准凭据：`docs/governance/CE-01R-CHECKLIST.md` 人工签署。

## 1. 审核目标与判定范围（轨道 A / catalog 层）

- **任务**：对 A2 富集样本 80 篇（54 项历史拒收 + 26 项历史收录）逐篇判定
  "该文献是否值得 ChildEvidence 馆藏"（轨道 A catalog 层，无 RQ 绑定）。
- **不是**：研究质量评分（appraisal 属 L6，不进入本判定）；不是任何 RQ 的
  included/excluded（轨道 B）——两类判定不得混填（decision-scope 契约）。
- **判定值域**（标注阶段语义，ANNOTATION_GUIDE §3）：
  `relevant` / `boundary` / `not_relevant` / `undecided`；
- **回写映射**（工具只提供映射，不执行主库写入）：
  | 标注 decision | catalog 值域 | 说明 |
  |---|---|---|
  | relevant | ingested | 仅人工阶段回写 |
  | not_relevant | rejected | 仅人工阶段回写 |
  | boundary | **pending** | 保守映射，人工决定 |
  | undecided | **pending** | 合法长期状态（P01/U01） |
- **inclusion/exclusion 依据**：`SCREENING_PROTOCOL.md` §3（I1–I5）与 §4（E1–E6，
  理由代码 R01–R06）；纳入理由 A01（实证）/A02（理论/综述）/A03（实践指南）；
  边界理由 B01–B03；待定 P01、无法判断 U01。**无"方法质量低"代码**——
  方法学疑虑写入 notes 供 L6 参考。
- **缺 DOI/摘要**：允许 `undecided`（U01/P01），不得强判。

## 2. 盲法规则（不可颠倒的顺序）

1. 标注只使用盲法版 `docs/assessment/2026-10-13-poc-tech-evaluation/datasets/
   asreview-human-review-queue-blinded.csv`（80 条，无 historical_label / stratum /
   模型得分与排名）；
2. 工具侧保证（`research_library.annotation`，本 PR 实现）：
   - 导入按**白名单列**提取，标注库中不存在泄漏字段；
   - 输入 CSV 若携带 `historical_label` / `stratum` / 模型排序列或预填判定
     （gold_label/reviewer/...）且非空 → **fail-closed 拒绝导入**；
3. 带键解盲表（`asreview-human-review-queue.csv`）**仅**在全部人工标签锁定后
   由 `review audit` 读取（工具校验锁定前置），只读 join，不写回、不覆盖；
4. 解盲顺序：标注固定（lock）→ 解盲审计。任何在锁定前试图访问历史标签的
   路径都会被 `NotLockedError` 拒绝。

## 3. 工具使用说明（本地离线，零第三方依赖）

存储为**独立标注库** `<data-dir>/review/annotations.sqlite`
（默认 `data/review/annotations.sqlite`，已被 `.gitignore` 的 `data/` 覆盖）；
与主事实源 `library.sqlite` 无任何读写关联。

```powershell
$env:PYTHONPATH = "src"

# 1) 只读导入盲法队列（幂等；同库禁止混入不同队列）
python -m research_library review import --csv docs/assessment/2026-10-13-poc-tech-evaluation/datasets/asreview-human-review-queue-blinded.csv

# 2) 逐条人工判定（reviewer_id 必填；理由必填；undecided 合法）
python -m research_library review next
python -m research_library review judge a2-001 --reviewer "<审核者ID>" --decision relevant --reason-code A01 --reason-text "儿童执行功能元分析，符合馆藏范围" --confidence high

# 3) 暂停 / 恢复 / 进度 / 未决队列
python -m research_library review pause --note "周三继续"
python -m research_library review resume
python -m research_library review progress
python -m research_library review pending

# 4) 修改留痕（追加 amendment 事件，原始判定保留）
python -m research_library review judge a2-001 --reviewer "<审核者ID>" --decision not_relevant --reason-code R01 --reason-text "修正理由" --amend

# 5) 第二审核人独立盲标 → 分歧登记（保留双方原始意见）
python -m research_library review judge a2-001 --reviewer "<第二审核者ID>" --decision relevant --reason-code A02 --reason-text "独立二审"
python -m research_library review compare          # 一致→independent_double_human 流；不一致→登记
python -m research_library review disagreements
# 第三人裁决（仅限已登记分歧；tier 仍 provisional）
python -m research_library review record-adjudication a2-001 --adjudicator "<裁决人ID>" --decision boundary --reason-code B01 --reason-text "裁决理由"

# 6) 全部 80 条提交后：人工锁定 → 解盲审计（锁定是审计的硬前置）
python -m research_library review lock --confirmed-by "<负责人ID>"
python -m research_library review audit --keyed-csv docs/assessment/2026-10-13-poc-tech-evaluation/datasets/asreview-human-review-queue.csv --outdir data/review/audit

# 7) 导出（provisional 快照 + 追加式事件流；不含任何历史标签/分层/排名）
python -m research_library review export --outdir data/review/export

# 8) Gold 签署（唯一人工 Gold 通道；须独立复核一致或裁决完成 + 真实签署文件）
python -m research_library review record-signoff a2-001 --sign-off-by "<知识负责人ID>" --sign-off-date 2026-10-13 --evidence-file docs/governance/CE-01R-CHECKLIST.md
```

## 4. 标注 schema / 契约（独立标注库，schema_version=1）

- `queue_items`：盲法白名单字段（queue_id, sample_id, doi, title, abstract,
  language, publication_year, review_task）+ 导入审计（imported_at, source_csv,
  source_sha256）。**无 historical_label / stratum / 排名列**。
- `annotation_events`：**追加式事件流**（judgement / amendment / adjudication /
  signoff / lock），数据库触发器拒绝 UPDATE/DELETE（审计不可覆写，AGENTS #2）；
  修改经 amendment 留痕并引用被修正事件（payload）。
- `review_state`：每条目当前状态（pending/submitted/locked），可由事件流重建；
  **锁定后 judge/amend/adjudication 一律拒绝**（标签固定是解盲审计的前提，
  裁决与修正必须在锁定前完成；签署在锁定后允许）。
- `disagreements`：分歧登记（双方 decision/reason 保留），裁决经
  `resolution` 字段登记，原始意见不覆盖。
- `session_state`：暂停/恢复断点。
- 标签层级字段：`label_tier ∈ {proxy, silver, provisional, gold}`、
  `produced_by_kind`、`ai_assisted` —— 语义与校验规则
  `docs/governance/contracts/CE-01R-label-tiers.contract.json`（LT-01…LT-04）一致；
  **脚本录入恒为 provisional/single_human**；gold 只能经 `record-signoff`
  （要求 independent_double_human / adjudicated_human + 真实签署文件）产生，
  **不存在其他升 Gold 代码路径**；历史标签一律 proxy，永不自动转层级。
- 迁移：`migrate_store()` 幂等（schema_version 门禁：更新版本拒绝未知旧库，
  已含事件库不重置版本）；本 PR **不修改主库 schema**，无 library.sqlite 迁移。

## 5. 80 项人工审核指引与进度清单（人工阶段执行）

> 以下清单为人工执行的载体模板；`review progress` 提供实时计数。
> AI 不代填、不声称完成（HUMAN_REVIEW_PENDING）。

| 阶段 | 动作 | 责任人 | 完成 |
|---|---|---|---|
| 0 准备 | 人工批准/豁免 DRAFT v1.1 规程（CE-01R-CHECKLIST 签署） | 知识负责人 | ☐ |
| 1 盲标 | 80/80 判定 + 理由码 + 理由 + 置信度（reviewer_id 留痕） | 授权审核者 | ☐ 0/80 |
| 1a 未决 | undecided 条目全文补读或保持 P01/U01 | 授权审核者 | ☐ |
| 2 复核 | 第二审核人独立盲标（或声明单人模式，封顶 provisional） | 第二审核者 | ☐ |
| 3 分歧 | 分歧登记 → 第三人裁决 / 负责人确认 | 裁决人 | ☐ |
| 4 锁定 | `review lock --confirmed-by` | 知识负责人 | ☐ |
| 5 解盲 | `review audit`（只读 join 带键表） | 知识负责人 | ☐ |
| 6 签署 | Gold 条目 `record-signoff`（凭据文件留档） | 知识负责人 | ☐ |
| 7 回写 | 人工按 CATALOG_MAPPING 回写主库（另行变更流程） | 知识负责人 | ☐ |

判定提示（SCREENING_PROTOCOL §6.4 保护条款，DRAFT v1.1）：出版年代不得作为
排除理由（经典理论）；语言不得作为质量理由（中文研究）；负面/无显著结果不得
因方向不利排除；争议研究记录争议点，可标 undecided，不得静默丢弃。

## 6. 解盲审计与统计边界

- **审计输出**：`audit-results.jsonl`（逐条：stratum_keyed、protective_layer_proxy、
  historical_label、human_decision、relation、tier、reviewer）+
  `audit-report.md`（模板见 [CE-02-AUDIT-REPORT-TEMPLATE.md](CE-02-AUDIT-REPORT-TEMPLATE.md)）。
- **分层**：审计报告按保护层**机械近似**分组（language=zh / 出版年≤2000 /
  负面结果关键词），报告中声明为近似，人工可修正。
- **历史标签仅 proxy**：对照结果不覆盖原决策、不自动改判、不自动升层级。
- **外推**：A2 为富集样本（54/80 历史拒收），仅报告 A2 样本结果；估计全库
  393 项误拒率必须由人工提供抽样概率、分层加权方法与置信区间
  （`--extrapolation-note`），否则报告维持"不得外推总体"。
- **ASReview proxy 性能**：本工具不训练/不回训任何模型；任何基于历史 proxy 的
  性能补充分析必须单独报告人工 Gold 子样本，**禁止**用人工复核数据回训模型后
  再在同批条目上报告无偏性能。

## 7. 隐私与 Git 收录决策

- 标注库与导出/审计输出默认位于 `data/`（gitignored）：**真实标注数据默认不
  收录 Git**（AGENTS #8；含 reviewer_id 与判定记录）。
- 收录 Git 的仅限：本计划、审计报告**模板**、代码与测试。若未来人工决定收录
  真实标注数据，须先做隐私审查（reviewer_id 处理、许可确认）并另行评审。
- 科研原文（PDF）不出本地、不提交外部模型（AGENTS #6/#14）。

## 8. 回归测试覆盖（tests/test_annotation_review.py，30 项）

| Issue #2 要求 | 测试 |
|---|---|
| blind 泄漏检测 | historical_label/stratum/预填 gold_label 导入拒绝；store 无泄漏列；next() 不暴露 |
| 审计不可覆写 | annotation_events UPDATE/DELETE 触发器拒绝 |
| 人工权限门禁 | 单人标注拒绝签署；签署须证据文件；分歧未决拒绝签署；无脚本升 Gold 路径 |
| pending/undecided | undecided 合法并入未决队列 |
| 重复标注 | 重复提交拒绝；--amend 追加且原始保留 |
| 解盲前不可访问历史标签 | 部分/全部未锁定 audit 拒绝；锁定是硬前置 |
| 数据无损 | 真实 A2 CSV 80 条导入/导出 round-trip；主库零接触 |
| 迁移保障 | migrate_store 幂等；未来版本拒绝；有事件库不重置版本 |

全量门禁：`python -m unittest discover -s tests`（≥100 项）+
`python scripts\smoke_offline.py`（主库路径不受影响）。
