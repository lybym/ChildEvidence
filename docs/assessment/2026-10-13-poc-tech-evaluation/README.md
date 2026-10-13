# ChildEvidence-POC — 三项开源技术实机验证（独立工作区）

本目录是 ChildEvidence（`C:\CODE\ChildEvidence`）的**独立 POC 工作区**：
ASReview / Docling+GROBID / PaperQA2+SciFact 的上游审查、数据基线冻结与隔离实机实验。
对 ChildEvidence 只读；原库 SHA-256 与全部 PDF 哈希在实验前后经回归测试校验一致。

## 顶层文档

| 文件 | 内容 |
|---|---|
| `UPSTREAM_AUDIT.md` | 五个上游项目的版本/SHA/许可证/关键源码位置/风险（Step 01） |
| `results/preflight-report.md` | 本机环境与资源预检（Step 00） |
| `EXPERIMENT_PROTOCOL.md` | 统一实验协议：数据/标签分层/指标公式/口径（Step 03） |
| `reports/asreview-evaluation.md` | POC-A 报告 |
| `reports/pdf-parser-comparison.md` | POC-B 报告 |
| `reports/evidence-verification.md` | POC-C 报告 |
| `FINAL_RECOMMENDATION.md` | 技术选型与 Roadmap（Step 08） |

## 目录

```text
adapters/            各上游适配与说明
benchmarks/          实验脚本（可独立运行、失败可恢复）
configs/             依赖 freeze 快照
datasets/            manifest.json（393 条）+ A1 CSV + A2 标注队列 + PDF 抽样 + scifact 数据
parsed/              docling / pdfplumber / reference 原始输出
results/             指标 CSV、JSONL、报告与运行元数据
figures/             图表（recall 曲线、解析对比、渲染目检页）
snapshots/           SQLite Backup API 快照 + schema + 行数 + 哈希清单
tests/               回归测试（venvs/common）
upstream/            五个上游仓库浅克隆（grobid 已 checkout tag 0.9.1）
venvs/               4 个隔离虚拟环境（common / asreview / docling / paperqa）
cache/ runtimes/     模型缓存（HF 镜像）、JDK21、uv、pdfalto 等
```

## 复现命令（PowerShell）

```powershell
# 0) 数据基线冻结（只读原库）
$py = "$env:DSH_PYTHON"   # 或自带 CPython 3.12.14 路径
& $py scripts\baseline_freeze.py
& $py scripts\build_datasets.py

# 1) POC-A（asreview venv）
& venvs\asreview\Scripts\python.exe benchmarks\run_asreview.py --seeds 11,23,37,51,67
& venvs\common\Scripts\python.exe benchmarks\plot_asreview.py

# 2) POC-B（docling venv；须 HF 镜像）
$env:HF_ENDPOINT='https://hf-mirror.com'; $env:HF_HOME="$PWD\cache\hf"; $env:HF_HUB_DISABLE_XET='1'
& venvs\docling\Scripts\python.exe benchmarks\run_docling.py
& venvs\common\Scripts\python.exe benchmarks\run_pdfplumber.py
& venvs\common\Scripts\python.exe benchmarks\eval_parsers.py

# 3) POC-C（common + paperqa venv）
& venvs\common\Scripts\python.exe benchmarks\run_scifact.py
$env:PQA_HOME="$PWD\cache\pqa"
& venvs\paperqa\Scripts\python.exe benchmarks\run_paperqa_offline.py
& venvs\common\Scripts\python.exe benchmarks\run_c1_baseline.py
& venvs\common\Scripts\python.exe benchmarks\run_evidence_cards.py

# CE-01：从原始排序重算 v2 指标 + 数学一致性测试
& venvs\common\Scripts\python.exe benchmarks\recompute_metrics.py

# 4) 回归测试
& venvs\common\Scripts\python.exe tests\test_regression.py
```

## 数据安全边界（已由 tests/test_regression.py 固化）

1. 原库与 35 份 PDF 的 SHA-256 在实验前后一致；
2. 所有原库访问走 `mode=ro` 连接或 Backup API 快照；
3. PDF 副本只读、哈希与原件一致；
4. 全部 `allowed_for_external_models=false`；无任何云 LLM 调用（无授权 Key）；
5. Evidence Card 一律 `human_review_status=pending`、`allowed_for_agent_release=false`。
