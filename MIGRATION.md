# MIGRATION.md — Research Library v0.1 → ChildEvidence 迁移记录

> 迁移执行时间：2026-10-13（UTC 时间戳见各审计文件）。
> 性质：保留既有实现的仓库拆分与目录迁移，非重新开发、非架构重构。

## 1. 原始项目与来源

| 项 | 值 |
|---|---|
| 原项目目录 | `C:\CODE\LumiThink` |
| 原始 Git HEAD SHA | `aaec68179c8bce4b32161c2e490c79dfe5c72505` |
| 原始分支 | `poc/r0-01-dsh-child-sdk-profile`（远程同步） |
| 迁移对象 | `research-library/`（196+ 文件）、`docs/research/`（5 文件）、`data/research-library/`（620 文件，约 87MB） |
| 目标项目 | `C:\CODE\ChildEvidence`（迁移前不存在，全新创建） |

## 2. 基线冻结（迁移前）

- 独立备份：`C:\CODE\Backups\ChildEvidence-migration-20261013\`
  - `lumi-research-library\`、`lumi-docs-research\`、`lumi-data-research-library\`（与源文件计数逐一核对一致：239/5/620，含瞬时测试工件）
  - `library.sqlite.snapshot`（SQLite Backup API 一致性快照，`PRAGMA integrity_check` = ok）
  - `baseline-manifest.json`（821 个文件的 SHA-256、全部表行数、works.internal_id 全集、ingested DOI 全集、单元测试结果、Git HEAD）
- 数据库完整性：`PRAGMA integrity_check` = ok；`wal_checkpoint(TRUNCATE)` 后快照
- 基线数字：**文献 ingested 141 / 拒收 252；本地 PDF 35；单元测试 44 全绿**（与交付报告一致，无差异）
- LumiThink Git 全历史扫描：从未提交过任何 research/pdf/sqlite 文件（无敏感数据残留）

## 3. 迁移过程

1. **阶段 A（备份+暂存）**：独立备份（上表）→ 暂存区 `C:\CODE\.tmp\ce-staging\ChildEvidence` 按新布局复制（全部为复制，原目录只读不动）。
2. **阶段 B（解除耦合）**：
   - `config.py`：重定位到 `PROJECT_ROOT`（`parents[2]`），`exports_dir`→`<root>/exports`、`docs_dir`→`<root>/docs/research`、默认数据目录→`<root>/data/research-library`
   - 新增 `CHILDEVIDENCE_DATA_DIR` / `CHILDEVIDENCE_CONTACT_EMAIL`（保留 `RESEARCH_LIBRARY_DATA_DIR`、`LUMITHINK_CONTACT_EMAIL` 为兼容别名）
   - UA 更新为 `ChildEvidence-ResearchLibrary/0.1`；项目文案（`__init__`/`cli`/`exporters`/`reports`/YAML 注释）改为 ChildEvidence
   - 新增 `pyproject.toml`（src 布局 + `research` console script）、`.gitignore`、`.env.example`、`README.md`、`AGENTS.md`、`scripts/smoke_offline.py`（离线端到端冒烟）
   - **回归发现并修复既有 bug**：`cli.py cmd_import_pdf` 引用不存在的 `args.id`（dest 为 `id_`），该 CLI 路径此前从未被真实执行过；已修复并由离线冒烟覆盖
3. **落位**：暂存验证通过后整体复制到 `C:\CODE\ChildEvidence`（668 文件，计数与暂存一致）。
4. **受控 DB 路径迁移**：扫描全部表全部 TEXT 列，仅替换项目前缀
   `C:\CODE\LumiThink` → `C:\CODE\ChildEvidence`；结果：**仅 `works.local_pdf_path` 35 行更新**，
   其余字段零变动；`PRAGMA integrity_check` 前后均 ok；审计文件
   `data/research-library/logs/path-migration-20261012T164824Z.json`。
   **未修改任何 schema**；DOI/标题/摘要/来源元数据/SHA-256 全部原样。列名
   `applicability_to_lumithink` 作为历史 schema 名称保留（避免不必要迁移），已在本文件记录。

## 4. 数据校验（阶段 C 结果）

| 校验项 | 结果 |
|---|---|
| SQLite `PRAGMA integrity_check` | ok（迁移前后各一次 + 快照一次） |
| 表行数（works 393 / manual_queue 106 / download_log 188 / api_log 788 / runs 12） | 与基线一致 |
| ingested 数量 | 141 = 基线 |
| `works.internal_id` 全集 | 与基线逐项一致 |
| ingested DOI 全集 | 与基线逐项一致 |
| PDF 哈希链（DB.sha256 = 基线 manifest = 暂存文件 = 最终文件） | 35/35 一致 |
| PDF↔条目映射 | `local_pdf_path` 已受控迁移到新根，`verify-pdfs` 35/35 通过 |
| 拒收候选 / 人工队列 / 审计日志 | 252 / 106 / 788+188+12 全部保留 |
| exports 重新导出 | 141/141/141（CSV/JSONL/BibTeX 均从迁移后 DB 重新生成） |
| 新旧路径混用 | 数据库 0 行、代码/配置 0 处、重新生成的文档/导出 0 处（旧 `exports/` 为 URL 修复前陈产物，已重新生成替换） |

## 5. 完整回归（阶段 D 结果）

- 单元测试：**44/44 通过**（暂存区、最终目录各一轮；最终目录在迁移后再次全绿）
- `scripts/smoke_offline.py`（离线端到端：夹具入库 → CLI import-pdf → SHA/页数校验 → 幂等重导入 → HTML 伪装拒绝 → 导出 → 报告生成）：**PASS**
- CLI：`status` / `verify`（幂等 0 网络调用）/ `export` / `docs` / `verify-pdfs` 全部通过
- 非项目工作目录调用（`C:\CODE` 下运行，无 `--data-dir`）：默认数据目录正确解析到 `C:\CODE\ChildEvidence\data\research-library`，与 CWD 无关
- 环境变量覆盖：`CHILDEVIDENCE_DATA_DIR` 生效
- 未执行网络采集（未重复 788 次 API 调用、未重复下载任何 PDF）
- 原项目产品代码零改动（仅 README 增加一段说明，见 §7）

## 6. Git 仓库

- `C:\CODE\ChildEvidence` 独立 `git init`，全新历史起点
- `.gitignore`：排除 `data/`、`.tmp-test/`、`__pycache__/`、`.env`、日志等；**不提交** PDF 原文、SQLite 运行数据、API 缓存、密钥
- 已审查后跟踪：源码、config（无凭据）、tests、scripts、`docs/research/*.md`（无个人信息/凭据/受限全文，仅含本机路径与公开书目数据）、`exports/`（纯书目数据）
- 首个提交：见 §8（第二次小提交回填 SHA）

## 7. LumiThink 清理

- 已删除（迁移验收通过且备份校验后）：`research-library\`、`docs\research\`、`data\research-library\`
- 三者均为未跟踪文件（Git 无需 rm 记录）；删除前均已在备份与 ChildEvidence 各存一份并验证
- README 变更：在独立分支 `chore/migrate-research-library-out` 提交一段说明（Research Library 已拆分为 ChildEvidence，后续经版本化知识包使用），不混入 `poc/*` 分支
- 产品代码、Prisma schema、Roadmap、DAH 配置、`poc/` 均未触碰

## 8. 提交记录

- 首个提交：`950dcd8a385e93539dcc0862e5d791c57ac567aa`
  `chore: import ChildEvidence v0.1 from LumiThink Research Library`
  （48 个文件，8970 行；`data/` 按规则未入库）
- 本小节由第二次提交回填，记录首个提交 SHA。

## 9. 回滚方式

1. 数据回滚：`C:\CODE\Backups\ChildEvidence-migration-20261013\` 内三目录 + DB 快照可直接还原到 LumiThink 或 ChildEvidence 任意位置；
2. ChildEvidence 回滚：删除 `C:\CODE\ChildEvidence`（首提交后所有状态在 Git 与备份中）；
3. LumiThink README 说明：`git revert` 或删除 `chore/migrate-research-library-out` 分支即可。

## 10. 遗留事项

1. `applicability_to_lumithink` 列名保留为历史 schema 名称（v0.2 如需改名须走迁移脚本）；
2. `docs/research/*.md` 由最终位置重新生成，生成时间戳为迁移时刻（内容与数据一致）；
3. 迁移的旧 `exports/` 是 URL 修复前的陈产物，已在最终位置重新生成覆盖；
4. 暂存区 `C:\CODE\.tmp\ce-staging` 保留至验收后可删（含临时测试工件，未迁移）；
5. 人工下载队列 106 项仍待机构订阅获取（见 manual-download-queue.md）。
