# ASTRA-PILOT.md — CE-06 首篇试运行条件确认与产物契约（待真实决定、待激活）

> 状态：**实现与验证记录（2026-10-18），待批准条件未满足**。对应 Issue
> <https://github.com/lybym/ChildEvidence/issues/10>（`CE-06 Astra Research Reviewer Pilot`，
> 路线见 [growth-support-issues](../roadmap/growth-support-issues.md) P1 行）。
> 权限登记与获准包契约见 [MODEL-ACCESS](MODEL-ACCESS.md)；实现位于
> [astra_pilot.py](../../src/research_library/astra_pilot.py)，验证报告见
> [docs/verification/astra-pilot-runner](../verification/astra-pilot-runner/REPORT.md)。
> 本文件与运行器**不激活出站门禁、不调用模型、不代签批准、不关闭 Issue**；
> GS-D3（[#10](https://github.com/lybym/ChildEvidence/issues/10) 是否保留 Astra 限定）
> 仍为待人工决定，运行器把请求目标模型作为显式输入如实记录，不预设该决定。

## 1. 定位

运行器是 [MODEL-ACCESS §供 #10 的可复现运行步骤](MODEL-ACCESS.md) 中
register → prepare → preflight → validate 链路之上的**确定性本地编排**：

1. 把 Issue #10 的验收要求机器化为 13 项条件预检（§2）；
2. 在每次尝试前后对受保护资产做 SHA-256 快照核对（原件、主库、人工标注/Gold、
   生产导出、既有登记与审计、历史试运行记录；§4）；
3. 条件全部满足时经 `model_access.prepare` 构建获准最小包并核验绑定
   （`ready_for_reviewer_session`），审查会话只拿包、不拿库/PDF；
4. 会话候选经 `review_contract` 全量校验后定稿九件产物（§3）；
5. 幻觉引用、越权内容、Gold 升级、受保护资产变化任一出现即 FAIL（§5）；
6. 缺批准环境 / 实际模型 / 输入可用性即 BLOCKED，并完整记录缺失清单——
   **BLOCKED 是如实结果，不是工具失败，更不是科研 PASS**。

运行器自身无网络、无模型调用、无数据库写入；产物根目录沿用 Issue #10 规定的
`data/review/astra-pilot/`（默认布局）；自定义 `CHILDEVIDENCE_DATA_DIR` 时为该
数据目录同级的 `review/astra-pilot/`，两种布局下都始终位于库数据目录与
model-access 目录之外。`requested_model_id` 按每次调用显式传参记录。

## 2. 条件预检（`precheck`，只读）

`python -m research_library.astra_pilot precheck --work-id <id> --requested-model-id <目标>`
（可选 `--mode/--scope/--environment/--model-id/--model-identity-evidence/--pdf/--source/--ranges`）。
全部通过时 exit 0，否则 exit 2 并列出缺失项；不写任何文件。

| 条件 id | 内容 |
|---|---|
| `work_in_library` | 本地库（只读）存在该 Work 且元数据状态可用 |
| `original_available` | 原件 PDF 存在（库记录路径或显式传入） |
| `original_version_matches_library` | PDF SHA-256 与库记录 `sha256` 一致（版本核对） |
| `permission_registered` | 登记表最新决定为 `allowed` 且政策版本匹配（work+PDF 哈希） |
| `mode_supported` | 用途属于 reviewer 五模式 |
| `policy_active` | `model_access.POLICY_ACTIVE` 出站门禁在预检时为激活态 |
| `environment_confirmed` | 已确认服务/环境指针，且与登记记录一致 |
| `scope_registered` | 请求 scope 在登记范围内 |
| `model_request_recorded` | 请求目标模型已如实记录 |
| `model_identity_verifiable` | 实际模型身份与可核验依据同时提供；否则记 unknown，**不得宣称已执行 Astra** |
| `derivative_text_available` | 本地已核对的 UTF-8 `.txt` 衍生文本存在 |
| `selection_ranges_available` | 非空整数区间与登记一致 |
| `derivative_registered` | 衍生文本哈希+scope 在登记来源绑定中 |

## 3. 产物契约（九件，仅存 `data/review/astra-pilot/<run_id>/`）

| 文件 | 内容 |
|---|---|
| `review.json` / `provenance.json` / `review.md` / `validation.json` | 审查 envelope 四件套，由 `review_contract.finalize` 写入；blocked 尝试写入确定性演示 envelope（未调用模型、未读原文、silver/L0/not_reviewed） |
| `screening.json` | 筛选决定载体（非 screen 模式或 blocked 时 decision=null 并注明原因） |
| `evidence-card.md` | 证据卡草稿载体：元数据标识、适用边界、偏倚与局限、不确定性、未决问题 |
| `appraisal.md` | 方法学评价草稿载体：样本/干预/对照/测量/偏倚、年龄/家庭/学习行为/情绪调节、相关与因果、证据充分性 |
| `uncertainty.md` | 不确定性登记：全部条目 unresolved，实际模型身份不可核验时登记 `model_identity_unknown` |
| `audit.json` | 试运行审计：条件清单、verdict、requested/actual 模型、受保护资产前后哈希、产物哈希 |

AI 草稿始终 `silver`/`L0`/`not_reviewed`/`allowed_for_agent_release=false`；
缺失事实保持 null/unknown；AI 复核与人工复核分别留痕，不得用 AI 一致性冒充人工。
产物目录在 Git 忽略的 `data/` 下，不入库。

## 4. 受保护资产（验收：原件/主库/人工标注/生产知识包不修改）

尝试前快照、尝试后逐一复算 SHA-256，任何变化即 FAIL（`protected_asset_modified`）：
库 `library.sqlite`、人工标注库 `annotations.sqlite`（两个约定候选位置，如存在：
CLI 默认 `<data_dir>/review/annotations.sqlite` 与数据根 `review/annotations.sqlite`）、
该 Work 原件 PDF、`model-access/permissions.json` 与既有审计文件、
`astra-pilot/` 下全部既有文件、`exports/` 生产导出。运行器只写入全新 `<run_id>`
目录或 `.ready`/`.failed` 标记文件，不改写任何历史记录；`.ready` 标记在终态
（completed/failed）后关闭移除，之后重跑 `complete` 得到显式的"已终态"错误，
而不是 FileExistsError 崩溃窗口或部分覆盖。

## 5. verdict 与 FAIL/BLOCKED 语义

| verdict | 触发 |
|---|---|
| `blocked` | 任一条件缺失；或条件满足但 `prepare` 仍拒绝。两种情况均写九件产物目录 `<run_id>/`，完整记录缺失清单 |
| `ready_for_reviewer_session` | 条件全满足、获准包构建并核验通过；写 `<run_id>.ready.json`（含包绑定），等待会话产出候选；终态后该标记关闭移除 |
| `completed` | 候选通过 silver/L0/not_reviewed 门、run_id 绑定、暂存包绑定核对（候选 provenance 的 `model_access_package` 源必须就是 ready 标记记录的获准包，不符即 FAIL `package_binding_mismatch`）、`review_contract` 全量校验并 finalize；九件产物齐备，完成后关闭 ready 标记 |
| `failed` | 校验失败（映射 `hallucinated_or_unverifiable_citation`、`unauthorized_content_use`、`gold_upgrade_attempted`、`run_id_mismatch`、`package_binding_mismatch` 等）、或受保护资产变化；`.failed.json` 为终态记录，重跑 `complete` 直接拒绝 |

## 6. 运行步骤（激活后同一命令序列即真实链路）

```powershell
$env:PYTHONPATH = "src"
# 0) 条件确认（只读；当前预期 blocked，exit 2）
python -m research_library.astra_pilot precheck --work-id <work_id> --requested-model-id <请求目标>
# 1) 尝试记录：blocked 九件产物，或（激活后）获准包 + ready 标记
python -m research_library.astra_pilot run --work-id <work_id> --environment <服务/环境指针> --requested-model-id <请求目标> --model-id <实际模型> --model-identity-evidence <依据指针> --source <已登记.txt> --ranges <区间.json>
# 2) 按 MODEL-ACCESS 步骤 3 在会话内对包执行 reviewer preflight，产出候选 review/provenance
# 3) 校验并定稿九件产物；任何 FAIL/BLOCKED 语义见上节
python -m research_library.astra_pilot complete --run-id <ce06 run_id> --review <候选 review.json> --provenance <候选 provenance.json>
```

登记（`model_access register`）仍由负责人完成，运行器不代填授权结论。

## 7. 当前首篇条件确认状态（2026-10-18 干跑，见验证报告）

- 首选 `lt-1ae2bbde5d0f`：5 项通过（在库且 crossref_verified、原件存在、版本哈希一致、
  用途受支持、请求目标已记录）；8 项缺失（权限未登记、门禁未激活、环境未确认、
  scope 未登记、实际模型身份不可核验、无衍生文本、无区间、衍生未登记）→ **BLOCKED**。
  尝试记录：`data/review/astra-pilot/ce06-20261018T151352Z-f7be692e/`（九件产物齐备，
  受保护资产前后哈希一致；未读取原文、未调用模型）。
- 备选 `lt-2f7e083d392e`：precheck 同样 5 项通过、8 项缺失（同一组门禁），未做 run 记录。
- 待负责人动作：一次性登记允许范围与已确认服务/环境依据（`model_access register`）、
  提供本地核对的衍生文本与区间、在具备可核验实际模型身份的会话中执行审查。
  在此之前不开展批量运行，不伪装科研 PASS，不自动升级 Gold。
