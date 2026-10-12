# 研究分类体系（research-taxonomy）

> ChildEvidence Research Library v0.1。分类字段存储于 `library.sqlite`，由采集与人工审核共同维护。

## 研究领域（research_domains）

| 代码 | 含义 | 说明 |
|---|---|---|
| child_development | 儿童发展心理学 | 皮亚杰/维果茨基/埃里克森/鲍尔比/布朗芬布伦纳/班杜拉、执行功能、社会性与情绪发展、神经多样性 |
| learning_sciences | 教育心理学与学习科学 | SDT、自我调节学习、元认知、成长型思维、认知负荷、提取/间隔/交错练习、阅读与数学困难、反馈与脚手架 |
| behavior_support | 儿童行为与心理支持 | 情绪共同调节、挫折耐受、学习焦虑与回避、亲子冲突、正向行为支持、睡眠与习惯、SEL、转介边界 |
| ai_children | AI 儿童陪伴与数字心理学 | 儿童与对话式 AI、拟人化与信任、依赖与信任校准、隐私与伦理、生成式 AI 有效性、评估方法（重点 2023–2026） |
| china_family | 中国儿童与家庭教育 | 中国小学生学习行为、作业与课业压力、亲子互动、教育焦虑、CFPS/CEPS 实证研究；中文资料独立收录 |
| cross_domain | 跨领域 | 综合报告、方法论资源 |

## 主题标签（topic_tags）

示例：`executive_function`、`working_memory`、`self_regulated_learning`、`metacognition`、
`growth_mindset`、`cognitive_load`、`retrieval_practice`、`spaced_practice`、`interleaving`、
`emotion_regulation`、`co_regulation`、`attachment`、`peer_relations`、`empathy`、
`scaffolding`、`feedback`、`formative_assessment`、`homework`、`academic_pressure`、
`test_anxiety`、`procrastination`、`sleep`、`sel`、`conversational_ai`、`trust_calibration`、
`child_ai_privacy`、`generative_ai`、`neurodiversity`、`math_difficulties`、`reading`。

## 理论框架（theoretical_frameworks）

`piaget_cognitive_development`、`vygotsky_sociocultural_zpd`、`erikson_psychosocial`、
`bowlby_attachment`、`bronfenbrenner_bioecological`、`bandura_social_learning_self_efficacy`、
`self_determination_theory`、`cognitive_load_theory`、`baddeley_working_memory`、
`gross_emotion_regulation`。

## 证据类别（evidence_category）

| 代码 | 含义 | 判定方式 |
|---|---|---|
| meta_analysis | Meta 分析 | 标题/类型明确标识；机器初判，待人工确认 |
| systematic_review | 系统综述 | 标题/类型明确标识；机器初判 |
| narrative_review | 叙述性综述 | OpenAlex type=review 且非系统综述 |
| rct | 随机对照试验 | 标题明确标识 randomized trial |
| longitudinal | 纵向研究 | 标题含 longitudinal；待人工确认 |
| other_empirical | 实证研究（设计待核） | 默认值；全文阅读后升级 |
| theoretical_conceptual | 理论/概念研究 | 专著、章节等 |
| practice_guideline | 循证实践指南 | EEF/WWC 等机构指南 |
| policy_report | 政策/机构报告 | NAP/OECD/UNICEF 等报告 |
| preprint_empirical | 预印本（未经同行评议） | 独立标记，不等同正式发表 |

## 证据分级原则

1. 区分**研究设计分类**（上表）、**方法质量评估**（人工，需读全文）与**人工审核结论**（review_status/reviewer_notes）。
2. 不以期刊影响因子或引用量作为证据等级；引用量仅用于发现排序。
3. 主动收录重要的负面结果、重复失败与争议证据（如成长型思维效应量争议）。
4. 经典理论区分历史地位与当代实证支持：每条理论框架保留原始文献 + 当代检验/综述。
5. 群体统计结论不得解释为个体诊断；本库只做证据编目，不生成个体干预规则。

## 文献筛选原则

- 优先同行评议、高质量系统综述/Meta 分析、方法严谨的实验与纵向研究。
- 经典研究不受年份限制；前沿研究重点覆盖近五年（尤其 2024–2026）。
- 预印本单独标记，不作为正式证据。
- 宁缺毋滥：不编造数据凑数；无法核实的关键字段置 NULL 并注明待读全文。
