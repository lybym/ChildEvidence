# ce-growth-support-seams — DSH 接缝验证插件（Issue #13）

ChildEvidence Issue
[#13](https://github.com/lybym/ChildEvidence/issues/13)
的最小可复现 DSH 原生插件：用合成数据（`demo-*` 标识）验证已安装 DSH 的
原生插件、结构化工具、工具策略、取消与 Session 接缝。它不是儿童交互产品，
不携带真实专业资产，不改变任何现有 profile。

- 插件版本：0.1.0（本仓库内交付）
- 目标宿主：DSH CLI（验证记录基于本机实际安装的 `dsh --version`
  `0.2.1-rc.2`，Cordis 4.0.5；Issue 基线 `0.2.0-rc.2` 在本机不可用，差异见
  [验证报告](../../docs/verification/dsh-seam-verification/REPORT.md)）
- 运行时依赖：**无**（零 npm 依赖；由宿主提供 `ctx.tools` 服务与 loader）
- 数据边界：全部标识符、授权范围与方法均为本文件内 `demo-*` 合成夹具；
  不读写真实儿童数据，不上传任何记录，不授予真实发布资格

## 插件注册了什么

| 工具 | 作用（对应 contracts.md §3 候选接口） |
|---|---|
| `ce_prepare_support` | 校验统一输入 `ce.support-input.draft-0.1`，返回结构化 `SupportResult`（或带失败码的 blocked；升版 `schema_version` 以 `unsupported_schema_version` 拒绝） |
| `ce_validate_support_proposal` | 校验模型提案：有限动作词表、demo 方法归属、revision 一致、拒绝信号暂停 |
| `ce_record_support_outcome` | 记录真实回执；`expected_revision` 并发检查（contracts.md §5 宿主写入要求）；按 `(request_id, action_id)` 幂等且重放返回原回执；取消/失败/拒绝不写成功行；不可归属的 blocked 回执省略计数，不伪造零值 |
| `ce_session_audit` | 汇报受控调用轨迹（按宿主 scope 过滤主体）；对未经过受控入口的 request 给出检测提示 |

安全语义（合成实现，对应 contracts.md §2/§5/§6）：

- `authorization_ref` 必须是宿主配置授予的 scope；自报身份不产生权限；
- scope 绑定主体（subject），跨主体读写返回 `subject_scope_mismatch`；
- 未知动作类型、未知观察来源一律**保留原值并拒绝放行**（unknown preservation）；
- 取消通过 `exec.signal` 协作观察：中止后不产生状态变更、不写成功记录；
- 加载/卸载回执：配置 `receipt_dir` 后写入 `load-receipt.json` /
  `unload-receipt.json`（默认关闭，验证时用 `--patch` 覆盖开启）。

## 在干净隔离环境安装、运行、卸载（PowerShell）

以下命令全部使用隔离的 `DSH_HOME`（临时目录），不触碰现有 profile。

### 1. 创建隔离 home 与验证 profile

```powershell
$env:DSH_HOME = "C:\CODE\.tmp\ce-dsh-home"   # 任一仓库外目录；不存在会自动创建
dsh --profile ce-verify --from-default-profile headless "profile bootstrap (synthetic)"
dsh --profile ce-verify --dump-config         # 组合树可打印，profile 可用
```

`--from-default-profile headless` 从随宿主分发的 headless 模板复制新
profile；首次启动时宿主会安装模板自带依赖（需要 registry 访问，这是宿主
自身的依赖，与本插件无关）。

### 2. 离线安装插件（零依赖 `file:` spec）

```powershell
dsh plugin --profile ce-verify add file:C:\CODE\ChildEvidence\plugins\growth-support-seams
dsh --profile ce-verify --dump-config         # 组合树应包含 ce-growth-support-seams
```

### 3. 开启回执并启动（加载可观察）

```powershell
@'
- id: ce-growth-support-seams
  config:
    receipt_dir: C:\CODE\.tmp\ce-seam-receipts
'@ | Set-Content C:\CODE\.tmp\ce-seam-patch.yml

dsh --profile ce-verify --patch C:\CODE\.tmp\ce-seam-patch.yml headless "demo task (synthetic)"
Get-Content C:\CODE\.tmp\ce-seam-receipts\load-receipt.json
```

headless 一次性任务在插件挂载后运行；隔离 home 中没有模型凭据，任务会在
模型请求处失败并退出 1——这是预期行为，加载回执已经证明插件真实挂载。
（有 API key 时，同一命令会用真实模型走完一次工具调用回路。）

### 4. Session 持久化接缝（可选）

```powershell
# 第一次运行不带 --session-id：创建默认 session-<uuid> 并持久化
# （--json 开场事件携带本次使用的 Session 身份）
dsh --profile ce-verify --patch C:\CODE\.tmp\ce-seam-patch.yml headless --json "demo task (synthetic)"

# 用上一步得到的 id 采纳已持久化的 Session（未知 id 会在任务运行前直接拒绝，
# 因此第二次调用若报模型凭据错误而非 "session does not exist"，即证明采纳成功）
dsh --profile ce-verify --patch C:\CODE\.tmp\ce-seam-patch.yml headless --session-id <上一步的sessionId> "demo task again (synthetic)"
```

### 5. 卸载并验证移除

```powershell
dsh plugin --profile ce-verify remove ce-growth-support-seams
dsh --profile ce-verify --dump-config         # 不再包含 ce-growth-support-seams
```

恢复方式：删除 `$env:DSH_HOME` 所指目录即回到干净状态；现有 profile 未被
修改。

## 离线测试

- Node 自检（受控流程、拒绝路径、unknown 保留、主体隔离、幂等与原回执重放、
  `expected_revision` 并发检查、协作取消、回执与 exit 兜底监听器生命周期）：

  ```powershell
  node plugins\growth-support-seams\tests\self-check.mjs
  ```

- Python 套件（包结构、patch 声明、schema 子集、合成卫生；自动定位 Node，
  无 Node 时跳过行为测试）：

  ```powershell
  $env:PYTHONPATH = "src"
  python -m unittest tests.test_dsh_seam_plugin
  ```

- 真机 schema 校验（用真实 `@deepseek-ai/dsh-tools` 校验器验证 schema 与
  contracts.md §2.1 示例输入，并打印校验器路径与版本作 provenance）。
  **注意**：安装的宿主包位于 `.asar` 归档内，普通 `node` 读不到；要么通过
  宿主运行时执行，要么把 `CE_DSH_TOOLS_LIB` 指向一份解包的 dsh-tools：

  ```powershell
  # 方式 A：宿主运行时（可读安装负载，只读不改）
  $env:ELECTRON_RUN_AS_NODE = "1"
  & "$env:LOCALAPPDATA\Programs\DeepSeek Harness\DeepSeek Harness.exe" --expose-internals `
      plugins\growth-support-seams\tools\validate-with-host.mjs

  # 方式 B：普通 node + 显式路径（例如装有 dsh-tools 的隔离 profile）
  node plugins\growth-support-seams\tools\validate-with-host.mjs <profileDir>

  # 方式 C：普通 node + CE_DSH_TOOLS_LIB 指向解包的 dsh-tools lib/index.js
  $env:CE_DSH_TOOLS_LIB = "<解包目录>\dsh-tools\lib\index.js"
  node plugins\growth-support-seams\tools\validate-with-host.mjs
  ```

  解析顺序：显式参数 → `CE_DSH_TOOLS_LIB` → `$env:LOCALAPPDATA` 推导的安装
  负载（只读）。所有候选都不可用时，helper 以 exit 1 输出上述诊断，不产生
  假 PASS。

## 明确不做什么

- 不实现媒体处理（语音/照片/Web 只作为统一输入中的来源元数据字段）；
- 不持久化成长记录（真实成长记录由宿主管理，contracts.md §5）；
- 不宣称"强制专业流程"成立：工具注册只证明可调用，不证明每次必经；受控
  入口/最终输出检查的可实现程度见
  [能力矩阵](../../docs/verification/dsh-seam-verification/CAPABILITY-MATRIX.md)；
- 不写入任何凭据、真实儿童数据或论文内容。
