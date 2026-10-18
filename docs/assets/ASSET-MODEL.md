# 专业资产领域模型与人格版本契约（Issue #15）

> 实现记录，2026-10-19。对应 Issue
> <https://github.com/lybym/ChildEvidence/issues/15>
> （`[P1][专业资产] 生产支持方法、复盘与互动人格契约`）。实现位于
> [assets.py](../../src/research_library/assets.py)、
> [contracts/assets/](../../src/research_library/contracts/assets/)，
> 共享严格校验器 [strict_schema.py](../../src/research_library/strict_schema.py)，
> 存储接入 [db.py](../../src/research_library/db.py)，CLI 入口
> `research assets`（[cli.py](../../src/research_library/cli.py)）。
> 本文档描述已实现的工程契约；它不声称任何科研结论、教育有效性、发布资格或
> 规程生效。设计依据：[contracts.md](../design/growth-support-mvp/contracts.md)
> §1（DRAFT v0.2，实现按其结构落地，不冻结其草案状态）。

## 1. 目的与边界

在既有书目事实源（`works`）与 Evidence/Claim 科研语义层（Issue #14）之上，
建立**可独立演进的专业资产领域层**：Strategy（策略）、SupportMethod（支持方法）、
InteractionProfile（互动人格）、EvaluationCase（评测案例）。公共信封包含稳定
ID、不可变修订、内容哈希、来源、审核方式与资格；依据四分（直接研究/研究综合/
应用推导/设计选择）显式标记，研究依据不足就标记不足，不补造引文。

明确不做（与 Issue #15 一致）：不训练小模型、不创建多专家 Agent 团队、不收
真实儿童档案、不把单篇研究证明扩成完整角色有效性；不实现运行核心（Issue #17）、
私有发布包与撤回服务（Issue #16/#19）；不把任何 demo 资产当真实资产。

## 2. 领域对象与公共信封

| 对象 | 存储 | 语义要点 |
|---|---|---|
| Strategy | `asset_strategies` | 目标、适用/排除条件、有限动作步骤、观察结果、调整/停止条件、诚实的证据摘要 |
| SupportMethod | `asset_support_methods` | 信息前提、竞争解释维度、有限状态/动作、状态迁移、用户拒绝与方法无效分支、儿童/家长/教师适配、冲突优先级、复盘标准、`unknown_policy='block'` |
| InteractionProfile | `asset_interaction_profiles` | 倾听/提问/反馈/表达规范、对象适配、冲突优先级；GS-04：任何版本携带依据与评测引用，`runtime_effect` 仅 `new_version_release` |
| EvaluationCase | `asset_evaluation_cases` | 合成输入（`fixture_kind='synthetic'` 常量）、预期/禁止行为、评分依据、覆盖的资产版本；不包含真实儿童记录 |

公共信封（四个 kind 共有）：`schema_version`（const `ce.assets/1`）、`asset_id`
（跨修订稳定）、`revision`（≥1，内容不可变）、`content_hash`、
`supersedes_revision`、`title`、`created_by`、`created_at`、`basis_kind`、
`basis_sufficiency`、`basis_refs`、`evaluation_refs`（EvaluationCase 除外）、
`demo_only`、`review_origin`、`review_status`、`technical_validation`、
`scientific_appraisal`、`release_eligibility`、`lifecycle_status`、
`retraction_reason/retracted_at/retraction_ref`。

- **内容哈希**（`compute_content_hash`）：对声明内容字段（身份、依据、评测
  引用与全部 kind 载荷）做规范化 JSON 的 sha256；生命周期/审核/资格等状态
  注解不参与哈希——状态可演进而内容身份不变。插入时必须携带且逐字复算
  （AS-Hash），无静默自动哈希；手写记录用 `prepared_record` + 
  `compute_content_hash` 生成。
- **不可变修订链**（AS-Revision/AS-Chain）：`revision` 只能追加（必须是既有
  最大修订 +1，禁止改写与留洞）；`revision>1` 必须 `supersedes_revision=revision-1`。
  新修订落库时把前一修订标记为 `superseded`（已撤回的保持 `retracted`），
  内容字段与哈希不变。这是对 GS-LIM-01（单记录契约无法校验版本链）在资产层
  的存储级回答。
- **引用携带修订**：`basis_refs`/`evaluation_refs`/`covers` 一律是
  `{ref, revision}` 结构，不只写显示名称。

## 3. 依据四分与不足标记（不补造引文）

`basis_kind ∈ {direct_research, research_synthesis, application_inference,
design_choice}`；`basis_sufficiency ∈ {research_supported, insufficient}`。

- AS-BasisRef：`claim`/`source_version`/`work` 类依据引用必须在
  `evidence_claims`/`evidence_source_versions`/`works` 中真实存在——研究引用
  必须可核查，不能凭空声明。
- AS-Basis：`basis_sufficiency='research_supported'` 至少需要一条可核查的研究
  引用；`basis_kind='design_choice'` 必须标记 `insufficient`。其余组合
  （如 `application_inference` + `insufficient`）是合法的诚实不足声明。
- `design_note`/`external` 引用只是数据指针（如指向设计文档或外部来源），
  不参与存在性校验，也不得表述为研究支持。

## 4. 方法的可执行结构（验收 #2）

SupportMethod 的结构字段是**必需项**（schema `required` + `minItems`），不是
约定：

- `explanation_dimensions`（竞争解释维度，≥1）；
- `on_user_decline` / `on_method_ineffective`（用户拒绝、方法无效分支，必填）；
- `audience_adaptation.child/parent/teacher`（三类请求者的表达适配共享一个
  连贯角色，全部必填）；
- `states`/`initial_state`/`transitions`（有限状态迁移；AS-State 校验迁移
  端点必须落在已声明状态内）；
- `allowed_actions` 只能取有限动作词表（contracts.md §1.2 的七个动作；代码
  常量 `ACTIONS` 与 schema enum 一致性有专门测试）；新增动作类型是版本化的
  schema 变更 + 兼容评测，不是运行时下载；
- `conflict_priority`（多专业视角冲突处理，≥1）、`review_criteria`
  （复盘：observe/adjust_when/stop_when，全部 ≥1）；
- `unknown_policy` 是 const `'block'`。

Strategy 同样要求有限动作步骤与调整/停止条件。

## 5. 未知与阻断（验收 #3）

- **未知不按 true 执行**：条件规格的 `on_unknown` 枚举只有
  `block | needs_information`，schema 层面就不存在"未知即放行"的写法。
  `condition_precheck(record, resolved_facts)` 实现数据层判定语义：
  事实集用确认在场（`"x"`）与显式确认缺席（`"!x"`）表达，缺席从不因沉默推断；
  未解析 → unknown → 按 `on_unknown` 阻断或请求信息；`applies_when` 被确定性
  违反 → 阻断；`excludes_when` 被命中 → 阻断。任何未知路径都不可能返回
  `can_proceed=True`。
- **缺证可阻断**：`asset_blockers(conn, kind, asset_id, revision)` 逐条返回
  运行适用性阻断码（ASB-Draft / ASB-Superseded / ASB-Retracted /
  ASB-EvalMissing / ASB-EvidenceInsufficient / ASB-ReviewMissing /
  ASB-NotEligible / ASB-DemoAsset / ASB-Missing），`usable` 只有零阻断才为
  true；运行核心（Issue #17）消费该判定，本层不提供任何翻转路径。
- **撤回可阻断**（GS-03）：`retract_asset` 追加式标注
  `lifecycle_status='retracted'` + 理由/时间/决定引用，内容与哈希不变；
  重复撤回被拒；撤回是终态。
- **资产仅是声明数据**：所有字段为字符串/列表/对象；每份 schema 声明
  `additionalProperties: false`，`script`/`code`/`exec` 等可执行字段被
  直接拒绝（有测试证明），不存在任意代码执行面。

## 6. 审核与发布正交（验收 #1；GS-01/02/04/05）

- **AS-Release**：`release_eligibility='eligible'` 要求
  `technical_validation='passed'` 且 `scientific_appraisal='done'` 且人工审核
  来源（`single_human`/`independent_double_human`/`adjudicated_human`）且
  `review_status='human_reviewed'`（GS-01/GS-02/GS-05；AI 来源永不自我晋升，
  对齐 evidence 层 EV-Release）。
- **AS-Lifecycle**：`lifecycle_status='released'` 要求 `eligible`——未批准
  草稿不能伪装成发布资产；`'superseded'` 只能由修订链产生，不能直接插入。
- **AS-GS04**：InteractionProfile 任何版本（含首版）`basis_refs` 与
  `evaluation_refs` 必填非空；`runtime_effect='immediate'` 被拒——任何版本
  （含首版）只能作为新版本发布生效，无版本豁免。
- **AS-Demo**：`demo-*` 前缀必须 `demo_only=true`；demo 资产永远
  `not_eligible` 且永远不能 `released`（合成夹具不携带真实资格）。
- 真实发布决定仍由 CE-GS-01（GS-01…GS-06）治理；本层只提供粗粒度状态与阻断
  判定，不代签任何批准。

## 7. 严格校验入口与规则表

- 记录信封：`schema_version` const `ce.assets/1`；四份严格 schema 位于包资源
  `research_library/contracts/assets/*.schema.json`，经 `importlib.resources`
  加载，脱离仓库 checkout 的安装副本同样可加载（有独立安装测试）。
- `assets.validate_record(kind, record)` 与 `assets.insert_record(...)` 共用
  同一规则；严格校验器来自共享模块 `research_library.strict_schema`
  （`additionalProperties: false`、数值边界、pattern、长度/条数、const/enum；
  Issue #14 的 `evidence._strict_validate` 原样上移，行为由既有 36 项测试锁定）。

| 规则 | 拒绝内容 |
|---|---|
| 信封 const/required | 缺少或错配 `schema_version` |
| additionalProperties=false | 任何未声明字段（含 `evaluation_case.evaluation_refs`、`script` 等可执行字段名） |
| AS-Hash | `content_hash` 缺失（插入时）或与复算不符 |
| AS-Revision | revision=1 带 supersedes；revision>1 未指向 revision-1 |
| AS-Chain | 修订不追加（改写/留洞/重复） |
| AS-Dup | 重复 (asset_id, revision)；数据库约束兜底 |
| AS-BasisRef | research 引用指向不存在的 claim/source_version/work |
| AS-Basis | research_supported 无可核查引用；design_choice 冒充 research_supported |
| AS-EvalRef | 评测引用指向不存在的案例，或案例 `covers` 未覆盖该资产版本 |
| AS-GS04 | InteractionProfile `runtime_effect='immediate'` |
| AS-Release | eligible 缺技术校验/科学评价/人工来源/human_reviewed |
| AS-Lifecycle | released 但不 eligible；直接插入 superseded |
| AS-Retract | 撤回缺理由/时间/决定引用 |
| AS-Demo | demo-* 未标 demo_only；demo 资产声明 eligible 或 released |
| AS-State | initial_state / transitions 端点不在声明状态内 |
| EV-Ref（schema 层） | 动作不在有限词表、`on_unknown='proceed'` 不可表达、revision<1 等 |

评测闭合方向：`covers` → 资产的存在性在**资产版本插入时**经 AS-EvalRef 反向
闭合（评测案例可以与资产新版本同批先行入库，`covers` 允许前向声明；资产侧
引用必须落到已存在且覆盖该版本的案例上）。

## 8. 迁移与兼容（AGENTS #11；失败与回滚）

- 四张新表 DDL 全部 `CREATE TABLE IF NOT EXISTS`，不改动 `works`、evidence_* 与
  任何既有表；`db.connect()` 每次执行合并后的 SCHEMA，新旧库在打开时收敛。
- 正式迁移入口：`python -m research_library assets migrate [--db PATH]`
  （`assets.migrate_with_backup`）：**先用 SQLite backup API 生成备份**
  `<db 目录>/backups/pre-assets-migration-<UTC>-<rand>.sqlite`，再应用 DDL，
  最后 `PRAGMA integrity_check`。恢复路径：直接以备份文件替换/复制回原路径。
- 兼容性测试：pre-assets 库（BASE_SCHEMA + evidence DDL）上迁移后，
  `works`/`download_log`/`evidence_claims` 遗留行逐行字节不变，备份可打开且
  行一致；全新建库无需备份。
- 生产库执行记录：`assets migrate --db data\research-library\library.sqlite`
  生成备份 `data\research-library\backups\pre-assets-migration-20261018T174952Z-7f07ce.sqlite`
  后应用，`integrity_check=ok`；迁移前后 `works` 393 行逐行一致；四张资产表
  均为空（未 seed 任何 demo 资产进生产库）。

## 9. 最小合成 demo 资产链（交付范围 #5）

打包夹具 `src/research_library/contracts/assets/fixtures/`（8 条记录，
`research assets seed-demo` 一次性播种，重复执行幂等）：

| 资产 | kind | 覆盖场景 |
|---|---|---|
| demo-strategy-learning-support@1 | strategy | 学习困难支持（E01/E05 关联） |
| demo-strategy-interest-exploration@1 | strategy | 兴趣/优势探索（E06 关联） |
| demo-method-clarify@1 | support_method | 澄清—支持法：竞争解释、拒绝/无效分支、三对象适配（E01/E05） |
| demo-profile-support@1 | interaction_profile | 支持型人格：GS-04 全字段 + `new_version_release`（E05/E11） |
| demo-eval-e01-clarify@1 / e05-decline@1 / e06-explore@1 / e11-profile@1 | evaluation_case | 合成行为评测夹具（对应 delivery-plan 矩阵 E01/E05/E06/E11） |

诚实标记：全部 `demo-*` + `demo_only=true`、`basis_kind='design_choice'`、
`basis_sufficiency='insufficient'`、`lifecycle_status='draft'`、
`release_eligibility='not_eligible'`；`evidence_refs` 不引用任何论文（不补造
引文）；`seed_demo` 拒绝任何含 `works` 行的数据库——demo 资产只进合成库，
永不进入生产研究库。评测引用与 `covers` 双向闭合有专门测试；所有已存记录的
content_hash 逐条复算测试通过。

## 10. 可复现命令（项目根，Python 3.11+，零第三方依赖）

```powershell
$env:PYTHONPATH = "src"
# 全量测试（含本交付新增 tests/test_asset_model.py 74 项）
python -m unittest discover -s tests
# 离线端到端冒烟
python scripts\smoke_offline.py
# 记录式迁移（先备份再应用；幂等）
python -m research_library assets migrate --db data\research-library\library.sqlite
# 严格校验一条记录（文件格式 {"kind": ..., "record": {...}}）
python -m research_library assets validate --file <record.json>
# 播种最小 demo 资产链（必须显式 --db；拒绝含 works 行的库）
python -m research_library assets seed-demo --db <synthetic-demo.sqlite>
# 查看一条资产版本 / 运行适用性阻断判定
python -m research_library assets show --kind interaction_profile --asset-id demo-profile-support --revision 1 --db <demo.sqlite>
python -m research_library assets blockers --kind interaction_profile --asset-id demo-profile-support --revision 1 --db <demo.sqlite>
```

注意：`python -m research_library status` 等常规命令在打开库时会以幂等方式
补齐资产表（additive）；对既有库执行任何写入前，先运行 `assets migrate`
取得备份。

## 11. 实际验证范围与未决项

已验证（全部离线、合成数据，未调用模型、未访问网络）：

- 全量单元测试（既有套件 + 新增 74 项，共 436 项，0 failure/error，1 项既有
  skip）与离线冒烟通过。
- 全新数据库建表、pre-assets 旧库增量迁移（works/download_log/evidence_claims
  遗留行逐行不变）、迁移备份可恢复；生产库迁移已按上节执行并核验。
- 严格校验正/负路径：额外字段、可执行字段名、错误信封、修订算术、修订链
  改写/留洞、错误依据/评测引用、immediate 生效声明、AI 来源自我晋升、草稿
  冒充发布、demo 资产声明资格、未知条件放行写法全部被拒。
- demo 链播种幂等、诚实标记、评测闭合、内容哈希复算、阻断判定
  （draft/缺评测/撤回/演示资产）。
- 脱离源码目录的安装副本（整包复制到临时目录）中 schema 加载与校验通过。

未验证 / 未决项（不冒充完成）：

- 本层不实现运行核心、发布包与云端服务（Issue #17/#16/#19）；`condition_precheck`
  与 `asset_blockers` 是数据层语义定义，运行时行为待 #17 落地并回归。
- 真实方法资产未生产：demo 链仅是合成演示，不构成科研支持或教育有效性证据；
  研究支持的资产需待 #10 闭环产出获准结果、并经证据层（#14）提取后再以
  `research_supported` + 真实引用生产新版本。
- `release_eligibility` 从未被置为 `eligible`；真实发布决定按 CE-GS-01 治理
  流程执行（GS-D1/GS-D4 仍未决定，不代签）。
- 行为评测（E01–E16 全矩阵、三组比较）不在本交付范围；夹具只覆盖 E01/E05/
  E06/E11 的程序可检查子集，表达质量评价留待预写量表人工执行。
- 独立 wheel 安装的包资源完整性仍沿用 README 当前结论（`pyproject.toml` 已
  声明新增 package-data，但未做 wheel 构建验收）。
