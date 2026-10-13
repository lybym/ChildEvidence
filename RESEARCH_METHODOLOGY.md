# RESEARCH_METHODOLOGY.md — ChildEvidence 科研方法论

> 状态：**DRAFT v1.0（CE-01）** — 由 Codex 起草于 2026-10-13，依据 POC 实测证据与用户复核意见；
> **须经人工审核确认后方可生效**。生效前，本文件与《SCREENING_PROTOCOL》《ANNOTATION_GUIDE》
> 《KNOWLEDGE_GOVERNANCE》共同构成本项目的科研规程草案。
> 依据：POC 技术评估（docs/assessment/2026-10-13-poc-tech-evaluation/）与 UPSTREAM_AUDIT。

## 1. 目的与适用范围

本文件定义 ChildEvidence 生产、维护与使用科研证据的方法学框架。适用于：

- 研究问题的提出与管理；
- 文献的检索、筛选、纳入与排除；
- 证据的提取、评价、综合与审核；
- 科研结论向知识包与 Agent 能力的转化（另见 KNOWLEDGE_GOVERNANCE.md）。

本文件不规定具体代码实现；实现层约束见 AGENTS.md。

## 2. 三层决策分离原则（不可自动连通）

| 决策层 | 内容 | 决策者 | 可自动化程度 |
|---|---|---|---|
| ① 科研决策 | 是否接受/修订某项研究结论；证据与主张的关系 | 领域审核人 | 检索/排序可自动化；**判定不可** |
| ② 知识工程决策 | 是否修改专业知识条目与实践指南 | 知识负责人（人） | 草稿可生成；**生效需人批** |
| ③ 产品决策 | 是否允许 Agent 调整人格、策略与交互行为 | 产品负责人（人） | **完全人工** |

规则：

1. 三层之间只允许"带审计的提案流"，不允许自动连动。
2. 一项新研究足以更新知识库（①→②），未必足以修改教育策略（②），**永远不足以**
   直接改变核心人格原则（③）。
3. 每次跨层提案必须记录：触发证据（Evidence Card id）、提案理由、批准人、生效版本。

## 3. 科研生命周期

```text
L1 研究问题注册（Research Question Registry）
L2 检索与发现（官方公开 API；SCREENING_PROTOCOL §2）
L3 筛选与纳入/排除（SCREENING_PROTOCOL §3–§5；人工决策）
L4 入库与元数据核验（SQLite 唯一事实源；verify 流程）
L5 全文解析与证据定位（v0.2 Docling Adapter；输出必须可回溯 PDF 页）
L6 证据评价与综合（关系判定 + 质量评价分离；v0.3）
L7 人工审核（ANNOTATION_GUIDE；Evidence Card pending → approved）
L8 知识发布（版本化知识包；KNOWLEDGE_GOVERNANCE）
L9 持续验证（新证据/撤稿/方法学变更触发再评价）
```

各阶段门槛：L3 未决条目不得进入 L6；L7 未 approved 的证据卡不得进入 L8；
L8 发布必须带 manifest 哈希与版本号，可回滚。

## 4. 方法学原则（M1–M10）

- **M1 唯一事实源**：`data/research-library/library.sqlite`；Markdown/exports 为派生物。
- **M2 字段级溯源**：DOI、作者、摘要等必须来自官方 API 响应（`raw_sources` 留存摘录）。
- **M3 不虚构**：未核实的字段保持 NULL 并注明"待读全文"；缺失摘要不得生成。
- **M4 预印本 ≠ 正式发表**：独立标记，不混合引用层级。
- **M5 引用量只用于发现排序，不得作为证据等级**。
- **M6 历史决策是代理标签**：v0.1 的 `record_status`（ingested/rejected）是流水线历史
  决策，仅作代理（historical silver proxy）；Gold Label 只能来自按本规程执行的人工标注。
- **M7 AI 产出必须标注**：AI 参与的提取/排序/草稿必须记录模型与版本；**AI 不得生成并
  自我确认 Gold Label**；多模型一致投票不等同专家共识。
- **M8 关系与质量分离**："研究 X 的发现与主张 S 相符"（关系判定）与"研究 X 方法可靠"
  （质量评价/appraisal）是两个独立判断，不得互相推导。
- **M9 可复现**：影响结论的实验必须固定上游版本、依赖、种子与配置，原始记录可重算
  （POC CE-01 的 ranking→metrics 重算与一致性测试是范例）。
- **M10 规程自身版本化**：修改本文件体系需人工批准并记录变更。

## 5. 研究问题管理（RQ Registry）

研究问题注册表（建议落库表 `research_questions`，v0.1.1 后续迁移，遵循 AGENTS #11）：

| 字段 | 说明 |
|---|---|
| rq_id | 稳定 ID（`rq-` 前缀） |
| question | 研究问题文本 |
| background | 为什么问这个问题（业务/理论动机） |
| inclusion_hints | 与该 RQ 相关的纳入要点（主题词、人群、年龄段） |
| domain | 关联 `research_domains` |
| status | active / paused / retired（含理由） |
| created_by / approved_by | 提出与批准人 |

规则：检索与筛选必须能回溯到某个 active RQ；RQ 退役需记录原因。

## 6. 证据评价框架

### 6.1 关系层（Claim ↔ Evidence，采用 SciFact 口径）

- `SUPPORT` / `CONTRADICT` / `NOT_ENOUGH_INFO`（NEI 为数据集原生第三类，非本项目发明）。
- 判定对象是"证据文本是否支持主张"，**不推断**干预有效性或理论正确性。

### 6.2 质量层（Research Appraisal，与关系层分离）

对每项纳入研究记录（对应 `works` 既有字段，v0.3 完善）：

- 研究设计：`evidence_category`（rct / meta_analysis / systematic_review / longitudinal /
  other_empirical / theoretical_conceptual / narrative_review / …）
- 样本与人群：`population`、`participant_age_range`、`sample_size`、`geographic_context`
- 测量与边界：`study_design`、`limitations`、适用年龄/文化边界
- 结论：appraisal 等级只能由人工审核产生（L7）。

### 6.3 证据分级

遵循 `docs/research/research-taxonomy.md`（生成物，只读引用）。禁止用引用量、
来源影响因子替代分级。

## 7. 不确定性管理

每张 Evidence Card 必须标注不确定性来源（可多选）：

- `single_study`（单项研究，未复现）
- `sample_limits`（样本量/人群局限）
- `measurement_limits`（测量效度存疑）
- `conflicting_evidence`（存在相反结果）
- `indirect_evidence`（只有间接证据）
- `unverified_metadata`（元数据未核验）

不确定性字段在人工审核前为 `not_assessed`。

## 8. 持续验证机制

触发器（任一满足即立案复审）：

1. 新证据与既有结论关系为 CONTRADICT；
2. 既有依据研究被撤稿/更正（`retraction_status`/`expression_of_concern` 变化）；
3. 方法学规程或证据分级标准变更；
4. 下游产品报告证据与实际不符。

复审输出三问的独立回答（见 §2）：现有知识是否仍成立？是否足以改变结论？
结论变化是否足以改变 Agent 行为？——每问独立记录决策人与依据。

## 9. 术语表

- **Historical Label**：v0.1 流水线历史决策（代理）。
- **Silver Label**：规则/模型辅助生成、未经人工确认的标签（须标注来源）。
- **Gold Label**：按本规程由人工产生、可审计的参考标签。
- **Evidence Card**：结构化证据单元（主张、证据、来源、页码、关系、审核状态）。
- **知识包**：版本固定的 catalog / evidence-cards / strategies + manifest，供下游导入。

## 10. 变更记录

| 版本 | 日期 | 说明 |
|---|---|---|
| DRAFT v1.0 | 2026-10-13 | Codex 起草（CE-01）；待人工审核确认 |
