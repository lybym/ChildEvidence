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

## 人工盲法复核（CE-02）

A2 80 篇文献相关性复核的**离线人工标注流水线**（`review` 子命令），实现依据
DRAFT v1.1 规程（ANNOTATION_GUIDE 等，未经人工批准不生效）。要点：

- 独立标注库 `data/review/annotations.sqlite`，与主事实源 `library.sqlite` 零读写关联；
- 只读导入盲法 CSV，携带历史标签/抽样层/模型排名或预填判定的输入被拒绝；
- 人工判定追加式留痕（理由码必填，undecided 合法，单人标注封顶 provisional）；
- 唯一 Gold 通道 = 独立复核一致或裁决完成 + 人工签署（`record-signoff`）；
- 解盲审计的硬前置：全部标签锁定；审计只读 join 带键表，原决策不覆盖。

完整流程、schema 与边界见
[docs/review/CE-02-ANNOTATION-PLAN.md](docs/review/CE-02-ANNOTATION-PLAN.md)。

## 受控 PDF 解析（CE-03，可选依赖）

`parse` 子命令提供 **Docling 优先 + pdfplumber 回退** 的受控解析流水线
（数据加工层；不生成 Claim/Evidence 语义，不触碰知识包与 Agent 策略）。
**默认 CLI 保持零第三方依赖**——只有显式运行 `parse` 时才在隔离 venv 内懒加载
docling/pdfplumber（引入理由：POC-B 实测 Docling 2.138.0 为唯一同时满足
结构化+页码/坐标溯源+中英可靠的解析器；见
[docs/assessment/2026-10-13-poc-tech-evaluation/FINAL_RECOMMENDATION.md](docs/assessment/2026-10-13-poc-tech-evaluation/FINAL_RECOMMENDATION.md) §9）。

```powershell
# 一次性：隔离 venv 安装可选依赖（不影响零依赖采集环境）
python -m venv C:\path\to\ce03-venv
C:\path\to\ce03-venv\Scripts\python.exe -m pip install ".[parsing]"
# 一次性：下载 Docling 运行权重到本地缓存（唯一联网步骤；需显式授权执行）
C:\path\to\ce03-venv\Scripts\python.exe -m research_library parse models --artifacts-dir C:\path\to\model-cache
# 日常：离线解析（产物版本化、幂等、断点续跑）
C:\path\to\ce03-venv\Scripts\python.exe -m research_library parse run --manifest <manifest.json>
C:\path\to\ce03-venv\Scripts\python.exe -m research_library parse report --format md --out report.md
```

要点：物理页/印刷页严格分离（印刷页只由人工校正文件写入，永不推断）；
bbox 只代表"坐标存在"而非"定位正确"（存在率与准确率分开报告，准确率留给
CE-04 人工 Gold）；失败回退显式标记 `fallback`；双解析冲突生成复核任务不自动裁决；
解析产物写入 `data/research-library/parse-output/`（gitignored），
`library.sqlite` 零写入。完整说明与边界见 [docs/parsing/README.md](docs/parsing/README.md)。

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

## 手动 AI 科研审查 Skill

显式调用 `$child-evidence-reviewer` 对指定文献/草稿执行 screen、appraise、extract、
challenge 或 audit。Skill 位于 `.agents/skills/child-evidence-reviewer/`，
`allow_implicit_invocation=false`；使用当前 Codex 会话并如实记录模型身份，不能自动
切换为 Astra。它只读输入，输出独立 silver/L0 提案到
`data/review/ai-review/<run_id>/`；不改科研库、人类标注、Gold 或发布门禁。

先用本地标准库工具做许可/政策预检，再决定模型可读范围。现行摘要/PDF出站禁令
同样约束 Docling/审核草稿衍生内容；本地读文件不代表模型离线。无 API 客户端、
API Key 依赖、常驻服务或批量调度。使用方法、Schema/哈希说明、离线测试和风险
见 [Skill 使用说明](.agents/skills/child-evidence-reviewer/references/usage.md)。
工程验证与少量真实来源拒绝演示见
[AI Skill 验证记录](docs/review/AI-SKILL-VALIDATION.md)。
来源 Work 身份与 scope 严格绑定；模型引用须同时获准且声明实际入模型，
包括两个 Pass 原始结果，blocked 状态也不豁免。离线回归共231项（46项Skill测试）。

四份科研规程保持 DRAFT v1.1 未签署。实机发现已验证，科研模型审查尚未运行；
本次少量真实来源演示只验证本地预检/结构与拒绝边界，不宣称 Astra 正确率。

## Evidence Extraction 路线图（v0.2+）

本版（v0.1）只做采集、核验、编目与导出。后续规划（尚未实现，**不用虚构数据填充**）：

1. `catalog.jsonl` — 面向下游的稳定条目导出（含版本与清单哈希）；
2. `evidence-cards.jsonl` — 逐篇结构化证据卡（研究设计/样本/效应量/局限，人工阅读回填）；
3. `strategies.jsonl` — 经审核的教育策略证据条目（含适用年龄与边界）；
4. `manifest.json` — 知识包版本、来源、审计信息。

发布流程：ChildEvidence 审核 → 版本固定知识包 → 下游产品按版本导入。
本阶段不实现 MCP Server、HTTP API、RAG 服务或新的数据库系统。
