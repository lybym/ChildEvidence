# CE-06 Astra Pilot 运行器与首篇条件确认验证报告（Issue #10）

> 状态：验证记录，2026-10-18。对应 Issue
> <https://github.com/lybym/ChildEvidence/issues/10>
> （`CE-06 Astra Research Reviewer Pilot`）。运行器实现位于
> [astra_pilot.py](../../../src/research_library/astra_pilot.py)；
> 条件清单、产物契约与当前确认状态见
> [ASTRA-PILOT](../../review/ASTRA-PILOT.md)；
> 权限与获准包契约见 [MODEL-ACCESS](../../review/MODEL-ACCESS.md)。
> 本报告只声明实际执行过的验证；代码存在不推定门禁激活、权限登记完成或
> 任何科研批准。

## 1. 验证环境与基线

| 项 | 值 | 来源 |
|---|---|---|
| 代码基线 | `master` = `84c592f`（Issue #12 合并后） | 本地 fast-forward 后与 `origin/master` 一致 |
| Python | 3.12.14 | DeepSeek Harness 自带运行时（系统 PATH 无 Python，与 [#12 报告](../model-access-package-contract/REPORT.md)一致） |
| 门禁 | `model_access.POLICY_ACTIVE = False`，全程未改 | 代码检查 + 测试断言 |
| 干跑产物 | `data/review/astra-pilot/<run_id>/`（Git 忽略，不入库） | `.gitignore` `data/` |

全部验证离线、合成数据；未读取任何论文摘要/正文/PDF 内容、未调用任何模型、
无网络访问（新测试含 `socket.socket` 禁用断言）。

## 2. 实际执行的验证与结果

| 命令（项目根） | 结果 |
|---|---|
| `python -m unittest discover -s tests` | **317 项全部通过**（1 项既有 skip，与本改动无关）；本 PR 新增 `tests/test_astra_pilot.py` 18 项 |
| `python scripts\smoke_offline.py` | SMOKE_OFFLINE PASS |
| `python -m research_library status` | 正常；计数与基线一致（ingested 141 / rejected 252 / pdf 35 个文件，零数据库写入路径） |

新增测试覆盖：未登记/门禁关闭/环境不匹配/实际模型身份不可核验/缺 PDF/库版本
不一致均 BLOCKED 且不建包；激活态（仅测试内 patch，与既有 staged-builder 测试
同法）合成链路 staging → ready 标记 → 候选校验 → completed 九件产物；幻觉引用、
Gold 升级、run_id 不一致、受保护资产篡改均 FAILED；`precheck` 只读且 exit code
反映门禁；CLI `run` blocked 记录 exit 0；输出根目录越界拒绝。

## 3. 首篇条件确认干跑（真实环境，只读 + 新增记录）

| 命令 | 结果 |
|---|---|
| `astra_pilot precheck --work-id lt-1ae2bbde5d0f --requested-model-id gpt-6-astra` | exit 2；5 项通过（在库且 crossref_verified、原件存在、PDF SHA `9c48bd…` 与库记录一致、用途受支持、请求目标已记录）、8 项缺失（`permission_registered`、`policy_active`、`environment_confirmed`、`scope_registered`、`model_identity_verifiable`、`derivative_text_available`、`selection_ranges_available`、`derivative_registered`） |
| `astra_pilot precheck --work-id lt-2f7e083d392e --requested-model-id gpt-6-astra` | exit 2；同样 5 通过 / 8 缺失（同一组门禁），未做 run 记录 |
| `astra_pilot run --work-id lt-1ae2bbde5d0f --requested-model-id gpt-6-astra` | exit 0；run_id `ce06-20261018T151352Z-f7be692e`，verdict **blocked**，确定性演示 envelope 已写入（未调用模型、未发送内容），九件产物齐备，受保护资产前后哈希一致 |

干跑审计核对：请求目标 `gpt-6-astra` 如实记录；实际模型身份 `unknown`
（无主张）；库许可声明按原值 `cc-by` 记录、未改标；PDF 哈希与库记录及
2026-10-14 人工尝试记录（`data/review/astra-pilot/ce06-20261014T023936Z-*/pilot-status.json`）
一致；`library.sqlite` 哈希 `36fb8ba…` 与该记录一致——主库未被改动。

## 4. Issue #10 验收条件映射

| 验收条件 | 证明 |
|---|---|
| 权限、版本、范围和环境预检通过 | 12 项条件预检（`precheck`）+ 激活态合成链路全通过测试；当前真实状态如实 BLOCKED（§3） |
| 内容包与原文逐项核对 | `prepare`/`verify_package` 哈希与区间链路复用（#12 契约），运行器仅在其上编排，不绕过 |
| 事实/引文有来源哈希及位置，不虚构 | `complete` 强制 `review_contract.validate`（引文哈希+本地文本匹配）；幻觉引用测试 FAILED |
| Evidence Card 含适用边界、偏倚、不确定性、未决问题 | `evidence-card.md` 四节结构测试断言；blocked 状态一律"未开展"+null，不虚构样本/效应/DOI/页码 |
| 原件、主库、人工标注/Gold、生产知识包不修改；前后校验哈希 | `protected_assets`/`verify_protected` 前后 SHA-256 核对；篡改测试 FAILED；干跑审计前后一致 |
| 幻觉引用、越权读取、自动升级 Gold 任一即 FAIL | 三类 FAIL 测试（引文/`unauthorized_content_use` 映射/`gold_upgrade_attempted`）+ `protected_asset_modified` |
| 缺批准环境/实际模型/输入可用性为 BLOCKED，不伪装科研 PASS | 干跑 §3 即该语义的实机记录；未登记/门禁关闭/身份不可核验测试均 BLOCKED；演示 envelope 摘要明确"未调用模型" |

## 5. 实际验证范围声明

已验证：合成、离线、只读链路 + 一次真实环境的 BLOCKED 干跑记录；运行器对
`model_access`/`review_contract` 为纯编排、无新依赖、无 schema 变更、无数据库
写入路径。未验证（明确不冒充完成）：真实权限登记（负责人动作）、已确认服务/
环境指针、实际 Astra 会话与模型身份核验、真实获准包构建与真实内容审查、
`ready_for_reviewer_session → completed` 的真实链路（仅合成验证）。

## 6. 失败与未决项

- 本次交付的测试无失败用例；全量 317/317 通过（1 项既有 skip）。
- 未决项：负责人一次性登记允许范围与环境依据；本地核对衍生文本与区间；
  具备可核验实际模型身份的会话；GS-D3（是否保留 Astra 限定）待人工决定；
  `POLICY_ACTIVE` 激活代码验收未发生，本 PR 未提供任何激活开关。缺任一条件
  即保持 BLOCKED，不开展批量运行，不发布知识资产。
