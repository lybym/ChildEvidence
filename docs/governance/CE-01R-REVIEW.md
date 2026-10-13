# CE-01R-REVIEW.md — 科研规程 v1.0 跨文件一致性审计意见

> 性质：CE-01R 修订工作的**逐条审计记录**（问题、依据、风险、处置），供人工审核
> DRAFT v1.1 时参考。本文件不是批准记录；批准见 CE-01R-CHECKLIST.md。
> 审计对象：RESEARCH_METHODOLOGY.md、SCREENING_PROTOCOL.md、ANNOTATION_GUIDE.md、
> KNOWLEDGE_GOVERNANCE.md（v1.0）、AGENTS.md（v0.1.1）。
> 结论产物：上述文件修订为 **DRAFT v1.1**（仍待人工审核，未生效）。

## R1 科研双轨缺失（Issue 修订项 1）

- **问题**：v1.0 RESEARCH_METHODOLOGY §5 要求"检索与筛选必须能回溯到某个 active RQ"，
  而 v0.1 既有 141 篇馆藏均无 RQ 挂接；若按 v1.0 字面执行，全部馆藏处于违规状态，
  或被迫伪造回溯绑定。
- **依据**：RESEARCH_METHODOLOGY v1.0 §5 规则 1；SCREENING_PROTOCOL v1.0 §2.2；
  库历史（`record_status` 141 ingested / 252 rejected，无 RQ 字段）。
- **风险**：规程不可执行；历史记录被追溯性"补挂"RQ 造成语义漂移。
- **处置（v1.1）**：RESEARCH_METHODOLOGY §5 定义双轨——轨道 A（Scoping / Horizon
  Scanning 馆藏建设，不绑 RQ）与轨道 B（Question-driven Evidence Review，必须挂
  active RQ）；既有 141 篇馆藏不强制回溯绑定新 RQ（§5.1/§5.3）。SCREENING_PROTOCOL
  §1/§2 同步。

## R2 Catalog 决策与 Review×RQ 决策混用（Issue 修订项 2）

- **问题**：v1.0 未区分"书目收录状态"（Work/Catalog 层）与"RQ 级纳入状态"；同一
  Work 在不同 RQ 下应有不同纳入结论的语义无处安放；"ingested/rejected"与
  "included/excluded"两个值域可能被混填。
- **依据**：SCREENING_PROTOCOL v1.0 §5（决策记录只有 ingested/rejected/pending）；
  SQLite `works.record_status` 无 RQ 维度。
- **风险**：CE-02 复核结论被误读为 RQ 级结论；未来 Review 表设计被历史值域绑架。
- **处置（v1.1）**：RESEARCH_METHODOLOGY §5.3 明确两层对象与值域
  （catalog: ingested/rejected/pending；review: included/excluded/pending，必须携带
  rq_id+版本）；SCREENING_PROTOCOL §5.2、ANNOTATION_GUIDE §1/§3（新增 `track` 字段）
  同步；逻辑契约固化为
  `contracts/CE-01R-decision-scope.contract.json`（只建文件契约，不迁移 SQLite，
  遵守 Issue 边界与 AGENTS #11）。

## R3 RQ 管理不完整（Issue 修订项 3）

- **问题**：v1.0 RQ Registry 仅有字段建议（status 三态、无版本、无修订/退役流程、
  无审核者强制要求），且无任何示例。
- **依据**：RESEARCH_METHODOLOGY v1.0 §5。
- **风险**：RQ 被隐性改写后检索不可复现；退役 RQ 的历史结论无版本可循。
- **处置（v1.1）**：RESEARCH_METHODOLOGY §6 扩充生命周期
  （registered→active/paused/retired）、版本递增与 history、approved_by 人工批准、
  检索式挂接；契约 `contracts/CE-01R-rq-registry.contract.json` 与 3 个示例 RQ
  （`contracts/CE-01R-example-research-questions.json`：小学任务启动/回避、情绪调节
  与成人支持、儿童 AI 伙伴信任/依赖/安全）。示例 RQ 的 approved_by 置空并标注
  待批——示例不构成已批准 RQ。

## R4 Gold 标注定义缺口（Issue 修订项 4）

- **问题**：v1.0 只有 Historical/Silver/Gold 三层；"单人审核"的位置没有定义，
  Gold 的产生流程（独立复核、冲突裁决、签署）未成文；"无法复核时"的边界缺失。
- **依据**：RESEARCH_METHODOLOGY v1.0 术语表；ANNOTATION_GUIDE v1.0 §7.5
  （已有"单人标注需声明"但无层级约束）。
- **风险**：单人标注被直接当 Gold 消费，绕过交叉验证；知识包门禁失去可执行判据。
- **处置（v1.1）**：RESEARCH_METHODOLOGY §7 定义四级标签 proxy / silver /
  provisional（单人审核，封顶 L2）/ gold（独立复核一致或裁决完成 + 知识负责人
  签署）；无法独立复核时封顶 provisional 并强制声明；禁止模型自证 Gold
  （含多模型投票）。ANNOTATION_GUIDE §8 执行化；契约
  `contracts/CE-01R-label-tiers.contract.json`。

## R5 入排标准未覆盖非 DOI 标识与三级判定（Issue 修订项 5）

- **问题**：v1.0 I5 要求"DOI 或等价官方标识"但未列 ISBN、机构报告编号、权威馆藏
  记录，实际操作易把无 DOI 经典著作（如皮亚杰/维果茨基原典、NAP 报告）误判 E6；
  且未区分相关性、全文资格与研究方法质量——"方法差"可能被当排除理由。
- **依据**：SCREENING_PROTOCOL v1.0 §3 I5 / §4 E6；README 数据源含机构报告渠道；
  RESEARCH_METHODOLOGY M8。
- **风险**：系统性误拒经典与中文文献（POC-A 已实测排序层同类偏差）；筛选理由
  代码被挪用为质量评级。
- **处置（v1.1）**：I5 列明五类可核验标识（DOI / ISBN / 机构报告编号 / 权威馆藏
  记录 / 官方出版页）；E6 收紧为"穷尽 I5 渠道仍不可核验且关键内容缺失"；§4 开头
  声明三级判定分离，方法质量不进 E/R 代码（写入 appraisal）。ANNOTATION_GUIDE
  §4/§5 同步（无"方法质量低"代码）。

## R6 筛选停止规则可被误用（Issue 修订项 6）

- **问题**：v1.0 §6.3 已有停止规则雏形，但未明令禁止"未完成独立评估前宣称达到
  95% 召回"，保护层（中文/经典/阴性/争议）无可操作定义，无法机检或人工核对。
- **依据**：SCREENING_PROTOCOL v1.0 §6；FINAL_RECOMMENDATION §9.2（WSS@95 v2 口径
  只反映排序效率）；POC-A errors.jsonl。
- **风险**：以模拟指标（WSS@95）冒充真实停止性；保护层名存实亡。
- **处置（v1.1）**：SCREENING_PROTOCOL §6.2 增加停止声明禁令（独立评估 + 人工批准
  前不得宣称 95% 召回/可停止；模拟口径不构成证明）；§6.4 给出保护层四类的可操作
  定义（language=zh、年份+类别、结果方向声明、争议/CONTRADICT/EOC）；停止规则参数
  变更同样需人工批准并记录批准人。AGENTS #21 同步。

## R7 工作流阶段与审核成熟度两套编号混用风险（Issue 修订项 7）

- **问题**：v1.0 仅有 L1–L9 工作流阶段；无审核成熟度体系，状态机与标签层级之间
  缺少显式映射；"approved 之后如何退休"已有但"回边禁令"未显式，存在被解读出
  循环依赖的空间（如消费端需求倒推卡片状态）。
- **依据**：RESEARCH_METHODOLOGY v1.0 §3；KNOWLEDGE_GOVERNANCE v1.0 §3。
- **风险**：不同读者把"L3"读成工作流或成熟度，治理门禁失准；状态机出现隐式环。
- **处置（v1.1）**：RESEARCH_METHODOLOGY §3 固定编号约定（L1–L9=工作流阶段，
  L0–L4=审核成熟度），新增 §9 定义 L0 draft / L1 pending / L2 provisional /
  L3 approved / L4 retired，rejected 不在阶梯内、needs_more_evidence 回退不新增
  等级、成熟度只能由人工行为推进；KNOWLEDGE_GOVERNANCE §3 显式回边禁令
  （rejected/superseded/retracted 不得转回 approved）与映射表；§2.4 声明依赖单向
  无循环；§4 发布门禁绑定"approved 且 L3+gold"；Evidence Card 必填字段增加
  `maturity_level`。契约 `contracts/CE-01R-decision-scope.contract.json` 固化枚举。

## R8 POC v1 指标误导自动消费者（Issue 修订项 8）

- **问题**：FINAL_RECOMMENDATION §8.3 保留 v1 口径 WSS@95（0.075–0.152）与
  bottom-50% 漏筛（59–136）作为表格数字，§9.4 才声明已被 v2 口径取代；自动消费者
  或后续引用可能取 §8.3 旧值。v1→v2 修正（WSS@95=0.95−B95/N；Missed@50 逐 run
  口径）散落在正文，无权威指针。
- **依据**：FINAL_RECOMMENDATION §8.3/§9.4；
  `results/asreview-metrics-v2-summary.csv`（v2：svm 0.068 / nb 0.102 /
  logistic 0.096 / tfidf 0.025 / random 0.017；Missed@50 AL 42.6–47.2 vs
  random 72.4）；`results/asreview-metrics.csv`（v1 留痕）。
- **风险**：下游按 v1 数字做决策；或有人直接改写 §8.3 破坏原始记录可复算性。
- **处置（v1.1）**：新增权威更正索引 `CE-01R-ERRATA.md` 与机器可读最新指标指针
  `contracts/CE-01R-poc-metrics-latest.json`（逐值对齐 v2 summary CSV，由
  `tests/test_governance_contracts.py` 机器校验）；在 FINAL_RECOMMENDATION.md 顶部
  追加勘误指针（**不改写任何原始数字**，历史记录保留并标 superseded）。

## R9 AGENTS.md 工程约束缺口（Issue 修订项 9）

- **问题**：AGENTS.md v0.1.1 科研治理节引用 v1.0 规程；#5 把派生快照
  （docs/research/research-taxonomy.md）当作分级规范引用——违反"生成物不作不可变
  规范"；未声明 DRAFT 对 Agent 的约束力边界。
- **依据**：AGENTS.md v0.1.1 #5 与科研治理节；README（research docs 生成机制）。
- **风险**：Agent 把 DRAFT 当生效准则自动执行；生成物变更被误当作规范变更。
- **处置（v1.1）**：AGENTS.md #5 改为以规程文件为准、生成物仅作参考；新增 #22
  （交叉引用不指向生成物作为不可变规范）、#23（DRAFT 不可被 Agent 当作生效准则，
  生效唯一凭据是 CHECKLIST 人工签署）、#24（四文件同版本演进 + 一致性测试门禁）；
  #17/#18/#19/#21 引用与措辞同步 v1.1。

## 审计覆盖与限制（诚实清单）

- 本审计为静态文档与代码审计 + 既有 POC 原始数据复算结果对齐，未执行新的在线
  采集（Issue 边界）；未触碰 SQLite schema 与任何数据迁移（Issue 明确不做）。
- 契约文件为逻辑契约（文件级），未在库内实施唯一约束；其实施依赖后续 schema
  迁移 Issue（AGENTS #11 流程）。
- 3 个示例 RQ 为起草示例，未获批准（approved_by 空），不得直接转为 active。
