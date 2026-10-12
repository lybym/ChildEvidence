# ChildEvidence

> 儿童发展、教育心理学及相关研究的科研文献采集、证据管理与知识工程基础设施。
> 自 LumiThink Research Library v0.1 独立拆分而来（见 [MIGRATION.md](MIGRATION.md)）。

## 项目定位

ChildEvidence 是一个**独立科研证据生产与管理系统**，不是任何产品项目的内部模块：

- 以官方公开 API（OpenAlex / Crossref / ERIC / Europe PMC / PubMed / Unpaywall / Semantic Scholar）
  与机构官网为唯一数据来源，**不访问** Sci-Hub、LibGen 或任何绕过付费墙的来源；
- 以 SQLite 为事实源，字段级溯源（原始 API 响应摘录存于数据库 `raw_sources`）；
- 采集 → 核验 → 去重 → 开放 PDF 获取 → 导出 → 知识包发布的可持续流水线；
- 未来由本项目发布**经过审核、版本固定**的知识包（catalog / evidence-cards / strategies），
  由下游产品（如 LumiThink）按版本主动导入。

## 研究范围

| 领域 | 代码 |
|---|---|
| 儿童发展心理学（皮亚杰/维果茨基/埃里克森/鲍尔比/布朗芬布伦纳/班杜拉、执行功能、社会性与情绪发展、神经多样性） | `child_development` |
| 教育心理学与学习科学（SDT、SRL、元认知、成长型思维、认知负荷、提取/间隔/交错练习、阅读与数学困难、反馈与脚手架） | `learning_sciences` |
| 儿童行为与心理支持（共同调节、挫折耐受、学习焦虑与回避、亲子冲突、正向行为支持、睡眠、SEL、转介边界） | `behavior_support` |
| AI 儿童陪伴与数字心理学（2023–2026 重点） | `ai_children` |
| 中国儿童与家庭教育（中文文献独立收录，CFPS/CEPS 实证研究） | `china_family` |

分类体系与证据分级原则见 [docs/research/research-taxonomy.md](docs/research/research-taxonomy.md)。

## 项目架构

```
ChildEvidence/
├── README.md / AGENTS.md / MIGRATION.md
├── pyproject.toml            # 元数据与打包定义（纯标准库，无第三方依赖）
├── .env.example              # 环境变量模板
├── src/research_library/     # 流水线包（discovery/verify/acquisition/export/reports/CLI）
├── config/                   # sources.yaml / topics.yaml / seed-papers.yaml
├── tests/                    # 44 项单元测试（本地模拟 HTTP 服务器，离线）
├── scripts/                  # smoke_real.py（联网冒烟）、smoke_offline.py（离线冒烟）
├── docs/research/            # 生成的中文交付文档（tracked）
├── exports/                  # works.csv / works.jsonl / works.bib（tracked）
└── data/research-library/    # library.sqlite + pdf/ + cache/ + logs/（gitignored）
```

## 安装（Windows PowerShell）

要求 Python 3.11+，无任何第三方依赖。

```powershell
cd C:\CODE\ChildEvidence
$env:PYTHONPATH = "src"
python -m research_library status
```

可选：复制 `.env.example` 为 `.env` 并设置联系邮箱；或直接用环境变量
（`CHILDEVIDENCE_CONTACT_EMAIL`、`UNPAYWALL_EMAIL`、`CROSSREF_MAILTO`、`OPENALEX_API_KEY`）。
无任何密钥也可运行（官方 API 匿名/礼貌池访问）。

如需安装为命令行工具：`pip install .`（之后可用 `research` 命令）。

## 数据目录

默认 `\<项目根>\data\research-library\`，可用环境变量覆盖（优先级从高到低）：

1. `--data-dir` 命令行参数
2. `CHILDEVIDENCE_DATA_DIR`
3. `RESEARCH_LIBRARY_DATA_DIR`（旧别名）
4. 项目内默认路径

路径解析基于 `pathlib` 与模块文件位置，**不依赖当前工作目录**，也不依赖任何外部项目。

## CLI 使用

```powershell
$env:PYTHONPATH = "src"
python -m research_library discover    # 种子+主题检索+引用扩展+择优入库（联网）
python -m research_library verify      # Crossref 元数据核验 + OpenAlex 回填（联网，幂等）
python -m research_library acquire     # 下载合法开放 PDF 并校验（联网，幂等）
python -m research_library verify-pdfs # 校验本地 PDF（离线）
python -m research_library export      # exports/works.csv|jsonl|bib（离线）
python -m research_library docs        # 重新生成 docs/research/*.md（离线）
python -m research_library status      # 当前库状态（离线）
python -m research_library import-pdf <pdf路径> --doi 10.xxxx/yyyy  # 人工 PDF 导入（离线）

python -m unittest discover -s tests -v   # 单元测试
python scripts\smoke_offline.py           # 离线端到端冒烟
python scripts\smoke_real.py              # 联网端到端冒烟（少量真实请求）
```

增量更新：所有命令幂等，已核验/已下载条目自动跳过；删除 `data/research-library/cache/`
可强制重拉 API。

## PDF 获取与人工导入

自动下载仅尝试官方 API 标注的开放获取位置（Europe PMC 全文库、OpenAlex OA、Unpaywall、
Crossref 全文链接、ERIC、机构官网），并逐项校验：HTTP 状态 → Content-Type（拒绝 HTML）→
`%PDF-` 头 → 体积 → `%%EOF` → 页数扫描 → SHA-256 → 跨条目重复检测。
需机构订阅的文献进入 `docs/research/manual-download-queue.md`，人工下载后用
`import-pdf --doi` 导入，自动匹配去重，不产生重复条目。

## 版权边界

1. 开放获取 ≠ 可自由再分发；许可证逐条记录，未知记 `license_unknown`。
2. PDF 原文仅保存在本地 `data/`（已 gitignore），不提交公共仓库。
3. 不绕过任何付费墙、验证码或访问控制；付费文献仅保存书目与官方入口。
4. 预印本独立标记，不等同正式发表。

## Evidence Extraction 路线图（v0.2+）

本版（v0.1）只做采集、核验、编目与导出。后续规划（尚未实现，**不用虚构数据填充**）：

1. `catalog.jsonl` — 面向下游的稳定条目导出（含版本与清单哈希）；
2. `evidence-cards.jsonl` — 逐篇结构化证据卡（研究设计/样本/效应量/局限，人工阅读回填）；
3. `strategies.jsonl` — 经审核的教育策略证据条目（含适用年龄与边界）；
4. `manifest.json` — 知识包版本、来源、审计信息。

发布流程：ChildEvidence 审核 → 版本固定知识包 → 下游产品按版本导入。
本阶段不实现 MCP Server、HTTP API、RAG 服务或新的数据库系统。
