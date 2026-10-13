# POC 10 份 PDF 真实 E2E 回归报告（CE-03）

> 状态：issue #3 Step 03 交付（2026-10-13）。本报告**只含聚合统计与元数据，不含任何
> 文档文本**；逐份解析产物（含全文，视同原文衍生件）保留在本地
> `<data>/parse-output/`（gitignored），不入 Git（AGENTS.md #8）。
> 所有指标由版本化解析产物计算，同输入 + 同解析器版本 + 同配置可重复生成。

## 1. 运行环境

| 项 | 值 |
|---|---|
| 解析器（主） | docling==2.138.0（POC 固定基线；完整依赖冻结见 [docling-freeze.txt](docling-freeze.txt)） |
| 解析器（回退） | pdfplumber==0.11.10（本批**未触发**） |
| 运行方式 | 隔离 venv（Python 3.12.14），`pip install ".[parsing]"`；核心 CLI 零依赖不受影响 |
| 模型权重 | layout（heron，torch+onnx 变体）+ TableFormer（accurate/fast），缓存
  `C:\Users\lybym\OneDrive\WORK\.ce03-models\`（**不入 Git**）；经 `research parse models`
  下载（HF 镜像 hf-mirror.com，`HF_HUB_DISABLE_XET=1` 经典 HTTP），`--verify-only`
  逐文件 SHA-256 校验 **verified**（53 文件） |
| OCR | 关闭（`docling.ocr_enabled: false`，POC 基线；扫描页只会被标记，不会被 OCR 掩盖） |
| 并发 / 超时 | 1（顺序）/ 单文档 600 s 硬超时（subprocess 模式） |
| 输入 | POC 归档 `pdf-sample-manifest.json` 10 份；**SHA 前置校验 10/10 通过**后才开始解析；
  经 `--input-root` 文件名重映射到工作区副本，原件只读 |

## 2. 可复现命令（Windows PowerShell）

```powershell
$env:PYTHONPATH = "src"
$env:CHILDEVIDENCE_PARSING_MODELS_DIR = "C:\Users\lybym\OneDrive\WORK\.ce03-models"
# 一次性权重下载（唯一联网步骤，需显式授权）：
python -m research_library parse models --artifacts-dir $env:CHILDEVIDENCE_PARSING_MODELS_DIR
# 离线批量解析（产物版本化、幂等、断点续跑）：
python -m research_library parse run `
  --manifest docs\assessment\2026-10-13-poc-tech-evaluation\datasets\pdf-sample-manifest.json `
  --input-root <当前 PDF 样本目录>
# 聚合报告（从产物重算）：
python -m research_library parse report --manifest <manifest.json> --format md
```

## 3. 结果汇总

- **total 10 / parsed 10 / skipped 0 / failed 0 / integrity_failed 0；status：`ok` ×10**
  （无 degraded / fallback / failed——失败与降级路径由单测覆盖，见 §7）
- 解析器：docling ×10；语言检测：en ×6、mixed ×2、zh ×2
  （清单声明类别：en_regular ×4、zh ×3、short ×1、long_report ×1、review_meta ×1）
- 段落 2109（全部携带 bbox）、表格 45（全部携带 bbox）、章节结构正常生成；
  2 页无文本层（计入"不可定位"，**不计为错误**）
- 质量标记：`replacement_chars` / `pua_chars` / `suspicious_script_mix` /
  `no_text_layer_suspected` 均未触发（Docling 对本批中文 CID 映射正常）
- 产物 schema：`childevidence.parse v1`；`printed_page_no` 全部 `null`（无人工校正前
  保持未知，无任何固定页差推断）；`references.items=null` + 原因（诚实缺失）；
  `localization.verified` 全部 `false`

## 4. 存在率 vs 定位准确率（口径声明，硬边界）

- `bbox_presence_rate = 1.0`（aggregate）——**仅表示"坐标字段存在"**。
- `localization_accuracy = null`——解析层不测量定位正确性。准确率必须由 CE-04
  独立人工 Gold 基准测量；POC 12/12 AI 目检**不是人工 Gold**；本报告与代码库
  任何位置都**不声称生产级 ≥95% 定位准确率**。
- 页码/坐标/模型/依赖的溯源字段逐条记录于每份产物的 `source` / `parser` /
  `provenance` 节点，可追溯至源 PDF SHA-256 + 解析器版本 + 权重 manifest + 生效配置
  （`artifact_id = sha256(源SHA + 解析器身份 + options)`）。

## 5. 幂等 / 断点续跑证据

| 运行 | 结果 | 墙钟 |
|---|---|---|
| 首跑（全量解析） | 10 parsed / 0 failed，rc=0 | ≈15.2 min |
| 立即重跑（同输入同版本同配置） | **10 skipped / 0 parsed**，rc=0 | 5–8 s |
| `--force` 重跑（代码修订后重生成） | 10 re-parsed，状态/计数与首跑一致 | ≈13.7 min |
| 终验重跑 | 10 skipped（artifact_id 稳定复用），rc=0 | 5 s |

## 6. 运行开销

- `duration_sec`（逐文档，subprocess 计时）：min 14.5 / mean 85.5 / max 221.2 / total 854.8 s
- `peak_memory_mb`：本报告为 **n/a（诚实 null）**——见 §8 会话限制；非沙盒 Windows
  环境由 runner 子进程自测（psapi）填充该字段，缺失时报告保持 null 而非伪造数值。

## 7. 覆盖边界（本 E2E 证明了什么 / 没证明什么）

- **证明了**：10 份真实 POC PDF 全部成功解析且输出通过 `ce03-parse v1` 结构校验；
  无静默丢页（`page_count` 与逐页记录一致）；溯源字段完整；同配置可幂等重现。
- **没有证明**：定位正确性（CE-04 职责）；OCR / 扫描页路径（OCR 关闭，E2E 样本
  未触发降级）——损坏 PDF、乱码、0 文本、超时、回退、模型不可用、缓存污染等
  失败模式由 `tests/test_parsing_{pipeline,cli,report,schema}.py`（62 项新测试，
  全库 165 项 + smoke_offline 全绿）覆盖。

## 8. 已知会话限制（记录在案，不伪造数值）

- 本次 E2E 运行于 DSH 沙盒会话，进程内存查询被虚拟化：python ctypes psapi
  （父/子两个方向）与 .NET `Get-Process` 交叉验证均返回恒定 ~5 MB 假值
  （真实 docling+torch 工作集为 GB 级）。因此子进程自测同样得到诚实 null，
  报告不呈现假内存数。在普通（非沙盒）Windows 上该字段正常填充。
- 权重下载经 hf-mirror.com 镜像（huggingface.co 直连不可达，POC 上游审计实测）；
  Xet CAS 协议经镜像不可用（401），以 `HF_HUB_DISABLE_XET=1` 走经典 HTTP，
  逐文件 SHA-256 manifest 校验不受影响。

## 9. 主库与 35 份原始 PDF（后置核验）

- 35 份原始 PDF：解析前后 SHA-256 全部一致（35/35；持久化权威参考 =
  `datasets/manifest.json` 的 `pdf_sha256` 字段，可随时复核）。
- `library.sqlite`：SHA-256 前后一致（解析管线对主库**零写入**；
  `--from-library` 仅为只读 SELECT，本批未使用）。
- 原始 PDF 全程只读；临时文件只写产物目录。

## 10. 逐文档明细（仅 ID/计数，不含文本）

| document_id | sha12 | status | parser | pages | paras(bbox) | tables(bbox) | issues | duration_s |
|---|---|---|---|---:|---|---|---|---:|
| lt-3a3cfbaa18fd | 390ee252b0c6 | ok | docling | 54 | 241(241) | 7(7) | - | 221.2 |
| lt-1183287e1b1c | 7e68df2f632d | ok | docling | 19 | 238(238) | 5(5) | - | 159.1 |
| lt-66fdcac87579 | 804e8b3dbc8f | ok | docling | 18 | 311(311) | 6(6) | - | 57.6 |
| lt-f16c456c15ea | 875b76006d0e | ok | docling | 13 | 154(154) | 0(0) | - | 38.0 |
| lt-580de6652a2c | aca275c33eb8 | ok | docling | 26 | 218(218) | 6(6) | - | 96.6 |
| lt-ff6789b6c543 | ce082b98a83f | ok | docling | 13 | 181(181) | 0(0) | - | 38.0 |
| lt-dab4d327e195 | e0080d1ee67d | ok | docling | 14 | 222(222) | 0(0) | - | 38.6 |
| lt-ad6c6f6b125c | e089f7e74779 | ok | docling | 23 | 132(132) | 13(13) | - | 100.6 |
| lt-2f7e083d392e | f46b53fc42c3 | ok | docling | 2 | 29(29) | 0(0) | - | 14.5 |
| lt-37ad5059c0f3 | fbb1e15333f5 | ok | docling | 26 | 383(383) | 8(8) | - | 90.6 |

## 11. 参照来源声明

- 本报告全部数字来自版本化解析产物（`result.json` / `run-meta.json`），由
  `research parse report` 聚合生成，可重复计算。
- 本报告不含解析器间相对覆盖率指标；如需对比 pypdf/pdfplumber 参照口径，必须
  显式标注"解析器间相对指标（参照：xxx），非原文正确率"
  （FINAL_RECOMMENDATION §9 v1.1 解读边界）。
- 本层为数据加工层：不生成 Claim/Evidence 语义、不新增语义表、不发布知识包、
  不更改下游 Agent 行为（AGENTS.md #20；issue #3 交付边界）。
