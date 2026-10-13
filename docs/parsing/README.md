# CE-03 受控 PDF 解析流水线（数据加工层）

> 状态：工程实现（Feature PR，Issue #3）。本目录文档描述解析基础设施的运行方法、
> 配置、边界与审计口径。**本层不生成任何 Claim/Evidence 科研语义判断，不新增
> Evidence/Claim 表，不发布知识包，不更改下游 Agent 人格/策略**
> （AGENTS.md #20；FINAL_RECOMMENDATION §9.5 PR 边界调整）。

## 1. 是什么 / 不是什么

- **是**：`原 PDF → SHA/完整性校验 → Docling 解析（可配置回退 pdfplumber）→
  规范化输出 → 结果校验 → 版本化独立产物目录` 的可重复流水线，输出统一 schema
  （document / page / section / paragraph / table / reference / provenance），
  含源 SHA-256、解析器/模型/依赖版本、原始文本 span、物理页号与 bbox。
- **不是**：证据抽取器、页码"正确性"保证器、生产级解析服务。bbox 字段存在只
  证明**坐标被提取**，不证明坐标正确；定位准确率必须由 CE-04 独立人工 Gold
  基准测量（POC 12/12 AI 目检是弱参考，不是人工 Gold，不声称生产级 ≥95%）。

## 2. 安装（Windows PowerShell，隔离 venv，可选依赖）

零依赖核心不受影响：`research discover/verify/acquire/...` 永不 import docling。
解析功能通过 `[parsing]` extra 在**独立 venv** 安装：

```powershell
# 1) 创建隔离 venv（建议放在仓库外）
python -m venv C:\TOOLS\ce03-venv
C:\TOOLS\ce03-venv\Scripts\python.exe -m pip install --upgrade pip

# 2) 安装解析 extra（docling==2.138.0 为 POC 固定基线；见 docling-freeze.txt）
cd C:\path\to\ChildEvidence
C:\TOOLS\ce03-venv\Scripts\python.exe -m pip install ".[parsing]"

# 3) 下载 Docling 运行权重到本地缓存（唯一联网步骤，显式执行；见 §5）
C:\TOOLS\ce03-venv\Scripts\python.exe -m research_library parse models `
    --artifacts-dir C:\TOOLS\ce03-models

# 4) 校验权重缓存完整性（离线）
C:\TOOLS\ce03-venv\Scripts\python.exe -m research_library parse models `
    --verify-only --artifacts-dir C:\TOOLS\ce03-models
```

环境变量（优先级高于 config/parsing.yaml）：

| 变量 | 含义 |
|---|---|
| `CHILDEVIDENCE_PARSING_MODELS_DIR` | Docling 权重缓存目录（离线优先） |
| `CHILDEVIDENCE_PARSING_OUTPUT_DIR` | 产物根目录（默认 `<data>/parse-output`） |
| `CHILDEVIDENCE_PARSING_TIMEOUT_SEC` | 单文档超时（秒） |
| `CHILDEVIDENCE_PARSING_EXECUTION` | `subprocess`（默认，支持硬超时/内存上限）或 `inprocess`（测试） |
| `CHILDEVIDENCE_PARSING_OFFLINE` | `0` 关闭离线守卫（不建议）；其余值=离线 |
| `CHILDEVIDENCE_PARSING_PRIMARY` / `_FALLBACK` / `_FALLBACK_ENABLED` | 主/备解析器与回退开关 |
| `CHILDEVIDENCE_DATA_DIR` | 数据根目录（沿用主配置） |

## 3. 运行

```powershell
# 单文件
python -m research_library parse run --pdf C:\path\to\paper.pdf --document-id lt-xxxx

# 清单批量（推荐；manifest 格式见 POC pdf-sample-manifest.json：
# {"documents":[{"document_id","sha256","copy_path","category","language",...}]}）
python -m research_library parse run --manifest C:\path\to\manifest.json

# 清单条目记录的是旧机器绝对路径时，用文件名重映射到当前目录
python -m research_library parse run --manifest manifest.json --input-root C:\current\pdfs

# 从主库读取已下载 PDF 列表（只读 SELECT；不写库）
python -m research_library parse run --from-library

# 重新生成聚合报告（从产物重算，幂等）
python -m research_library parse report --format md  --out report.md
python -m research_library parse report --format json
```

产物布局（内容寻址，幂等/断点续跑）：

```
<data>/parse-output/<sha256前12位>/<artifact_id>/
├── result.json     # 规范化解析结果（ce03-parse v1 schema，含 provenance）
├── page-map.json   # 物理页↔印刷页映射（印刷页默认 null，见 §6）
└── run-meta.json   # 本次运行状态/耗时/警告（审计）
```

- `artifact_id = sha256(源SHA + 解析器名/版本 + 模型清单 + 生效配置)`。
- 重跑时：存在同 ID 且通过校验、状态非 failed 的产物 → **跳过**（断点续跑）；
  `--force` 强制重解；损坏/外来 result.json 视为缓存污染 → 警告并原子重建。
- 解析失败/损坏 PDF/SHA 不匹配 → 记录失败原因，不产生伪造结果。

## 4. 输出 schema（要点）

- `source`：原路径、字节数、**SHA-256**、完整性校验结果。
- `parser`：名称、版本、模型清单（来自权重缓存 manifest）、依赖版本、生效配置与 options_hash。
- `status`：`ok` / `degraded`（质量标记或零文本）/ `fallback`（主解析失败、备解析接管，主失败原因保留）/ `failed`。
- `pages[]`：`physical_page_no`（定位基准）+ `printed_page_no`（默认 null）+
  尺寸、是否有文本层、页级质量标记。
- `paragraphs[] / tables[]`：阅读顺序、原文文本、`provenance.bbox`（PDF 点，
  左上原点 y 向下）、`char_span`、来源 label；无坐标 → `localization.status=unavailable`。
  **`localization.verified` 在本层恒为 false**。
- `sections[]`：标题层级/分组（pdfplumber 回退时为空并注明）。
- `references`：解析器不支持参考文献切分时 `items=null` + 原因说明（诚实缺失，不推测）。
- `issues`：`replacement_chars`（CID 乱码疑似）/ `pua_chars`（私有区字符）/
  `suspicious_script_mix`（异常文字区块）/ `no_text_layer_suspected`（疑似扫描页，
  OCR 默认关闭）/ `table_structure_uncertain`（复杂表格不确定）等。
- `localization_summary`：**存在率**（字段存在比例）与**定位准确率**分开；
  准确率在本层恒为 null（CE-04 职责）。

## 5. 离线优先与权重来源（授权范围）

- 解析运行**零网络**：离线守卫设置 `HF_HUB_OFFLINE=1`、`TRANSFORMERS_OFFLINE=1`，
  权重从 `--artifacts-dir` 缓存加载；缓存缺失 → 明确 `model_unavailable` 失败（可回退）。
- 权重下载仅限 **Docling 运行所需模型**（layout/tableformer 等，Docling 固定
  版本所指向的 HuggingFace 仓库），经 `research parse models` 显式执行；
  本机实测 huggingface.co 直连不可达，默认走 `HF_ENDPOINT=https://hf-mirror.com`
  镜像（POC 上游审计结论）。
- 下载完成后对缓存内每个文件计算 SHA-256 写入 `models-manifest.json`；
  `--verify-only` 随时离线复核。
- **不向外传输任何 PDF 或机构订阅原文**；云端 LLM 调用不存在。
- 资源限制：默认并发=1（顺序执行）；`timeout_sec=600` 硬超时（subprocess 模式
  到点 kill）；可选 `max_memory_mb` 内存上限（采样超限 kill）。内存峰值按进程
  工作集记录（Windows psapi；其他平台为 null，不伪造数值）。

## 6. 物理页 vs 印刷页（人工校正）

- **物理页是唯一定位基准**；`printed_page_no` 默认 `null`。
- **不做任何固定页差推断**（不同文献前置页/章节重排/罗马数字会导致系统性错误）。
- 人工校正文件：`<data>/parse-corrections/<document_id>.json`：

```json
[
  {"physical_page_no": 4, "printed_page_no": 2, "note": "人工核对"},
  {"physical_page_no": 5, "printed_page_no": 3}
]
```

  重新运行（或 `--force`）后，对应页 `printed_page_no` 生效，
  `printed_page_origin=manual`，校正记录（来源文件+时间）写入 page-map.json 审计。
  印刷页未知就保持 null——这是特性，不是缺陷。

## 7. 双解析器策略

- 回退（默认开）：Docling 失败（异常/超时/模型缺失）→ pdfplumber 接管，
  产物 `status=fallback`，主失败原因保留在 `failure_reasons`。
- 交叉校验（`parser.cross_check: true` 时）：主解析成功后额外运行 pdfplumber，
  比对页数与页级文本量；**分歧不自动裁决**，生成
  `<data>/parse-output/parse-review-queue/*.json` 复核任务，由人工决定。
- 回退产物明确标注行级提取的局限（无章节结构、阅读顺序=行序）。

## 8. 与主库边界

- `library.sqlite` **零写入**（`--from-library` 只读 SELECT）。
- 解析产物不进入主库；全部落在 `<data>/parse-output/`（gitignored）。
- 原始 PDF 只读：源文件 SHA 校验 + 解析后无修改；临时文件只写产物目录。
- 后续 35 份批量任务：同管线、同清单格式；不改 works 数据（入参只读）。

## 9. 质量指标口径（引用纪律）

- 报告（`parse report`）只含**存在率/计数/耗时/内存/标记统计**，不含文档文本。
- 任何解析器间对比必须标注"**解析器间相对指标（参照：xxx），非原文正确率**"
  （POC-B v1.1 解读边界 ①③）。
- 禁止把 POC 12/12 AI 目检表述为人工 Gold；禁止声称生产级 ≥95% 定位准确率
  （该目标属 CE-04 独立人工基准）。

## 10. 测试与回归

- `python -m unittest discover -s tests`：全部单测**不需要** docling/pdfplumber
  （适配器在流水线缝隙被替换为桩；子进程超时用文档化的 `parser_module` 测试钩子）。
- 故障场景覆盖：损坏 PDF、乱码、0 文本、页码校正、缺失 bbox、超时、回退、
  多次幂等、路径变化、模型不可用、缓存污染。
- POC 10 份 PDF 的真实 E2E 回归记录见本目录
  `poc10-e2e-report.md`（聚合统计）与本地产物（不入 Git）。
