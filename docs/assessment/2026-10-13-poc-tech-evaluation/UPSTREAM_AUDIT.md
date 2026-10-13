# UPSTREAM_AUDIT.md — 五个上游项目实机审查（Step 01）

- 审查时间：2026-10-13（Asia/Shanghai）
- 审查方式：浅克隆上游仓库（`--depth 1`）到 `C:\CODE\ChildEvidence-POC\upstream\`，直接核对源码、
  依赖声明、许可证文件、入口点与文档；PyPI / GitHub Releases API 核对最新稳定版本。
- 本文件所有版本号、SHA、许可证均来自本次实际固定内容，未沿用任务书中的"已知线索"。

## 0. 环境事实（Preflight 摘要）

| 项目 | 值 |
|---|---|
| OS | Windows 11 家庭版 10.0.26300 x64 |
| CPU | AMD Ryzen 7 8845H，8C/16T |
| RAM | 27.8 GB（空闲约 6–10 GB，波动） |
| 磁盘 C: | 空闲约 425 GB |
| Python | 无系统 Python；使用 DSH 自带 CPython 3.12.14 作为 venv 基础解释器（位于 harness 运行时目录，只读使用） |
| Git | 2.56.0.windows.1 |
| Docker / WSL2 | 均不可用（未安装） |
| Java | 无系统 Java；本次下载 Microsoft OpenJDK 21 到 POC 工作区 `runtimes/jdk21` |
| 网络 | PyPI / GitHub 网页 / GitHub API / SciFact S3 / services.gradle.org / repo.maven.apache.org / api.adoptium.net / hf-mirror.com 可达；**huggingface.co 直连 SSL 失败**（须用 `HF_ENDPOINT=https://hf-mirror.com`）；GitHub Releases 资产 CDN 不稳定（uv 直接下载超时，改经 PyPI 安装成功） |
| 外部 LLM API Key | OPENAI / ANTHROPIC / DEEPSEEK / DASHSCOPE / MOONSHOT / ZHIPUAI / SILICONFLOW / HF_TOKEN 均不存在（只记录存在性，未读取值） |
| 结论 | 无云端 LLM 授权 → PaperQA2 生成环节默认 BLOCKED，走"本地检索 + 本地可选小模型"边界；GROBID 以本机 Gradle 方案替代 Docker |

## 1. ASReview — v3.0.8

- 官方仓库：https://github.com/asreview/asreview
- 上游 commit（main 浅克隆）：`79d568212b2b0a78f9fd7be3c5117dfb890489f9`（最后提交 2026-08-31）
- 最新稳定版：v3.0.8（GitHub Releases 2026-06-18；PyPI `asreview==3.0.8`）；v3.0rc 系列已被 3.0 稳定版取代
- 许可证：Apache-2.0（`LICENSE` 头部核对）
- requires-python：>=3.10；本次固定运行环境：Python 3.12.14 + scikit-learn 1.9.1（见 `configs/asreview-freeze.txt`）
- 关键依赖：numpy 2.5.4、pandas 2.3.3、scikit-learn 1.9.1、flask（webapp）、synergy-dataset、rispy。
  **核心包无 TensorFlow/PyTorch 依赖** → Windows 原生可用，无需 WSL2。
- 关键源码位置：
  - 模拟入口：`asreview/simulation/cli.py`（entry point `asreview simulate`），
    核心类 `asreview.simulation.simulate.Simulate`
  - 模型配置：`asreview/models/models.py`（AI_MODEL_CONFIGURATIONS：默认 ELAS u5 =
    SVM(loss=squared_hinge, C=0.0240, max_iter=5000) + tfidf(ngram 1-2, sublinear_tf) +
    balancer balanced(ratio=9.242) + querier max）
  - 分类器：`asreview/models/classifiers.py`（entry points：`svm`、`nb`、`rf`、`logistic`）
  - 查询策略：`asreview/models/queriers.py`（`random`、`top_down`、`uncertainty`、`max`、
    `max_uncertainty`、`max_random`）
  - 特征抽取：`asreview/models/feature_extractors.py`（`tfidf`、`onehot`）
  - 停止条件：`asreview/models/stoppers.py`（`LastRelevant`、`NLabeled`、`QuantileLabeled`、`NConsecutiveIrrelevant`）
  - 指标：`asreview/metrics.py`
- 接口约束：`asreview` CLI 子命令由 entry points 动态注册；模拟模式将数据集中 `included`
  列作为 oracle 标签；先验（n_prior_included/n_prior_excluded）从标签集中抽取。
- 随机性：随机种子经 `sklearn.utils.check_random_state`；先验抽样与查询策略均受种子影响 →
  多种子重复必须自行控制。
- 维护状态：活跃（2026-08 仍有提交；v3 大版本 2026-06 发布）。
- 风险：模拟评估的 Oracle Recall ≠ 真实筛选可停止时点；历史标签偏差会放大结果（本 POC 数据
  无独立 Gold，见 EXPERIMENT_PROTOCOL.md）。

## 2. Docling — v2.138.0

- 官方仓库：https://github.com/docling-project/docling
- 上游 commit（main 浅克隆）：`f0d90989b461656102da5d449db98e6be9285f93`（最后提交 2026-10-12，非常活跃）
- 最新稳定版：PyPI `docling==2.138.0`（仓库已改为模块化打包：`docling` 元包 = `docling-slim[standard]`）
- 许可证：MIT（仓库 `LICENSE`）；模型权重仓库（docling-project/docling-models、TableFormerV2、
  CodeFormulaV2）在 HF 上以 MIT/Apache 类开源许可发布（以 HF 页面为准，本地仅用于科研实验）
- 本次固定运行环境：Python 3.12.14 + docling-core 2.101.1、docling-ibm-models 4.0.3、
  docling-parse 7.22.2、pypdfium2 5.14.0、torch 2.14.1(CPU)、transformers 5.19.0、accelerate 1.15.0
  （见 `configs/docling-freeze.txt`）
- 模型下载：`huggingface_hub.snapshot_download`，repo id 为 `docling-project/docling-models`、
  `docling-project/TableFormerV2`、`docling-project/CodeFormulaV2`（见安装包
  `docling/models/stages/**`）。**huggingface.co 直连不可达 → 必须设置
  `HF_ENDPOINT=https://hf-mirror.com` 与本地 `HF_HOME`**。
- 关键源码位置：
  - SDK 入口：`docling.document_converter.DocumentConverter`（PDF 后端默认 docling-parse + pypdfium2 备选）
  - 版面/表格模型：`docling/models/stages/layout/layout_model.py`、
    `docling/models/stages/table_structure/table_structure_model.py`
  - 结构化输出：`docling_core.types.doc.DoclingDocument`，条目带 `prov`（page_no、bbox）→ 支持页面级定位
  - CLI：`docling`（`docling.cli.main:app`）、`docling-tools`（模型下载等）
- 能力核对：Markdown/JSON/DocTags 导出；表格结构（TableFormer）；页码/坐标 provenance；
  OCR 可选（默认仅文本层；扫描页需启用 OCR 模型）。
- 维护状态：极活跃。风险：模型首次下载需镜像；CPU 推理慢（10 份 PDF 约 3–10 min 级）；
  transformers 5.x 兼容性由上游 CI 保证，但需锁定 freeze 文件。

## 3. GROBID — 0.9.1

- 官方仓库：https://github.com/grobid/grobid
- 上游 master commit（浅克隆）：`c71ebff51e4d2a8257885458daeedede82698d43`（最后提交 2026-10-11，活跃）
- 最新稳定版：**0.9.1**（GitHub Releases 2026-08-04）。本次在克隆内 `git fetch tag 0.9.1` 并 checkout，
  实验/报告一律以 0.9.1 为准（master 为 0.9.2-SNAPSHOT，不用于实验）。
- 许可证：Apache-2.0（代码）；文档 CC-0；GROBID 官方标注数据 CC-BY；`grobid-home/models` 随仓库分发
  （约 469 MB，本次克隆包含，用于本地隔离运行）。
- 运行要求：OpenJDK 21（README 明确）；Gradle wrapper 9.6.1（`gradle/wrapper/gradle-wrapper.properties`）；
  `gradle.properties`：`org.gradle.jvmargs=-Xmx4g`、`org.gradle.java.installations.auto-download=false`
  → 必须自备 JDK21（本次：Microsoft OpenJDK 21 → `runtimes/jdk21`）。
- 部署形态：无 Docker/WSL2 可用。**实机构建结论（2026-10-13）：Windows 原生运行 BLOCKED**——
  ① `build.gradle`（0.9.1 第 30、613 行）在非 MAC/UNIX 平台直接抛
  `RuntimeException("Unsupported platform!")`；② GROBID 底层 PDF 解析器 pdfalto 的官方
  发行版（v0.6.3，含 all 包）只提供 linux/mac 二进制，无 Windows 版；③ 仓库虽含
  `grobid-home/lib/win-64/libwapiti.dll`（CRF 引擎可用），但缺 pdfalto 仍无法解析 PDF。
  不以魔改上游源码的方式强行运行。POC-B 以 Docling 实测 + pdfplumber 轻量坐标基线替代；
  GROBID 的 TEI/坐标能力按源码与文档（doc/Coordinates-in-PDF.md）作 REFERENCE 记录。
- 关键源码位置 / 接口：
  - REST：`/api/processFulltextDocument`（multipart `input`；可选 `teiCoordinates`、
    `segmentSentences`、`consolidateHeader`、`consolidateCitations` 等）
  - 坐标支持结构（doc/Coordinates-in-PDF.md）：`p`、`head`、`s`（需 segmentSentences）、
    `biblStruct`、`figure`（含表）、`formula`、`ref`、`persName`、`note`、`title`、`affiliation`
  - PDF 解析底层：pdfalto（`grobid-home/pdfalto`，超时 120s、内存上限 6096MB）
  - 配置：`grobid-home/config/grobid.yaml`（consolidation 默认 crossref，需 mailto；离线实验建议关闭或缓存）
- 维护状态：活跃；自称 production ready（ResearchGate、Semantic Scholar 等生产使用）。
- 风险：本机构建耗时与内存（Gradle 4GB 堆）；首次请求触发模型加载；句级坐标需显式开
  `segmentSentences`；跨页公式/表格坐标为已知弱项。

## 4. PaperQA2 — 2026.8.12

- 官方仓库：https://github.com/Future-House/paper-qa
- 上游 commit（main 浅克隆）：`57e89f7223b0960d5ee5ea048c69e3c47e088572`（最后提交 2026-08-12）
- 最新稳定版：PyPI `paper-qa==2026.8.12`（CalVer；tag v5.9.2 为旧线，PyPI 已到 2026 线）
- 许可证：Apache-2.0（`LICENSE`）
- requires-python：>=3.11；本次固定：Python 3.12.14（见 `configs/paperqa-freeze.txt`）
- 关键依赖（实测安装）：fhaviary 0.37.0（LLM agent 框架）、fhlmi 1.0.7、litellm 1.84.1、
  openai 2.54.0、tantivy 0.26.2（BM25 索引）、pybtex 0.26.1、tiktoken、paper-qa-pypdf（PDF 解析）
- 关键源码位置：`src/paperqa/`（docs.py、llms.py、configs.py、agents/）；
  CLI 入口 `[project.scripts] pqa = "paperqa.agents:main"`（无 `python -m paperqa`）
- LLM/Embedding 默认：经 litellm 调用云端模型（默认 OpenAI 系），embedding 默认 OpenAI；
  `paper-qa[local]` extra 提供 sentence-transformers 本地 embedding；**无任何 API Key 时生成
  与 Embedding 云调用均不可用**（本次实测：全部 Key 不存在）。
- 本机可离线使用的部分：`Docs.add()`（pypdf 解析 + 元数据）、tantivy BM25 文本索引、
  引用/citation 元数据结构；Agentic 问答/迭代检索需要 LLM → 默认 BLOCKED。
- 隐私边界：受限制文献全文不得送云端；本 POC 只允许本地组件处理 ChildEvidence PDF。
- 风险：版本迭代快（CalVer），API 与配置默认值随版本变化（本次以 2026.8.12 源码为准）；
  无本地 LLM 时无法完整评测。

## 5. SciFact — commit 68b98a56（无版本 tag）

- 官方仓库：https://github.com/allenai/scifact
- 上游 commit：`68b98a56d93e0f9da0d2aab4e6c3294699a0f72e`；**最后提交 2023-10-15 → 代码层面已停止维护**
- 许可证（LICENSE.md 原文核对）：
  - 代码：Apache-2.0
  - Claims + evidence 标注（`claims_*.jsonl`）：CC BY 4.0
  - 摘要语料（`corpus.jsonl`，来自 S2ORC）：ODC-By 1.0
- 数据集（官方 S3 `release/latest/data.tar.gz`，3.1MB，本次已下载解压到 `datasets/scifact/data/`）：
  - `claims_train.jsonl` / `claims_dev.jsonl`：**带标注**（evidence: doc_id → 句号列表 + label SUPPORT/CONTRADICT/NOT_ENOUGH_INFO）
  - `claims_test.jsonl`：**无标签**（官方不发布测试标签）→ 禁止用作带标签评测集
  - `corpus.jsonl`：摘要语料；`cross_validation/fold_1..5`：官方交叉验证划分
- 代码：`verisci/`（评估与模型代码）；`requirements.txt` 锁定 2020 年依赖（torch 1.5、
  transformers 2.7）→ 不建议按原 requirements 复现模型；官方口径评估指标用
  `verisci/evaluate` 的实现独立复算。
- 任务定位（README）：SciFact 是"摘要层面"的科学主张验证基准（rationale selection + label
  prediction），不能直接推断全文证据评价能力。
- 风险/结论：作为**数据集 + 评测口径 + 任务模式**使用；作为运行时组件不建议（无维护）。
  指标复现策略见 EXPERIMENT_PROTOCOL.md（官方口径公式 + 独立实现 + 公开 dev 集结果对照）。

## 6. 许可证与合规汇总

| 项目 | 代码 | 模型/数据 | ChildEvidence 使用边界 |
|---|---|---|---|
| ASReview | Apache-2.0 | 无随包模型 | 可直接集成/借鉴；模拟用历史标签须声明非 Gold |
| Docling | MIT | HF 模型 MIT/Apache 类 | 可集成；模型缓存入 POC 工作区 |
| GROBID | Apache-2.0 | 模型随仓库（Apache-2.0），官方标注数据 CC-BY | 可集成；consolidation 走 crossref 需 mailto 或关闭 |
| PaperQA2 | Apache-2.0 | 无随包模型；本地 embedding 可选 | 仅离线组件 + 本地模型；云 LLM 未授权即 BLOCKED |
| SciFact | Apache-2.0 | Claims CC BY 4.0；语料 ODC-By 1.0 | 引用须署名；test 集无标签不得用于精度宣称 |

## 7. 与任务书"已知线索"的差异（重核验结果）

- ASReview 已从 v2 进入 **v3.0 稳定版**（任务书写作时点信息较旧）；核心依赖无 TensorFlow。
- Docling 仓库结构已改为 **docling / docling-slim 双包**；版本 2.138.0 远新于常见教程（1.x/2.x 早期 API 变化大）。
- GROBID 最新稳定版 **0.9.1**（0.8.x 已过时）；模型已随主仓库分发。
- PaperQA2 版本线为 **2026.8.12**（"v5.x" 已被 CalVer 取代）；CLI 名为 `pqa`。
- SciFact **无 tag/releases**，代码 2023-10 后未动；数据集经 S3 latest 拉取，dev 集标签可用。
