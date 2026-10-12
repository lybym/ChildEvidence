# 采集执行报告（acquisition-report）

> 生成时间：2026-10-12 16:48 UTC；项目：ChildEvidence；数据来源：`library.sqlite` 实时查询，无人工估算。

## 总量与状态

- 数据库中文献记录总数（含候选/被拒）：393
- **正式入库（record_status=ingested）：141**
- 发现候选未入选：0
- 检索后按质量标准被拒：252

## 元数据核验

- Crossref 交叉核验通过：125
- 核验发现元数据冲突：0
- 无 DOI 文献（机构报告等，按官方来源核验）：12
- 需人工复核（标记 human_review_required）：0
- 撤稿记录：0；关注声明（expression of concern）：0

## 全文获取

- **成功下载并通过校验的 PDF：35**
- 有开放 HTML 全文但 PDF 待人工：39
- 官方 API 未列出任何开放 PDF 候选：66
- 需机构订阅人工获取：1
- 尚未尝试获取：0

## 分领域覆盖（一篇可属多领域）

| 领域 | 数量 |
|---|---|
| B. 教育心理学与学习科学 | 49 |
| A. 儿童发展心理学 | 36 |
| E. 中国儿童与家庭教育 | 30 |
| C. 儿童行为与心理支持 | 28 |
| D. AI 儿童陪伴与数字心理学 | 11 |
| F. 跨领域 / 综合资源 | 3 |

## 年代分布

| 年代 | 数量 |
|---|---|
| 1970s | 4 |
| 1980s | 4 |
| 1990s | 8 |
| 2000s | 17 |
| 2010s | 47 |
| 2020s | 61 |

## 语言分布

| 语言 | 数量 |
|---|---|
| en | 121 |
| zh | 20 |

## 证据类别分布

| 类别 | 数量 |
|---|---|
| 实证研究（设计待核） | 83 |
| Meta 分析 | 16 |
| 叙述性综述 | 15 |
| 理论/概念研究 | 9 |
| 系统综述 | 9 |
| 随机对照试验 | 3 |
| 政策/机构报告 | 3 |
| 循证实践指南 | 2 |
| 纵向研究 | 1 |

## 下载日志汇总

| 结果 | 次数 |
|---|---|
| failed | 126 |
| rejected | 13 |

## API 调用统计

| 来源 | 调用次数 | 成功 |
|---|---|---|
| acquisition | 190 | 64 |
| unpaywall | 160 | 151 |
| crossref | 157 | 147 |
| europepmc | 148 | 148 |
| openalex | 127 | 123 |
| eric | 6 | 6 |

## 最近运行记录

| id | 类型 | 开始 | 结束 | 说明 |
|---|---|---|---|---|
| 13 | verify | 2026-10-12T16:48:45Z | 2026-10-12T16:48:45Z | {"total": 0, "crossref_verified": 0, "conflict": 0, "api_error": 0, "no_doi_source_only": 0} |
| 12 | verify-pdfs | 2026-10-12T15:33:38Z | 2026-10-12T15:33:38Z | {"checked": 35, "ok": 35, "missing": 0, "corrupt": 0, "sha_mismatch": 0} |
| 11 | verify-pdfs | 2026-10-12T15:29:52Z | 2026-10-12T15:29:52Z | {"checked": 48, "ok": 48, "missing": 0, "corrupt": 0, "sha_mismatch": 0} |
| 10 | verify-pdfs | 2026-10-12T15:28:11Z | 2026-10-12T15:28:11Z | {"checked": 48, "ok": 48, "missing": 0, "corrupt": 0, "sha_mismatch": 0} |
| 9 | acquire | 2026-10-12T15:26:42Z | 2026-10-12T15:27:55Z | {"already": 0, "downloaded": 1, "duplicate_content": 0, "no_candidate": 66, "failed": 2, "open_html_only": 1, "manual_re |