# FINAL_RECOMMENDATION.md — ChildEvidence 三项开源技术 POC 技术选型报告

日期：2026-10-13。依据：`UPSTREAM_AUDIT.md`、`EXPERIMENT_PROTOCOL.md`、
`reports/{asreview-evaluation,pdf-parser-comparison,evidence-verification}.md` 与
`results/` 全部原始数据。所有数字均为本机实机测量，环境与版本见各文件。

---

## 8.1 Executive Summary

| 问题 | 结论 |
|---|---|
| ASReview 是否值得引入？ | **算法值得引入（PILOT），产品不集成**。AL 排序在代理标签下 Recall@20% 提升至 0.32–0.33（random 0.21），50% 预算处漏筛量减半（59–71 vs 136）；但 WSS@95 在 36% 正例占比下失真（0.07–0.15），且历史标签偏差会被模型放大。建议把 `nb+tfidf+max`（ELAS u3）作为排序器嵌入现有筛选界面，每批 10 条人工复核。 |
| Docling 与 GROBID 如何选择？ | **主解析器 Docling 2.138.0（ADOPT）**：10/10 真实 PDF 成功、页级文本覆盖率均值 0.80（pdfplumber 0.51）、100% 文本条目带页码+bbox 溯源、AI 目检页码命中 12/12、中文可靠。**GROBID 0.9.1 本机 BLOCKED**（build.gradle Windows 抛 Unsupported platform! + pdfalto 无 Windows 二进制 + 无 Docker/WSL2），其 TEI/坐标设计作 REFERENCE。pdfplumber 作 2.4s/文档的轻量回退。 |
| PaperQA2 是否适合作为科研证据检索组件？ | **REFERENCE，暂不 ADOPT**。离线实测：摄取 10/10 但内建 pypdf 解析对中文 CID 字体乱码、`maybe_is_text` 误拒中文、默认行为偏云（citation/元数据/enrichment 三处隐式外呼）、Windows `aadd_file` 有 PermissionError bug；本地 MiniLM 检索 doc_hit@5=3/12 低于自建 char-TF-IDF 的 8/12。其 Agentic RAG 因无授权 LLM 未测（BLOCKED）。 |
| SciFact 承担什么角色？ | **ADOPT 作为评测基准与任务模式**：官方口径指标管线已在 dev(300) 完整复现（本报告弱基线：检索命中 47.7%、Rationale F1 0.097、Label Macro-F1 0.435）；代码 2023-10 停更 → 不作运行时组件。 |
| 下一阶段优先实施什么？ | v0.1.1 存量审计 + A2 人工复核；v0.2 Docling 证据提取管道（页码/坐标溯源）；检索先用 char-TF-IDF/BM25 + Docling 语料；主张验证待有授权 LLM 后再建。 |

## 8.2 上游审查（要点，全文见 UPSTREAM_AUDIT.md）

| 项目 | 固定版本 | 上游 SHA/标签 | 许可证 | 维护状态 | 主要风险 |
|---|---|---|---|---|---|
| ASReview | 3.0.8（2026-06-18） | `79d5682`（2026-08-31） | Apache-2.0 | 活跃 | 模拟评估的 oracle 偏差；无 TF 依赖（Windows 友好） |
| Docling | 2.138.0 | `f0d9098`（2026-10-12） | MIT（模型 MIT/Apache 类） | 极活跃 | HF 模型下载需镜像；CPU 推理 ~40s/文档；迭代快需锁版本 |
| GROBID | 0.9.1（2026-08-04） | `523bb8e`（tag） | Apache-2.0 | 活跃 | **Windows 原生不支持**；Docker 为一等公民 |
| PaperQA2 | 2026.8.12 | `57e89f7`（2026-08-12） | Apache-2.0 | 活跃 | 默认云依赖多处；中文解析乱码；Windows aadd_file bug；CalVer 迭代快 |
| SciFact | commit `68b98a5` | 2023-10-15 | 代码 Apache-2.0；claims CC BY 4.0；语料 ODC-By 1.0 | **停更** | 仅作数据集/口径；test 集无标签 |

## 8.3 实验结果（数据集、方法、指标、置信度）

### POC-A（N=393，141 正例；5 种子；模拟完整排序）

| 指标 | svm_max | nb_max | logistic_max | tfidf_sim | random |
|---|---|---|---|---|---|
| Recall@10% | 0.172±.055 | 0.156±.059 | 0.160±.042 | 0.128±.038 | 0.112±.026 |
| Recall@20% | 0.325±.048 | 0.312±.039 | 0.323±.026 | 0.241±.052 | 0.210±.029 |
| WSS@95 | 0.118±.018 | 0.152±.011 | 0.146±.013 | 0.075±.016 | 0.067±.034 |
| Burden@95 | 346.6 | 333.4 | 335.8 | 363.4 | 366.8 |
| P@10% | 0.605 | 0.550 | 0.565 | 0.450 | 0.395 |
| bottom-50% 漏筛（去重） | 59 | 68 | 71 | 127 | 136 |

置信度：5 种子小样本，std 已报告；**标签为历史决策代理，非 Gold**——全部结论只支持
"排序效率差异"，不支持"真实筛选准确率"。失败案例：中文正例被排至 60–81% 分位、
1970s 理论文献沉底、citation_expansion 标签偏好被放大。

### POC-B（10 份真实 PDF：4 en 常规、3 zh、1 zh 元分析、1 短文、1 长文 54p）

| 指标 | Docling | pdfplumber | GROBID |
|---|---|---|---|
| 成功率 | 10/10 | 10/10 | BLOCKED |
| 页级文本覆盖率（有效参照 n=9） | **0.800** | 0.505 | — |
| 条目级页码+页内 bbox | 100%（2949 条） | 行级 100% | — |
| 表格结构 | 6 文档检出（TableFormer） | extract_tables（易误检） | — |
| 证据页码命中（AI 目检弱 Gold） | **12/12** | 8/8（抽查） | — |
| 每文档耗时 | 39.8 s | 2.4 s | — |

置信度：样本仅 10 份；参照为 pypdf 文本层（1 份中文因 pypdf CID 乱码判无效，
以渲染目检仲裁）；AI 目检非独立人类 Gold——指标标注为**弱参考**。
物理页/印刷页偏移实测：4↔2、21↔19、1↔1170（证据卡展示必须换算）。

### POC-C（C1 12 问题 + 10 PDF；C2 dev=300；C3 12 卡）

- C1：PaperQA2 离线 doc_hit@5 3/12（pypdf 中文乱码 + 英文中心 embedding）；
  自建 char-TF-IDF 基线 8/12；Agentic 生成 BLOCKED（无授权 LLM，0 次云调用）。
- C2：官方口径复现（弱基线）：检索 gold∈top3 143/300；Rationale F1 0.097；
  Label Acc 0.831 / Macro-F1 0.435（without NEI 0.182）；transformer 级复现未做（无 GPU）。
- C3：12 张 Evidence Card 草稿（SUPPORT 15 / INSUFFICIENT 15，扩展标签），
  全部 pending 人工审核，未写回正式库。

## 8.4 技术选型矩阵

权重：科研任务正确性 30% / 可追溯性 25% / 错误漏检风险 20% / 集成维护 10% /
性能资源 10% / 许可证部署 5%。打分 1–5（5 最好），基于上文实测。

| 候选 | 正确性×30% | 可追溯×25% | 风险×20% | 集成×10% | 性能×10% | 许可×5% | 加权 | 判定 |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| Docling 2.138.0 | 4.5 | 5.0 | 4.0 | 4.0 | 3.0 | 5.0 | **4.40** | **ADOPT** |
| ASReview 3.0.8（算法） | 3.5 | 3.0 | 3.5 | 3.5 | 4.5 | 5.0 | 3.48 | **PILOT**（算法层） |
| ASReview 3.0.8（完整产品） | 3.0 | 2.5 | 3.0 | 2.0 | 4.0 | 5.0 | 2.93 | REFERENCE |
| pdfplumber 0.11.x（回退） | 3.0 | 3.5 | 3.0 | 4.5 | 5.0 | 5.0 | 3.48 | ADOPT（仅作回退/校验） |
| PaperQA2 2026.8.12 | 2.0 | 2.5 | 2.0 | 2.5 | 3.0 | 5.0 | **2.33** | **REFERENCE** |
| SciFact（基准） | 4.0 | 4.0 | 4.0 | 4.0 | 5.0 | 5.0 | 4.10 | **ADOPT**（基准/口径） |
| SciFact（运行时组件） | 2.0 | 2.0 | 2.5 | 2.0 | 3.0 | 4.0 | 2.33 | REJECT |
| GROBID 0.9.1 | 4.0* | 4.0* | 3.0* | 2.0 | 2.0 | 5.0 | 3.45* | **BLOCKED**（本机；*为文档级评分，非实测） |

红线复核：无数据泄露（原库哈希一致）、无不可核查引用（Evidence Card 全部带页码+SHA）、
无许可证冲突（Apache/MIT/CC-BY/ODC-By 均可科研使用）。

## 8.5 Proposed Architecture（基于实测的下一阶段架构）

```text
┌─ ChildEvidence v0.1（保持不变）─────────────────────────┐
│ SQLite 事实源（works/api_log/…）＋ 只读快照访问层        │
└──────────────┬──────────────────────────────────────┘
               │ work_id / doi / sha256 / 本地 PDF 路径
┌──────────────▼──────────────────────────────────────┐
│ 解析 Adapter 层（v0.2 新增，可替换）                  │
│  DoclingParser（主，ADOPT）→ 结构化 JSON+页码+bbox   │
│  PdfPlumberParser（回退/交叉校验）                    │
│  GrobidParser（预留接口，待容器环境 PILOT）           │
│  统一中间结构：pages/sections/paragraphs/tables/refs  │
└──────────────┬──────────────────────────────────────┘
┌──────────────▼──────────────────────────────────────┐
│ 检索与排序层（v0.2–v0.3）                             │
│  筛选排序：TF-IDF + NB/SVM + max（借鉴 ASReview，     │
│            自研嵌入现有 UI，批 10 条人工复核）         │
│  证据检索：char-TF-IDF/BM25 over docling 段落         │
│           （Docling 语料为唯一解析源——PaperQA2 内建   │
│            解析对中文不可靠，实测依据见 POC-C）        │
└──────────────┬──────────────────────────────────────┘
┌──────────────▼──────────────────────────────────────┐
│ Evidence / Claim 建模（v0.3，分开建模）               │
│  Evidence：来源(SHA,物理页,印刷页,bbox,文本) + 关系标签 │
│  Claim：主张文本 + 证据关系（SUPPORT/CONTRADICT/NEI）  │
│  研究质量评价（appraisal）与关系判定严格分离          │
│  全部人工审核字段：pending→approved/rejected（不可绕过）│
└──────────────┬──────────────────────────────────────┘
               │ 仅 approved + 版本固定
┌──────────────▼──────────────────────────────────────┐
│ 知识包发布（v0.4+）：catalog/evidence-cards/strategies │
│ Agent Knowledge Pack（v0.5，后置，需授权 LLM 评测通过）│
└─────────────────────────────────────────────────────┘
```

原则：不新增微服务/图数据库（SQLite 够用）；解析器可替换；检索算法独立于筛选规程；
人工审核不可绕过；本地优先，云 LLM 须显式授权。

## 8.6 Implementation Roadmap（可转 GitHub Issues）

### v0.1.1 科研选择规程与存量审计

| # | 标题 | 验收标准 | 优先级 |
|---|---|---|---|
| 1 | 完成 A2 标注包 80 条人工复核（54 条历史拒收） | Gold Label 覆盖 A2 全部条目；kappa 双人复核（如有第二人）；更新 asreview-evaluation 结论 | P0 |
| 2 | 历史拒收重审流水线：AL 排序 + 人工队列界面 | 被模型排入 top-20% 的历史拒收全部人工过目；记录推翻率 | P0 |
| 3 | 筛选停止规则与抽样复核规程 | 文档化停止规则；每周抽样 20 条验证残余漏筛率 | P1 |
| 4 | 121 条缺失摘要条目补齐计划 | 缺摘要清单 + 人工补录规程（不虚构） | P1 |

### v0.2 PDF 证据提取

| # | 标题 | 验收标准 | 优先级 |
|---|---|---|---|
| 5 | DoclingParser adapter 入库 schema（pages/sections/paragraphs/tables/prov） | 统一 JSON schema；解析结果含 page_no+bbox；10 样本文档 100% 可溯源 | P0 |
| 6 | 解析流水线：SHA 校验→Docling→失败回退 pdfplumber→冲突标记 | 回归测试覆盖损坏 PDF/超时/空文档；双解析不一致→human_review | P0 |
| 7 | 印刷页码↔物理页码映射 | 每文档 page_map 自动提取 + 抽样校验（≥95% 目标） | P0 |
| 8 | 中文 CID 字体检测与 OCR 路由 | 检测 pypdf/docling 乱码（CJK 占比启发式）→标记待 OCR | P1 |
| 9 | 长文档（>50p）分块与增量解析 | 637p 文档解析内存 <4GB、可断点续跑 | P2 |

### v0.3 主张与证据综合

| # | 标题 | 验收标准 | 优先级 |
|---|---|---|---|
| 10 | Evidence/Claim 表结构（与 works 关联，不迁移动态） | schema 迁移脚本+兼容测试（ALTER TABLE） | P0 |
| 11 | 证据检索：char-TF-IDF/BM25 over 解析语料 | 12 题集 doc_hit@5 ≥ 8/12 保持；页码命中 ≥4/12 提升 | P0 |
| 12 | 主张-证据关系判定（授权 LLM 或本地 NLI，两案并行） | Citation Precision 人工评测 ≥95% 才准入；扩展标签明示 | P1 |
| 13 | Evidence Card 生成 + 人工审核 UI 字段 | 全卡 pending 初始态；审核流转审计字段 | P0 |
| 14 | SciFact 口径回归测试集（30 条自建主张） | 与 dev 分开报告；宏 F1 基线记录 | P2 |

### v0.4 专业指南工程 / v0.5 Agent Knowledge Pack

| # | 标题 | 验收标准 | 优先级 |
|---|---|---|---|
| 15 | 指南条目仅由 approved Evidence 组装 | 无未审核证据进入指南 | P0 |
| 16 | 知识包版本发布（manifest+哈希） | 版本固定、可验证 | P1 |
| 17 | Agent Pack：仅消费 approved 卡片；含证据定位回链 | 每条 agent 输出可回溯 PDF 页 | P1 |
| 18 | GROBID 容器环境补测（引用解析/consolidation） | Docker/WSL2 可用时执行；TEI+坐标评测协议沿用 POC-B | P2 |

依赖关系：5→6→7→8 串行；10←11←12；13 依赖 10；15 依赖 13；17 依赖 15、16。
风险提示：#12 在未获授权 LLM 前不得启动云方案；#1 是一切相关结论的前提。

---

## 9. 决策修订 v1.1（2026-10-13，用户复核 POC 汇报后生效）

> 本节为最终决策，与 §8.4 矩阵冲突处以本节为准。POC 全套材料作为**独立技术评估归档**，
> 不直接进入生产代码库。

### 9.1 总体判定

POC 工程执行：可验收；原始数据保护：通过；技术路线：方向明确；
**科研评测有效性：需修正与复核**；正式生产集成：尚未全部具备条件。

### 9.2 五项技术最终选型（"试验可用"与"生产可用"分开）

| 技术 | 决策 | 正式使用边界 |
|---|---|---|
| Docling 2.138.0 | **ADOPT** | 默认 PDF 解析组件；证据定位必须复核（bbox 存在≠坐标正确；12/12 目检≠全库 ≥95%）；覆盖率为解析器间相对指标 |
| ASReview 3.0.8 | **PILOT** | 保留主动学习排序能力；**禁止自动终局拒收**；WSS@95 一律用 v2 口径（0.95−B95/N） |
| GROBID 0.9.1 | **DEFER**（替代原 BLOCKED 判定） | 不投入 Windows 原生适配；待 Linux/容器环境补测 |
| PaperQA2 2026.8.12 | **REFERENCE** | 借鉴检索与引用机制；不直接集成整套 Agent |
| SciFact | **ADOPT Benchmark** | 用于主张关系的测试规范与指标参考；不作科研质量裁判 |

### 9.3 检索路线修正

char-TF-IDF（8/12 doc-hit@5）优于 PaperQA2 离线配置（3/12）仅基于 12 题，且
Document Hit@5 ≠ 证据段落召回率。**路线：先构建可靠的中英混合检索基线并固化评测集
（扩题），再依次检验 BM25、字符 n-gram、双语 Embedding、Reranker 的实际增益**；
不先引入 Agentic RAG。

### 9.4 指标修正执行记录（CE-01 已完成部分）

- WSS@95 已改为 **0.95 − B95/N** 并从原始排序重算（nb 0.102 / logistic 0.096 /
  svm 0.068 / tfidf 0.025 / random 0.017）；旧口径更名 `wss@95_unadjusted` 仅留痕。
- 运行次数澄清：**25 runs** = 20 次 ASReview Simulate（含官方 Random querier）+ 5 次自建 tfidf_sim。
- Missed@50 改为逐 run 口径：AL 42.6–47.2 vs random 72.4±3.8（理论 70.3）；
  v1 的跨种子并集数字（59–136）作废。
- 一致性测试：`results/asreview-consistency-tests.json` 25/25 通过；
  回归测试 test_16 固化该验收（16/16 通过）。
- 协议 §2（EXPERIMENT_PROTOCOL.md）与 reports/asreview-evaluation.md §0 已同步修订。

### 9.5 下一阶段关键路径（取代 18 项一次性推进）

| 阶段 | 任务 | 验收条件 |
|---|---|---|
| P0 | **CE-01 指标审计与科研规程冻结**（已完成机械部分） | 全部指标可从原始排序重算 + 数学一致性测试 ✅；检索/纳入/排除/评价规则文本冻结 |
| P0 | **CE-02 文献标注与选择质量审计** | A2 80 项可追溯的人类审核记录；分歧与无法判断条目单独标识；单人标注+复核抽样可接受，但必须保留审核者身份与方法；**不得以多模型投票冒充专家共识** |
| v0.2 | **CE-03 Docling 原文解析流水线** | 35 份原始 PDF 不变；输出可追溯至 PDF 哈希+解析器版本+原文位置；不自动生成科学结论 |
| v0.2 | **CE-04 原文定位 Gold Benchmark** | 独立于解析器构建的人工 Gold；按中英文/文档类型分别报告误差；处理印刷页偏移 |
| v0.3 | **CE-05 Evidence/Claim 最小模型** | 每张卡事实字段可溯源原文；未经审核不得发布 |

**PR 边界调整**：CE-03（数据加工层）与 CE-05（科研语义层）不得捆绑为同一 PR，
各自独立设计、测试与发布。

### 9.6 长期核心竞争力（产品原则）

ChildEvidence 的资产优先级：研究规程 > 证据体系 > 专业知识 > Agent 能力契约 >
持续验证机制；ASReview/Docling/PaperQA2 等均为可替换实现。演进次序：
先科研方法正确（v0.1.1）→ 再数据提取正确（v0.2）→ 最后 Agent 自动化（v0.5）。

---

## 附：本次未完成/受限事项（诚实清单）

1. A2 人工复核未执行（无人类标注员）→ 标注包已交付。
2. GROBID 未运行（本机环境限制，源码级证据已留档；最终决策 DEFER）。
3. PaperQA2 Agentic RAG 未运行（无授权 LLM Key，0 云调用）。
4. SciFact transformer 基线未训练（无 GPU）。
5. 证据定位 Gold 为 AI 目检弱参考（12 条），非独立人类 Gold。
6. 检索对比仅 12 题，样本过小（CE 阶段需扩题并改用证据段落级召回口径）。
