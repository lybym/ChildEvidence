# EXPERIMENT_PROTOCOL.md — ChildEvidence POC 统一实验协议

版本：v1（2026-10-13）。所有实验遵循本协议；口径变更必须记录于本文件并说明理由。

## 1. 数据与标签

- 唯一数据源：`snapshots/library-snapshot.sqlite`（library.sqlite 的 Backup API 一致性快照，
  源库 SHA-256=36fb8ba68fee…d276，快照前后一致）。
- 数据集：`datasets/manifest.json`（393 条，seed=20261013，manifest SHA-256 见 build 输出）。
- 标签分层（任务书 2.3 要求）：
  - **Historical Label**：`record_status`（ingested=1 / rejected=0）。这是 ChildEvidence v0.1
    流水线在发现→核验→入库阶段做出的决策，**不是独立专家 Gold Standard**。
  - **Silver Label**：暂无（无既有规则标签）。
  - **Gold Label**：本机无人类标注员。已生成 80 条分层抽样标注包
    （`datasets/asreview-human-review-queue.csv`，含 54 条历史拒收样本），但**未完成人工标注**。
  - 因此：A1 为**代理指标实验**（proxy evaluation）；A2 仅交付标注任务，不标记完成；
    所有结论必须声明"基于历史标签代理，存在选择偏差放大风险"。
- 缺失摘要规则：121 条无摘要或摘要≤40 字符。**不虚构补全**：ASReview 输入使用
  `title + ". " + abstract(若缺失则为空串)`，缺失情况单独统计并纳入风险分析。

## 2. POC-A：ASReview 模拟协议

- 数据：A1（393 条，141 正例）。
- 统一 screened-order 定义：模拟将全部 393 条标注完毕（stopper=NLabeled(393)），
  `_results` 的记录顺序 = 筛选顺序（先验 2 条位于最前）。
- 先验：每 run 按 seed 抽 1 条相关 + 1 条不相关（模拟真实 cold-start）。
- 批量：n_query=10（ASReview 默认节奏）。
- 模型配置（全部来自 ASReview 3.0.8 官方定义）：
  - `nb_max`：ELAS u3 = NaiveBayes(alpha=3.822) + tfidf(stop_words=english) + balanced(ratio=1.2) + max
  - `svm_max`：ELAS u4 = SVM(loss=squared_hinge, C=0.11) + tfidf(ngram 1-2, sublinear_tf, max_df=0.95) + balanced(ratio=9.8) + max
  - `logistic_max`：LogisticRegression(默认参数) + tfidf(同 u4) + balanced(ratio=9.8) + max
  - `random`：ASReview Random querier（无分类器）
  - `tfidf_sim`（本 POC 自建基线）：TF-IDF(1-2 gram) 与先验相关文档质心的余弦相似度排序
- 种子：[11, 23, 37, 51, 67]（模型/先验/Random 共用；tfidf_sim 无模型随机性，仅先验随机）。
- 运行总数（CE-01 澄清）：**25 = 4 系统 × 5 种子经 ASReview 官方 Simulate 循环**
  （nb_max / svm_max / logistic_max / random——random 为 ASReview 官方 Random querier，
  非另外生成的排序基线）**+ 5 次 tfidf_sim**（Simulate 之外的自建基线）。
- 显著性声明：n=5 不足以支撑均值显著性检验；只报告逐种子数值、mean±std 与对 random
  的逐种子配对胜次（先验按种子共享，配对有效）；禁止使用"显著优于"表述。
- 可重算性（CE-01 验收）：全部指标必须可从 `results/asreview-ranking.jsonl` 重算并通过
  数学一致性测试（`benchmarks/recompute_metrics.py` → `results/asreview-consistency-tests.json`）。

### 指标定义（v2，2026-10-13 修订；全部基于同一筛选顺序，禁止不同口径）

设 N=393，R=相关总数，s(i)=第 i 位是否相关，cum(k)=前 k 位相关数。

| 指标 | 公式 |
|---|---|
| Recall@p | cum(ceil(p*N)) / R |
| WSS@95（v2） | **0.95 − n95/N**，n95=min{k: cum(k) ≥ ⌈0.95R⌉}（系统综述通行定义：扣除随机抽样在 95% 召回时本身可省的 5% 工作量；不可达记 NULL） |
| WSS@95_unadjusted（v1 留痕） | 1 − n95/N（旧口径，未扣随机基线；**仅作追溯，不得用于结论**） |
| Screening Burden@95 | n95（绝对数）与 n95/N |
| Precision@p | cum(ceil(p*N)) / ceil(p*N) |
| Missed@50（v2，逐 run） | R − cum(⌈0.5N⌉)：单次运行筛至 50% 预算时未发现的相关数；**禁止跨种子取并集后当作单次性能**（v1 报告的并集口径作废）。random 理论期望 = R·(N−⌈0.5N⌉)/N ≈ 70.3，用于核对 |
| Seed Variance | 逐种子数值 + mean±std + 对 random 的逐种子配对胜次 |

- 明确声明：**模拟中的 Oracle Recall ≠ 真实筛选中"何时已达到 95% 召回"的可知性**；
  真实场景需要停止规则与人工抽查，本 POC 不宣称可停止性。
- 输出：`results/asreview-metrics.csv`、`results/asreview-ranking.jsonl`、
  `results/asreview-errors.jsonl`（每 run bottom-50% 相关文献、全部低排名中文文献、
  经典理论文献排名）与 `figures/asreview-recall-curve.png`。

## 3. POC-B：PDF 解析协议

- 样本：`datasets/pdf-sample/`（10 份：4 英文常规 + 3 中文 + 1 综述 + 1 短文 + 1 长文），
  均为 ChildEvidence PDF 的独立只读副本（SHA-256 校验与原库一致）。
- 解析器：
  1. **Docling 2.138.0**（结构化：版面/表格模型 + DoclingDocument，含 prov 页码/bbox）
  2. **pdfplumber 0.11.x**（轻量文本+坐标基线；非结构化解析器，仅作文本/坐标对照）
  3. **GROBID 0.9.1**：本机 BLOCKED（build.gradle 在 Windows 直接抛 Unsupported platform!；
     上游 pdfalto 无 Windows 二进制；无 Docker/WSL2）。**不以魔改上游源码的方式强行运行**。
- 统一结构：`parsed/<parser>/<doc_id>.json`（pages/sections/paragraphs/tables/references/
  citations/extraction_warnings；GROBID 缺席，其字段说明 NULL 原因）。
- 参考文本（弱参考，非 Gold）：pypdf 文本层逐页抽取作为第三方参照；页码定位以
  pypdfium2 渲染页面 + 实机目检（AI 标注，声明为弱参考）抽样复核。
- 指标（定义与分母）：
  - Text Coverage：解析文本 3-gram 命中参照文本 3-gram 的比例（每文档按页聚合）
  - Page hit rate：抽查句子的正确物理页码命中率（分子/分母）
  - 定位成功率：给定研究发现句 → 能回溯到 (页码, bbox/坐标) 的比例
  - 中文：中文文档 CER（jiwer，对参照页文本）
  - 性能：每文档 wall time、失败/超时
- 混合方案评估：由于 GROBID BLOCKED，仅评估 Docling 单方案 + pdfplumber 回退方案。

## 4. POC-C：证据检索与主张验证协议

### C1 PaperQA2（部分 BLOCKED）
- 无任何已授权 LLM API Key（实测 8 类 Key 均不存在）→ **Agentic RAG 生成环节 BLOCKED**，
  不进行任何付费/云端调用；受限制文献 PDF 不出本地。
- 实际运行部分（离线）：`Docs.add()` 摄取 5–10 篇 PDF（pypdf 解析 + 元数据 + tantivy BM25 索引），
  记录可离线验证的摄取/检索行为与引用元数据结构。
- 自建检索基线（可完整运行）：对 10–15 个人工核验问题，用 BM25(tantivy 或 sklearn TF-IDF)
  在解析后的语料上做 Evidence Recall@K / Page Accuracy 评测（答案=抽取式证据句，逐条对照
  人工标注的证据页码与原文）。

### C2 SciFact（可完整运行）
- 数据：官方 S3 latest（`datasets/scifact/data/`）；仅使用**带标签的 dev 集**（33 claims）
  与 train 集；test 集无标签，不用于精度评测。
- 指标口径：rationale selection（evidence sentence P/R/F1，按官方 evaluation 定义，
  口径与 `verisci` 一致并独立实现）+ label prediction（SUPPORT/CONTRADICT/NOT_ENOUGH_INFO
  macro-F1 与混淆矩阵）。注：NOT_ENOUGH_INFO 是数据集原始第三类标签；本 POC 不发明新标签。
- 系统：无 GPU/无授权 LLM → 用 TF-IDF/BM25 检索 + 可复现的轻量打分（词汇重叠 +
  句级最大相似度）作为**基线系统**，目标是复现"官方口径指标计算"而非 SOTA 模型精度；
  同时把官方论文数字作为对照上限引用。训练模型不在本 POC 范围（资源/时间限制，明确声明）。
- ChildEvidence 领域扩展测试集：若时间允许，构建 20–30 条主张（人工/AI 目检并声明），
  **与 SciFact dev 分开报告**。

### C3 端到端 Evidence Card
- 在 C1 检索基线 + C2 验证机制上生成 `results/evidence-cards-draft.jsonl`
  （结构按任务书示例；全部 human_review_status=pending，allowed_for_agent_release=false，
  不写回 ChildEvidence 数据库）。

## 5. 数据安全与回归

- 原库只读：所有访问走快照或 mode=ro 连接；实验前后重算 library.sqlite SHA-256 与
  PDF 哈希（`scripts/verify_integrity.py`）。
- 回归测试：`tests/` 覆盖只读边界、空数据集、缺失摘要、中文、损坏 PDF、超时、无引用答案等
  （Mock 覆盖异常路径；至少一次真实端到端运行）。
