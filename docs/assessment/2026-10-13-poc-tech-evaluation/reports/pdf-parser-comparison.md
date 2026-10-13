# POC-B 报告：Docling vs GROBID（+ pdfplumber 基线）PDF 解析与证据定位评测

> **v1.1 解读边界（2026-10-13，用户复核后）**：
> ① "100% 文本条目带 bbox" 只证明**坐标字段存在**，不证明坐标正确——本 POC 未做
> bbox IoU 金标准评测（列入 CE-04）。
> ② "12/12 页码命中" 是小样本 AI 目检弱 Gold 抽检，**不能**据此宣称全库页码定位
> 准确率 ≥95%；该目标需 CE-04 的独立标注集验证。
> ③ "页级文本覆盖率 0.800" 的参照由 pypdf（另一解析器）生成，属**解析器间相对比较**，
> 不得表述为"对原文的准确率"（其中 1 份中文文档参照已判无效）。
> ④ 状态更正：Docling = **ADOPT for controlled integration**（允许受控集成），
> 尚未达到"生产级证据引用标准"。

- 实验日期：2026-10-13。样本：`../datasets/pdf-sample/`（10 份真实 PDF：4 英文常规 +
  3 中文 + 1 中文元分析 + 1 短文(2p) + 1 长文(54p)），全部为 ChildEvidence 原件的
  SHA-256 校验副本（清单 `../datasets/pdf-sample/manifest.json`）。
- 解析器：**Docling 2.138.0**（TableFormerMode=ACCURATE，OCR 关闭）、
  **pdfplumber 0.11.x**（轻量坐标基线）、**GROBID 0.9.1（BLOCKED，见 §1；最终决策 DEFER）**。
- 参照（弱参考）：pypdf 文本层逐页抽取（`../parsed/reference/`）；关键证据页以
  pypdfium2 渲染人工目检（AI 实机目检，`../datasets/pdf-gold-annotations.jsonl`）。

## 1. GROBID 为什么 BLOCKED（上游源码级证据）

1. `build.gradle`（tag 0.9.1）第 30、613 行：非 MAC/UNIX 平台直接
   `throw new RuntimeException("Unsupported platform!")`（Gradle 配置期即失败，
   本次实测 4m39s 构建在配置阶段报错）。
2. 底层 PDF 解析器 pdfalto 官方发行版（v0.6.3，含 all 包）只有 linux/mac 二进制，
   无 Windows 版；仓库内 `grobid-home/pdfalto/` 同样只有 lin/mac。
3. 本机无 Docker、无 WSL2（Windows 家庭版 + 无管理员安装路径）。
4. 结论：**不以魔改上游源码的方式强行运行**。GROBID 的 TEI/坐标能力
   （`teiCoordinates` 支持 p/head/s/biblStruct/figure/ref 等，需 `segmentSentences`
   开启句级坐标——来自 `doc/Coordinates-in-PDF.md`）作为 REFERENCE 记录，
   待有容器环境时再评测。

## 2. 定量结果（`../results/pdf-parsing-metrics.csv`）

汇总（有效参照文档 n=9；lt-ff6789b6c543 参照无效见 §3）：

| 指标 | Docling 2.138.0 | pdfplumber 0.11.x |
|---|---|---|
| 页级文本 3-gram 覆盖率（均值） | **0.800** | 0.505 |
| 最低单页覆盖率（跨文档） | 0.0（个别页） | 0.0 |
| 文本条目带有效页码+页内 bbox | **100%**（2949 条） | 100%（行级，11250 条） |
| 表格结构识别 | 6/10 文档检出表格（5–13 个/文档，TableFormer） | 6 文档有 extract_tables 结果（无结构语义、易误检） |
| 章节标题/结构标签 | section_header/text/list_item/footnote 等 | 无（行级对象） |
| 参考文献解析 | 不支持（如实 NULL） | 不支持 |
| 平均每文档耗时 | 39.8 s（2.1–114 s） | **2.4 s**（0.3–6 s） |
| 失败/超时 | 0/10 | 0/10 |

分文档覆盖率（docling / pdfplumber）：580de 0.738/0.402；37ad 0.765/0.301；
ad6c 0.809/0.927；66fd 0.783/0.114；dab4(zh) 0.956/0.488；f16c(zh) 0.869/0.397；
1183287(zh meta) 0.727/0.548；2f7e 0.798/0.398；3a3c(54p) 0.753/0.976；
ff67(zh) 参照无效（pypdf CID 乱码，目检确认该 PDF 为数字文本、docling 输出正确）。

### 证据定位成功率（Gold 目检，`../datasets/pdf-gold-annotations.jsonl`）

- 12 条 AI 目检弱 Gold（7 条研究发现句/统计句 + 4 条章节标题 + 1 条补充），
  全部通过渲染页逐条核对：**Docling 页码命中 12/12（100%）**，
  pdfplumber（抽查 8 条）8/8；样本量小，仅为弱参考结论。
- 定位能力差异：Docling 每条文本自带 `(page_no, bbox)` 溯源 + 结构标签，
  可直接回答"这段发现在第几页哪个区域"；pdfplumber 只有行级坐标、无结构。
- **物理页 vs 印刷页混淆实测**：lt-3a3cfbaa18fd 物理页 4 = 印刷页 2、物理页 21 = 印刷页 19；
  lt-1183287e1b1c 物理页 1 = 印刷页 1170。Gold 标注同时记录两者；
  Docling 的 `page_no` 是物理页，与 ChildEvidence 需要的"回溯到 PDF 位置"一致，
  但对外展示引用时必须换算印刷页码（已在协议中列为必须处理项）。

## 3. 参照失效案例（方法论发现）

`lt-ff6789b6c543`（心理科学进展 2012，数字文本 PDF）：pypdf 参照输出 CID 乱码
（含藏文区字符），导致两个解析器"覆盖率"都虚低（0.13–0.18）、CER 45+；
渲染目检确认 docling 提取完全正确。**教训：pypdf 不能作为中文 PDF 的唯一参照**，
评测必须以渲染目检为最终仲裁（已在该文档标记 `reference_valid=False`）。

## 4. 其他观察

- Docling 个别页覆盖率 0：54 页 CAAS 稿件中部分页（封面/授权页）版面特殊，
  未见文本项（54 页全部有文本项，个别页 3-gram 与参照无交集）——属参照口径噪声，
  未发现真实丢页。
- 中文表现：docling 对 3 篇中文文档覆盖 0.73–0.96、与参照的 CER 低至 0.001–0.26
  （vs pypdf 参照，弱参考）；中文双栏恢复正确（目检 p1）。
- 内存峰值可控（<4GB）；TableFormer ACCURATE 是主要耗时项。

## 5. 结论（供 FINAL_RECOMMENDATION 引用）

- **主解析器选 Docling**：结构化（章节/表格/段落标签）+ 100% 带页码/坐标溯源 +
  中英文都可靠；代价是 CPU 推理慢（~40s/文档）与 HF 模型依赖（须镜像）。
- **pdfplumber 作为轻量回退/交叉校验**：6s 内出文本+行坐标，适合超时回退与
  双解析冲突检测（本 POC 已实现其输出统一结构）。
- **GROBID：BLOCKED（本机），REFERENCE（设计）**：其引用解析/consolidation 能力
  在 ChildEvidence 的参考文献核验场景仍有价值，待容器环境后补测。
- 混合方案按协议 §3 只评估了 "Docling 主 + pdfplumber 回退"（因为 GROBID 缺席），
  其额外成本已量化（双份解析时间 +10%）。
