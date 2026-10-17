# CE-POL-01 最小权限登记实现（待批准、待验收）

> 路线衔接（2026-10-17）：当前实现仍是科研生产侧预检，不是成长支持插件的个人数据权限系统。下一阶段接入获准最小包、按实际服务/环境记录模型身份，并接续 #10；任务见 [Issue 索引](../roadmap/growth-support-issues.md)。本次路线更新不改变以下门禁。

依据 [政策 PR #8](https://github.com/lybym/ChildEvidence/pull/8)。现行出站政策继续有效；`POLICY_ACTIVE=False` 是代码门禁，没有启动参数或环境变量豁免。登记 `allowed` 也不会授权当前模型读取正文。正式批准和代码验收后，另行同步规程、Skill、包输入校验器及激活门禁；本变更不代签批准。

标准库工具：`python -m research_library.model_access register --record <本地记录.json>`。
登记表在 Git 忽略的 `data/review/model-access/permissions.json`；配置 `CHILDEVIDENCE_DATA_DIR` 后位于该目录的 `review/model-access`。保留历史，最新同 Work/PDF 决策生效；撤销追加 `restricted`。单进程手动操作，不支持并发登记。

记录字段：`work_id`、`pdf_sha256`、`source_url`（HTTPS 官方来源）、`rights_basis`（权利依据及署名要求/证据指针）、`scope`（metadata/abstract/article_text）、`decision`（allowed/needs_verification/restricted）、`confirmed_by`、`confirmed_at`（ISO 时间）、`policy_version`（CE-POL-01-draft-2026-10-14）、`codex_environment`（账户/组织/设置版本指针）、`sources`。不记录正文、凭据；所有确认由项目负责人完成，不由模型填写授权结论。

`sources` 每项包含 `sha256`（人工本地核对的 UTF-8 .txt 衍生文本字节哈希）、`scope`、`ranges`（允许字符区间，如 `[[0,1200]]`，右端不含）。对一篇一次性登记允许范围；排除第三方图片、附录、敏感内容。PDF 哈希与衍生文本哈希同时绑定，不能用任意 Docling/旧审查文件或改名取得权限。字符范围由本地核验确定，程序不证明解析正确或作法律判断。

预检命令：`python -m research_library.model_access prepare --work-id <id> --pdf <原件> --source <已登记.txt> --scope article_text --mode appraise --environment <已确认设置指针> --ranges <区间.json> --model-id <实际身份>`。不知实际模型则省略。输出仅决策/哈希/范围，无正文；每次生成独立 audit JSON。未知、错 SHA、错范围、错环境、撤销、政策变更、未生效均 blocked。预检无网络、无数据库迁移。

获准包构建逻辑已实现并用合成数据测试，但当前生产不可到达。未来激活后包只包含本次选中的片段及原件/衍生物哈希、出处、权利依据和范围，按新 run 保存，只读。文件只读属性不是访问隔离：实际审查必须在仅含获准包的受控工作区执行，不能给模型原 PDF/数据库访问权限。包尚不能作为现行 reviewer 的获准来源；当前 reviewer 仍会拒绝正文，禁止手工改 provenance 绕过。

科研门禁不变：silver/L0、not_reviewed、禁止人工 Gold、approved 或 Agent 发布。历史 blocked 审查不改写。
