# CE-01R-CHECKLIST.md — DRAFT v1.1 人工批准清单

> 性质：CE-01R 规程 DRAFT v1.1 的**人工批准记录**。这是规程生效的唯一凭据
> （AGENTS.md #23）。
> **在负责人逐项签署完成之前，四份规程保持 DRAFT 未生效状态；任何 Agent 不得
> 将其当作生效准则，也不得自动勾选、代签或宣布本清单通过。**

待批对象（均为 DRAFT v1.1，2026-10-13）：

1. RESEARCH_METHODOLOGY.md
2. SCREENING_PROTOCOL.md
3. ANNOTATION_GUIDE.md
4. KNOWLEDGE_GOVERNANCE.md
5. AGENTS.md（科研治理节 #16–#24 修订）

审计依据：[CE-01R-REVIEW.md](CE-01R-REVIEW.md)；勘误索引：[CE-01R-ERRATA.md](CE-01R-ERRATA.md)；
机器可校验契约：[contracts/](contracts/)。

## A. 逐条修订确认（对应 Issue #1 修订项与 REVIEW R1–R9）

| # | 事项 | 依据 | 确认（√/×/NA） | 意见 | 签署人 | 日期 |
|---|---|---|---|---|---|---|
| A1 | 科研双轨定义（馆藏建设 vs RQ 专题评价）；141 篇馆藏不强制回溯绑定 RQ | R1 | ☐ | | | |
| A2 | Catalog 决策与 Review×RQ 决策分离；同一 Work 可在不同 RQ 下结论不同 | R2 | ☐ | | | |
| A3 | RQ 生命周期/版本/退役/审核者；3 个示例 RQ 仅作示例未批准 | R3 | ☐ | | | |
| A4 | 四级标签（proxy/silver/provisional/gold）与 Gold 资格流程；禁模型自证 Gold | R4 | ☐ | | | |
| A5 | I5 标识放宽（ISBN/报告编号/馆藏记录/官方页）；三级判定分离；E6 收紧 | R5 | ☐ | | | |
| A6 | 停止声明禁令（未独立评估不得宣称 95% 召回）；保护层可操作定义 | R6 | ☐ | | | |
| A7 | L1–L9 与 L0–L4 编号区分；状态机回边禁令；发布门禁绑定 L3+gold | R7 | ☐ | | | |
| A8 | POC 勘误索引与机器可读指标指针；v1 旧指标标 superseded 且原始记录不改写 | R8 | ☐ | | | |
| A9 | AGENTS.md #5、#22–#24（DRAFT 非生效准则；生成物不作不可变规范） | R9 | ☐ | | | |

## B. 机器校验（可由测试自动验证，签署前重跑）

| # | 检查 | 命令 | 结果 | 执行人 | 日期 |
|---|---|---|---|---|---|
| B1 | 44+ 单元测试全绿（含新增治理契约/一致性测试） | `python -m unittest discover -s tests` | ☐ | | |
| B2 | 离线冒烟通过 | `python scripts\smoke_offline.py` | ☐ | | |
| B3 | 库状态正常（关键表记录数与 35 份 PDF 哈希无本 Issue 引起的变化） | `python -m research_library status`；`python -m research_library verify-pdfs` | ☐ | | |
| B4 | 契约自校验与文档一致性检查通过（含于 B1） | `tests/test_governance_contracts.py` | ☐ | | |

## C. 边界确认（负向清单，全部应为"未发生"）

| # | 禁止事项 | 确认 |
|---|---|---|
| C1 | 未直接推送/合并 master；改动仅在特性分支 + PR | ☐ |
| C2 | 未执行任何 SQLite schema 迁移或数据迁移 | ☐ |
| C3 | 未执行在线论文采集；未引入 Docling；未做 A2 代标 | ☐ |
| C4 | 未改写 POC 原始数据/指标数字（仅新增勘误索引与指针） | ☐ |
| C5 | 未把任何待审规则自动改成 APPROVED/生效；未代签本清单 | ☐ |
| C6 | 未将 141/252 历史记录自动翻转、升级标签或绑定新 RQ | ☐ |

## D. 最终生效签署

> 四份规程（含 AGENTS.md 科研治理节）整体生效需下表全部签署。任一未签即维持
> DRAFT 状态。

| 角色 | 姓名/ID | 决定（APPROVE / REQUEST_CHANGES） | 意见摘要 | 日期 |
|---|---|---|---|---|
| 科研负责人（领域审核人） | | ☐ | | |
| 知识负责人 | | ☐ | | |
| 产品负责人 | | ☐ | | |

签署后动作（由人执行，不由 Agent 代办）：在四份规程头部与 AGENTS.md 中把
"DRAFT v1.1（待人工审核）"改为生效版本标注并记录日期与本清单链接。
