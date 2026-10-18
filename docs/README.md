# 文档导航

## 产品方向与开发路线

- [项目 README](../README.md)：产品目标、已实现能力、运行方式与边界。
- [成长支持 MVP 设计](design/growth-support-mvp/README.md)：融合多专业视角的角色、DSH 插件、本地生产与云端服务。
- [架构](design/growth-support-mvp/architecture.md)、[契约](design/growth-support-mvp/contracts.md)、[完整样例](design/growth-support-mvp/walkthrough.md)、[验收路线](design/growth-support-mvp/delivery-plan.md)。
- [Issue 执行索引](roadmap/growth-support-issues.md)：以实际 GitHub Issue 为准，不把规划阶段名当作 Issue 编号。

## 约束、治理与衔接

- [AGENTS.md](../AGENTS.md)：当前工程与数据操作约束。
- 根目录科研规程：[研究方法](../RESEARCH_METHODOLOGY.md)、[筛选](../SCREENING_PROTOCOL.md)、[标注](../ANNOTATION_GUIDE.md)、[知识治理](../KNOWLEDGE_GOVERNANCE.md)，当前均为 DRAFT v1.1。
- [CE-01R 批准清单](governance/CE-01R-CHECKLIST.md)：未签署，不能因 #1 关闭而推定生效。
- [成长支持治理衔接](governance/GROWTH-SUPPORT-TRANSITION.md)：最新方向与既有规则的冲突和修订顺序。
- [CE-POL-01 提案](governance/CE-POL-01-PUBLIC-RESEARCH-AI-USE.md)、[访问登记实现](review/MODEL-ACCESS.md)：当前门禁未激活。

## 当前能力说明

- [Evidence/Claim 领域模型（#14）](evidence/EVIDENCE-MODEL.md)：科研语义层对象、严格校验入口、增量迁移与 #10 映射；不声称科研结论或发布资格。
- [专业资产领域模型（#15）](assets/ASSET-MODEL.md)：Strategy/SupportMethod/InteractionProfile/EvaluationCase、公共信封与 GS-04 人格版本规则、增量迁移与最小合成 demo 链；不声称科研结论、教育有效性或发布资格。
- [最小私有专业能力包与撤回机制（#16）](publish/PACK-MODEL.md)：字段白名单发布器、全量不可变快照、差异报告、原子激活与独立撤回账本；内容哈希与发布者认证分开，不声称发布资格或真实批准。
- [CE-02 人工盲法复核](review/CE-02-ANNOTATION-PLAN.md)：工具与人工执行分开验收。
- [CE-03 受控解析](parsing/README.md)：文档加工与科研证据语义分开。
- [AI Reviewer 使用](../.agents/skills/child-evidence-reviewer/references/usage.md)：科研生产 Skill，不是儿童交互插件。
- [DSH 接缝验证（#13）](verification/dsh-seam-verification/REPORT.md)及[能力矩阵](verification/dsh-seam-verification/CAPABILITY-MATRIX.md)：隔离 profile 合成验证；受控入口/最终输出在当前宿主版本不可实现，不声称强制专业流程成立。

## 历史与生成材料

- [MIGRATION.md](../MIGRATION.md)：拆分时点的记录，不能当作当前产品能力清单。
- [POC 归档](assessment/2026-10-13-poc-tech-evaluation/ARCHIVE_README.md)及 [CE-01R 勘误](governance/CE-01R-ERRATA.md)：保留原记录，由勘误指向更正。
- [AI Skill 验证记录](review/AI-SKILL-VALIDATION.md)、[解析 E2E](parsing/poc10-e2e-report.md)：结论仅覆盖各报告声明的时点与范围。
- `docs/research/` 与 `exports/` 是数据库派生快照，不手改，也不视为已获准的正式知识包。

产品需求已进入 Issue-first 规划；接口、具体技术选型及科研发布资格仍按对应任务决策。历史材料不因路线更新而改写，新的方向也不能把历史未完成事项标成完成。
