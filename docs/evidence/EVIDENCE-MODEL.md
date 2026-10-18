# Evidence/Claim 领域模型与来源版本契约（Issue #14）

> 实现记录，2026-10-18。对应 Issue
> <https://github.com/lybym/ChildEvidence/issues/14>
> （`[P1][领域] 建立 Evidence/Claim 模型与来源版本契约`）。实现位于
> [evidence.py](../../src/research_library/evidence.py)、
> [contracts/evidence/](../../src/research_library/contracts/evidence/)，
> 存储接入 [db.py](../../src/research_library/db.py)，CLI 入口
> `research evidence`（[cli.py](../../src/research_library/cli.py)）。
> 本文档描述已实现的工程契约；它不声称任何科研结论、发布资格或规程生效。

## 1. 目的与边界

在既有书目事实源（`works` 表，SQLite）之上建立**可独立演进的科研语义层**：
区分 Work / SourceVersion、Study 关联、研究问题（RQ）、Finding、Claim、证据关系
与 Appraisal；把证据方向（支持/反证/证据不足）、科学质量、人工审核来源与发布
资格保持正交。支持无 DOI 的报告/调查来源（所有关系引用 `works.internal_id`，
从不引用 DOI）。

明确不做（与 Issue #14 一致）：不生产个体诊断、不写儿童档案、不自动提升
Gold、不做全库迁移填充或发布策略；解析加工（CE-03）缺陷另行处理，不与本
模型捆绑（AGENTS #20）。

## 2. 领域对象

| 对象 | 存储 | 语义要点 |
|---|---|---|
| Work | 既有 `works` 表（不改动） | 书目事实源；Work ≠ Study |
| ResearchQuestion | `evidence_research_questions` | 同一 Work 可挂在多个 RQ 下；version 数值 ≥1 |
| Study | `evidence_studies` | 研究分组；`study_key` 可空（未知保留 null） |
| StudyReport | `evidence_study_reports` | 同一研究的多篇报告/Work 关联；复合主键去重 |
| SourceVersion | `evidence_source_versions` | Work 的一个具体来源版本：原件版本标签/哈希、解析版本哈希、定位验证状态；未知一律 null |
| Finding | `evidence_findings` | 研究条件下的观察；`attributes` 严格白名单键；未核实字段为 null |
| Claim | `evidence_claims` | 可评价主张；不是教育行动或儿童画像 |
| Relation | `evidence_relations` | Claim↔Finding 的 supports / refutes / insufficient；每对 (claim, finding) 唯一 |
| Appraisal | `evidence_appraisals` | 科学质量/偏倚/局限/适用性 + 审核来源 + 审核状态 + 发布资格，全部与证据方向正交 |
| LocatorCheck | `evidence_locator_checks` | 追加式定位验证事件；`verified` 只能来自显式核验 |

### 2.1 正交分离（交付范围 #3）

- **证据方向**只在 `evidence_relations.relation`（supports/refutes/insufficient）。
- **科学质量**在 `evidence_appraisals.quality/biases/limitations/applicability`。
- **人工审核**在 `review_origin`（`single_human` / `independent_double_human` /
  `adjudicated_human` 为人工来源；`ai_draft` / `multi_model_consistent` 永远不是）与
  `review_status`。
- **发布资格**在 `release_eligibility`，默认 `not_eligible`；代码不提供任何把它
  自动置为 `eligible` 的路径。校验规则 `EV-Release`：`eligible` 要求人工审核
  来源 + `review_status='human_reviewed'`（对齐 GS-02：AI 一致性永不自我晋升）。
  真实发布决定仍由 CE-GS-01（GS-01…GS-06）治理，本字段只是粗粒度状态。

### 2.2 定位验证与 bbox（交付范围 #2）

`evidence_source_versions.locator_status ∈ {unknown, unverified, verified, failed}`，
初始 `unknown`。状态只能通过追加 `evidence_locator_checks` 事件更新：

- `result='verified'`：仅限非 bbox-only 方法（如 `page_anchor_match`），且必须
  携带非空 `details`；把状态置为 `verified`。
- `result='failed'`：置为 `failed`。
- `result='detected'`（bbox/坐标检测）：仅把 `unknown` 细化为 `unverified`，
  永远不会升级为 `verified`，也不会清除 `verified`/`failed`——bbox 存在不等于
  定位准确（与 CE-03 审计结论一致）。

规则 `EV-Locator` 在校验入口直接拒绝"bbox 检测被记为 verified"或
"verified 无 details"的记录。

## 3. 严格校验入口（交付范围 #4）

- 记录信封：每条记录携带 `schema_version`，当前为 `ce.evidence/1`。
- 九份严格 JSON Schema 位于包资源
  `research_library/contracts/evidence/*.schema.json`，经
  `importlib.resources` 加载（`evidence.load_schema(kind)`），因此**脱离仓库
  checkout 的安装副本同样可加载**（见 `tests/test_evidence_model.py::IndependentInstallTests`）。
- `evidence.validate_record(kind, record)` 与存储层
  `evidence.insert_record(conn, kind, record)` 共用同一套规则。
- 每份 Schema 声明 `additionalProperties: false`；校验器实现
  `additionalProperties`、`minimum`/`maximum`、`pattern`、长度/条数边界、
  `const`/`enum` 等关键字。

### 3.1 为什么不能复用 `governance.validate`

`research_library.governance.validate` 是 CE-01R 契约的最小子集校验器，**忽略
`additionalProperties` 与数值边界**——非法额外字段和越界数值会被静默放行
（Issue #14 验收 #2 明确禁止）。`tests/test_evidence_model.py` 中
`test_governance_validator_would_silently_pass` 用同一记录对比证明：partial
校验器返回空错误，严格入口拒绝。

### 3.2 拒绝规则（EV-*）

| 规则 | 拒绝内容 |
|---|---|
| 信封 const/required | 缺少或错配 `schema_version`（如 `ce.evidence/2`） |
| additionalProperties=false | 任何未声明字段（含嵌套 `attributes` 白名单键） |
| minimum/maximum | `version<1`、`sample_size<1` 或 `>10^9` 等 |
| EV-Fields | `parsed_sha256` 与 `parsed_format` 必须成对（诚实绑定） |
| EV-Dup | 重复主键、重复 (claim, finding) 关系对、重复 study_report 对、重复 (study, source_version, statement) 发现、数据库约束兜底 |
| EV-Ref | 引用不存在的 work/study/source_version/RQ/claim/finding/appraisal target |
| EV-Version | 绑定 Work 已记录的同一原件文件（sha256 相同）却声明不同版本标签；不同文件版本（如预印本）是合法的第二个 SourceVersion |
| EV-Locator | bbox-only 方法记为 verified；verified 缺 details |
| EV-Release | 非（人工来源 + human_reviewed）却声明 eligible |

### 3.3 不重复计证（验收 #1）

`evidence.evidence_summary(conn, claim_id)` 按 **distinct study** 计数：同一研究
的多篇报告/多个来源版本产生的多条 Finding 合并为一个研究，同时保留
finding 级计数供审计。`supports/refutes/insufficient` 分列，矛盾证据自然表达。

## 4. 迁移与兼容（验收 #3；失败与回滚）

- 新表 DDL 全部 `CREATE TABLE IF NOT EXISTS`，**不改动 `works` 与任何既有表**；
  `db.connect()` 每次执行合并后的 SCHEMA，旧库与新库在打开时即收敛到同一结构。
- 正式迁移入口：`python -m research_library evidence migrate [--db PATH]`
  （`evidence.migrate_with_backup`）：**先用 SQLite backup API 生成备份**
  `<db 目录>/backups/pre-evidence-migration-<UTC>-<rand>.sqlite`，再应用 DDL，
  最后 `PRAGMA integrity_check`。恢复路径：直接以备份文件替换/复制回原路径。
- 兼容性测试：`UpgradeCompatibilityTests` 用 pre-evidence 结构建库、写入遗留
  行，迁移后逐行比对 `works` / `download_log` 完全不变、旧 `internal_id`
  不变，备份文件可打开且含相同行；`FreshDatabaseTests` 覆盖全新建库。
- 没有写入任何生产迁移数据填充；不回填历史馆藏。

## 5. Issue #10 结果映射（验收 #4）

入口：`python -m research_library evidence map-pilot --run-dir
data/review/astra-pilot/<run_id> [--apply]`（`evidence.map_pilot_run`）。

映射语义（诚实优先）：

- 读取运行目录的 `audit.json`（必须携带 `astra-pilot-audit/*` 信封与 Issue #10
  URL）与 `review.json`；从 `original_available` 条件提取原件 PDF sha256。
- 生成一条 SourceVersion：`version_id = sv-pilot-<run_id>`（幂等，重复映射报
  `already_mapped`，不产生重复）；`source_kind='unspecified'`；
  `origin='pilot_mapping'`；`origin_ref=<run_id>`。
- **刻意保留 unknown**：`parsed_sha256/parsed_format`（运行记录无已核验解析产物
  绑定）、`study_id`（无研究提取记录）、`locator_status='unknown'`（无定位核验；
  绝不从 bbox/文件存在性推断）。
- **不映射科研内容**：Findings/Claims/Appraisals 一律不生成——blocked 运行未做
  模型审查；即使未来出现 completed envelope，内容映射也需人工批准的提取流程。
  不确定性代码原样保留在记录 notes 中。

当前实际状态（诚实记录）：#10 的最新记录
`ce06-20261018T151352Z-f7be692e`（Work `lt-1ae2bbde5d0f`）为 **BLOCKED**
（权限/门禁/环境/身份等 8 项条件缺失，`model_review_performed=false`），
**尚不存在获准的模型审查结果**。因此本交付映射的对象是该次 BLOCKED 尝试的
真实运行记录，缺证字段全部诚实未定；待 #10 产出获准结果后，可用同一命令
映射其来源版本（科研内容映射仍需人工批准流程）。此为明确登记的未决项，
不以代码存在推定验收完成。

## 6. 可复现命令（项目根，Python 3.11+，零第三方依赖）

```powershell
$env:PYTHONPATH = "src"
# 全量测试（含本交付新增 tests/test_evidence_model.py 36 项）
python -m unittest discover -s tests
# 离线端到端冒烟
python scripts\smoke_offline.py
# 记录式迁移（先备份再应用；幂等）
python -m research_library evidence migrate --db data\research-library\library.sqlite
# 严格校验一条记录（文件格式 {"kind": ..., "record": {...}}）
python -m research_library evidence validate --file <record.json>
# #10 运行映射：先干跑查看，确认后 --apply
python -m research_library evidence map-pilot --run-dir data\review\astra-pilot\<run_id>
python -m research_library evidence map-pilot --run-dir data\review\astra-pilot\<run_id> --apply
# 某 Claim 的证据摘要（按 distinct study 计数）
python -m research_library evidence summary --claim-id <claim_id>
```

注意：`python -m research_library status` 等常规命令在打开库时会以幂等方式补齐
新表（additive）；对既有库执行任何写入前，先运行 `evidence migrate` 取得备份。

## 7. 实际验证范围与未决项

已验证（全部离线、合成数据，未调用模型、未访问网络）：

- 全量单元测试（既有套件 + 新增 36 项）与离线冒烟通过；结果摘要见 PR 描述。
- 全新数据库建表、pre-evidence 旧库增量迁移（遗留行/旧 ID 逐行不变）、迁移
  备份可恢复。
- 严格校验正/负路径：额外字段、数值边界、重复键、错引用、错版本、bbox 冒充
  verified、AI 来源自我晋升全部被拒；partial 校验器静默放行行为有对比测试。
- 脱离源码目录的安装副本（整包复制到临时目录）中 Schema 加载与校验通过。
- #10 映射：合成运行目录干跑/幂等 apply 测试通过。

真实环境执行（只读 + 备份 + 一条新表记录）：

- `evidence migrate --db data\research-library\library.sqlite`：生成
  `data\research-library\backups\pre-evidence-migration-*.sqlite` 备份后应用，
  `integrity_check=ok`；`works` 等既有表零改动。
- `evidence map-pilot --run-dir data\review\astra-pilot\ce06-20261018T151352Z-f7be692e`
  干跑 + `--apply`：映射 SourceVersion `sv-pilot-ce06-20261018T151352Z-f7be692e`
  （Work `lt-1ae2bbde5d0f`，原件 sha256 `9c48bd…c0c`，`original_version=
  published_version` 与库记录一致；`parsed_*`/`study_id`/`locator_status` 全部
  保持未知），未生成任何 Finding/Claim/Appraisal。

未验证 / 未决项（不冒充完成）：

- #10 尚无获准的模型审查结果；获准结果的来源与科研内容映射待 #10 闭环后执行。
- 生产库中尚无 Study/Finding/Claim 等科研内容记录（等待获准结果与人工批准的
  提取流程）；`evidence summary` 仅为工具验证，未对真实 Claim 执行。
- 定位验证（`verified` 状态）未对真实 PDF 执行；解析产物哈希绑定待 CE-03 解析
  产物接入后补齐。
- 发布资格（`eligible`）从未被设置；真实发布决定仍按 CE-GS-01 治理流程执行。
