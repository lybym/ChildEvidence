# DSH 接缝能力矩阵：supported / unsupported / unknown（Issue #13）

> 状态：验证记录，2026-10-18。宿主为本机实际安装的 DSH `0.2.1-rc.2`
> （Cordis 4.0.5；Issue 基线 `0.2.0-rc.2` 本机不可用，差异见
> [REPORT.md](REPORT.md)）。全部结论只覆盖本报告声明的隔离环境与合成数据，
> 不代表真实儿童使用、真实专业资产或发布资格。
> 对应 Issue：<https://github.com/lybym/ChildEvidence/issues/13>；
> 实现与命令见插件
> [README](../../../plugins/growth-support-seams/README.md)。

状态定义：

- **supported**：已在本机 DSH 上实际执行并观察到该接缝行为（附证据位置）。
- **partial**：插件侧或宿主源码/组合层面已证实，但缺少真实模型回合的端到端证据。
- **unsupported**：当前安装版本未提供该接缝；需要宿主改动或组合变更，本仓库不得私自绕过。
- **unknown**：未验证；无法在不触碰现用 profile 或不使用模型凭据的情况下确认。

## 矩阵

| # | 接缝 | 状态 | 依据与证据 | 限制 / 失败模式 |
|---|---|---|---|---|
| 1 | 原生插件加载（Cordis 对象插件 `apply(ctx, config)`） | **supported** | 隔离 profile 实机启动后写入 `load-receipt.json`（4 个工具、3 个 demo scope、2 个 demo 方法）；`--dump-config` 组合树包含条目 | 插件代码在宿主进程内执行；加载失败会阻止 profile 启动（宿主契约：插件加载失败在 runner 挂载前退出） |
| 2 | 插件卸载/释放 | **supported** | 进程退出时写入 `unload-receipt.json`（load 后 6ms）；卸载后再启动无回执 | `internal/plugin` 遥测事件为 Cordis 内部契约，已按"事件钩子 + 进程退出兜底"双层实现；HMR 热重载路径未测（headless 模板禁用 HMR） |
| 3 | 隔离 profile 安装/卸载（`dsh plugin add/remove file:`） | **supported** | `add` 零下载完成（resolved 1 / downloaded 0）；`remove` 后组合树 0 处匹配、node_modules 条目消失 | 首次引导 profile 需 registry 下载宿主模板自身依赖（宿主依赖，与插件无关） |
| 4 | 结构化工具注册（原生 JSON Schema 参数 + `output {schema, render}`） | **supported** | 真机 `@deepseek-ai/dsh-tools` `assertSupportedJsonSchema` 8/8 通过（6 份 schema + 正例 + 负例）；注册契约（无 `run_code` 保留名、output 形状、timeoutMs 校验）在 Node 自检复验 | 零依赖插件以纯对象定义注册，不 import `dsh-tools`，保证 `file:` 离线安装 |
| 5 | 工具输入校验（模型参数按 schema 校验后才执行） | **partial** | 真机 `validateJsonSchemaValue` 通过 contracts.md §2.1 示例、拒绝伪造 actor 角色；宿主源码确认 dispatch 前校验 | 真实模型回合中的无效参数→结构化错误路径未实测（无模型凭据） |
| 6 | 工具策略（`ctx.tools.guard` 单调拒绝、`tools/pre-execute` allow/deny/ask） | **partial** | 宿主 README/源码核验：guard 在 pre-execute 之后单调生效，任何 guard 拒绝不可被后续放行 | 只约束**经过工具接缝的调用**；本次未实机注册 guard 演示拒绝（范围外，#17 运行核心承接） |
| 7 | 协作取消（`exec.signal`） | **supported**（插件侧） | Node 自检：entry-abort 无状态变更；mid-delay abort 不写成功记录；宿主契约：body 前中止为 `ABORTED_BEFORE_DISPATCH`，body 后中止仅覆盖成功结果 | 宿主回合级取消（用户中断模型回合传导到工具）未实测 |
| 8 | 工具超时强制 | **unsupported** | 宿主 README 明示：定义上的 `timeoutMs` 仅声明，registry 不强制；强制需组合 `@deepseek-ai/dsh-tool-call-timeout-policy` | 需要宿主组合变更才能宣称超时行为；本插件不依赖它，验证夹具用 `delay_ms` + AbortSignal 演示协作取消 |
| 9 | Session 持久化与跨进程采纳 | **supported** | `--json` 开场 `session` 事件携带身份；第二次调用按 `--session-id` 采纳已持久化 Session（错误从"session 不存在"变为模型凭据阶段）；未知 id 在任务运行前拒绝 | 采纳校验 cwd/preset 绑定（宿主契约）；完整模型回合内的 Session 事件序列未测 |
| 10 | Session 日志数据路径 | **supported**（路径核验） | `<DSH_HOME>/sessions/--<cwd>--/session-<uuid>/session.v4.jsonl.zstd`；投影缓存 `<DSH_HOME>/storages/session_projcache/sessions/*.json` | 压缩 JSONL，非整理后的成长记录（contracts.md §4 区分） |
| 11 | 模型请求遥测（session-log-deepseek） | **partial** | 组合树含 `session-log-deepseek`；宿主文档：默认 `enabled: true`，对官方 API 请求附加 `dsh_session_log` 字段（随请求上传 Session 日志后缀） | 本机现用（GUI）profile 的实际开关未检查——检查会触碰现用配置，超出本 Issue 边界；"本地保存不等于不外发"必须持续声明 |
| 12 | **受控入口**（保证每次相关互动必经插件工具） | **unsupported** | 宿主只提供"注册后可见、可调用"；无"强制每次调用"的接缝。audit 工具可对**已知 request_id** 检测 0 次受控调用（`uncontrolled_request_hint`），对从未调用工具的会话无轨迹可查 | 注册工具 ≠ 每次必用（architecture.md §4 关键接缝）。需要宿主受控入口/会话编排支持，属明确宿主依赖（#17/#18 承接）；降级模式：明确区分"工具建议模式"与"受控支持模式"，不得将前者验收成后者 |
| 13 | **最终输出检查**（宿主检查最终 assistant 输出） | **unsupported** | `dsh-tools` 管线（pre-execute → guards → execute → post-execute → result）只作用于工具调用与结果，不检查最终自由文本回答 | **未覆盖最终输出时不得声称强制专业流程成立**（Issue 验收条件 3）。模型跳过工具直接回答 = 集成失败，仅靠提示词不能宣称强制执行（contracts.md §6） |
| 14 | 统一输入上下文字段（宿主填充 provenance/媒体来源元数据） | **unknown** | schema 与语义校验已就绪（真机校验通过）；宿主在真实回合中实际填哪些字段未测 | 语音/文字/照片/Web 只作来源元数据（R4）；需真实宿主回合验证 |
| 15 | 请求者/主体/回应对象分离 | **partial** | 插件侧合成验证：scope 绑定主体、跨主体拒绝、自报身份不授权（Node 自检 + 真机 schema 负例） | 宿主真实身份绑定与权限授予未测（需要宿主身份服务） |
| 16 | 成长记录持久化（重启后读取） | **unsupported**（本插件内） | 按设计（contracts.md §5）成长记录由宿主拥有；本插件只定义语义并内存保存会话内状态 | 宿主记录服务（#18）落地前，重启不保留记录是有意的诚实行为；不冒充记得历史 |

## 结论摘录

1. 可以在本仓库内交付的最小插件上，**真实证明**：插件加载/卸载、结构化工具注册与
   schema 校验、协作取消、Session 持久化采纳、数据路径——均 supported（附证据）。
2. **受控入口与最终输出检查在当前安装版本不可实现**：不能宣称"每次相关互动都会
   走专业流程"；任何此类声明都需要宿主改动（宿主依赖已单列，不绕过到普通回答）。
3. 其余（模型回合内行为、宿主身份绑定、真实遥测开关）保持 **unknown** 并列出
   验证前置条件；未验证项不得因代码存在而推定完成。
