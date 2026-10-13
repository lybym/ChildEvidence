# KNOWLEDGE_GOVERNANCE.md — 科研结果进入 Agent 能力的治理规则

> 状态：**DRAFT v1.1（CE-01R）** — 2026-10-13 依据跨文件一致性审计修订（逐条意见见
> [docs/governance/CE-01R-REVIEW.md](docs/governance/CE-01R-REVIEW.md)）。
> **仍待人工审核，未生效**：Agent 不得将本文件当作生效准则执行（见 AGENTS.md 科研治理节）；
> 人工批准以 [docs/governance/CE-01R-CHECKLIST.md](docs/governance/CE-01R-CHECKLIST.md) 为准。
> 上位文件：RESEARCH_METHODOLOGY.md（三层决策分离、L0–L4 成熟度）；配套：SCREENING_PROTOCOL、
> ANNOTATION_GUIDE。

## 1. 目的

规定科研证据如何**受控地**转化为知识包与 Agent 能力，并建立持续验证与回滚机制。
核心目标不是让 Agent 不断吸收新知识，而是让它能持续完成三个独立判断：

1. 现有知识是否仍然成立？
2. 新证据是否足以改变结论？
3. 结论变化是否足以改变 Agent 的行为？

三问是三个独立决策，分别属于科研决策 / 知识工程决策 / 产品决策，**不能自动连通**。

## 2. 三层决策的流转规则

```text
① 科研决策（Evidence 层）
   输入：Evidence Card（pending）+ 原文定位
   判定人：领域审核人
   输出：approved / rejected / needs_more_evidence（含理由）
         ↓ 仅 approved（成熟度 L3，RESEARCH_METHODOLOGY §9）的卡片可提名
② 知识工程决策（Knowledge 层）
   输入：approved 证据卡集合 + 现行知识条目
   判定人：知识负责人
   输出：知识条目/策略草稿 → 版本化知识包发布（含 manifest 哈希）
         ↓ 仅已发布版本的条目可提名
③ 产品决策（Agent 层）
   输入：已发布知识包 diff + Agent 能力契约
   判定人：产品负责人
   输出：Agent 行为/策略变更（须通过回归评测用例）；人格原则不在可变更范围
```

禁止事项：

- 任何自动管线不得跳过 ② 的版本发布与 ③ 的显式批准；
- 研究结论的更新**不自动**修改教育策略；教育策略更新**不自动**修改 Agent 人格；
- 未审核（pending）证据卡禁止出现在任何已发布知识包中；
- 下游（②③）不得反向改写上游对象的审核状态、标签层级或结论（依赖单向，
  RESEARCH_METHODOLOGY §2.4——无循环依赖）。

## 3. Evidence Card 状态机与成熟度映射

```text
draft → pending → approved ──┐
              │→ rejected    ├──→ 提名进入知识工程（②）
              └→ needs_more_evidence ──→ 回到 L5/L6 补证
approved 卡片可被复审改判：approved → superseded / retracted（留审计链）
```

**回边禁令（v1.1 显式化，防循环依赖）**：

- 唯一允许的回退是 `needs_more_evidence → 补证 → pending`（回 L5/L6）；
- `rejected`、`superseded`、`retracted` 是终局状态，**不得**转回 `approved`；翻案须
  新建卡片并引用原卡留审计链；
- 不存在任何"消费端需求自动提升卡片状态"的路径；approved 只能由人工审核行为产生。

**成熟度映射（RESEARCH_METHODOLOGY §9 的 L0–L4）**：

| 状态机状态 | 成熟度 |
|---|---|
| draft | L0 |
| pending（未经单人审） | L1 |
| pending（单人已审、未独立复核；标签 provisional） | L2 |
| approved（gold，独立复核/裁决 + 签署） | L3 |
| superseded / retracted | L4 |
| rejected | 终局否定，不在 L0–L4 阶梯内 |

卡片必填字段（v0.3 schema 的治理约束）：claim、evidence[]（work_id、pdf_sha256、
物理页+印刷页、文本 span、relation、不确定性来源）、`human_review_status`、
`maturity_level`（L0–L4）、`allowed_for_agent_release=false`（默认，直至 ③ 批准）。

## 4. 知识包发布（② 的产物）

1. 版本化产物：`catalog.jsonl`、`evidence-cards.jsonl`、`strategies.jsonl`、`manifest.json`
   （版本号、生成时间、来源证据卡 id 列表、内容哈希）；
2. 发布门禁（v1.1 与 L0–L4 对齐）：全部引用卡片状态 `approved` 且成熟度 ≥ L3
   （标签层级 gold；`provisional` 单人记录不满足门禁——见 RESEARCH_METHODOLOGY §7/§9）；
   差异审查通过；manifest 哈希可复算；
3. 下游（如 LumiThink）只按版本导入，不做增量混读（AGENTS #15）；
4. 每个版本可回滚：保留历史版本与 diff。

## 5. Agent 能力契约（③ 的约束文件）

每个 Agent 策略条目必须声明：

| 字段 | 说明 |
|---|---|
| scope | 适用场景与目标用户 |
| allowed | 允许的行为与话术边界 |
| forbidden | 禁止行为（含"不得将群体统计结论用于个体诊断"等 AGENTS #4 约束） |
| evidence_basis | 依据的知识包版本与证据卡 id |
| expiry/review_trigger | 失效条件与复审触发器 |
| regression_cases | 变更前必须通过的评测用例 id |

## 6. 持续验证与触发器

触发复审的条件（RESEARCH_METHODOLOGY §11）：新 CONTRADICT 证据、撤稿/更正、
规程变更、下游实测不符。复审必须对三问分别给出独立书面结论与决策人。

## 7. 审计与回滚

1. 审计记录（决策、理由、批准人、版本）只追加不删除（对齐 AGENTS #2）；
2. 知识包支持版本回滚；Agent 行为变更回滚须重跑 regression_cases；
3. 违规示例（负面清单）：用 pending 卡片生成指南；跳过 ② 直接改 Agent 策略；
   用引用量替代证据分级；用模型投票冒充专家共识；用 provisional（单人）标签
   冒充 gold 通过发布门禁。

## 8. 变更记录

| 版本 | 日期 | 说明 |
|---|---|---|
| DRAFT v1.0 | 2026-10-13 | Codex 起草（CE-01）；待人工审核确认 |
| DRAFT v1.1 | 2026-10-13 | CE-01R 一致性审计修订：回边禁令显式化（rejected/superseded/retracted 不得转回 approved）、L0–L4 成熟度映射与必填字段、发布门禁绑定 L3+gold、provisional 冒充 gold 入负面清单、单向依赖声明；**仍待人工审核，未生效** |
