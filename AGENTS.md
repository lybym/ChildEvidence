# AGENTS.md — ChildEvidence 开发约束

本文件约束后续在此仓库工作的 Codex / Agent。违反任何一条的变更都不得合并。

## 数据与事实

1. **SQLite（`data/research-library/library.sqlite`）是科研文献唯一事实源。**
   Markdown 报告与 `exports/` 是派生产物，只能由 `research docs` / `research export`
   从数据库重新生成，禁止手改生成文件。
2. 一切数据变更必须可追溯：不要删除 `api_log`、`download_log`、`runs`、
   `retrieval_errors`、`ingestion_notes`、`raw_sources` 中的历史记录；需要纠正时
   追加说明（reviewer_notes / ingestion_notes），不覆盖既有审计信息。
3. **不得虚构学术元数据或研究结论**：DOI、作者、年份、卷期页、摘要必须来自官方
   API 响应或已验证的官方页面；研究设计、样本量、效应量等只能来自文献原文，
   未能核实的字段保持 NULL 并注明待读全文。
4. 不得把预印本当正式论文；不得把群体统计结论写成个体诊断；不得把未经审核的
   研究结论自动发布为正式教育策略或儿童干预规则。
5. 引用量只能用于发现排序，不得作为证据等级；证据分级原则以
   `RESEARCH_METHODOLOGY.md`（规程文件）为准——`docs/research/research-taxonomy.md`
   是 `research docs` 生成的派生快照，仅作参考，**不得**被当作不可变规范引用
   （AGENTS 科研治理节 #22）。

## 访问与版权

6. 只使用官方公开 API 与合法开放全文；**禁止** Sci-Hub / LibGen / 任何绕过付费墙、
   验证码、登录或访问控制的行为。
7. 开放获取 ≠ 可自由再分发：许可证逐条记录，未知记 `license_unknown`。
8. PDF 原文与数据库运行数据（`data/`）永不提交 Git；`exports/` 与 `docs/research/`
   提交前必须审查（不含个人信息、凭据、受限全文）。

## 工程约束

9. 保持标准库实现（Python 3.11+，零第三方运行时依赖）；确需引入依赖时先在
   README 记录理由并经确认。
10. 修改采集/核验/去重/导出逻辑必须同步更新 `tests/` 并保证 44+ 项测试全绿；
    涉及网络行为的功能用 `tests/test_downloader.py` 的本地模拟服务器模式测试，
    不在单测中访问真实网络。
11. schema 变更必须提供迁移脚本 + 兼容性测试；能用 `ALTER TABLE ADD COLUMN`
    完成的不要重写表。
12. 数据目录必须保持可配置（`CHILDEVIDENCE_DATA_DIR`），路径一律用 `pathlib`，
    不允许硬编码绝对路径进入版本管理。
13. 每次修改后在项目根运行：
    ```powershell
    $env:PYTHONPATH = "src"
    python -m unittest discover -s tests
    python scripts\smoke_offline.py
    python -m research_library status
    ```

## 隐私与隔离

14. 科研原文（`data/research-library/pdf/`）与儿童个人数据**严格隔离**：
    本仓库禁止出现任何儿童个人信息、诊断记录或产品用户数据。
15. 下游产品（如 LumiThink）只允许通过 ChildEvidence 发布的版本化知识包
    （catalog / evidence-cards / strategies + manifest）消费科研成果，
    不得直接读写本仓库数据库。

## 科研治理（CE-01/CE-01R，v1.1 草案）

> 依据文件（均为 **DRAFT v1.1**，**待人工审核确认后生效**）：
> `RESEARCH_METHODOLOGY.md`、`SCREENING_PROTOCOL.md`、`ANNOTATION_GUIDE.md`、
> `KNOWLEDGE_GOVERNANCE.md`。逐条审计意见见
> `docs/governance/CE-01R-REVIEW.md`；人工批准清单见
> `docs/governance/CE-01R-CHECKLIST.md`；POC 指标勘误索引见
> `docs/governance/CE-01R-ERRATA.md`。技术评估归档见
> `docs/assessment/2026-10-13-poc-tech-evaluation/`。

16. 科研决策、知识工程决策、产品决策三层**不得自动连通**；任何自动管线不得跳过
    人工审核与知识包版本发布（KNOWLEDGE_GOVERNANCE §2）。
17. 主动学习/排序模型（ASReview 类）只提供建议阅读顺序，**禁止自动终局拒收**；
    经典理论、中文、负面结果与争议研究属强制人工复核层（SCREENING_PROTOCOL §6）。
18. 模型生成的标签、摘要或证据草稿必须标记 AI 来源，且**不得生成并自我确认
    Gold Label**；多模型一致投票不等同专家共识；标签层级与 Gold 资格流程见
    RESEARCH_METHODOLOGY §7、ANNOTATION_GUIDE §8。
19. 人工标注按 ANNOTATION_GUIDE 执行：盲法标注（不展示历史标签与模型排名）、
    理由代码必填、分歧留痕；`undecided` 是合法状态；单人标注封顶 provisional。
20. Evidence/Claim（科研语义层）与 PDF 解析（数据加工层）分属不同工作包，
    独立设计、测试与发布，不得捆绑同一 PR；未经 `approved` 的证据卡不得进入
    任何已发布知识包或 Agent 行为（KNOWLEDGE_GOVERNANCE §3–§5）。
21. 影响科研结论的实验必须可从原始记录重算并通过一致性测试
    （范例：POC CE-01，`docs/assessment/` 归档；RESEARCH_METHODOLOGY M9）；
    历史指标被修正时以 `docs/governance/CE-01R-ERRATA.md` 勘误索引为权威指针，
    不改写原始记录，也不得在独立评估完成前宣称达到 95% 召回（SCREENING_PROTOCOL §6）。
22. **交叉引用不指向生成物作为不可变规范**：`docs/research/*.md` 与 `exports/` 是
    `research docs` / `research export` 的派生产物，可随数据重新生成；规程、
    字段语义与判定标准只能引用规程文件（根目录四份 DRAFT v1.1）及其治理文档
    （`docs/governance/`）与机器可校验契约
    （`docs/governance/contracts/*.json`，校验器 `research_library.governance`，
    测试 `tests/test_governance_contracts.py`）。派生快照只能作"当前参考"标注。
23. **DRAFT 规程不可被 Agent 当作生效准则**：四份规程处于 DRAFT 状态时，Agent 只能
    把它们当作待审提案阅读与引用，不得据此自动执行决策（包括自动改 APPROVED、
    自动终局拒收、自动发布知识包）；生效唯一凭据是 CE-01R-CHECKLIST 的人工签署。
24. 规程修订必须保持四份文件同版本演进（当前 v1.1），并通过
    `tests/test_governance_contracts.py` 的文档一致性检查（状态头、术语、
    交叉引用、勘误指针、契约自校验）。
