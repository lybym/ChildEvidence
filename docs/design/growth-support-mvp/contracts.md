# 专业资产、统一交互与成长记录契约

> DRAFT v0.2，2026-10-17。字段表与 JSON 是接口设计示例，不是已实现或正式冻结的 Schema；示例协议版本仍保留 draft-0.1，未作不必要的格式升级。所有 `demo-*` 为合成标识，不对应论文、真实儿童、真实批准或可发布知识。实现任务见 [Issue 索引](../../roadmap/growth-support-issues.md)。

## 1. 专业资产：把研究转成可用方法

公共信封建议包含：`id`、`revision`、`schema_version`、`content_hash`、`supersedes`、`created_by`、`created_at`、`basis_kind`、`basis_refs`、`review`、`release_eligibility`。ID 跨修订稳定，revision 指向不可变内容；引用必须携带目标修订，不只写显示名称。

`basis_kind` 区分 `direct_research`（直接研究支持）、`research_synthesis`（综合）、`application_inference`（应用推导）、`design_choice`（设计选择）。每项仍经过本地生产与版本发布；不把推导或价值选择伪装成论文结论。研究中的相关关系不能自动转换成个体因果解释。

| 对象 | 最小内容 | 重要边界 |
|---|---|---|
| SourceVersion | Work ID、资料类型、原件版本/哈希、合法处理范围、正式发表/报告/预印本标记 | Work 不等于唯一 Study；同研究多篇报告需能关联，防止重复计证 |
| SourceLocator | 原件与解析版本、物理页/段或其他稳定位置、定位验证状态 | 无页码的机构报告或网页可用其他定位；不能虚构印刷页 |
| Finding | 研究条件、观察结果、样本/人群、测量和不确定性 | 未核实字段为 null；原文片段是否可入发布包另行审查 |
| Claim | 可评价主张、范围、支持/反对/证据不足关系 | 不是教育行动，也不是儿童画像 |
| Appraisal | 研究质量、偏倚、局限、适用性、研究间差异 | 与模型自信、人工审核、发布资格分开 |
| EvidenceCard | Claim/Finding 的可追溯组合、反证、适用边界、评价引用 | 多篇支持不自动等于独立证据或强证据 |
| Strategy | 目标、适用与排除条件、行动步骤、观察结果、调整/停止条件、证据关系 | 不足证据须显式说明；个体计划是运行时另一个对象 |
| SupportMethod | 所需信息、候选解释维度、状态与动作、方法选择和冲突处理规则、复盘标准 | 包含教育判断与复盘方法，不能只是几段提示词 |
| InteractionProfile | 倾听/提问/反馈/表达规范、不同回应对象的适配、冲突优先级、行为评测引用 | 稳定人格不随一次模型推理漂移；更新来自本地生产与明确版本 |
| EvaluationCase | 合成输入、预期行为、不允许行为、评分依据、覆盖的资产版本 | AI 评分不等于独立人类效度验证；不包含真实儿童记录 |

一般心理支持与教学、教练方法共同服务一个角色。方法选择需要处理冲突，例如任务完成速度与理解、增加挑战与当前负担之间的权衡。建议顺序是：权限和范围 → 明确意愿/拒绝 → 证据适用性 → 当前共同目标 → 可尝试且可调整的行动。该顺序是待评测的产品方法提案，不冒充已验证的科学定律。

### 1.1 审核与发布状态必须正交

- `technical_validation`：结构、引用、哈希与可执行状态检查。
- `scientific_appraisal`：质量、局限与不确定性；允许争议和不足。
- `review_origin`：AI / 单人 / 独立人工复核等实际方式，不伪造身份。
- `release_eligibility`：依据哪一版治理规则、允许什么用途、由何记录决定。
- `runtime_applicability`：当前情境是否具备使用条件，由运行时决定，不能提升科研等级。

这是未来模型建议，不是对现有 Gold/L0–L4 的静默替换。当前门禁未完成变更前，AI 草稿依旧不能成为真实 Agent 正式行为资产。

### 1.2 方法如何可执行

MVP 采用有限的动作词汇，例如 `ask_clarification`、`offer_choice`、`explain_with_support`、`propose_activity`、`request_feedback`、`pause`、`suggest_human_help`。每个方法声明所需信息、允许动作、条件和允许的状态迁移。未知条件结果为 `unknown`，不能按 true 放行。

模型可以提出情境解释、方法候选和表达草案；核心检查动作是否属于当前方法、引用是否存在且可用、必须信息是否齐备、反馈是否已发生、是否存在用户拒绝。核心不能仅靠字段检查证明解释真实或教育效果成立。

资产为数据，不携带可任意执行的 JS/Python。增加新动作类型需要受版本管理的代码变更和兼容评测，不能从云端包下载后任意执行。

## 2. UnifiedSupportInput：Harness → 插件

| 字段 | 责任与含义 |
|---|---|
| `schema_version`、`request_id`、`session_ref` | 协议版本、幂等请求标识、宿主局部会话引用 |
| `actor`、`subject_ref`、`response_audience` | 请求者角色、正在帮助的学习主体、回应对象；身份绑定由宿主提供 |
| `authorization_ref` | 宿主授予的上下文访问范围；正文自称“我是家长”不能赋予权限 |
| `intent`、`task` | 当前目标与任务内容；学科答案/题目来源及核验情况另外标注 |
| `observations` | 可定位的观察，注明 child_self_report / adult_report / host_observation / model_inference |
| `input_quality` | ASR/OCR/宿主解释的歧义、缺失、需确认项；置信度未知就为空 |
| `context_snapshot` | 最小相关历史、来源事件、当前假设与支持结果；不传整个日志 |
| `state_revision`、`active_plan_ref` | 并发修改检查与当前计划；不得从其他主体复制上下文 |
| `capabilities` | 宿主实际可执行的表达/活动类型，取消和回执能力；不是媒体数据本身 |
| `asset_lock` | 当前包版本与状态，不能让模型自报为“已批准” |

统一输入可以包含任务结构与宿主保留的媒体引用，但插件不读取原照片、不重新做 OCR。来源信息只用于解释当前观察可靠性，不恢复多套模态管线。

### 2.1 合成输入示例

```json
{
  "schema_version": "ce.support-input.draft-0.1",
  "request_id": "demo-request-001",
  "session_ref": "demo-session-A",
  "actor": {"role": "child", "principal_ref": "demo-principal-A"},
  "subject_ref": "demo-learner-A",
  "response_audience": "child",
  "authorization_ref": "demo-host-scope-A",
  "intent": "help_with_current_task",
  "task": {
    "kind": "school_task",
    "content": "合成题目：三组各有四个物品，一共有多少个？",
    "source_ref": "demo-host-event-01",
    "content_verification": "synthetic_fixture"
  },
  "observations": [
    {
      "id": "demo-observation-01",
      "kind": "child_self_report",
      "statement": "我不知道从哪里开始。",
      "source_event_ref": "demo-host-event-02"
    }
  ],
  "input_quality": {"ambiguities": [], "confidence": null},
  "context_snapshot": {"observations": [], "hypotheses": [], "outcomes": []},
  "state_revision": 0,
  "active_plan_ref": null,
  "capabilities": {"presentation": ["text", "speech", "web_activity"], "action_receipts": true},
  "asset_lock": {"pack_version": "demo-only", "purpose": "synthetic_evaluation"}
}
```

题目与对话为明确合成例子，不包含真实出版物、真实儿童成绩或观察。它只能用于接口讨论/隔离评测，不能赋予 `demo-only` 资产真实发布资格。

## 3. 运行步骤与候选工具

逻辑操作建议为 `prepare_support` → Harness 模型提出候选 → `validate_support_proposal` → 宿主呈现/执行 → `record_support_outcome`。这些是候选接口名，不是已注册 DSH API。

1. `prepare_support` 校验统一输入、身份范围、上下文版本、资产可用性，返回相关方法、缺失信息及允许动作。
2. 模型根据返回资产提出解释、行动与表达。方法和人格已经在本地生产，运行时只是情境化应用，不是重写它们。
3. `validate_support_proposal` 校验引用、前置条件、拒绝/停止信号和输出契约；失败返回原因与可修复项。
4. 宿主确认实际呈现/执行状态。计划生成不等于儿童已尝试，也不等于行动有效。
5. `record_support_outcome` 接收真实回执与反馈，生成受宿主权限约束的记录变更。重试必须幂等。

即使程序校验通过，也只能称结构与明确规则通过。是否正确理解儿童、是否有充分证据，仍需要行为评测和后续反馈。不要保存模型隐藏思维过程；保留简短的判断依据、已知事实、备选解释和引用即可。

## 4. SupportResult：插件 → Harness

| 字段 | 内容 |
|---|---|
| `status` | `needs_information` / `proposal_ready` / `paused` / `out_of_scope` / `blocked` / `degraded` |
| `understanding` | 观察引用、候选解释、未知项与相互竞争的解释；非诊断 |
| `next_action` | 有限动作类型、内容、方法引用、必要前置条件 |
| `activity_spec` | 可选的活动目标、结构化参数、结束条件、回执要求；不是任意 HTML/JS |
| `presentation_constraints` | 人格版本、回应对象、表达与解释要求 |
| `review_plan` | 观察什么、何时或遇到什么条件复盘、何时调整或停止 |
| `record_proposals` | 最小记录候选，不直接写宿主全局记忆 |
| `provenance` | 包、方法、策略、人格、运行核心版本及来源引用 |
| `validation` | 通过/失败项、用途范围、是否允许在当前环境执行 |

宿主不支持 Web 时，核心返回同一教育目标下的文字/语音替代方案或说明缺失能力，不生成假活动结果。图片、网页和模型内容都是非可信输入，不能携带身份变更或改变发布规则的指令。

### 4.1 合成输出示例

```json
{
  "schema_version": "ce.support-result.draft-0.1",
  "request_id": "demo-request-001",
  "status": "needs_information",
  "understanding": {
    "observation_refs": ["demo-observation-01"],
    "candidate_explanations": [
      {"id": "demo-hypothesis-01", "statement": "可能尚未理解题目要求。", "status": "unconfirmed"},
      {"id": "demo-hypothesis-02", "statement": "可能理解题意但不确定第一步。", "status": "unconfirmed"}
    ],
    "unknowns": ["孩子如何理解题目", "已有尝试"]
  },
  "next_action": {
    "kind": "ask_clarification",
    "content": "你觉得这道题想让我们找出什么？",
    "method_ref": "demo-method-clarify@1"
  },
  "activity_spec": null,
  "presentation_constraints": {"profile_ref": "demo-profile@1", "audience": "child"},
  "review_plan": {"trigger": "after_response", "observe": ["对题目要求的表达"], "on_decline": "pause"},
  "record_proposals": [],
  "provenance": {"pack_version": "demo-only", "evidence_refs": [], "basis_kind": "design_choice"},
  "validation": {
    "status": "illustration_not_executed",
    "purpose": "synthetic_evaluation",
    "eligible_for_real_user_delivery": false
  }
}
```

`evidence_refs` 为空是刻意诚实缺失：本轮没有读取获准论文或生产真实方法。正式资产不得将示例改名后宣称有研究支持。

## 5. GrowthRecord：个人观察与成长记录

科研库不保存 GrowthRecord。插件定义语义，宿主负责落盘、授权、删除和导出；暂时不假定 DSH 已有符合本设计的个人记录服务。若宿主没有，应作为明确适配依赖实现，而不是暗中上传到 ChildEvidence 云端。

| 对象 | 最小字段与规则 |
|---|---|
| Observation | 主体、情境、来源事件、时间、陈述、产生者；直接观察与转述分开 |
| Hypothesis | 解释、支持/反例观察、未知项、暂定状态、复查触发器；不得固定成儿童标签 |
| Goal | 儿童或请求方表达的目标、共同约定、优先级、可调整/撤回状态 |
| SupportAttempt | 使用的方法/策略版本、拟采取行动、实际执行回执；未执行不得计为有效尝试 |
| Outcome | 任务表现、所需帮助、儿童体验、情境差异、缺失原因；不把沉默视为失败 |
| Exploration | 提供的机会、选择/拒绝、当次体验、后续意愿；不推出职业或天赋定性 |

不给“潜力”一个伪精确总分。相同表现可能受题目难度、疲惫、帮助程度等影响；重复观察来自同一任务也不能冒充跨情境证据。可增加主观信心等级，但必须注明来源与未校准性质。

宿主写入要求：绑定主体与访问范围；`expected_revision` 做并发检查；`request_id + action_id` 去重；记录实际发生时间；失败或取消不得写成功结果。不同儿童严格隔离，家长/教师也不得仅靠自报身份读取记录。

个人记录不套用科研审计“永久追加不可删”的政策。需要支持纠正、遗忘、保留期限、导出和删除；删除还要覆盖衍生摘要/索引及宿主可控制的日志，并说明无法控制的模型服务留存边界。默认不把儿童交互用于科研库回流、训练或评测数据集。

## 6. 失败与更新契约

| 情况 | 行为 |
|---|---|
| 题目/输入有歧义 | 返回 `needs_information`，先核对输入，不能当作儿童能力不足 |
| 缺少必要信息或研究依据 | 诚实返回未知与补充问题；不虚构支持来源 |
| 包版本不兼容、哈希不符或资产已撤回 | `blocked` 或受限 `degraded`；不能自动切换到未知版本 |
| 取消、超时、重试 | 保留已完成回执；没有证据时结果为 unknown；不得重复落盘或执行活动 |
| 个人记录不可用 | 明示使用本次会话信息；不假装记得历史，不把别人的记录补进来 |
| 模型跳过工具直接回答 | 记录为集成失败；需要宿主受控入口/输出接缝；仅靠提示词不能宣称已强制执行 |
| 请求超出低风险范围 | 停止对应自动流程，提供合适的求助方向；不把通用支持插件变成诊疗系统 |
| 新研究与旧方法冲突 | 本地形成复审与新版本；不直接改变正在进行的儿童计划；紧急撤回例外优先 |
