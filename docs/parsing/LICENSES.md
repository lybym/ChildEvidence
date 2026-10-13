# CE-03 解析依赖来源与许可审计

> 审计日期：2026-10-13。范围：`research parse` 可选依赖（`[parsing]` extra）
> 及其模型权重。核心 CLI（零依赖）不在本表范围。结论先行：**全部为
> MIT / Apache-2.0 / BSD 类许可，可科研集成；无 copyleft 传染风险。**

## 1. Python 包（隔离 venv 安装，版本见 docling-freeze.txt）

| 包 | 版本（POC 基线） | 许可证 | 来源 | 用途 | 维护状态 |
|---|---|---|---|---|---|
| docling | ==2.138.0（固定） | MIT | PyPI / github.com/docling-project/docling（上游审计快照 `f0d9098`，2026-10-12） | 主解析器编排 | 极活跃 |
| docling-core | 2.101.1 | MIT | PyPI | DoclingDocument 类型/序列化 | 活跃 |
| docling-ibm-models | 4.0.3 | MIT | PyPI | 版面/表格模型包装 | 活跃 |
| docling-parse | 7.22.3 | MIT | PyPI | PDF 原生解析后端 | 活跃 |
| pypdfium2 | 5.14.0 | Apache-2.0 / BSD-3（双子许可） | PyPI | pdfium 渲染后端 | 活跃 |
| torch | 2.14.1（CPU） | BSD-3 类 | PyPI | 模型推理运行时 | 活跃 |
| transformers | 5.19.0 | Apache-2.0 | PyPI | 模型加载 | 活跃 |
| accelerate | 1.15.0 | Apache-2.0 | PyPI | 推理加速抽象 | 活跃 |
| pdfplumber | 0.11.x（`>=0.11,<0.12`） | MIT | PyPI | 回退/交叉校验解析器 | 活跃 |

完整冻结清单（安装实测 `pip freeze`）见 [docling-freeze.txt](docling-freeze.txt)。

## 2. 模型权重（本地缓存，离线加载）

| 模型 | 上游仓库 | 许可证（以模型卡为准） | 缓存位置 | 完整性 |
|---|---|---|---|---|
| 版面分析（LayoutModel，heron 系，torch+onnx 引擎变体） | `docling-project/docling-layout-heron`（HF，随 docling 固定 revision） | MIT | `<artifacts-dir>/docling-project--docling-layout-heron*` | `models-manifest.json` 逐文件 SHA-256 |
| 表格结构（TableFormer ACCURATE/FAST，标准版非 V2） | `docling-project/docling-models`（HF，`model_artifacts/tableformer/`，随 docling 固定） | MIT / Apache 类 | `<artifacts-dir>/docling-project--docling-models` | 同上 |
| （如启用才下载）CodeFormula 等 | `docling-project/CodeFormulaV2` | Apache-2.0 类 | （未下载） | 同上 |

- 下载仅经 `research parse models` 显式执行（Issue #3 授权范围：Docling 运行所需
  权重、固定版本；实际下载子集 = layout + tableformer，OCR/图片分类/代码公式等
  模型族在流水线关闭对应功能时不下载）；本机走
  `HF_ENDPOINT=https://hf-mirror.com` 镜像（huggingface.co 直连不可达，POC 上游
  审计实测；Xet CAS 协议经镜像不可用，`HF_HUB_DISABLE_XET=1` 走经典 HTTP）。
- 权重缓存不入 Git；`--verify-only` 可随时离线复核哈希。
- **不下载**、不调用任何云 LLM / 云 OCR / 云 API；不向外传输 PDF 或机构订阅原文。

## 3. 许可义务与边界

1. MIT/Apache/BSD 类许可要求保留版权与许可声明——本仓库不再分发上游代码本身，
   仅通过 PyPI 引用，义务由上游发行物自带文件满足；本仓库不复制其代码。
2. 模型权重仅本地科研使用；不随知识包再分发（知识包发布属 CE-05/CE-06 流程，
   届时逐项复核权重与文本再分发边界）。
3. 解析产物包含文献全文文本 → 视同原文衍生件，**不提交 Git**（同 PDF 原文，
   AGENTS.md #8）；仓库只提交聚合统计（无文本）。
4. 许可证以各模型卡/PyPI 元数据为准；如版本变更需重跑本审计并更新 freeze 文件。

## 4. 上游审计追溯

POC 阶段上游审查（commit/SHA/风险）见
[../assessment/2026-10-13-poc-tech-evaluation/UPSTREAM_AUDIT.md](../assessment/2026-10-13-poc-tech-evaluation/UPSTREAM_AUDIT.md) §2（Docling）、§6（pdfplumber 相关）；
技术决策与边界见 FINAL_RECOMMENDATION §9（v1.1）。
