# DSH 接缝验证报告（Issue #13）

> 状态：验证记录，2026-10-18。对应 Issue
> <https://github.com/lybym/ChildEvidence/issues/13>
> （`[P0][DSH] 验证原生插件、统一接口与受控输出接缝`）。
> 能力分级见 [CAPABILITY-MATRIX.md](CAPABILITY-MATRIX.md)；实现与可复现命令见
> [插件 README](../../../plugins/growth-support-seams/README.md)。
> 本报告只声明实际执行过的验证；代码存在不推定验收完成。

## 1. 验证环境与版本

| 项 | 值 | 来源 |
|---|---|---|
| 宿主 CLI 版本 | `0.2.1-rc.2` | `dsh --version`（本次实测） |
| 宿主包 | `@deepseek-ai/dsh` 0.2.1-rc.2，`@deepseek-ai/cordis` 4.0.5 | 安装负载 `package.json`（只读） |
| Node | 24.21.0 | 安装负载 `runtime.json`（只读） |
| Python（测试用） | 3.12.14 | DeepSeek Harness 自带运行时；系统 PATH 无 Python |
| Issue 基线 | `0.2.0-rc.2` | Issue 正文"以安装的 DSH 0.2.0-rc.2 为已知基线" |

**版本差异（重要）**：本机实际安装为 `0.2.1-rc.2`，不是 Issue 记载的
`0.2.0-rc.2`。本报告的全部接缝结论只适用于 `0.2.1-rc.2`；对 `0.2.0-rc.2`
的兼容性**未验证**（该版本本机不可用）。验证插件不声明 `engines.dsh` 约束，
版本兼容要求记录在插件 README 与契约 JSON 的 `$id`（`ce.support-*.draft-0.1`，
对接 contracts.md DRAFT v0.2 草案示例，正式冻结按路线归属 #14）。

**安全声明**：全部宿主操作在隔离 `DSH_HOME`（`C:\CODE\.tmp\ce-dsh-home`，
仓库外临时目录）中进行；现用 GUI profile 未被读取或修改；无真实儿童数据、
论文内容或凭据进入本仓库或验证产物；未调用任何模型（隔离环境无凭据）。

## 2. 实际执行的验证与结果

以下命令均为实际执行（PowerShell，`$env:DSH_HOME` 指向隔离目录）。

### 2.1 隔离环境安装/运行/卸载（验收条件 1）

| 步骤 | 命令 | 结果 |
|---|---|---|
| 引导隔离 profile | `dsh --profile ce-verify --from-default-profile headless "profile bootstrap (synthetic)"` | profile 创建成功；任务在模型凭据处失败退出 1，错误为结构化 `dsh: MISSING_CREDENTIAL: llm-deepseek: no API key ...`（预期：插件挂载先于模型请求） |
| 组合树检查（装前） | `dsh --profile ce-verify --dump-config` | 退出 0；包含 `tools`、`session`、`session-persistence-jsonl`、`session-log-deepseek`、`headless-runner` 等条目 |
| 离线安装插件 | `dsh plugin --profile ce-verify add file:...\plugins\growth-support-seams` | 退出 0；pnpm 输出 `resolved 1, reused 1, downloaded 0`——零网络下载完成 |
| 组合树检查（装后） | `dsh --profile ce-verify --dump-config` | 退出 0；包含 `- id: ce-growth-support-seams` 及 `demo-learner-*` / `demo-method-*` 配置 |
| 卸载 | `dsh plugin --profile ce-verify remove ce-growth-support-seams` | 退出 0；依赖移除 |
| 卸载后核验 | `--dump-config` + 文件检查 | 组合树 0 处匹配；profile node_modules 条目消失；再次启动**无**加载回执 |

### 2.2 插件加载/卸载可观察性（验收条件 1、2）

启动 `dsh --profile ce-verify --patch <overlay> headless "demo task (synthetic)"`：

- `load-receipt.json`：`event: load`，4 个工具全部注册
  （`ce_prepare_support` / `ce_validate_support_proposal` /
  `ce_record_support_outcome` / `ce_session_audit`），3 个 demo scope、
  2 个 demo 方法——**在真实宿主进程内由 `apply()` 写出**；
- `unload-receipt.json`：`event: unload`，load 后 6ms 写出（进程退出时）；
- 卸载插件后重复启动：不再产生任何回执。

### 2.3 统一输入 → 工具 → 校验 → 结构化输出（验收条件 2）

两条证据链：

1. **真机 schema 校验**（`plugins/growth-support-seams/tools/validate-with-host.mjs`，
   用真实 `@deepseek-ai/dsh-tools` 校验器）。**校验器解析规则（Round 2 修复后，
   版本管理中不再含任何硬编码机器路径）**：显式参数（装有 dsh-tools 的隔离
   profile 或直接 lib 路径）→ `CE_DSH_TOOLS_LIB` 环境变量 → `$env:LOCALAPPDATA`
   推导的已安装宿主负载（只读）。**运行时要求**：安装负载位于 `.asar` 归档内，
   普通 `node` 无法读取（`existsSync` 返回 false——首轮 Review 复现的
   `dsh-tools not found` 即由此产生），必须通过宿主运行时执行
   （`$env:ELECTRON_RUN_AS_NODE="1"` + `DeepSeek Harness.exe --expose-internals`，
   见插件 README）；helper 在全部候选不可用时以 exit 1 输出可操作诊断，
   不产生假 PASS。
   实际重跑（Round 2，宿主运行时）：打印 provenance
   `dsh-tools version: 0.2.1-rc.2`（与宿主包版本一致）；
   `assertSupportedJsonSchema` 对全部 6 份注册用 schema 通过；
   `validateJsonSchemaValue` 对 contracts.md §2.1 的合成示例输入通过；
   伪造 `actor.role` 的负例被拒绝。**8/8 PASS**。
2. **受控流程行为**（`plugins/growth-support-seams/tests/self-check.mjs`，
   Node 24，24/24 通过）：完整链路 `prepare → validate → record` 产生
   `ce.support-result.draft-0.1` 结构化结果（`validation.eligible_for_real_user_delivery`
   恒为 `false`，`provenance.evidence_refs` 恒为空——不虚构研究支持）。

### 2.4 工具遗漏/拒绝用例（验收条件 2）

- **拒绝用例**（确定性）：`prior_decline` → `paused` 且不存提案，后续
  `record` 报 `unvalidated_outcome`；呈现后拒绝的回执 `success_written: false`。
- **未知保留**：未知 `action_kind` / 未知观察来源 → 结构化 `blocked` +
  原值保留在 `understanding.unknowns`，绝不按 true 放行（contracts.md §1.2）。
- **工具遗漏检测**：`ce_session_audit` 对已知 `request_id` 返回 0 次受控调用
  并置 `uncontrolled_request_hint: true`（E14 检测语义）。**检测≠强制**：
  从未调用任何工具的会话不产生轨迹，审计无法发现——强制需要宿主接缝，
  当前版本不可实现（见矩阵 #12/#13）。

### 2.5 取消/超时可观察（验收条件 2）

- 协作取消（插件侧，Node 自检）：entry-abort 后零状态变更；mid-delay abort
  不写成功记录。宿主契约（源码核验）：body 前中止 `ABORTED_BEFORE_DISPATCH`，
  body 后中止 `ABORTED`，均以结构化错误呈现、不结束回合。
- 超时：`timeoutMs` 在本版本**仅声明不强制**（宿主 README 明示，强制需组合
  `@deepseek-ai/dsh-tool-call-timeout-policy`）→ 矩阵 #8 记 unsupported。
  宿主回合级取消传导未实测（无模型凭据）。

### 2.6 Session 持久化与数据路径（交付范围）

- `--json` 开场事件：`{"type":"session","sessionId":"session-79c40867-…"}`
  （会话身份可机读）。
- 第二次调用 `--session-id session-79c40867-…` **采纳成功**：错误从
  "session does not exist" 变为模型凭据阶段——持久化与跨进程采纳被证明；
  未知 id 在任务运行前被拒绝。
- 落盘路径（隔离 home 实测）：`<DSH_HOME>\sessions\--C-CODE--\session-<uuid>\session.v4.jsonl.zstd`、
  投影缓存 `<DSH_HOME>\storages\session_projcache\sessions\*.json`。
- 模型请求遥测：组合树含 `session-log-deepseek`；宿主文档明示默认
  `enabled: true`，对官方 API 请求附加 `dsh_session_log` 字段（上传 Session
  日志后缀）。**本机现用 profile 的实际开关未检查**（检查会触碰现用配置，
  超出本 Issue 边界）；"日志在本地 ≠ 不外发"必须持续声明。

### 2.7 仓库内离线测试（验收条件 4）

| 测试 | 命令 | 结果 |
|---|---|---|
| Node 自检（24 项，Round 2 起） | `node plugins\growth-support-seams\tests\self-check.mjs` | 24 pass / 0 fail |
| Python 套件（本插件部分） | `python -m unittest tests.test_dsh_seam_plugin`（`PYTHONPATH=src`） | 全部通过（无 Node 环境时行为测试自动 skip，不 fail） |
| 仓库全量回归 | `python -m unittest discover -s tests`、`python scripts\smoke_offline.py`、`python -m research_library status` | 见 §4 |

## 3. 验收条件对照

| Issue 验收条件 | 状态 | 证据 |
|---|---|---|
| 1. 可按文档在干净隔离环境重复安装、运行、卸载；版本与插件依赖明确 | **达成**（在隔离 home、无模型凭据的边界内；完整模型回合运行未执行，见 §5） | §2.1、§2.2；插件 README 全流程命令；`package.json` 零依赖声明 |
| 2. 至少一次统一输入→工具→校验→宿主输出和一次工具遗漏/拒绝用例；取消/超时可观察 | **达成（离线/隔离口径）**：结构化输出与拒绝/遗漏/取消用例全部确定性验证；"宿主输出"指结构化结果契约，真实模型回合内呈现未执行 | §2.3–§2.5 |
| 3. supported/unsupported/unknown 能力矩阵；未覆盖最终输出时不得声称强制专业流程成立 | **达成** | [CAPABILITY-MATRIX.md](CAPABILITY-MATRIX.md)（#12/#13 明确 unsupported 并声明不得声称） |
| 4. 对应文档、可复现命令与必要的离线/隔离测试；说明实际验证范围、失败和未决项 | **达成** | 本报告 + 矩阵 + 插件 README；§5 未决项如实登记 |

## 4. 工程回归

- `python -m unittest discover -s tests`（Python 3.12.14，自带运行时）：全量
  通过，无 failure/error（原基线 237 项 + 本插件新增测试）。
- `python scripts\smoke_offline.py`：通过。
- `python -m research_library status`：在空合成数据目录验证通过；未访问
  生产数据库。

## 5. 实际验证范围、失败与未决项

**未验证（unknown，均需额外条件，不在本 Issue 内执行）：**

1. **真实模型回合的端到端回路**（模型调用工具、遗漏工具、取消传导、宿主
   呈现/执行回执）：隔离 headless 无凭据（`MISSING_CREDENTIAL`，已如实记录）；
   使用现用 GUI profile 会触碰正在使用的配置，被 Issue 边界禁止。前置条件：
   有可用的 API key 或专用凭据的隔离环境。
2. **宿主身份绑定**：统一输入中 `authorization_ref` 的真实宿主授予机制、
   请求者/主体分离的真实身份服务（#18 宿主记录契约）。
3. **`0.2.0-rc.2` 兼容性**：本机不可用，未验证。
4. **HMR 热重载卸载路径**：headless 模板禁用 HMR；只验证了进程退出路径。
5. **GUI 表面的插件页面行为**：只验证 CLI/组合层；Web 插件管理页未测。
6. **遥测实际外发行为**：`session-log-deepseek` 请求字段与默认开关来自宿主
   文档与组合树；未发送任何真实请求验证上传。

**执行中失败及处理：**

- `validate-with-host.mjs` 首次以 profile 目录解析 `dsh-tools` 失败——隔离
  profile 的 node_modules 只含本插件，宿主包在应用负载内。Round 1 改为三段
  解析时误将本机安装负载绝对路径写进版本管理，且文档化命令用普通 `node`
  执行（读不到 `.asar` 归档，首轮独立 Review 复现 `dsh-tools not found`）。
  **Round 2 根因修复**：移除硬编码路径，改为"显式参数 → `CE_DSH_TOOLS_LIB`
  → `$env:LOCALAPPDATA` 推导负载"的运行时解析 + 失败时可操作诊断；文档
  更正为宿主运行时执行；以 `dsh-tools 0.2.1-rc.2` 重跑，8/8 通过（§2.3）。
- `--session-id` 首次对从未存在的 id 直接拒绝（宿主语义：只采纳、不创建）；
  调整为先创建再采纳，两种语义均已验证并记录（插件 README §4 已同步更正
  命令流程）。

## 6. 结论

**与既有约束的一致性**：零第三方运行时依赖保持；未修改持久化 schema；未
触碰四份 DRAFT 规程、治理门禁、生成快照与既有 Skill；`demo-*` 与真实发布
资格隔离（GROWTH-SUPPORT-QUALIFICATION §3 共同限制）。

在当前安装的 DSH `0.2.1-rc.2` 上，最小插件真实证明了：插件加载/卸载、结构
化工具注册与校验、协作取消、Session 持久化采纳、数据路径（#1–#5、#7、#9、
#10，均 supported）。受控入口与最终输出检查在当前版本不可实现（#12/#13
unsupported），**因此本验证不声称"强制专业流程成立"**；这两项与宿主真实
身份绑定、真实模型回合行为一起，作为明确宿主依赖移交 #17/#18 承接。

## 7. Round 2（Step 05 Review 修复）更新记录

首轮独立 Review（`lybym-codex-reviewer[bot]`，CHANGES_REQUESTED，针对
`ed20620`）的全部 findings 已处理，修复后基线：

- P1-1：硬编码绝对路径移除，真机校验证据链以可复现命令重建（§2.3）；
- P2-1：record 入参 `$id` 改为 `ce.support-record-args.draft-0.1`，不再与
  回执 `schema_version`（`ce.support-record.draft-0.1`）撞名；
- P2-2：blocked 回执仅在请求+主体可归属时携带真实计数/revision，否则省略
  字段（`RECORD_RECEIPT_SCHEMA.receipt.required` 相应收缩）；
- P2-3：幂等重放返回**原存储回执**的 `outcome_kind`/`success_written`；
- P2-4：`receipt_dir` 未配置时不注册 exit 兜底监听器；写出卸载回执后立即
  `removeListener`，重复 apply/dispose 不再累积；
- P2-5：镜像一致性测试改为双向键集合对比（mirror 侧漂移也会被发现）；
- 测试缺口：schema 升版拒绝（`unsupported_schema_version` 专用失败码）、
  异 outcome 重放、record `expected_revision` 并发检查（contracts.md §5
  宿主写入要求）均已实现并有回归测试；Node 自检 20 → 24 项，全绿。
