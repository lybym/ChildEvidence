# CE-POL-01 最小权限登记实现（待批准、待验收）

> 路线衔接（2026-10-17）：当前实现仍是科研生产侧预检，不是成长支持插件的个人数据权限系统。下一阶段接入获准最小包、按实际服务/环境记录模型身份，并接续 #10；任务见 [Issue 索引](../roadmap/growth-support-issues.md)。本次路线更新不改变以下门禁。
> Issue #12（2026-10-18）：预检与获准包补充服务/环境、请求/实际模型分离绑定；Reviewer 业务校验核心迁移为 Harness 无关的 `research_library.review_contract`，新增 `model_access_package` 来源核实链路（验证报告见 [docs/verification/model-access-package-contract](../verification/model-access-package-contract/REPORT.md)）。`POLICY_ACTIVE=False` 门禁不变，下述未生效声明继续有效。

依据 [政策 PR #8](https://github.com/lybym/ChildEvidence/pull/8)。现行出站政策继续有效；`POLICY_ACTIVE=False` 是代码门禁，没有启动参数或环境变量豁免。登记 `allowed` 也不会授权当前模型读取正文。正式批准和代码验收后，另行同步规程、Skill、包输入校验器及激活门禁；本变更不代签批准。

标准库工具：`python -m research_library.model_access register --record <本地记录.json>`。
登记表在 Git 忽略的 `data/review/model-access/permissions.json`；配置 `CHILDEVIDENCE_DATA_DIR` 后位于该目录的 `review/model-access`。保留历史，最新同 Work/PDF 决策生效；撤销追加 `restricted`。单进程手动操作，不支持并发登记。

记录字段：`work_id`、`pdf_sha256`、`source_url`（HTTPS 官方来源）、`rights_basis`（权利依据及署名要求/证据指针）、`scope`（metadata/abstract/article_text）、`decision`（allowed/needs_verification/restricted）、`confirmed_by`、`confirmed_at`（ISO 时间）、`policy_version`（CE-POL-01-draft-2026-10-14）、`codex_environment`（已确认的服务/环境指针：账户/组织/设置版本；历史字段名保留以兼容既有登记表，语义是按真实服务/环境绑定，不用平台名称泛化授权）、`sources`。不记录正文、凭据；所有确认由项目负责人完成，不由模型填写授权结论。

`sources` 每项包含 `sha256`（人工本地核对的 UTF-8 .txt 衍生文本字节哈希）、`scope`、`ranges`（允许字符区间，如 `[[0,1200]]`，右端不含）。对一篇一次性登记允许范围；排除第三方图片、附录、敏感内容。PDF 哈希与衍生文本哈希同时绑定，不能用任意 Docling/旧审查文件或改名取得权限。字符范围由本地核验确定，程序不证明解析正确或作法律判断。

预检命令：`python -m research_library.model_access prepare --work-id <id> --pdf <原件> --source <已登记.txt> --scope article_text --mode appraise --environment <已确认设置指针> --ranges <区间.json> --model-id <实际身份> --requested-model-id <请求目标>`。`--model-id` 是实际可核验的模型身份，`--requested-model-id` 是本次请求的目标模型；两者分开绑定，不知实际模型则省略并保持 unknown，不发明 ID。输出仅决策/哈希/范围，无正文；每次生成独立 audit JSON（含 requested/actual model）。未知、错 SHA、错范围、错环境、错模型身份、撤销、政策变更、未生效均 blocked。预检无网络、无数据库迁移。

获准包构建逻辑已实现并用合成数据测试，但当前生产不可到达。激活后包只包含本次选中的片段及出处与绑定（见下节），按新 run 保存，只读。文件只读属性不是访问隔离：实际审查必须在仅含获准包的受控工作区执行，不能给模型原 PDF/数据库访问权限；包目录本身只含该 run 的获准片段，是当前代码内可核验的最小交付单元，宿主侧进程隔离在真实激活时落地。

## 获准包与 Reviewer 契约的接通（Issue #12）

- 包自描述绑定：`run_id`、`work_id`、`pdf_sha256`、`source_sha256`、`scope`（范围）、`mode`（用途）、`environment`（服务/环境）、`model_id`（实际，可 unknown）、`requested_model_id`（请求）、`source_url`、`rights_basis`、`segments`；构建时逐项与登记表/审计对齐，不允许任意 Docling/审查容器。
- 只读复核：`research_library.model_access.verify_package(<content.json>)` 在审查侧重新校验包位置（`packages/<run_id>/content.json`）、审计 `output_sha256` 字节哈希、登记表最新决定（追加 `restricted` 即失效）、政策版本、服务/环境、范围与用途、每段许可区间及段长度一致性；任何不一致抛错。该函数只读，不返回正文。
- Reviewer 来源：`preflight --kind model_access_package --selector <run_id> --source <content.json>`。仅当 `POLICY_ACTIVE` 激活且上述复核全部通过时 `model_access_allowed=true`（`policy_reason=registered_minimal_package_verified`）；门禁未激活时一律 `policy_not_active`，与现行预检拒绝语义一致。该来源的 `license`/`access_basis` 字段仅如实记录声明、不参与判定（六维分离：资料处理权限由登记链决定，不与许可混用）。
- 引用回指与模型绑定：模型审查对包内容的引文 `source_hash` 必须等于该包文件哈希（回指同一源版本）；review 的 `mode`（用途）与 `requested_model_id`/`model_id` 必须与包绑定一致，包绑定未知模型时审查不得声称已核实其他模型（unknown 保持 unknown）。校验器在每次 validate 时重新执行全部复核，手工改 provenance 不能绕过。
- 契约中立化：`requested_model_id` 不再固定为 `gpt-6-astra`，按本次请求如实记录；`execution_kind` 接受 `codex_session`/`harness_session`（按实际宿主记录）；`skill_version` 放宽为语义化版本（当前 0.2.0）。旧结果（0.1.0、codex_session、gpt-6-astra）仍通过同一 schema——保留旧结果格式，无需迁移。
- 业务校验核心：`src/research_library/review_contract.py`（可测试、标准库、零新依赖），Skill 脚本 `validate_review.py` 只做参数/输出薄适配；两条测试（`tests/test_review_contract_package.py`、`tests/test_ai_review_skill.py`）绑定两者行为一致。

## 供 #10 的可复现运行步骤（合成演练；真实内容须获准）

在项目根执行。今天第 2 步会因 `POLICY_ACTIVE=False` 返回 blocked、第 3 步保持 `policy_not_active`（预期门禁）；治理决定落实并完成激活代码验收后，同一命令序列即真实链路：

```powershell
$env:PYTHONPATH = "src"
# 1) 登记（本地 JSON 记录，字段见上；登记表不入 Git）
python -m research_library.model_access register --record <本地记录.json>
# 2) 预检并留审计；当前 blocked/policy_not_active，激活后生成获准包
python -m research_library.model_access prepare --work-id <work_id> --pdf <原件> --source <已登记.txt> --scope article_text --mode appraise --environment <服务/环境指针> --ranges <区间.json> --model-id <实际模型> --requested-model-id <请求模型>
# 3) Reviewer 侧核实包（激活后 model_access_allowed=true；当前 policy_not_active）
python .agents/skills/child-evidence-reviewer/scripts/validate_review.py preflight --source <data-review-model-access/packages/<run_id>/content.json> --kind model_access_package --selector <run_id>
# 4) 审查结果本地校验（业务校验核心 research_library.review_contract）
python .agents/skills/child-evidence-reviewer/scripts/validate_review.py validate --review <candidate-review.json> --provenance <candidate-provenance.json>
```

科研门禁不变：silver/L0、not_reviewed、禁止人工 Gold、approved 或 Agent 发布。历史 blocked 审查不改写。
