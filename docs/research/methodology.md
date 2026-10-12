# 采集方法与可重复执行说明（methodology）

> 生成日期：2026-10-12。本文档说明 research-library 首批采集的数据来源、检索词、筛选规则、下载策略、
> 去重逻辑、版权处理与质量限制；所有步骤可由 CLI 重复执行并增量更新。

## 1. 数据来源与优先级

- **发现与开放全文定位**：OpenAlex（`api.openalex.org`，polite pool，mailto 标识）
- **DOI 与出版元数据核验**：Crossref（`api.crossref.org`）
- **领域补充检索**：ERIC（`api.ies.ed.gov/eric/`）、Europe PMC（`ebi.ac.uk/europepmc/webservices/rest`）
- **OA 定位补充**：Unpaywall（`api.unpaywall.org/v2/<doi>`，仅新版按 DOI 查询接口）
- **机构报告**：National Academies Press、EEF、WWC(IES)、OECD、UNICEF 官方页面
- **中文/中国研究**：经 OpenAlex/Crossref 检索中国主题的英文与中文文献；CNKI/万方无开放 API，
  只保留书目元数据并进入人工下载队列，不绕过任何访问控制。

## 2. 检索词与查询（topics.yaml，共 76 条）

- `dev_ef_recent`（A. 儿童发展心理学）: {"title.search": "executive function", "from_publication_date": "2018-01-01", "type": "article|review"}
- `dev_ef_reviews`（A. 儿童发展心理学）: {"title.search": "executive function", "from_publication_date": "2015-01-01", "type": "review"}
- `dev_ef_training`（A. 儿童发展心理学）: {"title.search": "executive function training", "from_publication_date": "2014-01-01"}
- `dev_zpd`（A. 儿童发展心理学）: {"title.search": "zone of proximal development"}
- `dev_scaffolding`（A. 儿童发展心理学）: {"title.search": "scaffolding", "from_publication_date": "2016-01-01", "type": "article|review"}
- `dev_attachment`（A. 儿童发展心理学）: {"title.search": "attachment security", "from_publication_date": "2015-01-01"}
- `dev_emotion_regulation`（A. 儿童发展心理学）: {"title.search": "emotion regulation", "from_publication_date": "2020-01-01", "type": "article|review"}
- `dev_peer_empathy`（A. 儿童发展心理学）: {"title.search": "empathy children"}
- `dev_self_efficacy`（A. 儿童发展心理学）: {"title.search": "self-efficacy", "from_publication_date": "2019-01-01", "type": "article|review"}
- `dev_ecological`（A. 儿童发展心理学）: {"title.search": "ecological systems"}
- `dev_neurodiversity`（A. 儿童发展心理学）: {"title.search": "neurodiversity", "from_publication_date": "2020-01-01"}
- `dev_piaget`（A. 儿童发展心理学）: {"title.search": "Piaget"}
- `dev_erikson`（A. 儿童发展心理学）: {"title.search": "psychosocial development"}
- `dev_social_competence`（A. 儿童发展心理学）: {"title.search": "social competence", "from_publication_date": "2018-01-01", "type": "article|review"}
- `dev_epmc_ef_training`（A. 儿童发展心理学）: executive function training AND children
- `ls_srl`（B. 教育心理学与学习科学）: {"title.search": "self-regulated learning", "from_publication_date": "2017-01-01", "type": "article|review"}
- `ls_srl_elementary`（B. 教育心理学与学习科学）: {"title.search": "self-regulated learning elementary"}
- `ls_metacognition`（B. 教育心理学与学习科学）: {"title.search": "metacognition", "from_publication_date": "2019-01-01", "type": "article|review"}
- `ls_metacognition_children`（B. 教育心理学与学习科学）: {"title.search": "metacognition children"}
- `ls_retrieval_practice`（B. 教育心理学与学习科学）: {"title.search": "retrieval practice", "from_publication_date": "2015-01-01"}
- `ls_spaced`（B. 教育心理学与学习科学）: {"title.search": "spaced practice"}
- `ls_interleaving`（B. 教育心理学与学习科学）: {"title.search": "interleaving"}
- `ls_cognitive_load`（B. 教育心理学与学习科学）: {"title.search": "cognitive load", "from_publication_date": "2018-01-01", "type": "article|review"}
- `ls_working_memory`（B. 教育心理学与学习科学）: {"title.search": "working memory academic"}
- `ls_growth_mindset`（B. 教育心理学与学习科学）: {"title.search": "growth mindset", "from_publication_date": "2018-01-01"}
- `ls_sdt_motivation`（B. 教育心理学与学习科学）: {"title.search": "self-determination theory", "from_publication_date": "2018-01-01"}
- `ls_formative_assessment`（B. 教育心理学与学习科学）: {"title.search": "formative assessment", "from_publication_date": "2017-01-01"}
- `ls_math_difficulties`（B. 教育心理学与学习科学）: {"title.search": "mathematical learning difficulties"}
- `ls_number_sense`（B. 教育心理学与学习科学）: {"title.search": "number sense", "from_publication_date": "2016-01-01"}
- `ls_reading`（B. 教育心理学与学习科学）: {"title.search": "reading comprehension", "from_publication_date": "2019-01-01", "type": "article|review"}
- `ls_test_anxiety`（B. 教育心理学与学习科学）: {"title.search": "test anxiety", "from_publication_date": "2016-01-01"}
- `ls_procrastination`（B. 教育心理学与学习科学）: {"title.search": "academic procrastination"}
- `ls_eric_metacog`（B. 教育心理学与学习科学）: metacognition AND elementary AND peerreviewed:T
- `ls_eric_math_rct`（B. 教育心理学与学习科学）: mathematics intervention AND randomized AND elementary AND peerreviewed:T
- `bs_co_regulation`（C. 儿童行为与心理支持）: {"title.search": "co-regulation"}
- `bs_self_regulation`（C. 儿童行为与心理支持）: {"title.search": "self-regulation", "from_publication_date": "2019-01-01", "type": "article|review"}
- `bs_pbs`（C. 儿童行为与心理支持）: {"title.search": "positive behavior support"}
- `bs_homework_parent`（C. 儿童行为与心理支持）: {"title.search": "parental involvement homework"}
- `bs_emotion_coaching`（C. 儿童行为与心理支持）: {"title.search": "emotion coaching"}
- `bs_school_anxiety`（C. 儿童行为与心理支持）: {"title.search": "school anxiety", "from_publication_date": "2017-01-01"}
- `bs_delay_gratification`（C. 儿童行为与心理支持）: {"title.search": "delay of gratification"}
- `bs_sleep`（C. 儿童行为与心理支持）: {"title.search": "sleep problems children"}
- `bs_sel`（C. 儿童行为与心理支持）: {"title.search": "social-emotional learning", "from_publication_date": "2016-01-01"}
- `bs_sel_eric`（C. 儿童行为与心理支持）: social emotional learning AND elementary AND peerreviewed:T
- `bs_parent_conflict`（C. 儿童行为与心理支持）: {"title.search": "parent-child conflict"}
- `bs_school_mental_health`（C. 儿童行为与心理支持）: {"title.search": "school mental health services", "from_publication_date": "2016-01-01"}
- `bs_epmc_stress`（C. 儿童行为与心理支持）: academic stress AND children AND randomized
- `ai_conversational_agents`（D. AI 儿童陪伴与数字心理学）: {"title.search": "conversational agents children", "from_publication_date": "2021-01-01"}
- `ai_voice_assistants`（D. AI 儿童陪伴与数字心理学）: {"title.search": "voice assistants children", "from_publication_date": "2020-01-01"}
- `ai_trust`（D. AI 儿童陪伴与数字心理学）: {"title.search": "trust in AI", "from_publication_date": "2022-01-01"}
- `ai_companion`（D. AI 儿童陪伴与数字心理学）: {"title.search": "AI companion", "from_publication_date": "2023-01-01"}
- `ai_chatbot_learning`（D. AI 儿童陪伴与数字心理学）: {"title.search": "chatbot learning", "from_publication_date": "2021-01-01"}
- `ai_generative_education`（D. AI 儿童陪伴与数字心理学）: {"title.search": "generative AI", "from_publication_date": "2023-01-01", "type": "article|review"}
- `ai_llm_tutoring`（D. AI 儿童陪伴与数字心理学）: {"title.search": "language model tutoring", "from_publication_date": "2023-01-01"}
- `ai_child_robot`（D. AI 儿童陪伴与数字心理学）: {"title.search": "child-robot interaction", "from_publication_date": "2019-01-01"}
- `ai_privacy`（D. AI 儿童陪伴与数字心理学）: {"title.search": "children data privacy", "from_publication_date": "2021-01-01"}
- `ai_ethics_education`（D. AI 儿童陪伴与数字心理学）: {"title.search": "AI ethics education", "from_publication_date": "2022-01-01"}
- `ai_epmc_conversational`（D. AI 儿童陪伴与数字心理学）: conversational agent AND children AND (PUB_YEAR:2024 OR PUB_YEAR:2025 OR PUB_YEAR:2026)
- `cn_academic_stress`（E. 中国儿童与家庭教育）: {"title.search": "academic stress China"}
- `cn_academic_pressure`（E. 中国儿童与家庭教育）: {"title.search": "academic pressure Chinese"}
- `cn_homework`（E. 中国儿童与家庭教育）: {"title.search": "homework Chinese"}
- `cn_parenting`（E. 中国儿童与家庭教育）: {"title.search": "parenting Chinese children"}
- `cn_srl`（E. 中国儿童与家庭教育）: {"title.search": "self-regulated learning Chinese"}
- `cn_emotion`（E. 中国儿童与家庭教育）: {"title.search": "emotion regulation Chinese"}
- `cn_cfps`（E. 中国儿童与家庭教育）: China Family Panel Studies
- `cn_ceps`（E. 中国儿童与家庭教育）: China Education Panel Survey
- `zh_executive_function`（E. 中国儿童与家庭教育）: 执行功能 儿童
- `zh_family_education`（E. 中国儿童与家庭教育）: 小学生 家庭教育
- `zh_learning_motivation`（E. 中国儿童与家庭教育）: 学习动机 小学生
- `cn_education_anxiety`（E. 中国儿童与家庭教育）: {"title.search": "education anxiety China"}
- `cn_engagement`（E. 中国儿童与家庭教育）: {"title.search": "student engagement China"}
- `cn_eric_elementary`（E. 中国儿童与家庭教育）: China AND elementary school students AND peerreviewed:T
- `cn_journal_classics`（E. 中国儿童与家庭教育）: {"primary_location.source.id": "S4306548924|S4306548927|S4210189644|S4306548935", "type": "article"}
- `cn_journal_recent_ef`（E. 中国儿童与家庭教育）: 执行功能
- `cn_journal_recent_family`（E. 中国儿童与家庭教育）: 父母教养
- `cn_journal_recent_emotion`（E. 中国儿童与家庭教育）: 情绪调节

## 3. 筛选规则（discover.run_topics / promote_candidates）

- 排除：无标题/无作者/无年份、撤稿记录、editorial/letter/erratum/paratext、年份越界。
- 每条查询最多入库 10 条候选；按领域配额（topics.yaml `quota`）用打分器择优转正：
  Meta 分析 +3.5、系统综述 +3.0、RCT +2.2、2024+ 新近 +1.0、高被引 +1.5、
  开放获取 +0.6、期刊同行评议 +0.8、AI 领域 2024+ 额外 +1.5；预印本 -1.0。
- 未入选候选保留 `record_status='rejected'` 供审计。

## 4. 下载策略（acquisition.py）

1. 仅尝试官方 API 标注为开放获取的 URL：Europe PMC（PMCID 全文库）、OpenAlex OA location、
   Unpaywall `url_for_pdf`、Crossref 全文链接、ERIC 官方文件库、机构官方页面。
2. 下载校验：HTTP 200 → Content-Type 检查（拒绝 text/html）→ `%PDF-` 文件头 → 体积下限
   → `%%EOF` 尾标记 → 页数扫描（含对象流解压）→ SHA-256 → 跨文献重复内容检测。
3. 记录：最终 URL、来源、时间、版本（published/accepted/submitted，来自 API 元数据）、
   许可证（API 提供；未知记 `license_unknown`，不臆断可再分发）。
4. 失败重试：指数退避（2/5/10s），尊重 Retry-After；每次尝试写入 download_log。
5. 原始 PDF 仅保存在本地 `data/research-library/pdf/`，不提交公共仓库。

## 5. 去重逻辑（dedup.py）

- **DOI 精确匹配**（规范化小写）→ 合并进已有条目。
- 无 DOI：规范化标题全等 + 年份一致 + 第一作者姓氏一致 → 保守合并。
- 相似度 ≥0.93 且（≥0.98 或同第一作者姓氏）→ **不合并**，标记 `human_review_required`。
- 合并冲突（如年份不一致）写入 `conflicting_metadata` 并转人工复核。

## 6. 版权处理

- 开放获取 ≠ 可自由再分发：许可证逐条记录，未知记 `license_unknown`。
- 付费文献只保存书目信息与官方链接；PDF 一律人工经机构订阅获取。
- 不访问 Sci-Hub/LibGen 等侵权来源；不绕过付费墙、验证码或访问控制。

## 7. 质量限制与人工复核

- `metadata_status`：crossref_verified / no_doi_source_only / conflict / api_error。
- 研究方法、样本量、效应量等高级字段默认 NULL，需阅读全文后人工填写（review_status）。
- 撤稿状态来自 Crossref `update-to` 与 OpenAlex `is_retracted`；未查到撤稿不代表无其他争议。

## 8. 可重复执行

```bash
# 环境：Python 3.11+（无需第三方依赖）
export RESEARCH_LIBRARY_DATA_DIR=<数据目录>   # 可选，默认 <repo>/data/research-library
python -m research_library discover   # 种子+主题检索+引用扩展+择优入库
python -m research_library verify     # Crossref 核验 + OpenAlex 回填
python -m research_library acquire    # 合法开放 PDF 下载与校验
python -m research_library export     # CSV/JSONL/BibTeX
python -m research_library docs       # 重新生成 docs/research/*.md
python -m research_library status     # 当前建设状态
```

API 缓存（C:\CODE\ChildEvidence\data\research-library\cache）默认 7 天 TTL；删除缓存即可强制重新拉取。
数据库 WAL 模式，进程中断可安全重跑；所有命令幂等（跳过已完成条目）。
