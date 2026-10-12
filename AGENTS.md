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
5. 引用量只能用于发现排序，不得作为证据等级；证据分级遵循
   `docs/research/research-taxonomy.md`。

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
