# RESEARCH_METHODOLOGY.md — ChildEvidence 科研方法论

> 状态：**DRAFT v1.1（CE-01R）** — 2026-10-13 依据跨文件一致性审计修订（逐条意见、依据与
> 风险见 [docs/governance/CE-01R-REVIEW.md](docs/governance/CE-01R-REVIEW.md)）。
> **仍待人工审核，未生效**：Agent 不得将本文件当作生效准则执行（见 AGENTS.md 科研治理节）；
> 人工批准以 [docs/governance/CE-01R-CHECKLIST.md](docs/governance/CE-01R-CHECKLIST.md) 的
> 签署记录为准。本文件与其他三份规程（SCREENING_PROTOCOL、ANNOTATION_GUIDE、
> KNOWLEDGE_GOVERNANCE）同版本演进，互引章节以"文件 §编号"显式标注。
> 依据：POC 技术评估（docs/assessment/2026-10-13-poc-tech-evaluation/）、UPSTREAM_AUDIT、
> v1.0 规程的 CE-01R 审计意见。

## 1. 目的与适用范围

本文件定义 ChildEvidence 生产、维护与使用科研证据的方法学框架。适用于：

- 研究问题的提出与管理（仅轨道 B，见 §5）；
- 文献的检索、筛选、纳入与排除（双轨语义见 §5，操作规程见 SCREENING_PROTOCOL）；
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
4. 依赖方向单向：① 产生对象 → 对象达 L3（§9）→ ② 版本化发布 → ③ 消费；**任何下游
   层不得反向改写上游对象的审核状态或结论**（无循环依赖，见 KNOWLEDGE_GOVERNANCE §3）。

## 3. 科研生命周期（L1–L9：工作流阶段编号）

```text
L1 研究问题注册（Research Question Registry；仅轨道 B）
L2 检索与发现（官方公开 API；SCREENING_PROTOCOL §2）
L3 筛选与纳入/排除（SCREENING_PROTOCOL §3–§5；人工决策）
L4 入库与元数据核验（SQLite 唯一事实源；verify 流程）
L5 全文解析与证据定位（v0.2 Docling Adapter；输出必须可回溯 PDF 页）
L6 证据评价与综合（关系判定 + 质量评价分离；v0.3）
L7 人工审核（ANNOTATION_GUIDE；Evidence Card pending → approved）
L8 知识发布（版本化知识包；KNOWLEDGE_GOVERNANCE）
L9 持续验证（新证据/撤稿/方法学变更触发再评价）
```

**编号约定（v1.1 明确）**：L1–L9 是**工作流阶段**编号，只描述"一件事处在流水线的哪一步"，
**不描述**任何对象（文献、标注、证据卡、知识条目）的审核成熟度；成熟度使用独立的
L0–L4 等级（§9）。两套编号不混用：书写时"L1–L9"恒指工作流阶段，"L0–L4"恒指审核
成熟度等级。

各阶段门槛：L3 未决条目不得进入 L6；L7 未 approved 的证据卡不得进入 L8；
L8 发布必须带 manifest 哈希与版本号，可回滚。

**双轨对 L1–L9 的使用差异**：轨道 B（§5.2）走完整 L1→L9；轨道 A（§5.1）只走
L2→L4（检索、入库）并产出目录与导出（L8 的 catalog 派生物），不进入 L5–L7 的
RQ 级评价，除非该文献后来被某轨道 B RQ 正式纳入。

## 4. 方法学原则（M1–M10）

- **M1 唯一事实源**：`data/research-library/library.sqlite`；Markdown/exports 为派生物。
- **M2 字段级溯源**：DOI、作者、摘要等必须来自官方 API 响应（`raw_sources` 留存摘录）。
- **M3 不虚构**：未核实的字段保持 NULL 并注明"待读全文"；缺失摘要不得生成。
- **M4 预印本 ≠ 正式发表**：独立标记，不混合引用层级。
- **M5 引用量只用于发现排序，不得作为证据等级**。
- **M6 历史决策是代理标签（catalog 层）**：v0.1 的 `record_status`
  （141 ingested / 252 rejected，合计 393 条）是**轨道 A 馆藏建设**的流水线历史决策，
  仅作目录级代理（historical catalog-level proxy，标签层级见 §7）；它们**不是**
  任何 RQ 的 Review 级纳入/排除决策，其含义不因本规程引入 RQ 语义而改变（§5.3）。
  Gold Label 只能来自按本规程执行的人工标注（§7）。
- **M7 AI 产出必须标注**：AI 参与的提取/排序/草稿必须记录模型与版本；**AI 不得生成并
  自我确认 Gold Label**；多模型一致投票不等同专家共识（§7）。
- **M8 关系与质量分离**："研究 X 的发现与主张 S 相符"（关系判定）与"研究 X 方法可靠"
  （质量评价/appraisal）是两个独立判断，不得互相推导；方法质量低**不等于**离题
  （SCREENING_PROTOCOL §4）。
- **M9 可复现**：影响结论的实验必须固定上游版本、依赖、种子与配置，原始记录可重算
  （POC CE-01 的 ranking→metrics 重算与一致性测试是范例）；历史指标被修正时以勘误
  索引为权威指针，不改写原始记录（docs/governance/CE-01R-ERRATA.md）。
- **M10 规程自身版本化**：修改本文件体系需人工批准并记录变更；**DRAFT 版本在获批前
  对 Agent 不是生效准则**。

## 5. 科研双轨与对象职责分离

### 5.1 轨道 A：广域文献发现与经典知识馆藏（Scoping / Horizon Scanning）

- 目的：持续建设覆盖五个研究领域的**馆藏（Catalog）**，发现新方向、储备经典与边缘
  文献，不预设具体研究问题。
- 判定对象：该文献是否值得进入馆藏（书目收录价值）。
- 值域（catalog 层）：`ingested` / `rejected` / `pending`（沿用 `record_status` 历史语义）。
- **不强制绑定 RQ**：轨道 A 的检索与收录不需要、也不得追溯要求挂接研究问题。
- 既有 141 篇 ingested / 252 条 rejected 历史记录属于轨道 A 的历史产物，其含义保持
  不变（§5.3）；后续馆藏扩充继续走轨道 A。

### 5.2 轨道 B：基于已注册 RQ 的专题循证评价（Question-driven Evidence Review）

- 目的：回答一个**已注册**（§6）且处于 active 状态的研究问题，产出可审核的
  Evidence Card 与 RQ 级纳入结论。
- 判定对象：该文献对**该 RQ** 的证据资格。
- 值域（review 层）：`included` / `excluded` / `pending`，**只能**与某个 RQ 版本联合
  存在；不存在"脱离 RQ 的 included/excluded"。
- 检索式、入排裁剪与停止规则以该 RQ 的注册内容为基线（SCREENING_PROTOCOL §2、§6）。

### 5.3 对象职责分离与历史记录语义

- **Catalog 决策与 Review 决策是两类对象**：前者回答"是否值得馆藏"，后者回答
  "是否满足某 RQ 的证据资格"。二者字段、值域与审计记录互不混用，逻辑契约见
  [docs/governance/contracts/CE-01R-decision-scope.contract.json](docs/governance/contracts/CE-01R-decision-scope.contract.json)
  （本 Issue 仅建立文件契约，不迁移 SQLite schema；库内迁移遵照 AGENTS #11 另行立项）。
- **同一 Work 可在不同 RQ 下得到不同结论**：Work W 在 RQ-1 下 `included`、在 RQ-2 下
  `excluded` 是正常状态；Review 决策记录必须携带 `rq_id` + RQ 版本。
- **历史 141/252 记录语义不变**：它们全部是轨道 A catalog 决策；不得被自动解释为
  任何 RQ 的 included/excluded；不得被自动改写、自动提升为 Gold 或自动翻转结论。
  历史拒收的重新审读（如 CE-02 A2 复核）产出的仍是 catalog 层复核记录，并按 §7
  确定其标签层级。

## 6. 研究问题管理（RQ Registry，仅轨道 B）

机器可校验契约与示例：
[docs/governance/contracts/CE-01R-rq-registry.contract.json](docs/governance/contracts/CE-01R-rq-registry.contract.json)、
[docs/governance/contracts/CE-01R-example-research-questions.json](docs/governance/contracts/CE-01R-example-research-questions.json)
（本 Issue 只建文件，不建 `research_questions` 表；落库迁移遵照 AGENTS #11 于后续 Issue 执行）。

| 字段 | 说明 |
|---|---|
| rq_id | 稳定 ID（`rq-` 前缀） |
| version | RQ 版本号（实质修改内容即递增；历史版本只保留不删除） |
| question | 研究问题文本 |
| background | 为什么问这个问题（业务/理论动机） |
| scope | 适用范围：人群、年龄段、语言、出版类型、时间窗口 |
| search_queries | 与该 RQ 挂接的检索式（来源、关键词与过滤参数） |
| inclusion_hints / exclusion_hints | 该 RQ 的入排要点（在 SCREENING_PROTOCOL §3–§4 之上裁剪） |
| domain | 关联 `research_domains` |
| status | `registered` → `active` / `paused` / `retired`（终态；retired 必须记录理由） |
| created_by / approved_by | 提出人；**批准人（人工）**——未获批不得转 `active` |
| history[] | 修订记录：版本、日期、变更摘要、批准人 |

规则：

1. 轨道 B 的检索与筛选必须能回溯到某个 **active** RQ 的具体版本；RQ 退役后不得新启
   筛选，历史 Review 决策与结论保留并标注其版本。
2. RQ 实质修订（问题文本、范围、入排要点）必须递增版本并留 `history`；检索式微调
   （同版本内）须在 `runs.notes` 留痕。
3. RQ 的注册与版本批准是人工决策；Agent 可起草，不得自批。

## 7. 标签层级与 Gold 资格

机器可校验契约：
[docs/governance/contracts/CE-01R-label-tiers.contract.json](docs/governance/contracts/CE-01R-label-tiers.contract.json)。

| 层级 | 定义 | 来源 | 资格边界 |
|---|---|---|---|
| **proxy** | 历史流水线决策的代理标签 | v0.1 `record_status` 等既有记录（轨道 A） | 永不自动升为 gold；仅用于排序、审计与富集抽样 |
| **silver** | 模型辅助生成、未经人工确认 | 规则/模型产出，带 `ai_assisted=true` 与模型版本 | 只可作建议输入；不得自动成为人工结论 |
| **provisional** | 单人人工审核并签署，未经独立复核 | 一名审核人的 decision + 理由 + 时间戳 | 封顶于 L2（§9）；不得单独支撑知识包发布 |
| **gold** | 满足 Gold 资格流程的人工参考标签 | 见下 | 唯一可支撑知识工程决策（②）的标签层级 |

**Gold 资格流程（全部满足）**：

1. 独立复核：第二名审核人按同一标准**独立**盲标（ANNOTATION_GUIDE §2），或
2. 冲突裁决：不一致时按 ANNOTATION_GUIDE §7 裁决（第三人独立标注或双人协商后由知识
   负责人确认，保留双方原始意见），且
3. 人工签署：知识负责人在批准清单/审计记录中签署确认（决策人、日期、版本）。

**无法独立复核时的边界**：确无第二人时，标签**封顶 provisional**，必须在标注包与
导出物中显式声明"单人标注，未经第二人独立验证"（ANNOTATION_GUIDE §7.5），且不得
进入知识包发布门禁（KNOWLEDGE_GOVERNANCE §4）。**禁止模型自证 Gold**：任何模型产出
（含多模型一致投票）都不能产生或替代 Gold；模型只能产出 silver 并被人工重审。

## 8. 证据评价框架

### 8.1 关系层（Claim ↔ Evidence，采用 SciFact 口径）

- `SUPPORT` / `CONTRADICT` / `NOT_ENOUGH_INFO`（NEI 为数据集原生第三类，非本项目发明）。
- 判定对象是"证据文本是否支持主张"，**不推断**干预有效性或理论正确性。

### 8.2 质量层（Research Appraisal，与关系层分离）

对每项纳入研究记录（对应 `works` 既有字段，v0.3 完善）：

- 研究设计：`evidence_category`（rct / meta_analysis / systematic_review / longitudinal /
  other_empirical / theoretical_conceptual / narrative_review / …）
- 样本与人群：`population`、`participant_age_range`、`sample_size`、`geographic_context`
- 测量与边界：`study_design`、`limitations`、适用年龄/文化边界
- 结论：appraisal 等级只能由人工审核产生（L7）。

**三级判定分离（v1.1，与 SCREENING_PROTOCOL §3–§4 对齐）**：相关性（是否离题）→
全文资格（是否可评）→ 研究方法质量（appraisal）。方法质量只影响证据等级、权重与
适用边界，**不得**用"方法差"替代离题排除（理由代码表无此用法）。

### 8.3 证据分级

证据分级原则以本文件与 `docs/research/research-taxonomy.md` 的当前派生快照为参考；
**规范以规程文件为准，派生快照不是不可变规范**（AGENTS.md 科研治理节）。禁止用
引用量、来源影响因子替代分级。

## 9. 审核成熟度等级（L0–L4）

适用于所有受审对象（标注决策、Evidence Card、知识条目草案）。与 L1–L9 工作流阶段
编号严格区分（§3）；与标签层级（§7）正交：层级描述**数据来源质量**，成熟度描述
**人工审核进度**。

| 等级 | 名称 | 定义 | 对应状态机（KNOWLEDGE_GOVERNANCE §3） |
|---|---|---|---|
| L0 | draft | 机器或人工起草，未提交人工审 | `draft` |
| L1 | pending | 已提交，等待人工审核 | `pending` |
| L2 | provisional | 单人已审并签署，未独立复核（标签 ≤ provisional） | `pending` 审毕的单人记录（卡仍在 `pending` 池等待复核） |
| L3 | approved | 独立复核一致或经裁决后签署（标签 gold） | `approved` |
| L4 | retired | 复审改判的历史终态 | `superseded` / `retracted` |

规则：

1. `rejected` 是终局否定结论，**不属于**成熟度阶梯（它不是"还没成熟"，而是"审后否定"）；
   `needs_more_evidence` 是回退路径，补证后重新进入 L1，不新增等级。
2. 唯一终态回边禁令：L4 与 `rejected` **不得**回到 L3/approved；确需翻案时新建对象
   并保留审计链（KNOWLEDGE_GOVERNANCE §3）。
3. L3 是进入知识包发布门禁的最低成熟度（KNOWLEDGE_GOVERNANCE §4）。
4. 成熟度只能由人工审核行为（含裁决与签署）推进；任何自动管线不得越级（L0→L2/L3
   直跳视为违规）。

## 10. 不确定性管理

每张 Evidence Card 必须标注不确定性来源（可多选）：

- `single_study`（单项研究，未复现）
- `sample_limits`（样本量/人群局限）
- `measurement_limits`（测量效度存疑）
- `conflicting_evidence`（存在相反结果）
- `indirect_evidence`（只有间接证据）
- `unverified_metadata`（元数据未核验）

不确定性字段在人工审核前为 `not_assessed`。

## 11. 持续验证机制

触发器（任一满足即立案复审）：

1. 新证据与既有结论关系为 CONTRADICT；
2. 既有依据研究被撤稿/更正（`retraction_status`/`expression_of_concern` 变化）；
3. 方法学规程或证据分级标准变更；
4. 下游产品报告证据与实际不符。

复审输出三问的独立回答（见 §2）：现有知识是否仍成立？是否足以改变结论？
结论变化是否足以改变 Agent 行为？——每问独立记录决策人与依据。

## 12. 术语表

- **轨道 A / 轨道 B**：馆藏建设（Scoping/Horizon Scanning）与 RQ 专题循证评价
  （Question-driven Evidence Review），见 §5。
- **Catalog 决策 / Review 决策**：馆藏收录判定（ingested/rejected/pending）与
  RQ 证据资格判定（included/excluded/pending），互不混用，见 §5.3。
- **Historical Label / proxy**：v0.1 流水线历史决策（轨道 A 代理标签）。
- **Silver Label**：规则/模型辅助生成、未经人工确认的标签（须标注来源与模型版本）。
- **Provisional Label**：单人人工审核并签署、未经独立复核的标签（封顶 L2）。
- **Gold Label**：按 §7 资格流程产生、可审计的人工参考标签。
- **L1–L9**：工作流阶段编号（§3）。**L0–L4**：审核成熟度等级（§9）。两套编号不得混写。
- **Evidence Card**：结构化证据单元（主张、证据、来源、页码、关系、审核状态）。
- **知识包**：版本固定的 catalog / evidence-cards / strategies + manifest，供下游导入。

## 13. 变更记录

| 版本 | 日期 | 说明 |
|---|---|---|
| DRAFT v1.0 | 2026-10-13 | Codex 起草（CE-01）；待人工审核确认 |
| DRAFT v1.1 | 2026-10-13 | CE-01R 一致性审计修订：科研双轨与对象职责分离、RQ 管理扩充（版本/退役/审核者）、标签层级与 Gold 资格、L0–L4 成熟度与 L1–L9 编号区分、三级判定分离；**仍待人工审核，未生效** |
