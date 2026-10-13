# audit

参考 ANNOTATION_GUIDE §2/§7/§8/§9、RESEARCH_METHODOLOGY M9、KNOWLEDGE_GOVERNANCE §7（DRAFT v1.1）。仅审计用户指定 AI 结果文件；先做确定性 schema/hash/许可预检，不自动读取人工库或历史标签。

核查同一来源不同结论、输入/规程版本漂移、缺失引用、伪 DOI、页码、未决被忽略、来源身份伪装、输出哈希与重复运行覆盖；区分结构失败和科学判断尚未核实。保留所有异常和原意见，不覆盖任何旧文件。数量/一致率不是正确率，更不是独立人类 Gold。

输出 `assessments.audit_issues`；未能逐项追溯时 unresolved。这里不读 A2 keyed CSV、不替 CE-02 完成 80 项人工审核、不对历史 proxy 计算专家准确率。以后独立专家 benchmark 的许可、身份和外部预测冻结应另行明确，本 Skill 不批量调度评测。
