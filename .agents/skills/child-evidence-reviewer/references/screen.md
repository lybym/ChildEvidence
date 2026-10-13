# screen

参考 RESEARCH_METHODOLOGY §5、SCREENING_PROTOCOL §3–§7、ANNOTATION_GUIDE §3–§6（DRAFT v1.1）。先选 catalog 或 review；catalog 无 RQ，review 必有具体 RQ 对象/版本，核查 status=active 与人工 approved_by。未获批只报告未决提案，不能激活 RQ。

依次判断相关性、全文资格；方法质量另走 appraise，不能作为离题排除。`recommendation` 只用 relevant/boundary/not_relevant/undecided；这些是建议，不写 ingested/rejected/included/excluded。理由遵守已有代码：A01–A03、B01–B03、R01–R06、P01/U01。R06 必须穷尽 DOI/ISBN/报告编号/馆藏/官方页渠道且关键内容缺失；缺 DOI 本身不是排除理由。R04 需要实际重复对象依据。

经典理论、中文、负面结果、争议研究保留人工复核需求；语言、年代、引用量、结果方向不能作排除或质量代理。缺/短摘要（≤40字符）记录缺失，不生成。标题级建议不可冒充全文核验。仅使用指定 blinded 行；不展示历史标签、抽样层、模型排名或人工预填结论，不解盲。

输出 `assessments.relevance`；没有足够获准来源时 recommendation=undecided、P01/U01、unresolved，其他评价维度 null。
