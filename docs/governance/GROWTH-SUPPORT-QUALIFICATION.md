# GROWTH-SUPPORT-QUALIFICATION.md — 成长支持首包资格与人格演进决策记录

> 状态：**DRAFT 2026-10-18（治理决策登记与路线比较）** — 对应 Issue
> [#11](https://github.com/lybym/ChildEvidence/issues/11)。
> **待真实决定，未生效**：本文件是决策登记与提案，不是生效声明；除标注
> `decided_documentation` 的结构性记录外，任何条目都**不改变现行门禁**。
> Agent 不得据此放行未审核资产，**不代签**批准，不代填、不关闭
> [#2](https://github.com/lybym/ChildEvidence/issues/2) 或
> [#10](https://github.com/lybym/ChildEvidence/issues/10)，不冒充完成。
> 机器可校验契约：
> [docs/governance/contracts/CE-GS-01-qualification-decisions.contract.json](contracts/CE-GS-01-qualification-decisions.contract.json)
> （校验器 `research_library.governance`；测试 `tests/test_growth_support_governance.py`）。
> 源码审计基线：`57b309e91610449ea8025099f414e325e7b70e10`；治理衔接见
> [GROWTH-SUPPORT-TRANSITION.md](GROWTH-SUPPORT-TRANSITION.md)。

## 1. 范围与依据

本文件处理 Issue #11 的三类内容：

1. 比较首包资格两条路线并登记决定状态（§3，GS-D1）；
2. 把资料处理权限、技术校验、科学评价、审核来源、发布资格与个体适用性
   分离表达，不增加没有实际作用的重复审批（§2）；
3. 把人格/表达登记为可追溯、需评测的版本资产提案，并给出更新、撤回、
   未审核拒绝与两类数据边界的可执行正负向验收标准（§4、§5）。

依据：AGENTS #16/#18/#20/#23、KNOWLEDGE_GOVERNANCE §2–§5（DRAFT v1.1）、
CE-01R 契约族（label-tiers、decision-scope）、设计文档
[contracts.md](../design/growth-support-mvp/contracts.md) §1.1 与
[delivery-plan](../design/growth-support-mvp/delivery-plan.md) §5（D1/D2）。
继续复用现有 Python/SQLite、CE-03 解析、生产侧 Reviewer 与权限预检，不推倒重写；
技术实施属于依赖任务（#12/#14/#15/#16），本文件不实现业务代码。

## 2. 六维分离（decided_documentation）

六维彼此正交；一项检查只服务一个维度，禁止用重复执行同一检查充当另一维度的
审批。本节是对既有约束的重述与细分，不新增门禁，不需签署。

| 维度 | 定义与判定 | 判定责任 | 与相邻维度的去重 | 现有依据 |
|---|---|---|---|---|
| 资料处理权限 | 哪些来源可被读取、解析、外发给模型 | 权限登记 + 预检（POLICY_ACTIVE=False） | 有权限处理 ≠ 已审核 ≠ 可发布；不重复建审批链 | AGENTS #6/#8；model_access 登记 |
| 技术校验 | 结构、引用、哈希与可执行状态 | 生产侧自动检查 + 留痕 | 结构正确 ≠ 科研结论成立 | contracts.md §1.1；manifest 哈希复算 |
| 科学评价 | 质量、偏倚、局限、不确定性 | 科研评价记录（Appraisal） | 与模型自信、审核来源分开；允许争议与不足 | RESEARCH_METHODOLOGY 证据分级；Appraisal 对象 |
| 审核来源 | 实际审核方式：AI / 单人 / 独立人工 | 如实标记 review_origin，不伪造身份 | AI 一致性 ≠ 人工 Gold ≠ 发布资格 | AGENTS #18；LT-03/LT-04 |
| 发布资格 | 依据哪一版治理规则、允许什么用途、由何记录决定 | 治理决定记录（本文件 §6 登记） | 任一单项通过都不构成发布资格 | KNOWLEDGE_GOVERNANCE §2–§4；GS-01..GS-05 |
| 个体适用性 | 当前情境是否具备使用条件 | 运行时判定 | 个体适用 ≠ 提升科研等级或证据强度 | contracts.md §1.1；AGENTS #4 |

## 3. 首包资格两条路线比较（GS-D1：pending_human_decision）

| | 路线 A：保留人工发布资格 | 路线 B：低风险私有 AI 审查试用资格（提案） |
|---|---|---|
| 状态 | **现行门禁，继续有效**（依 AGENTS/KNOWLEDGE_GOVERNANCE 现行规则） | **未被预先选择**；启用须真实决定并完成同版本规程修订 |
| 适用用途 | 真实发布（含真实儿童/家长/教师使用）前的全部资产 | 低风险、私有研究试用的受限资产；不含真实发布、正式行为资产或批量审查 |
| 实际审核方式 | Evidence 层领域审核人 approved（L3/gold）→ 知识负责人版本发布（manifest 哈希）→ 产品负责人显式批准 + 回归评测 | 技术校验单独留痕；AI 审查如实标记 review_origin（ai_draft / multi_model_consistent），不伪造人工身份；用途限定 + 未验证部分显式声明 |
| 批准条件 | CE-01R-CHECKLIST 人工签署；gold 资格流程（独立双人或裁决 + 签署）；人工复核资源按 GS-D2 落实 | 用户真实决定启用并明确用途清单；四份规程、AGENTS、契约同版本修订并过一致性测试；保留未验证声明 |
| 未验证部分 | 现实阻塞：当前无第二名人工 Reviewer（R9）；四份规程仍 DRAFT 待签 | AI 审查的科学效度无独立人工验证；AI 一致性不能产生人工 Gold；长期行为影响与个体适用性未验证 |

共同限制（两条路线下都成立）：

- AI 草稿维持 silver/L0、`not_reviewed`，不得进入真实发布或 Agent 正式行为资产；
- 多模型一致投票 ≠ 专家共识 ≠ 人工 Gold（AGENTS #18；LT-03/LT-04；契约 GS-02）；
- 合成工程演练（`demo-*`）始终与真实发布隔离，不赋予任何资产真实资格。

## 4. 人格与表达作为版本资产（提案依据；生效须 GS-D4）

现状：KNOWLEDGE_GOVERNANCE §2（DRAFT v1.1）写明"人格原则不在可变更范围"。
本节登记修订提案，**不直接修改该规程**；修订须 GS-D4 真实决定后按 §6 生效动作执行。

提案内容（decided_documentation 层面记录方向）：

- 人格/表达 = `InteractionProfile` 版本资产：稳定 ID + 不可变修订 + 内容哈希 +
  显式发布动作；引用携带目标修订，不只写显示名称（contracts.md §1）。
- 依据四分：`direct_research`（直接研究支持）/ `research_synthesis`（综合）/
  `application_inference`（应用推导）/ `design_choice`（设计选择）；
  研究支持、综合推导与设计选择明确区分，价值与交互偏好不得伪装成实证结论。
- 新研究**不直接改变运行行为**：运行时只应用已发布版本；任何版本（含首版
  revision=1）都必须携带依据与评测引用（EvaluationCase，覆盖对应资产版本），
  只能作为新版本发布生效，不存在 immediate 改写运行行为的版本豁免（契约 GS-04）。
- 稳定人格不随一次模型推理漂移；更新与回滚保留旧版本与变更理由。

## 5. 可执行正负向验收标准（契约规则 GS-01…GS-06）

机器可校验形态见
[CE-GS-01-qualification-decisions.contract.json](contracts/CE-GS-01-qualification-decisions.contract.json)
（内嵌 schema、正例必须通过、负例必须按规则码失败）。

| 规则 | 正向（允许通过） | 负向（必须拒绝/报错） |
|---|---|---|
| GS-01 发布资格签署 | approved 携带 approved_by、approved_date 与 decision_record_ref | 缺签署、缺日期或缺决定记录引用 |
| GS-02 审核来源与 AI 一致性 | approved/revoked 携带人工审核来源（single_human / independent_double_human / adjudicated_human）；AI 来源记录停留在 pending，如实标记 | `ai_draft`/`multi_model_consistent` **或来源未标记（null/unknown）**出现 approved/revoked |
| GS-03 发布撤回 | revoked 携带理由、日期与决定引用；保留原 revision 与审计链 | 无理由/日期的撤回；以删除代替追加式撤回（见下方局限登记） |
| GS-04 人格资产版本 | InteractionProfile **任何版本（含首版）**携带 basis_refs 与 evaluation_refs，`runtime_effect=new_version_release` | 任一版本缺评测引用或依据；声明 `immediate` 直接改写运行行为（无版本豁免） |
| GS-05 未审核拒绝 | approved 前置 technical_validation=passed 且 scientific_appraisal=done | 校验未跑/评价未做却 approved |
| GS-06 两类数据边界 | research_library 不携带 subject_ref；personal_growth_record 由宿主管理且支持纠正删除 | 科研库混入个人主体引用；个人记录无宿主管理与纠正能力 |

已登记局限（契约 `known_limitations`，如实声明单记录校验的边界）：

- **GS-LIM-01（跨记录语义）**：本契约与单记录校验器无法检测删除历史版本、
  改写 revision 链或以删除代替追加式撤回；这些语义由后续实现任务
  （#12/#14/#15/#16 的发布器与审计层）做跨记录校验。单记录校验通过不等于
  版本链完整性已证明。
- **GS-LIM-02（决定记录引用）**：GS-01 的 `decision_record_ref` 仅作存在性
  检查，其指向记录的真实性由人工治理流程与审计保证；approved 同时要求人工
  review_origin 以收窄伪造面。

两类数据边界语义：

- **research_library（科研库）**：SQLite 唯一事实源；追加式审计不删除
  （AGENTS #2）；不收儿童个人档案（AGENTS #14）；下游只经版本化知识包消费
  （AGENTS #15）。
- **personal_growth_record（个人成长记录）**：宿主管理落盘、授权、导出、
  纠正、删除与保留期限；默认不回流科研库、训练或评测数据集
  （contracts.md §5）；不同主体严格隔离。

## 6. 未决问题登记（全部 pending_human_decision；不代填、不关闭）

| decision_id | 事项 | 选项 | 理由与适用范围 | 生效动作 |
|---|---|---|---|---|
| GS-D1 | 首包资格路线（§3） | A：保留人工发布资格；B：启用低风险私有 AI 审查试用 | 路线 B 未预先选择；两条路线的用途、审核方式、批准条件与未验证部分见 §3；适用于全部成长支持资产发布 | 由用户/负责人真实决定后，同版本修订四份规程、AGENTS、治理契约并过一致性测试 |
| GS-D2 | [#2](https://github.com/lybym/ChildEvidence/issues/2) 人工盲法复核任务继续、缩小或延期 | 继续 80 项 / 缩小样本并明确抽样与外推边界 / 延期并如实登记 HUMAN_REVIEW_PENDING | AI 结果不得代替人工完成；保留原 Issue 历史与语义；适用于 CE-02 人工标注与 Gold 升级路径 | 由负责人在 #2 内登记决定；本文件不直接修改或关闭该 Issue |
| GS-D3 | [#10](https://github.com/lybym/ChildEvidence/issues/10) 是否保留 Astra 限定 | 保留 / 改为按真实服务/环境/模型身份管理 | 不用平台名称泛化授权；模型身份须有可核验依据，未知记 unknown；适用于 Reviewer 契约与 #10 权限预检 | 由负责人在 #10 内登记决定；本文件不直接修改或关闭该 Issue |
| GS-D4 | 人格资产演进规程修订（KNOWLEDGE_GOVERNANCE §2 等） | 按 §4 提案修订 / 保持"人格原则不在可变更范围" | 现行 DRAFT 文本与产品方向冲突；修订须同版本演进、保留批准历史与变更理由 | 由用户/负责人真实决定后执行同版本修订；不代签、不改写签署或历史结论 |

## 7. 失败与回滚

- 决策未达成：保持当前门禁（路线 A；AI 草稿不发布），不创建替代性"形式化按钮"。
- 修订必须保留旧版本与变更理由；不改写签署或历史结论（先例：
  [CE-01R-ERRATA.md](CE-01R-ERRATA.md) 勘误索引模式——原记录不改动，新增权威指针）。
- 契约或一致性测试失败：修复或回滚本分支；不影响既有 CE-01R 契约与 label-tiers
  语义（历史标签含义不改写；AI 一致性不能产生人工 Gold 的既有约束不变）。

## 8. 验证范围与未决项

已验证（离线、只读仓库文件）：

- 契约 envelope、schema、正例/负例与 GS-01…GS-06 规则一致性：
  `tests/test_growth_support_governance.py`；
- 治理文档集一致性（含本文件标记、六维、未决登记与 #2/#10 引用）：
  `tests/test_governance_contracts.py` 与新增测试均通过；
- 四份规程保持 DRAFT v1.1 未改动；历史数字与签署记录未改写
  （既有 errata/POC 指针检查通过）；
- 单记录校验的已知局限（跨记录追加性/版本链不可变、decision_record_ref
  真实性）已在 §5 与契约 `known_limitations`（GS-LIM-01/GS-LIM-02）登记，
  由后续实现任务的跨记录审计承接；本文件不宣称这些语义已被本契约覆盖。

可复现命令（项目根）：

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests
python scripts\smoke_offline.py
python -m research_library status
```

未验证/不在本任务范围：未读取或发布论文原文；未激活模型出站；未批量科研
审查；未执行真实儿童试用；GS-D1…GS-D4 全部未决定；路线 B 的科学效度无独立
验证。代码或契约存在不等于真实验收或科研批准完成。
