# 获准最小包与 Reviewer 契约验证报告（Issue #12）

> 状态：验证记录，2026-10-18。对应 Issue
> <https://github.com/lybym/ChildEvidence/issues/12>
> （`[P0][科研] 接通获准最小包与 Harness 中立的 Reviewer 契约`）。
> 契约与运行说明见 [MODEL-ACCESS](../../review/MODEL-ACCESS.md)；
> 实现位于 [model_access.py](../../../src/research_library/model_access.py)、
> [review_contract.py](../../../src/research_library/review_contract.py) 与
> [Skill 薄适配器](../../../.agents/skills/child-evidence-reviewer/scripts/validate_review.py)。
> 本报告只声明实际执行过的验证；代码或契约存在不推定真实验收、激活或科研批准完成。

## 1. 验证环境与基线

| 项 | 值 | 来源 |
|---|---|---|
| 代码基线 | `master` = `659e97d`（Issue #13 合并后） | 本地 fast-forward 后与 `origin/master` 一致 |
| Python | 3.12.14 | DeepSeek Harness 自带运行时（系统 PATH 无 Python，与 [#13 报告](../dsh-seam-verification/REPORT.md)记录一致） |
| 契约版本 | review-result schema v1，`skill_version` 0.2.0（向后兼容 0.1.0） | schema 放宽 + 兼容测试 |
| 门禁 | `model_access.POLICY_ACTIVE = False`，全程未改 | 代码检查 + 负例测试 |

全部验证离线、合成数据；未读取任何论文摘要/正文/PDF、未调用任何模型、无网络访问（测试含 `socket.socket` 禁用断言）。

## 2. 实际执行的验证与结果

| 命令（项目根） | 结果 |
|---|---|
| `python -m unittest discover -s tests` | **298 项全部通过**（1 项既有 skip，与本改动无关；基线为 282 项） |
| `python scripts\smoke_offline.py` | SMOKE_OFFLINE PASS |
| `python -m research_library status` | 正常；科研库计数未变化（本次改动零数据库写入路径） |

新增测试 `tests/test_review_contract_package.py`（16 项）覆盖完整链路：登记 → `prepare`（补丁激活态）→ 包 → `preflight`/`validate`（契约侧复核）。`POLICY_ACTIVE` 仅在测试作用域内 patch，且每条链路都断言门禁关闭时的 blocked 语义。

### 2.1 验收条件 1：九类合成负例

| 负例 | 覆盖（测试） |
|---|---|
| 未登记 | 空登记表、伪造 run 目录、复制出审计位置、纯 .txt 冒充包均 blocked（`test_unregistered_and_tampered_packages_blocked`） |
| 错哈希 | 包字节篡改 → 审计 `output_sha256` 不匹配；引文 `source_hash` 不匹配被拒（同上） |
| 错范围 | 登记区间收窄后校验侧重核失败；`prepare` 区间越界（`test_registry_changes_reverified_at_validation_time`、既有 `test_wrong_bindings_and_excluded_ranges_block`） |
| 错服务环境 | 登记环境变更 → 校验侧 blocked；`prepare` 环境不匹配（同上 + 既有用例） |
| 撤销 | 追加 `restricted` 后最新决定生效，包立即失效（`test_registry_changes_reverified_at_validation_time`、既有 `test_derivative_mutation_and_revocation`） |
| 政策变化 | `policy_version` 变更 blocked；`POLICY_ACTIVE=False` 时一律 `policy_not_active`（同上 + `test_gate_closed_blocks_package_without_activation`） |
| 注入 | 包内"ignore prior instructions"文本按数据处理：精确引用通过、改写拒绝；审查保持 silver/L0/not_reviewed（`test_injection_is_data_not_instructions`） |
| 派生文本绕过 | Docling/审查容器/改名文件不能取得包资格（既有 `test_policy_change_unregistered_and_container_rejected`）+ 本链路位置/审计/选择器复核（同上） |
| 许可范围超出 | scope 越界、区间越界、abstract-only 登记下请求 article_text 均 blocked（`test_scope_and_license_excess_blocked_at_prepare`） |

### 2.2 验收条件 2：范围交付与模型身份

- 允许路径仅交付本次范围：包只含登记区间内片段；段长度与声明偏移一致、段落与审计 `ranges` 一致（`verify_package`）。
- 引用回指同一源版本：引文 `source_hash` 必须等于包文件哈希；`preflight` 的 `selection_hash` 绑定已核验绑定，登记变化即失效。
- requested/actual model 分开：`prepare --requested-model-id/--model-id` 分别绑定入包与审计；review 与包绑定强制一致（`test_requested_and_actual_model_binding`）。
- 未知保持 unknown：包未绑定模型时审查可 unknown 通过；声称已核实其他模型被拒（`test_unbound_package_keeps_unknown_and_rejects_verified_claim`）；无效模型身份使 `prepare` blocked（`test_invalid_model_identity_blocks`）。
- 用途绑定：review `mode` 与包 `mode` 不一致被拒（`test_mode_purpose_binding`）。

### 2.3 验收条件 3：兼容性与可复现步骤

- 既有 282 项测试全部通过：历史结果 envelope（`gpt-6-astra`、`codex_session`、0.1.0）与预检拒绝语义兼容（`test_legacy_result_format_remains_valid`、`tests/test_ai_review_skill.py` 42 项）。
- 科研库/PDF/人工记录未改动：全链路无数据库写入路径；`status` 输出与基线一致。
- #10 可复现运行步骤见 [MODEL-ACCESS §供 #10 的可复现运行步骤](../../review/MODEL-ACCESS.md)。

### 2.4 验收条件 4：文档与声明

本报告、[MODEL-ACCESS](../../review/MODEL-ACCESS.md)（契约与 #10 步骤）、[Skill 文档](../../../.agents/skills/child-evidence-reviewer/SKILL.md)（0.2.0，中立化措辞）随本 PR 交付；验证范围、失败与未决项如下节。

## 3. 实际验证范围声明

已验证：上述合成、离线、只读链路；契约向后兼容；门禁关闭语义。测试期间未调用科研模型、未读取真实受限内容、未修改 `data/`、`exports/` 或生成快照。

## 4. 失败与未决项

- 本次交付的测试无失败用例；全量 298/298 通过。
- 未验证（明确不冒充完成）：真实模型调用与真实模型身份核验；真实 PDF/Docling 内容的包构建；真实登记数据与权利依据；DSH 宿主端到端消费科研包（[#13](https://github.com/lybym/ChildEvidence/issues/13) 验证的是插件接缝，不是本科研链路）。
- 未决项：宿主侧"仅含获准包的受控工作区"进程隔离在真实激活时落地（只读文件属性不冒充隔离，代码内边界是包目录最小交付单元 + 校验侧全量复核）；GS-D3（#10 是否保留 Astra 限定）等治理决定未落，本实现不预设结论；`model_access_package` 实际放行依赖未来激活代码验收，本 PR 未提供任何激活开关。
