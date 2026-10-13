# SCREENING_PROTOCOL.md — ChildEvidence 文献筛选与纳入规程

> 状态：**DRAFT v1.0（CE-01）** — Codex 起草（2026-10-13），待人工审核确认。
> 上位文件：RESEARCH_METHODOLOGY.md；配套：ANNOTATION_GUIDE.md、KNOWLEDGE_GOVERNANCE.md。

## 1. 目的与范围

规定研究文献从检索到纳入/排除的完整规程，覆盖全部 5 个研究领域
（child_development / learning_sciences / behavior_support / ai_children / china_family）。

硬性边界（继承 AGENTS #6–#8）：

- 只使用官方公开 API 与合法开放全文；禁止 Sci-Hub / LibGen / 绕过任何访问控制；
- 开放获取 ≠ 可自由再分发；许可证逐条记录，未知记 `license_unknown`；
- PDF 原文与 `data/` 运行数据永不提交 Git。

## 2. 检索规程

1. **数据源**（限定官方）：OpenAlex、Crossref、ERIC、Europe PMC、PubMed、Unpaywall、
   Semantic Scholar，以及机构官网（人工渠道）。每次检索记录 `source`、`query_key`、
   时间与命中数（`api_log` 已自动记录，不得删除）。
2. **检索式管理**：检索式必须挂接到某个 active RQ（RESEARCH_METHODOLOGY §5）；
   主题词变更须在 `runs.notes` 留痕。
3. **增量与幂等**：沿用 discover/verify/acquire 幂等流程；重复条目按
   DOI（NOCase）→ `title_norm` + `first_author_surname` 双通道去重，合并冲突置
   `merge_conflict=1` 人工处理。
4. **预印本**：独立标记 `document_type=preprint`，不与正式版本混同。

## 3. 纳入标准（全部满足方可纳入）

| 编号 | 标准 |
|---|---|
| I1 | 主题属于 §1 五个领域之一，且服务于某个 active RQ |
| I2 | 研究对象为 0–18 岁儿童青少年，或其照养者/教师/家庭系统；理论文献可放宽至概念体系本身 |
| I3 | 文献类型：实证、综述、元分析、理论/概念、实践指南均可；必须能归入 `evidence_category` |
| I4 | 语言：en / zh（现存 ja/it/de 条目保留，新增按 RQ 需要个案决定） |
| I5 | 具备标题；DOI 或等价官方标识可核验（`metadata_status`） |

## 4. 排除标准（命中即排除，须记理由代码）

| 编号 | 标准 | 理由代码 |
|---|---|---|
| E1 | 主题在五个领域之外 | R01 |
| E2 | 人群不符（非儿童/照养者场景，且无概念迁移价值） | R02 |
| E3 | 无可检验内容：纯商业宣传、无方法描述且无理论贡献 | R03 |
| E4 | 重复（与已纳入条目同内容） | R04 |
| E5 | 来源不可信：predatory 迹象、伪造元数据 | R05 |
| E6 | 元数据无法核验且关键内容缺失 | R06 |

## 5. 筛选流程与决策记录

1. **两级筛选**：T1 标题/摘要初筛 → T2 疑义条目进入 `P01 待定`（可全文辅助）。
2. **决策记录**：每次决策记录 `reviewer_id`、决策（ingested/rejected/pending）、
   理由代码（§4 / A01–A03）、一句话理由、时间戳。审计记录只追加不删除（AGENTS #2）。
3. **纳入理由代码**：A01 纳入-实证、A02 纳入-理论/综述、A03 纳入-实践指南。
4. **待定**：`P01` 是合法长期状态，未决条目不得进入证据提取（L6）。

## 6. 主动学习排序器的使用边界（POC-A 实测依据）

1. ASReview 类模型（nb/svm + tfidf + max）**只提供阅读顺序建议**；
   **禁止任何自动终局拒收**——排序末位的条目仍须人工确认或进入周期性复核。
2. 已知风险（POC-A errors.jsonl 实测）：中文正例被排至 60–81% 分位、1970s 经典理论
   文献沉底、历史关键词偏好被放大。因此以下层为**强制人工复核层**：
   - 全部中文条目；
   - 出版年 ≤2000 的理论/概念文献；
   - 负面/无显著结果研究；
   - 与既纳结论相悖的争议研究。
3. 停止规则：采用"连续 N 条不相关 + 定期抽样残余漏筛率估计"，阈值由人工确认后固化；
   模拟中的 WSS@95（v2 口径）不等于真实可停止性。

## 7. 缺失摘要处理

1. 缺失或过短摘要（≤40 字符）标记 `abstract_missing`，**不虚构补全**（AGENTS #3）。
2. 缺失摘要条目可参与标题级初筛，但纳入决策建议在摘要/全文补齐后作出。
3. 人工补录摘要须记录来源与补录人。

## 8. 质量控制

1. **分层复核**：按 `datasets`（POC A2 设计）分层抽样送人工复核；
   盲法要求见 ANNOTATION_GUIDE §2。
2. **误拒审计**：定期对 rejected 层抽样（重点：高主题词重叠、中文、经典理论、
   负面结果），估计误拒并回捞；A2 为富集样本，误拒率外推至全库需按分层加权校正。
3. **分歧处理**：按 ANNOTATION_GUIDE §6 执行。

## 9. 与历史标签的关系

- v0.1 的 393 条 `record_status`（141 ingested / 252 rejected）是**历史代理决策**；
- 本协议经人工确认生效后的决策记录（含理由代码与 reviewer）才构成可审计的
  Gold 级数据；两者在库中通过 `ingestion_notes` / 审核字段区分，不覆盖历史。

## 10. 变更记录

| 版本 | 日期 | 说明 |
|---|---|---|
| DRAFT v1.0 | 2026-10-13 | Codex 起草（CE-01）；待人工审核确认 |
