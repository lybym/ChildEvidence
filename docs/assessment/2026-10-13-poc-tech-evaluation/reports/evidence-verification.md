# POC-C 报告：PaperQA2 / SciFact 科研证据检索与主张验证

> **v1.1 解读边界（2026-10-13，用户复核后）**：
> ① **指标命名修正（v1.2 补充）**：Label Accuracy 0.8311 的分母是 **900 个
> claim-document 评价实例**（300 claims × top-3 检索文档；对角线 (5+721+22)/900），
> **不是 300 个独立主张的端到端正确率**。指标已更名为
> `claim_document_label_accuracy`（见 results/scifact-metrics.csv）。且 NEI 实例占
> 754/900=83.8%——类别分布本身即说明不能凭该 Accuracy 判断科学验证能力。
> ② Label Accuracy **不得**被解读为"科研主张验证可靠"——官方主要评价是"证据文献 +
> 支持/反驳标签 + 证据句集合"的**联合正确性**（abstract_rationalized / sentence_label），
> 本报告的 Label Accuracy 只是官方 label_prediction 脚本语义的复算，不能替代联合口径。
> ③ 本弱基线（TF-IDF+Logistic）**禁止**接入 ChildEvidence 充当科学判断器；
> SciFact 的最终角色 = **ADOPT Benchmark**（测试规范/标注方法/指标参考），
> 不是科研质量裁判。
> ④ 自建 char-TF-IDF（8/12）优于 PaperQA2 离线配置（3/12）的结论基于 12 个问题，
> 样本过小，且 Document Hit@5 ≠ 正确证据段落召回率——只作为"先建可靠中英混合检索
> 基线，再检验 BM25/双语 Embedding/Reranker 增益"路线的初步依据。

- 实验日期：2026-10-13。协议：`../EXPERIMENT_PROTOCOL.md` §4。
- 隐私边界执行情况：本机实测 8 类 LLM API Key 均不存在 → **未发生任何云端 LLM/Embedding
  调用**；ChildEvidence PDF 全程本地处理；无付费调用。

## C1：PaperQA2 2026.8.12（离线组件实测 + Agentic 生成 BLOCKED）

### 实际运行内容（全部为真实 PaperQA2 代码路径）

1. `Docs.aadd()` 摄取 10 份真实 PDF（pypdf reader）：**10/10 成功，128 个文本块**；
   块名含页码范围（如 `lt-dab4d327e195 pages 5-7`）→ 页码溯源信息存在。
2. Embedding：本地 `sentence-transformers/multi-qa-MiniLM-L6-cos-v1`（经 HF 镜像下载，
   `HF_HUB_DISABLE_XET=1`），无云端调用。
3. `Docs.retrieve_texts()`（MMR 检索）：12 个经人工核验的问题全部运行成功。
4. `aquery` / agents（需 LLM）：**BLOCKED**——无授权 Key，不做调用。

### 检索质量（12 个问题，5–10 篇语料，`../results/paperqa-retrieval.jsonl`）

| 系统 | doc_hit@5 | evidence_phrase_hit@5 | gold_page_in_range@5 |
|---|---|---|---|
| PaperQA2（pypdf + 本地 MiniLM + MMR） | **3/12** | 0/15 | 2/12 |
| 自建 TF-IDF(char 1-3) top-5 基线 | **8/12** | 1/15 | 4/12 |

### 失败案例（每条都有源码/输出依据）

1. **pypdf 内建解析器对中文 CID 字体输出乱码**：`lt-dab4d327e195` 等中文 PDF 的块文本
   为乱码（与 POC-B 中 pypdf 参照失效同源）→ 中文检索失效。
   **推论：ChildEvidence 必须以 Docling 作为解析层，向检索组件投喂文本**，
   不能依赖 PaperQA2 内建解析。
2. **`maybe_is_text` 英文中心启发式误拒中文 PDF**：`lt-dab4d327e195` 首次摄取报
   "This does not look like a text document"，需 `disable_doc_valid_check=True` 绕过。
3. **`aadd_file` 在 Windows 上 PermissionError**（NamedTemporaryFile 未关闭即重开）；
   改用 `aadd(path)` 直读路径解决。
4. **默认行为偏云**：citation 缺省→LLM 生成；title 存在且 `use_doc_details`→
   Semantic Scholar 在线查询（实测 429）；multimodal 默认开 enrichment→LLM。
   全部需显式关闭（`citation/title` 显式提供、`use_doc_details=False`、
   `multimodal=OFF`），否则无 Key 环境直接失败或产生外呼。
5. **依赖缺失**：`pypdf[image]` 需要 pillow（缺省报 ImportError）。

### 结论（供 FINAL_RECOMMENDATION 引用）

- PaperQA2 作为**检索/引用组织的设计参考**（Doc/Text/DocDetails 模型、页码范围块名、
  citation 元数据）有借鉴价值；作为**运行组件**在中文科研语料上不达标
  （解析乱码 + 英文中心 embedding + 默认外呼），**REFERENCE 而非 ADOPT**。
- 其 Agentic RAG 的引用返回机制（certs、evidence summary）需在获得授权 LLM 且
  接入 Docling 解析层后另行评测。

## C2：SciFact 官方口径复现（轻量基线，dev=300 claims，官方 S3 latest）

系统（全 CPU、秒级、可复现，seed=20261013）：
TF-IDF(title+abstract, stop=english, 1-2gram) 检索 top-3 → 句级 TF-IDF 选 top-3 理由句
（官方 MAX_ABSTRACT_SENTS=3）→ TF-IDF+LogisticRegression（**仅官方 train split**，
分布对齐：检索到非证据 doc → NEI 训练对，class_weight=balanced）。

| 指标（官方口径，镜像 verisci/evaluate） | 本次轻量基线 | 说明 |
|---|---|---|
| 摘要检索 gold∈top3 | 143/300（47.7%） | 瓶颈在检索 |
| Rationale Selection F1（严格整组判定） | P 0.055 / R 0.407 / **F1 0.097** | 严格口径：整组 rationale 命中才计分 |
| Label Accuracy（官方 label_prediction 语义） | **0.8311** | NEI 主导（ retrieved 非证据 doc 计为 NEI） |
| Label Macro-F1 | **0.4345** | C 0.105 / N 0.939 / S 0.259 |
| Macro-F1 without NEI | 0.182 | CONTRADICT 几乎不可分（词汇基线极限） |
| 混淆矩阵（行=true C/N/S） | [[5,14,27],[12,721,21],[32,46,22]] | `../results/scifact-metrics.csv` |

**口径声明**：① 本表是"官方评估代码语义的独立复算 + 弱基线系统"，
**不是** SOTA 复现——官方/后续 transformer 系统（论文 RoBERTa 流水线与 MultiVerS，
见 [SciFact 论文](https://arxiv.org/abs/2004.14974)、[MultiVerS](https://github.com/dwadden/multivers)）
在 dev 上显著更高；本机无 GPU、无授权 LLM，训练 transformer 不在本 POC 资源范围。
② `claims_test.jsonl` 无标签，未用于任何精度评测。③ NOT_ENOUGH_INFO 是数据集原始
第三类标签，本 POC 未发明新标签。④ 结论：**官方口径指标管线已可复现运行**；
SciFact 适合作为评测基准与任务模式，不适合作为运行时组件（代码 2023-10 后停更）。

## C3：端到端证据链最小闭环（Evidence Card）

- 流程：RQ（12 个人工核验问题）→ 检索（docling 段落语料 1820 块）→ 结构化主张候选 →
  SciFact 风格关系判定（词汇对齐启发式，**实验扩展标签** SUPPORT/INSUFFICIENT，
  非原始 SciFact 标签，无自动 CONTRADICT——诚实声明无反证识别能力）→ 卡片。
- 输出：`../results/evidence-cards-draft.jsonl`（12 卡，30 条证据：SUPPORT 15 /
  INSUFFICIENT 15；全部 `human_review_status=pending`、
  `allowed_for_agent_release=false`、`research_appraisal_status=not_assessed`）。
- 边界声明：卡片不写回 ChildEvidence 数据库；不得从关系标签推断干预有效性；
  "某研究发现与主张相符"≠"主张已获充分科学验证"。

## 未获得证据支持的结论（明示）

1. PaperQA2 的 Citation Precision/Citation Recall 未测（需 LLM 生成答案）。
2. SciFact transformer 级精度未复现（无 GPU/训练预算）。
3. GROBID 引用解析未实测（BLOCKED）。
4. A2 人工复核未完成 → 所有"相关性"结论仍是代理口径。
