# Preflight Report — ChildEvidence POC

生成时间：2026-10-13T01:45+08:00。来源：实测命令输出（见会话日志与下表）。

## 运行环境

| 检查项 | 结果 | 影响与对策 |
|---|---|---|
| Windows | 11 家庭版 26300 x64 | — |
| CPU / RAM | Ryzen 7 8845H 8C16T / 27.8GB（空闲 6–10GB） | GROBID 构建 -Xmx4g 需关注内存；并发控制 ≤4 |
| GPU | 无独立 GPU（780M 核显） | 全部 CPU 推理：Docling/Embedding 慢但可行 |
| Python | 无系统 Python；DSH 自带 CPython 3.12.14（只读使用） | 四个 venv 建于 POC 工作区 |
| Git | 2.56.0 | 上游浅克隆 |
| Docker / WSL2 | 均不可用 | GROBID 走本机 Gradle + JDK21 |
| Java | 无系统 Java → Microsoft OpenJDK 21 → `runtimes/jdk21` | — |
| 磁盘 C: | 空闲 ~425GB | 充足 |
| 网络 | PyPI/GitHub/S3/Gradle/Maven/Adoptium/hf-mirror OK；huggingface.co SSL 失败 | HF 走镜像 `HF_ENDPOINT=https://hf-mirror.com` |
| GitHub Releases CDN | 不稳定（uv 直下超时；改 PyPI） | 大文件下载设置超时与备源 |
| LLM API Keys | 全部不存在（仅记录存在性） | PaperQA2 生成环节 BLOCKED，不做任何付费调用 |

## 资源与预算保护

- 单进程最大内存 4GB（GROBID 构建）；Docling 解析每 PDF 超时 600s；GROBID 单请求超时 120s。
- 全部缓存/模型/索引置于 `C:\CODE\ChildEvidence-POC\cache`、`runtimes`、`venvs`。
- 无外部付费 API 调用（0 次）；仅访问官方公开 API/镜像站点。
- 并发：git/uv/gradle 串行为主；Gradle workers.max=1（上游 gradle.properties）。

## 依赖安装状态（实测）

| venv | 关键包 | 状态 |
|---|---|---|
| venvs/common | matplotlib, pandas, scikit-learn, pypdf, jiwer, lxml, numpy, pyyaml | 完成 |
| venvs/asreview | asreview 3.0.8（+ sklearn 1.9.1 等 68 包） | 完成，`asreview --version`=3.0.8 |
| venvs/docling | docling 2.138.0（+ torch 2.14.1 CPU 等） | 完成 |
| venvs/paperqa | paper-qa 2026.8.12（+ litellm/tantivy/openai 等 80 包） | 完成，CLI=`pqa` |
| runtimes/jdk21 | Microsoft OpenJDK 21.0.12.1+1 | 完成 |
| upstream/grobid | tag 0.9.1（SHA 523bb8e）`gradlew assemble` | **Windows 原生构建失败（Unsupported platform! + 无 pdfalto Windows 二进制）→ GROBID BLOCKED** |

## 预计下载规模（已完成/进行中）

- 五仓库浅克隆 ~1.2GB（GROBID 含 469MB 模型）；uv/依赖 ~2.5GB（torch 占大头）；
  Docling HF 模型 ~1.0GB（走镜像，待首次转换时下载）；SciFact 数据 3.1MB。
