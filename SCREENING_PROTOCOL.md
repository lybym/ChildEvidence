# SCREENING_PROTOCOL.md — ChildEvidence 文献筛选与纳入规程

> 状态：**DRAFT v1.1（CE-01R）** — 2026-10-13 依据跨文件一致性审计修订（逐条意见见
> [docs/governance/CE-01R-REVIEW.md](docs/governance/CE-01R-REVIEW.md)）。
> **仍待人工审核，未生效**：Agent 不得将本文件当作生效准则执行（见 AGENTS.md 科研治理节）；
> 人工批准以 [docs/governance/CE-01R-CHECKLIST.md](docs/governance/CE-01R-CHECKLIST.md) 为准。
> 上位文件：RESEARCH_METHODOLOGY.md；配套：ANNOTATION_GUIDE.md、KNOWLEDGE_GOVERNANCE.md。

## 1. 目的与范围

规定研究文献从检索到纳入/排除的完整规程，覆盖全部 5 个研究领域
（child_development / learning_sciences / behavior_support / ai_children / china_family）。

**双轨适用（RESEARCH_METHODOLOGY §5）**：

- **轨道 A（馆藏建设）**：不要求绑定 RQ；本规程的 I/E 标准按"馆藏收录价值"裁剪执行，
  决策值域 `ingested / rejected / pending`。
- **轨道 B（RQ 专题评价）**：必须挂接 active RQ（RESEARCH_METHODOLOGY §6）；I/E 标准
  在该 RQ 的 scope 与 hints 内裁剪执行，决策值域 `included / excluded / pending`
  （记录必须携带 `rq_id` + RQ 版本）。两类决策互不混用。

硬性边界（继承 AGENTS #6–#8）：

- 只使用官方公开 API 与合法开放全文；禁止 Sci-Hub / LibGen / 绕过任何访问控制；
- 开放获取 ≠ 可自由再分发；许可证逐条记录，未知记 `license_unknown`；
- PDF 原文与 `data/` 运行数据永不提交 Git。

## 2. 检索规程

1. **数据源**（限定官方）：OpenAlex、Crossref、ERIC、Europe PMC、PubMed、Unpaywall、
   Semantic Scholar，以及机构官网（人工渠道）。每次检索记录 `source`、`query_key`、
   时间与命中数（`api_log` 已自动记录，不得删除）。
2. **检索式管理**：**轨道 B** 的检索式必须挂接到某个 active RQ 的具体版本
   （RESEARCH_METHODOLOGY §6）；主题词变更须在 `runs.notes` 留痕。**轨道 A** 的
   广域检索（Scoping/Horizon Scanning）不挂接 RQ，但同样留痕并可回溯。
3. **增量与幂等**：沿用 discover/verify/acquire 幂等流程；重复条目按
   DOI（NOCase）→ `title_norm` + `first_author_surname` 双通道去重，合并冲突置
   `merge_conflict=1` 人工处理。
4. **预印本**：独立标记 `document_type=preprint`，不与正式版本混同。

## 3. 纳入标准（全部满足方可纳入）

| 编号 | 标准 |
|---|---|
| I1 | 主题属于 §1 五个领域之一；轨道 B 另需服务于该 active RQ 的 scope，轨道 A 只需馆藏收录价值 |
| I2 | 研究对象为 0–18 岁儿童青少年，或其照养者/教师/家庭系统；理论文献可放宽至概念体系本身 |
| I3 | 文献类型：实证、综述、元分析、理论/概念、实践指南均可；必须能归入 `evidence_category` |
| I4 | 语言：en / zh（现存 ja/it/de 条目保留，新增按 RQ 需要个案决定）；中文资料受 §6 保护层约束，语言不得作为排除理由 |
| I5 | 具备标题，且标识符满足下列之一（v1.1 放宽，避免误杀无 DOI 经典著作）：DOI；ISBN（图书/报告）；机构报告编号（如 NAP/EEF/WWC/UNICEF/OECD 编号）；权威馆藏记录（OCLC/WorldCat、国家图书馆等可核验条目）；或经核验的官方出版页 URL。任一可核验标识即满足，`metadata_status` 记录实际使用的标识类型 |

## 4. 排除标准（命中即排除，须记理由代码）

**三级判定分离（v1.1，RESEARCH_METHODOLOGY §8.2）**：筛选阶段依次判定
①相关性（是否离题）→ ②全文资格（是否可评）→ ③研究方法质量（appraisal，L6 阶段）。
E 系列只覆盖 ①②；**方法质量低不是排除理由**——它影响证据等级与适用边界，
不得写成任何 R 系列代码，也不得把"方法差"当作 R03"无可检验内容"的同义词。

| 编号 | 标准 | 理由代码 |
|---|---|---|
| E1 | 主题在五个领域之外（且轨道 B 下不落入该 RQ scope） | R01 |
| E2 | 人群不符（非儿童/照养者场景，且无概念迁移价值） | R02 |
| E3 | 无可检验内容：纯商业宣传、无方法描述且无理论贡献 | R03 |
| E4 | 重复（与已纳入条目同内容） | R04 |
| E5 | 来源不可信：predatory 迹象、伪造元数据 | R05 |
| E6 | 标识符经 I5 所有渠道核验仍不可得，且关键内容缺失（v1.1 收紧措辞：必须先穷尽 I5 的 ISBN/报告编号/馆藏记录渠道，仅"无 DOI"不构成 E6） | R06 |

## 5. 筛选流程与决策记录

1. **两级筛选**：T1 标题/摘要初筛 → T2 疑义条目进入 `P01 待定`（可全文辅助）。
2. **决策记录**：每次决策记录 `reviewer_id`、决策、理由代码（§4 / A01–A03）、
   一句话理由、时间戳，以及**决策轨道与值域**：轨道 A 记 `ingested/rejected/pending`；
   轨道 B 记 `included/excluded/pending` 并附 `rq_id` + RQ 版本。审计记录只追加不删除
   （AGENTS #2）。
3. **纳入理由代码**：A01 纳入-实证、A02 纳入-理论/综述、A03 纳入-实践指南。
4. **待定**：`P01` 是合法长期状态，未决条目不得进入证据提取（L6）。
5. 逻辑契约（值域与字段分离）：
   [docs/governance/contracts/CE-01R-decision-scope.contract.json](docs/governance/contracts/CE-01R-decision-scope.contract.json)。

## 6. 主动学习排序器的使用边界与筛选停止规则（POC-A 实测依据）

1. ASReview 类模型（nb/svm + tfidf + max）**只提供阅读顺序建议（排序）**；
   **禁止任何自动终局拒收**——排序末位的条目仍须人工确认或进入周期性复核。
2. **停止声明的禁令（v1.1 明确）**：在停止规则参数完成人工批准且残余漏筛率完成独立
   评估之前，**禁止**宣布筛选已达到"95% 召回 / WSS@95 达标 / 可停止"；模拟口径的
   WSS@95（含 v2 修正口径，见 docs/governance/CE-01R-ERRATA.md）只是排序效率指标，
   **不构成**真实停止性证明。AL 排序不得自动生成停止结论。
3. 已知风险（POC-A errors.jsonl 实测）：中文正例被排至 60–81% 分位、1970s 经典理论
   文献沉底、历史关键词偏好被放大。
4. **强制人工复核层（保护层）的可操作定义（v1.1 操作化）**——满足任一即入层，
   入层条目不得由排序位置决定去留：
   - **中文条目**：`language=zh`，或出版机构/作者机构位于中国大陆/港台且原文为中文；
   - **经典理论文献**：出版年 ≤2000 且 `evidence_category ∈ {theoretical_conceptual,
     narrative_review}`，或属 README §研究范围所列理论框架的原典/综述；
   - **负面/无显著结果研究**：摘要或结果声明"无显著效应/未达显著/n.s."或方向与主流相反；
   - **争议研究**：与既纳结论 CONTRADICT、存在已登记的方法学争议或
     `expression_of_concern`。
5. **停止规则**：采用"连续 N 条不相关 + 定期抽样残余漏筛率估计"，阈值由人工确认后
   固化并记录批准人；停止规则的每次参数变更同样需人工批准。残余漏筛率估计必须
   独立于 AL 排序（如按保护层/随机层抽样），不得用模型自身评分自证漏筛率。

## 7. 缺失摘要处理

1. 缺失或过短摘要（≤40 字符）标记 `abstract_missing`，**不虚构补全**（AGENTS #3）。
2. 缺失摘要条目可参与标题级初筛，但纳入决策建议在摘要/全文补齐后作出。
3. 人工补录摘要须记录来源与补录人。

## 8. 质量控制

1. **分层复核**：按 `datasets`（POC A2 设计）分层抽样送人工复核；
   盲法要求见 ANNOTATION_GUIDE §2。
2. **误拒审计**：定期对 rejected 层抽样（重点：高主题词重叠、中文、经典理论、
   负面结果），估计误拒并回捞；A2 为富集样本，误拒率外推至全库需按分层加权校正。
3. **分歧处理**：按 ANNOTATION_GUIDE §6/§7 执行。

## 9. 与历史标签的关系

- v0.1 的 393 条 `record_status`（141 ingested / 252 rejected）是**轨道 A 馆藏层的历史
  代理决策**（RESEARCH_METHODOLOGY §5.3/§7）；其含义不因 RQ 语义引入而改变，不得被
  自动解释为任何 RQ 的 included/excluded，不得自动翻转或自动升级标签层级。
- 本协议经人工确认生效后的决策记录（含理由代码与 reviewer、按 §5 标注轨道与值域）
  才可能成为 Gold 级数据（Gold 资格流程见 RESEARCH_METHODOLOGY §7）；两者在库中通过
  `ingestion_notes` / 审核字段区分，不覆盖历史。

## 10. 变更记录

| 版本 | 日期 | 说明 |
|---|---|---|
| DRAFT v1.0 | 2026-10-13 | Codex 起草（CE-01）；待人工审核确认 |
| DRAFT v1.1 | 2026-10-13 | CE-01R 一致性审计修订：双轨适用与值域分离、I5 标识放宽（ISBN/报告编号/馆藏记录）、三级判定分离、E6 措辞收紧、停止声明禁令与保护层可操作定义、历史标签轨道归属明确；**仍待人工审核，未生效** |
