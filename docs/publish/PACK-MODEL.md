# 最小私有专业能力包与撤回机制（Issue #16）

> 实现记录，2026-10-19。对应 Issue
> <https://github.com/lybym/ChildEvidence/issues/16>
> （`[P1][发布] 构建最小私有专业能力包与撤回机制`）。实现位于
> [publish.py](../../src/research_library/publish.py)、
> manifest 严格 schema
> [contracts/publish/manifest.schema.json](../../src/research_library/contracts/publish/manifest.schema.json)、
> CLI 入口 `research publish`（[cli.py](../../src/research_library/cli.py)），
> 测试 `tests/test_publish_pack.py`（51 项）。
> 本文档描述已实现的工程契约；它不声称任何科研结论、发布资格、真实批准或
> 规程生效。设计依据：
> [architecture.md](../design/growth-support-mvp/architecture.md) §2/§6、
> [contracts.md](../design/growth-support-mvp/contracts.md) §1、
> [GROWTH-SUPPORT-QUALIFICATION.md](../governance/GROWTH-SUPPORT-QUALIFICATION.md)
> §2/§5（六维分离与 GS-01…GS-06）。

## 1. 目的与边界

现有 `research export` 是书目导出：`works.jsonl` 会带出摘要、`raw_sources`、
`local_pdf_path` 与内部审核字段，不能交给任何消费插件。本层在
Evidence/Claim（Issue #14）与专业资产（Issue #15）之上实现**字段白名单发布器**：
把可独立校验、可私下分发的通用专业资产打成最小私有能力包，并提供差异报告、
原子激活与独立撤回账本。

明确不做（与 Issue #16 一致）：不上传现有 exports，不部署云平台（Issue #19），
不自动改变科研审核状态，不把合成包用于真实用户；构建器只**读取**资格状态，
不提供任何把 `release_eligibility`/`review_status` 置为通过的代码路径
（AGENTS #23；GS-D1 仍未决定）。不修改任何数据库表结构（无迁移）。

## 2. 包格式（全量不可变快照）

```
ce-pack-<pack_version>/
  manifest.json                  严格 schema manifest（内容哈希；无凭据）
  catalog.jsonl                  白名单书目元数据（metadata-only）
  evidence-cards.jsonl           可发布的 Claim 卡（含 relations/findings/
                                 source_versions/appraisals）
  strategies.jsonl               Strategy 资产版本（逐字复制，含 content_hash）
  methods.jsonl                  SupportMethod 资产版本
  interaction-profiles.jsonl     InteractionProfile 资产版本
  evaluation-cases.jsonl         EvaluationCase 资产版本
```

- 每次构建都是**全量快照**：一个资产 id 只携带一个 revision，不混读不同版本；
  包目录一经写入拒绝重建（PUB-Immutable），修正内容必须发布新 `pack_version`。
- `content_class`：`research_assets`（真实合格资产）或 `synthetic_demo`
  （合成演练）。两类内容互斥：release 包拒绝 demo 资产，demo 包只含
  `demo_only` 夹具；合成演练与真实资格始终隔离（GS 共同限制）。
- `eligible_for_real_user_delivery` 恒为 `false`（const）：本工具不签发
  "可用于真实用户" 的任何声明；真实使用批准属于治理与 #21。
- `rights`：`redistribution_scope=metadata_only`、不含全文/摘要
  （const `false`），并如实统计 `license_unknown_count`（AGENTS #7）。
- `compatibility`：声明 `assets_schema`/`evidence_schema`/`min_runner`；
  读取方按自身版本与 schema 集合校验（PUB-Schema/PUB-Runner）。
- `pack_hash`：对 manifest 主体（除 `pack_hash` 本身）的规范化 JSON 做
  sha256；六个 jsonl 文件各带逐字节 sha256 与记录数。

## 3. 白名单与扫描（验收 #1）

- catalog 记录由 `CATALOG_FIELDS` 白名单**投影**生成：摘要、原文提取字段
  （main_findings/effect_size 等）、`raw_sources`、`local_pdf_path`、URL 之外
  的本机路径、审核簿记（reviewer_notes/retrieval_errors 等）**不可表达**。
- `validate_catalog_whitelist` 在每次构建前自检：白名单本身若被加入
  `abstract`/`raw_sources`/`api_key` 等禁用字段即 fail-fast（PUB-Whitelist）。
- 每条打包记录（构建时与验证时都）经 `scan_record` 扫描：
  - 禁用字段名（PUB-Whitelist）：凭据类（api_key/secret/password/token/
    private_key/credential）、儿童记录类（subject_ref/child_profile/
    growth_record/diagnosis_record 等，AGENTS #14 与 GS-06）、
    `raw_sources`/`local_pdf_path`/`abstract` 等；works 内部簿记字段
    （`review_status`/`limitations`）仅对 catalog 记录禁用——同名FieldName
    是资产信封与 Appraisal 的合法必需字段。
  - 字符串值扫描（PUB-LocalPath）：Windows 盘符路径、UNC、POSIX 用户目录
    绝对路径；仓库相对指针（如 `docs/design/...`）是数据引用，不受限。
  - 凭据形态扫描（PUB-Secret）：`ghp_/gho_/sk-/AKIA…/PRIVATE KEY/xox…/Bearer …`。
- 资格：release 包只装 `lifecycle_status='released'` 且
  `release_eligibility='eligible'` 的非 demo 资产；被撤回资产两种模式都不装
  （PUB-Eligibility，GS-03）。构建期由选择查询排除并在报告里给出
  `excluded` 计数；verify 期按 `content_class` 对包内容再扫一遍，篡改或手工
  拼装的包同样被拒。证据卡只收具有 `eligible` Appraisal 的 Claim（AGENTS #20：
  未经 approved 的证据卡不进入已发布知识包）。

## 4. 完整性与兼容（验收 #2）

`verify_pack` 对包目录做全量重算，任何不一致都是具名 `PUB-*` 错误，不做静默修复：

| 规则 | 拒绝内容 |
|---|---|
| PUB-Manifest | manifest 缺失/坏 JSON/严格 schema 违例（`additionalProperties: false`，含注入 `api_key` 等字段）；counts/rights/files 投影与重算不符；`pack_hash` 与重算不符 |
| PUB-Hash | 文件缺失、逐字节 sha256 与 manifest 不符、记录数不符 |
| PUB-ForeignFile | 包目录出现 manifest 之外的文件 |
| PUB-Whitelist / PUB-LocalPath / PUB-Secret | 打包记录或 manifest 值中出现禁用字段/本机路径/凭据形态 |
| PUB-Dup | catalog/卡片/资产重复 ID；同一资产 id 出现在多个 kind |
| PUB-MixedRevision | 同一资产 id 的两个 revision 同时在包内 |
| PUB-Record | 资产记录未通过资产层严格校验（含 AS-Hash 内容哈希复算、additionalProperties 等） |
| PUB-Closure / PUB-Covers | 引用闭包：work 引用不在 catalog（或未 ingested）、claim 引用无卡、source_version 无卡携带、evaluation_ref/covers 指向包外版本 |
| PUB-Eligibility | 包内容与 `content_class` 矛盾（demo/draft/未合格/retracted 记录） |
| PUB-Schema / PUB-Runner | 包 schema_version 不受支持、schema 声明与读取方不符、runner 版本低于 `min_runner` |

清单可重算：`_expected_projection` 是构建与验证共用的唯一投影来源——相同记录
必然重建出相同的 files/counts/rights；`pack_hash` 覆盖 manifest 主体
（含 `built_at`），因此对固定 `built_at` 的重建是字节确定的。

篡改检测分两层：改一个字节 → 文件哈希失配（PUB-Hash）；改记录内容并**重盖**
文件哈希与 `pack_hash` → 记录级 `content_hash`（AS-Hash）失配（PUB-Record）。
内容哈希证明"构建后未被修改"，不证明来源——**内容哈希与发布者认证分开**：
manifest 的 `publisher` 只含引用名（`authentication: "external"`、
`credentials_embedded: false`），不携带任何密钥；发布者身份认证是独立信任通道
（部署决策属 Issue #19），验证内容哈希不需要它。

## 5. 原子激活与干净环境读取（验收 #3）

- `activate_pack(pack_dir, consumer_dir)`：先 `verify_pack`（失败即拒绝，不写
  任何状态）→ 通过 staging 目录完整复制到 `<consumer>/packs/<pack_id>/`（复制
  后再次 verify，失败即清理 staging）→ 最后以 `os.replace` 原子写入
  `ACTIVE.json`。激活失败不留下半版本：前一个激活版本原样可用，可原子切回
  （失败与回滚要求）；历史包与审计从不删除。
- `read_active` 每次读取都重新 verify，并要求 `ACTIVE.json` 的 `pack_hash`
  与包目录一致——把别的版本目录换进来而不重新激活会被拒绝（PUB-Active），
  不混读不同版本。
- 消费端读取不需要科研数据库：`pack_status` / `resolve_assets` 只用包文件与
  账本（干净环境测试将包复制到独立目录后读取）。

## 6. 独立撤回账本（交付范围 #4；GS-03）

- `retractions.jsonl` 与 `ACTIVE.json` 同级，**独立于包版本**更新：
  `append_retraction` 不触碰任何包文件，也不需要重新构建。
- 条目字段：`asset_id`、`revision`（int 或 null=资产级全版本撤回）、可选
  `content_hash` 绑定、`reason`、`decision_ref`、`retracted_at`；缺理由或缺
  决定引用被拒（PUB-Retract，GS-03），重复撤回同一 (asset_id, revision) 被拒
  （追加式、终态，不删除不回滚）。
- **优先级**：`resolve_assets` 对活动包的每个资产先查账本——撤回信息优先于
  版本固定与回滚：激活旧包（回滚）不能复活已撤回资产（资产级 `revision=null`
  撤回覆盖所有 revision；`content_hash` 绑定进一步收窄）。阻断码
  `PUB-Retracted` 与包级诚实标注（`PUB-SyntheticPack`/`PUB-DemoAsset`/
  `PUB-Lifecycle`）一起返回；`usable` 只在零阻断时为 true。
- 构建侧：库内已撤回资产不进入新包（`excluded` 报告）；覆盖它的评测案例若
  仍指向包外版本，构建以 PUB-Closure 拒绝——撤回通过闭包自然向上传播。

## 7. 可复现命令（项目根，Python 3.11+，零第三方依赖）

```powershell
$env:PYTHONPATH = "src"
# 全量测试（含本交付新增 tests/test_publish_pack.py 51 项）
python -m unittest discover -s tests
# 离线冒烟
python scripts\smoke_offline.py

# 构建合成演练包（合成库；release 模式省略 --mode，要求资产合格）
python -m research_library assets seed-demo --db .tmp-test\demo.sqlite
python -m research_library publish build --db .tmp-test\demo.sqlite --out .tmp-test\packs --pack-version 2026.10.19-demo.1 --mode synthetic-demo
# 构建 release 包（默认 --mode release；catalog 为引用闭包，metadata-only）
python -m research_library publish build --db <library.sqlite> --out <packs> --pack-version <v> --publisher-ref <ref>

# 校验 / 差异 / 激活 / 状态 / 撤回 / 消费端读取
python -m research_library publish verify --pack <packs>\ce-pack-<v>
python -m research_library publish diff --from <packs>\ce-pack-<v1> --to <packs>\ce-pack-<v2>
python -m research_library publish activate --pack <packs>\ce-pack-<v> --consumer-dir <consumer>
python -m research_library publish status --consumer-dir <consumer>
python -m research_library publish retract --consumer-dir <consumer> --asset-id <id> [--revision N] --reason "<理由>" --decision-ref "<决定引用>"
python -m research_library publish read --consumer-dir <consumer>
python -m research_library publish read --consumer-dir <consumer> --kind strategy --asset-id <id> --revision 1
```

## 8. 实际验证范围与未决项

已验证（全部离线、合成数据，未调用模型、未访问网络；`tests/test_publish_pack.py`
51 项 + 全量 487 项 0 failure/error、1 项既有 skip，离线冒烟与 status 通过）：

- 白名单负向：欺诈白名单、禁用字段名、本机路径（盘符/UNC/POSIX）、凭据形态、
  资产信封同名字段回归（review_status/limitations 合法性）、release 包排除
  未合格/demo 资产、verify 拒绝 content_class 矛盾的包、manifest 注入
  api_key/本机路径被拒；built pack 目录断言无 abstract/raw_sources/
  local_pdf_path，catalog 键集恰为白名单。
- 完整性负向：文件字节篡改、重盖 manifest 的记录篡改（AS-Hash 捕获）、
  重复 ID、混版、未 ingest 引用闭包、verify 期闭包、外来文件、缺文件、
  counts 篡改、`ce.pack/2` schema、runner 低于 min_runner；投影确定性
  （相同记录 → 相同 files/counts/rights）。
- 激活与撤回：干净环境复制读取、激活失败（篡改包）不动 ACTIVE.json 且不落
  半版本、换包目录被 PUB-Active 拒绝、资产级/revision 级撤回阻断、回滚到
  旧包不复活撤回资产、重复撤回/缺理由/坏条目被拒、账本独立于激活版本。
- diff：revision 变更/新增/移除报告；CLI 端到端
  build→verify→activate→status→retract→read→diff。

未验证 / 未决项（不冒充完成）：

- 未构建真实资产包：库内无 `eligible` 资产（`release_eligibility` 从未被置为
  eligible；GS-D1/GS-D4 未决定），release 路径由合成合格夹具验证。
- 发布者认证未实现（设计上外置）：`pack_hash` 检测构建后修改，不认证来源；
  签名/通道属 Issue #19 部署决策。
- 云端查询/版本服务、运行核心消费（#17/#19/#20）不在本层；
  `resolve_assets` 是包边界判定，运行时行为待 #17 落地回归。
- wheel 安装的包资源完整性沿用 README 既有结论（pyproject 已声明
  `contracts/publish/*.schema.json`，未做 wheel 构建验收）。
