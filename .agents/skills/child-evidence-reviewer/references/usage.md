# 使用、契约与验证

这是显式手动 Codex Skill，不是 research CLI 扩展。调用示例：

```text
$child-evidence-reviewer screen work_id=lt-...，仅审查获准元数据。
$child-evidence-reviewer appraise 本地PDF=<path>，先做出站预检，不能送云则保留未决。
$child-evidence-reviewer extract DoclingJSON=<path>，核对样本量与定位。
$child-evidence-reviewer challenge EvidenceCard=<path>，寻找旧结论的遗漏和反证。
$child-evidence-reviewer audit 指定的review.json文件列表，保留所有异常。
```

可一次指定少量文献；每个结果限定 scope，逐项手动执行，不提供批处理/调度服务。RQ 用现有治理注册 JSON 明确选择 rq_id/version，不自动注册/批准。blinded CSV 只选择明确 queue_id；不读 keyed CSV、不预加载历史标签。

## 先预检，再读到模型

工具不调用模型，不需要 API Key，标准库运行。以下 `python` 指本机 Python 3.11+；如果 PATH 没有 Python，使用本机配置的解释器完整路径。根目录执行：

```powershell
$env:PYTHONPATH = "src"
$tool = ".agents/skills/child-evidence-reviewer/scripts/validate_review.py"
python $tool preflight --source data/research-library/library.sqlite --kind sqlite_metadata --selector <work_id>
python $tool preflight --source <pdf-path> --kind pdf --license CC-BY-4.0 --access-basis public_metadata
```

preflight 只打印路径、选择器、SHA、许可/政策结果，不打印标题、摘要、全文或原错误载荷。返回 2 表示模型不得读取内容，不代表文件解析失败。`--license` 不能覆盖 SQLite 实际 license；CSV 没有字段许可凭据，不能靠自称 MIT 开放。RQ 只接受项目 docs/governance 的 repository_governance 来源。即使许可放行，现行摘要/PDF出站政策仍拒绝全文/Docling/证据卡/旧审核等衍生内容。代码不提供豁免开关。数据政策修订、未来 AI-only 发布须另案治理；本次未修改或提出生效修订。

非敏感公开元数据也应由使用者核对来源许可与机构政策。机器预检不具备识别所有儿童个人信息或验证任意许可证真实性的能力；发现个人信息/密钥时停止，不把其内容送会话。`model_access_allowed` 仅限定所选白名单元数据，**不是**整份 SQLite/CSV 可读许可。不要用文件读取工具打印全行/整库；SQLite 必须 mode=ro/query_only，SELECT 限定 work_id 和元数据字段，不调用会建库的 research_library.db.connect。

## 统一记录

`schemas/review-result.schema.json` 为 Draft 2020-12 独立 JSON Schema。五模式统一 envelope：

- `requested_model_id=gpt-6-astra` 是期望；`model_id/model_version` 是实际已核实值，否则 null。`model_identity_status=verified` 需要 provenance 中会话配置的 `model_identity_evidence`；unknown 不发明 ID；没有模型审查时 not_called、model_review_performed=false、execution_kind=deterministic_demo。
- `reviewer_type=ai_model`、label_tier=silver、maturity_level=L0、human_review_status=not_reviewed、allowed_for_agent_release=false 为常量；schema 拒绝 Gold、人类来源和未知字段。
- scope 分 catalog/review，review 必须明确 RQ 来源、版本和状态。screen 只用原标注建议词表/理由码；其他模式 recommendation=not_assessed。所有结果保留 DRAFT 未生效状态。
- scope.work_ids 必须恰好对应此次 sqlite_metadata 来源的实际 internal_id，不能改成无关 Work 或漏记/重复。blinded 的 queue_id/sample_id 分别记录在来源 object_id/sample_id，均不自动等同 Work_ID；Docling 可核实的 document_id 只记录 document 身份，不能从文件名/文档ID推断 Work。只有PDF或blinded等输入时 work_ids=[]；需要与 Work 绑定时另加所选SQLite元数据来源。
- 每项事实在 findings 中；未核实 value=null，非空值必有 citation_ids。引用含源哈希、DOI（未知 null）、字符区间、物理/印刷页和 paragraph_id/metadata field。字符从0起算，右端不包含；Docling 字符区间相对**该 paragraph 的 text**，不冒充 PDF 全文坐标。printed_page_no 未经既有人工映射为 null。
- verification_status 只用 unverified/matched_local_text；验证器不接受 verified。后者仅证明选定本地文本片段相等，不能证明 DOI 真实、PDF 位置正确、事实推论成立。DOI 必须与指定来源一致；格式合法不证明 DOI 存在，不能据此作真实性断言。
- uncertainties 建议采用 evidence_insufficient/original_unavailable/methodology_unknown/substantive_disagreement/important_counterevidence/child_safety/serious_bias/citation_unverified/rq_not_approved；这些强制禁止 ai_reviewed。原文缺失、严重偏倚、安全风险即便模型忘记写代码也必须在人工检查时保留未决。校验器不能检测所有隐含安全风险。
- `passes` 禁用时 a/b=null；启用时保存两份原始结构、独立 context_id、结果哈希、共同 input_hash。两份建议/findings/assessments 不同必须保留 differences 和 substantive_disagreement；不允许抹掉任一 Pass 的 uncertainty。不同 context_id 只是一项审计声明，不能机器证明模型真的没有看过 A；隔离需要实际会话/子上下文证据。

`provenance.json` 字段固定为 schema_version/run_id/sources/protocol_files/skill_files/scope/input_hash/model_identity_evidence/model_content_source_ids。sources 采用 preflight 返回的完整对象，不能手工改许可/sha；`model_content_source_ids` 明确哪些获准来源内容实际进入会话，演示为 []。协议和 Skill 文件哈希用工具的 frozen_files() 生成，不写路径中间推导值。

每个来源另记录 object_type/object_id/sample_id。Work、blinded条目、文档、RQ、身份未知的file互不混用；validator重新从只读来源核对这些身份。实际模型审查的所有 supporting_sources 引文（包括两个Pass原始引文）必须既许可/政策放行又明确列入 model_content_source_ids；仅声明另一个合法元数据已发送不能替受限引文背书。非空事实要引用这些受控引文，模式评价也要有受控 supporting_sources。即便 review_status=blocked，也不得把禁传原文片段伪装成模型已生成的引用。本地确定性校验可记录片段匹配，但执行类型必须如实为 deterministic_demo，保持 blocked/unresolved。

input_hash 为 sources/protocol_files/skill_files/scope 的 canonical JSON SHA-256。canonical 用 UTF-8、ensure_ascii=false、sort_keys=true、分隔符逗号/冒号、禁止 NaN。output_hash 是 review 去掉自身 output_hash 后的 canonical SHA-256；每 Pass result_hash 同样去掉自身字段。validation.json 另记录 provenance_hash。原 SQLite 整文件 SHA 和所选元数据 selection_hash 都保留；无关行变化也会触发保守失效，需要新 run。

canonical 哈希不是 JSON 文件字节 SHA；validation.json 的 artifact_sha256 另列 review.json/provenance.json/review.md 的字节哈希，validation.json 不自哈希。默认校验/finalize 要求当前 Skill/规程与冻结版本一致。查看旧记录可用 validate --historical 检查其固定 manifest/输出哈希，不要求当前规程文件相同；这不证明旧规程版本可用或原输入仍存在。长期保存应同时保留对应 Git commit/Skill版本及原输入内容寻址副本。源文件变化显示输入版本不可重查，不据此宣布历史科学结论错误；不能用 --historical finalize 新结果。

## 保存与重审

将候选结构写入本地临时输出区，保持原输入只读。可以参考脚本 make_demo() 的 envelope 并填写实际已开展的工作，但不得把演示改称模型实审。模式评估内容/事实/引用由当前明确身份的会话起草；工具仅核查，不填科研答案。

```powershell
python $tool validate --review <candidate-review.json> --provenance <candidate-provenance.json>
python $tool finalize --review <candidate-review.json> --provenance <candidate-provenance.json>
```

finalize 先校验，然后用 exist_ok=false 与文件 x 模式生成全新 run_id 目录。默认 `<repo>/data/review/ai-review/<run_id>/`，配置 CHILDEVIDENCE_DATA_DIR 时是 `<data-dir>/review/ai-review/<run_id>/`；可显式 --out-root 指定独立输出区，不能覆盖任何来源。失败后保留不完整目录供排错，新 run_id 重试；不自动清理历史。重审新建 run_id，scope.prior_run_ids 引用旧记录。四个产物全部只属于独立 AI 草稿，不被现有正式管线读取。

确定性演示（**无模型审查**）：

```powershell
python $tool demo --mode screen --source <blinded-csv> --kind blinded_metadata --selector a2-001
python $tool demo --mode appraise --source <existing-pdf> --kind pdf
python $tool demo --mode extract --source <existing-docling-result.json> --kind docling
python $tool demo --mode challenge --source <existing-evidence-card-file> --kind evidence_card
python $tool demo --mode audit --source <existing-review.json> --kind review
```

demo 只做本地读取白名单/哈希/政策判断，输出 blocked/unresolved、空 findings、null appraisal，无正确率/召回率。不是 Astra 实审，也没有完成 CE-02 人工任务。使用 schema_errors() 可独立检查 JSON Schema；validate() 还核对 provenance、磁盘来源、模式/身份/分歧和发布隔离。预检、校验均无 HTTP、子进程、API 客户端或写库路径。review.md 是状态摘要，完整事实与引用以 review.json 为准。

## 验证与风险

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests
python scripts/smoke_offline.py
python -m research_library status
```

离线测试包括 schema、许可/政策、真实来源/定位哈希、中文/英文、缺失事实、错误 DOI/页码、注入文本、无效 JSON、A/B 差异、历史保护、readonly SQLite、新 run 保护和禁止 Gold。验证器证明结构、匹配和隔离，不能证明科学结论正确、原文定位准确、许可证法律有效、模型独立性或真实身份；最终仍需可信会话身份和人工治理。

已有 #4/#5/#6 review 非阻断意见在本次保留：RQ 契约条件/语言歧义与 decision Gold 检查、CE-02 签署/多审核人/报表/历史产物、CE-03 解析定位与质量局限都未修改；本 Skill 不调用这些薄弱门禁，独立来源与草稿隔离不自动修补治理。源规程、原始数据和人类历史不变。

本次真实 Codex `skills/list` 已发现该 Skill（scope=repo、enabled=true），未进行模型 `$skill` 调用；policy.allow_implicit_invocation=false 的文件与官方行为依据可核查，但未声称实机测试普通提示词不激活。官方 Skill 发现与显式调用文档：[Build Skills](https://learn.chatgpt.com/docs/build-skills)（查阅 2026-10-14）。模型选择需使用会话实际配置，不能由 Skill 自动切换。本次没有 API 适配器、网络传输、额外服务或正式发布能力。
