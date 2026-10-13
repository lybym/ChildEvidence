# extract

参考 RESEARCH_METHODOLOGY M2/M3/M8、§8.1/§8.2，KNOWLEDGE_GOVERNANCE §3（DRAFT v1.1），CE-03 docs/parsing/README.md §4/§6。

核对指定研究的设计、样本、发现、效应、区间、统计量、方向和限制；每个事实引用实际原文定位，不能从标题推断统计量。关系只用 SUPPORT/CONTRADICT/NOT_ENOUGH_INFO，与质量分开。缺全文、定位不可靠、数字/单位/分母不一致 → unresolved；缺字段保持 null。

Docling 引用携带源 PDF SHA、paragraph_id、物理页、原文字符区间。印刷页只接受既有人工作业映射，未知 null；不推算固定页差。解析文本片段匹配仅为 `matched_local_text`，不会证明 PDF 上位置正确，不能标 verified。PDF 只有二进制哈希不能验证引文；复用已有 CE-03 产物，不新建解析器或改解析结果。

输出 findings 与 `assessments.evidence_relation`；EvidenceCard 仅被读作草稿，不能 approved 或进入知识包。
