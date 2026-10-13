# ChildEvidence 手动 AI Reviewer Skill 验证记录

日期：2026-10-14。范围：用户最新规格 `USER_PROVIDED_SCOPE`，无对应 GitHub Issue URL。
这是独立、按需、显式调用的 Codex Skill；撤回的 API 执行器/AI SQLite/CLI/80项批量模拟方案
未实现。本次不关联 CE-02 Issue #2，不完成或代填其人工审核，不修改任何科研治理门禁。

## 工程验证

| 检查 | 结果 | 证明范围 |
|---|---|---|
| 本机 Codex `skills/list` | child-evidence-reviewer enabled=true、scope=repo | 真实发现；未创建模型审查会话 |
| agents/openai.yaml | allow_implicit_invocation=false | 静态配置与官方语义；未实测普通 prompt 不激活 |
| 官方 Skill quick_validate | Skill is valid | 使用已有开发环境 PyYAML；无运行时新依赖 |
| 全量 unittest | 231/231 PASS（原185+新增46） | 核心回归及Skill离线确定性行为 |
| smoke_offline | PASS | 既有离线流水线正常 |
| research status | 141 ingested / 252 rejected / 35 PDF | 既有目录规模；未回填AI记录 |
| Schema | 独立 Draft202012Validator.check_schema + 5/5真实演示验证通过 | 仅开发校验复用已有 jsonschema；Skill运行时无依赖，不等于科学事实正确性 |
| git diff --check | PASS | 无格式空白错误 |

新增测试覆盖显式配置/五模式、AI身份和Gold拒绝、缺来源与事实 abstain、
DOI/页码/字符区间/引文不一致、中文英文和注入字面量、不执行文本指令、
JSON重复键/NaN/无效结构、A/B隔离声明与分歧保留、原始SQLite只读与连接关闭、
来源哈希、许可不可覆盖、受限出站拒绝、同run重复写入拒绝、历史保留和版本校验。
网络被测试桩禁止，模型调用不存在；验证器标准库不 import API SDK。

独立工程复审发现并修复两项 P1：来源 Work 与 scope 可能错归属、合法元数据声明
可能被用来掩盖受限引用。新增6项回归用合法 metadata 与受限 text 混合夹具证明：
重新计算合法哈希仍不能错误归属 Work；queue/sample/document 不被推断为 Work；
模型全部引用须放行且声明实际发送，blocked 状态与两 Pass 原始结果都不豁免；
模式评价无受控引用时也不能通过。旧五项演示保留，以下列出的新run冻结修复后文件版本。

## 少量真实来源演示

每个模式仅一项来源。全部输出四件产物于本地 gitignored
`data/review/ai-review/<run_id>/`。完整记录含输入/protocol/skill哈希与结果状态；
本表不包含原文/摘要，不提交真实产物到 Git。

| 模式 | 实际来源（只读本地） | run_id | 状态 | 实际模型审查 |
|---|---|---|---|---|
| screen | 主SQLite选择 work_id=lt-1183287e1b1c 的白名单元数据 | demo-6324126451e04df8809610685342cade | blocked | false |
| appraise | 该条目的既有本地PDF | demo-35c2b96396ac4f3daec13ec3102ca4db | blocked | false |
| extract | 既有 POC Docling 产物 lt-1183287e1b1c.docling.json | demo-909c690f872f46eeb864ac0c58a01165 | blocked | false |
| challenge | 既有 POC evidence-cards-draft.jsonl（仅哈希，不读研究内容到会话） | demo-f04f0b7c79614f658b9945efc9445e91 | blocked | false |
| audit | 此次 screen 演示的 review.json（仅确定性来源校验） | demo-a6220f338c644d00930c1f97096769f3 | blocked | false |

5/5 结构/provenance校验通过，5/5来源字节SHA与演示前一致。screen 的许可未确认；
其他内容受现行摘要/PDF/衍生文本出站边界限制。每个结果 findings=[]、方法评价=null，
模型ID/snapshot=null、model_identity_status=not_called、silver/L0、无发布资格。
POC Docling 原格式与 CE-03 统一格式有别，本次只验证其文件哈希/出站拒绝，未声称
CE-03引文定位验证通过；实际引用校验只复用CE-03已验证格式。

**没有实际调用 GPT-6 Astra，没有向模型提供科研原文或摘要，没有科研正确率、召回率、
专家Gold或方法学结论。** 本次是受限来源的确定性工程演示，不是模型能力实测。
中文/英文引文匹配与错误 DOI/页码使用测试夹具离线验证，不能外推真实科研能力。

## 边界与技术风险

四份规程仍 DRAFT v1.1，未签署。新Skill依据草案提出建议，不让其自动生效。
没有 src/research_library 变更、主库迁移、人类CLI/历史记录变更、API客户端、
MCP/HTTP服务、定时调度、Gold晋升、EvidenceCard批准或知识发布。

许可证与出站政策是两个门槛；开放许可证不能绕过当前政策。本地工具哈希/SQL读取
不会把原文送模型；会话文件工具读取则会暴露内容，因此前置预检和模型读取范围
声明至关重要。机器预检不能保证识别所有儿童个人信息、秘密或许可证的法律真实性；
来源不明即停止，不把“本地文件”当作“本地模型”。

输出校验只证明结构、来源版本、选定片段匹配与声明一致，不证明推论、原PDF定位、
DOI注册真实性或实际模型身份。matched_local_text不是verified。两上下文ID和输入哈希
可审计隔离声明，不能取代真实上下文隔离证据，更不等于两名专家。严重偏倚、儿童
安全风险、缺全文和重要反证必须由执行者主动标记未决，不能让schema通过冒充科研批准。

历史结果不覆盖；新版本用新run。新finalize必须冻结当前Skill/规程；旧结果可用
validate --historical核查其固定manifest/输出完整性，但原输入不可用或版本改变时
不能宣称重新核验成功。长期保存需保留对应Git版本和合法来源副本。

已读 PR #4/#5/#6 正式Review及非阻断意见。RQ契约歧义、旧decision验证器的Gold
旁路、人工签署证据/多审核人/报表、解析定位质量与跨格式局限在本次不做无关修补；
新Skill使用独立strict schema且不调用这些旧门禁。未来数据出站或AI-only知识发布
必须另案治理、明确适用风险/范围、人工签署/产品批准与撤回机制，本次未开放。

Skill发现与显式策略依据：[OpenAI Build Skills](https://learn.chatgpt.com/docs/build-skills)
（查阅2026-10-14）。真实会话模型应从会话配置核验，未提供可核验身份时使用unknown，
不能以用户请求、开发Agent名称或订阅推断Astra/snapshot。
