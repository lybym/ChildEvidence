"""Markdown deliverables: catalog, manual queue, acquisition report,
taxonomy and methodology documents (all numbers from live SQL queries)."""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from . import db
from .config import DOMAIN_LABELS_ZH, DOMAIN_ORDER, PROJECT_ROOT, load_yaml

NOTE_RE = re.compile(r"<[^>]+>")


def _clean(text):
    if text is None:
        return ""
    t = NOTE_RE.sub(" ", str(text))
    return re.sub(r"\s+", " ", t).strip().replace("|", "\\|")


def _authors_short(authors: list, max_n=3) -> str:
    names = [a.get("name") or "" for a in authors or [] if a.get("name")]
    if not names:
        return "（佚名）"
    if len(names) > max_n:
        return "、".join(names[:max_n]) + " 等"
    return "、".join(names)


def _id_label(w: dict) -> str:
    if w.get("doi"):
        return f"[DOI:{w['doi']}](https://doi.org/{w['doi']})"
    if w.get("pmcid"):
        return f"[PMCID:{w['pmcid']}](https://europepmc.org/article/PMC/{w['pmcid']})"
    if w.get("eric_id"):
        return f"[ERIC:{w['eric_id']}](https://eric.ed.gov/?id={w['eric_id']})"
    if w.get("openalex_id"):
        return f"[OpenAlex:{w['openalex_id']}](https://openalex.org/{w['openalex_id']})"
    return "—"


def _pdf_label(w: dict) -> str:
    st = w.get("access_status")
    if st == "pdf_downloaded":
        path = w.get("local_pdf_path") or ""
        size = w.get("pdf_file_size")
        pages = w.get("pdf_page_count")
        meta = []
        if pages:
            meta.append(f"{pages}页")
        if w.get("pdf_version"):
            meta.append({"published_version": "正式发表版", "accepted_manuscript": "作者接受稿",
                         "submitted_version": "预印本/投稿稿"}.get(w["pdf_version"], w["pdf_version"]))
        lic = w.get("license") or "license_unknown"
        meta.append({"cc-by": "CC-BY", "cc-by-nc": "CC-BY-NC", "cc0": "CC0",
                     "pd": "公有领域", "license_unknown": "许可未知"}.get(lic, lic))
        return f"✅ 已获取（{path}{'；'.join([''] + meta) if meta else ''}）"
    if st == "open_html_only":
        return "🌐 有开放 HTML 全文，PDF 待人工获取"
    if w.get("canonical_url"):
        return f"❌ 待人工获取（[官方页面]({w['canonical_url']})）"
    return "❌ 待人工获取"


EV_ZH = {
    "meta_analysis": "Meta 分析", "systematic_review": "系统综述",
    "narrative_review": "叙述性综述", "rct": "随机对照试验",
    "longitudinal": "纵向研究", "quasi_experimental": "准实验",
    "other_empirical": "实证研究（设计待核）", "practice_guideline": "循证实践指南",
    "policy_report": "政策/机构报告", "theoretical_conceptual": "理论/概念研究",
    "preprint_empirical": "预印本（未经同行评议）",
}

TYPE_ZH = {
    "journal_article": "期刊论文", "review_article": "综述论文", "report": "报告",
    "practice_guide": "实践指南", "guideline": "指南", "book": "专著",
    "book_chapter": "书籍章节", "preprint": "预印本", "eric_document": "ERIC 文献",
    "conference_paper": "会议论文", "dissertation": "学位论文",
}


def _write(docs_dir: Path, name: str, content: str) -> Path:
    docs_dir.mkdir(parents=True, exist_ok=True)
    p = docs_dir / name
    p.write_text(content, encoding="utf-8")
    return p


def write_catalog(conn, docs_dir: Path) -> Path:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    works = [db.row_to_dict(r) for r in conn.execute(
        "SELECT * FROM works WHERE record_status='ingested' ORDER BY publication_year DESC, internal_id")]
    by_domain: dict[str, list] = {d: [] for d in DOMAIN_ORDER}
    for w in works:
        doms = w["research_domains"] or ["cross_domain"]
        for d in doms:
            by_domain.setdefault(d, []).append(w)

    lines = [
        "# ChildEvidence 科研文献总目录（literature-catalog）",
        "",
        f"> 由 `research docs` 命令从 `library.sqlite` 自动生成；生成时间：{now}。",
        "> 只收录 `record_status='ingested'` 的文献；候选、被拒记录见数据库。",
        "",
        "| 领域 | 数量 |",
        "|---|---|",
    ]
    total_rows = 0
    for d in DOMAIN_ORDER + [k for k in by_domain if k not in DOMAIN_ORDER]:
        n = len(by_domain.get(d, []))
        total_rows += n
        lines.append(f"| {DOMAIN_LABELS_ZH.get(d, d)} | {n} |")
    lines += ["", f"注：一篇文献可属于多个领域，因此分领域合计（{total_rows}）可能大于唯一文献数（{len(works)}）。",
              ""]

    for d in DOMAIN_ORDER + [k for k in by_domain if k not in DOMAIN_ORDER and k != "cross_domain"]:
        ws = by_domain.get(d, [])
        if not ws:
            continue
        lines.append(f"## {DOMAIN_LABELS_ZH.get(d, d)}")
        lines.append("")
        lines.append("| # | 标题 | 作者与年份 | 期刊/机构 | 标识 | 研究类型 | 主题标签 | PDF 状态 |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for i, w in enumerate(ws, 1):
            tags = "、".join(w["topic_tags"] or [])
            lines.append(
                f"| {i} | {_clean(w['title'])} | {_authors_short(w['authors'])}，{w.get('publication_year') or '？'} "
                f"| {_clean(w.get('journal_or_publisher')) or '—'} | {_id_label(w)} "
                f"| {EV_ZH.get(w.get('evidence_category'), w.get('evidence_category') or '—')}"
                f" / {TYPE_ZH.get(w.get('document_type'), w.get('document_type') or '—')} "
                f"| {tags or '—'} | {_pdf_label(w)} |")
        lines.append("")

    cross = by_domain.get("cross_domain", [])
    if cross:
        lines.append("## 跨领域 / 综合资源")
        lines.append("")
        for w in cross:
            lines.append(f"- {_clean(w['title'])}（{_authors_short(w['authors'])}，{w.get('publication_year')}）"
                         f" — {_id_label(w)} — {_pdf_label(w)}")
        lines.append("")
    return _write(docs_dir, "literature-catalog.md", "\n".join(lines))


def write_manual_queue(conn, docs_dir: Path) -> Path:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    rows = conn.execute(
        "SELECT w.*, q.priority AS q_priority, q.reason AS q_reason, q.search_hint AS q_hint"
        " FROM manual_queue q JOIN works w ON w.internal_id=q.internal_id"
        " WHERE w.record_status='ingested'"
        " ORDER BY q.priority, COALESCE(w.evidence_category,'zzz'), w.publication_year DESC"
    ).fetchall()
    lines = [
        "# 人工下载队列（manual-download-queue）",
        "",
        f"> 由 `research docs` 生成；生成时间：{now}。",
        "> 项目：ChildEvidence（儿童研究证据库）。",
        "> 这些文献未能通过合法公开渠道自动获取 PDF，需要使用机构订阅或图书馆权限人工下载。",
        "> 下载后执行：`python -m research_library import-pdf <文件路径> --doi <DOI>`，即可自动匹配入库并去重。",
        "",
    ]
    if not rows:
        lines.append("（队列为空）")
        return _write(docs_dir, "manual-download-queue.md", "\n".join(lines))
    lines.append("| 优先级 | 标题 | 作者与年份 | 出处 | 标识/入口 | 领域 | 原因 | 建议获取方式 |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for i, r in enumerate(rows, 1):
        w = db.row_to_dict(r)
        doms = "、".join(DOMAIN_LABELS_ZH.get(d, d) for d in (w["research_domains"] or []))
        lines.append(
            f"| {i} | {_clean(w['title'])} | {_authors_short(w['authors'])}，{w.get('publication_year') or '？'} "
            f"| {_clean(w.get('journal_or_publisher')) or '—'} | {_id_label(w)} | {doms or '—'} "
            f"| {_clean(w.get('q_reason')) or '—'} | {_clean(w.get('q_hint')) or '—'} |")
    lines.append("")
    lines.append("## 人工导入说明")
    lines.append("")
    lines.append("1. 从出版商官网或图书馆数据库下载 PDF（请遵守订阅协议，勿再分发）。")
    lines.append("2. 运行 `python -m research_library import-pdf <pdf路径> --doi <DOI>`。")
    lines.append("3. 程序将校验 PDF 文件头/页数/SHA-256，匹配到对应条目后更新状态，不会产生重复条目。")
    return _write(docs_dir, "manual-download-queue.md", "\n".join(lines))


def write_acquisition_report(conn, docs_dir: Path, config) -> Path:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    q = lambda sql: conn.execute(sql).fetchone()[0]
    total = q("SELECT COUNT(*) FROM works")
    ingested = q("SELECT COUNT(*) FROM works WHERE record_status='ingested'")
    candidates = q("SELECT COUNT(*) FROM works WHERE record_status='candidate'")
    rejected = q("SELECT COUNT(*) FROM works WHERE record_status='rejected'")
    verified = q("SELECT COUNT(*) FROM works WHERE metadata_status='crossref_verified' AND record_status='ingested'")
    meta_conflict = q("SELECT COUNT(*) FROM works WHERE metadata_status='conflict' AND record_status='ingested'")
    no_doi = q("SELECT COUNT(*) FROM works WHERE doi IS NULL AND record_status='ingested'")
    pdf_ok = q("SELECT COUNT(*) FROM works WHERE access_status='pdf_downloaded' AND record_status='ingested'")
    open_html = q("SELECT COUNT(*) FROM works WHERE access_status='open_html_only' AND record_status='ingested'")
    no_open_pdf = q("SELECT COUNT(*) FROM works WHERE access_status='no_open_pdf_found' AND record_status='ingested'")
    manual = q("SELECT COUNT(*) FROM works WHERE access_status='manual_required' AND record_status='ingested'")
    pending_ingested = conn.execute(
        "SELECT COUNT(*) FROM works WHERE access_status='pending' AND record_status='ingested'"
    ).fetchone()[0]
    review_req = q("SELECT COUNT(*) FROM works WHERE human_review_required=1 AND record_status='ingested'")
    retracted = q("SELECT COUNT(*) FROM works WHERE retraction_status='retracted'")
    eoc = q("SELECT COUNT(*) FROM works WHERE expression_of_concern=1")

    dom_counts = conn.execute(
        "SELECT j.value AS d, COUNT(*) FROM works w, json_each(w.research_domains) j"
        " WHERE w.record_status='ingested' GROUP BY j.value ORDER BY 2 DESC").fetchall()
    decades = conn.execute(
        "SELECT (publication_year/10)*10 AS dec, COUNT(*) FROM works"
        " WHERE record_status='ingested' AND publication_year IS NOT NULL"
        " GROUP BY dec ORDER BY dec").fetchall()
    langs = conn.execute(
        "SELECT COALESCE(language,'unknown'), COUNT(*) FROM works WHERE record_status='ingested'"
        " GROUP BY 1 ORDER BY 2 DESC").fetchall()
    ev = conn.execute(
        "SELECT COALESCE(evidence_category,'(未分类)'), COUNT(*) FROM works"
        " WHERE record_status='ingested' GROUP BY 1 ORDER BY 2 DESC").fetchall()
    fails = conn.execute(
        "SELECT status, COUNT(*) FROM download_log WHERE status != 'downloaded'"
        " GROUP BY status ORDER BY 2 DESC").fetchall()
    api_stats = conn.execute(
        "SELECT source, COUNT(*), SUM(ok) FROM api_log GROUP BY source ORDER BY 2 DESC").fetchall()
    recent_runs = conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 5").fetchall()

    lines = [
        "# 采集执行报告（acquisition-report）",
        "",
        f"> 生成时间：{now}；项目：ChildEvidence；数据来源：`library.sqlite` 实时查询，无人工估算。",
        "",
        "## 总量与状态",
        "",
        f"- 数据库中文献记录总数（含候选/被拒）：{total}",
        f"- **正式入库（record_status=ingested）：{ingested}**",
        f"- 发现候选未入选：{candidates}",
        f"- 检索后按质量标准被拒：{rejected}",
        "",
        "## 元数据核验",
        "",
        f"- Crossref 交叉核验通过：{verified}",
        f"- 核验发现元数据冲突：{meta_conflict}",
        f"- 无 DOI 文献（机构报告等，按官方来源核验）：{no_doi}",
        f"- 需人工复核（标记 human_review_required）：{review_req}",
        f"- 撤稿记录：{retracted}；关注声明（expression of concern）：{eoc}",
        "",
        "## 全文获取",
        "",
        f"- **成功下载并通过校验的 PDF：{pdf_ok}**",
        f"- 有开放 HTML 全文但 PDF 待人工：{open_html}",
        f"- 官方 API 未列出任何开放 PDF 候选：{no_open_pdf}",
        f"- 需机构订阅人工获取：{manual}",
        f"- 尚未尝试获取：{pending_ingested}",
        "",
        "## 分领域覆盖（一篇可属多领域）",
        "",
        "| 领域 | 数量 |",
        "|---|---|",
    ]
    for r in dom_counts:
        lines.append(f"| {DOMAIN_LABELS_ZH.get(r[0], r[0])} | {r[1]} |")
    lines += ["", "## 年代分布", "", "| 年代 | 数量 |", "|---|---|"]
    for r in decades:
        lines.append(f"| {r[0]}s | {r[1]} |")
    lines += ["", "## 语言分布", "", "| 语言 | 数量 |", "|---|---|"]
    for r in langs:
        lines.append(f"| {r[0]} | {r[1]} |")
    lines += ["", "## 证据类别分布", "", "| 类别 | 数量 |", "|---|---|"]
    for r in ev:
        lines.append(f"| {EV_ZH.get(r[0], r[0])} | {r[1]} |")
    lines += ["", "## 下载日志汇总", "", "| 结果 | 次数 |", "|---|---|"]
    if fails:
        for r in fails:
            lines.append(f"| {r[0]} | {r[1]} |")
    else:
        lines.append("| （无下载记录） | 0 |")
    lines += ["", "## API 调用统计", "", "| 来源 | 调用次数 | 成功 |", "|---|---|---|"]
    for r in api_stats:
        lines.append(f"| {r[0]} | {r[1]} | {r[2]} |")
    lines += ["", "## 最近运行记录", "", "| id | 类型 | 开始 | 结束 | 说明 |", "|---|---|---|---|---|"]
    for r in recent_runs:
        lines.append(f"| {r['id']} | {r['kind']} | {r['started_at']} | {r['finished_at'] or '—'} | {(r['notes'] or '')[:120]} |")
    return _write(docs_dir, "acquisition-report.md", "\n".join(lines))


TAXONOMY_MD = """# 研究分类体系（research-taxonomy）

> ChildEvidence Research Library v0.1。分类字段存储于 `library.sqlite`，由采集与人工审核共同维护。

## 研究领域（research_domains）

| 代码 | 含义 | 说明 |
|---|---|---|
| child_development | 儿童发展心理学 | 皮亚杰/维果茨基/埃里克森/鲍尔比/布朗芬布伦纳/班杜拉、执行功能、社会性与情绪发展、神经多样性 |
| learning_sciences | 教育心理学与学习科学 | SDT、自我调节学习、元认知、成长型思维、认知负荷、提取/间隔/交错练习、阅读与数学困难、反馈与脚手架 |
| behavior_support | 儿童行为与心理支持 | 情绪共同调节、挫折耐受、学习焦虑与回避、亲子冲突、正向行为支持、睡眠与习惯、SEL、转介边界 |
| ai_children | AI 儿童陪伴与数字心理学 | 儿童与对话式 AI、拟人化与信任、依赖与信任校准、隐私与伦理、生成式 AI 有效性、评估方法（重点 2023–2026） |
| china_family | 中国儿童与家庭教育 | 中国小学生学习行为、作业与课业压力、亲子互动、教育焦虑、CFPS/CEPS 实证研究；中文资料独立收录 |
| cross_domain | 跨领域 | 综合报告、方法论资源 |

## 主题标签（topic_tags）

示例：`executive_function`、`working_memory`、`self_regulated_learning`、`metacognition`、
`growth_mindset`、`cognitive_load`、`retrieval_practice`、`spaced_practice`、`interleaving`、
`emotion_regulation`、`co_regulation`、`attachment`、`peer_relations`、`empathy`、
`scaffolding`、`feedback`、`formative_assessment`、`homework`、`academic_pressure`、
`test_anxiety`、`procrastination`、`sleep`、`sel`、`conversational_ai`、`trust_calibration`、
`child_ai_privacy`、`generative_ai`、`neurodiversity`、`math_difficulties`、`reading`。

## 理论框架（theoretical_frameworks）

`piaget_cognitive_development`、`vygotsky_sociocultural_zpd`、`erikson_psychosocial`、
`bowlby_attachment`、`bronfenbrenner_bioecological`、`bandura_social_learning_self_efficacy`、
`self_determination_theory`、`cognitive_load_theory`、`baddeley_working_memory`、
`gross_emotion_regulation`。

## 证据类别（evidence_category）

| 代码 | 含义 | 判定方式 |
|---|---|---|
| meta_analysis | Meta 分析 | 标题/类型明确标识；机器初判，待人工确认 |
| systematic_review | 系统综述 | 标题/类型明确标识；机器初判 |
| narrative_review | 叙述性综述 | OpenAlex type=review 且非系统综述 |
| rct | 随机对照试验 | 标题明确标识 randomized trial |
| longitudinal | 纵向研究 | 标题含 longitudinal；待人工确认 |
| other_empirical | 实证研究（设计待核） | 默认值；全文阅读后升级 |
| theoretical_conceptual | 理论/概念研究 | 专著、章节等 |
| practice_guideline | 循证实践指南 | EEF/WWC 等机构指南 |
| policy_report | 政策/机构报告 | NAP/OECD/UNICEF 等报告 |
| preprint_empirical | 预印本（未经同行评议） | 独立标记，不等同正式发表 |

## 证据分级原则

1. 区分**研究设计分类**（上表）、**方法质量评估**（人工，需读全文）与**人工审核结论**（review_status/reviewer_notes）。
2. 不以期刊影响因子或引用量作为证据等级；引用量仅用于发现排序。
3. 主动收录重要的负面结果、重复失败与争议证据（如成长型思维效应量争议）。
4. 经典理论区分历史地位与当代实证支持：每条理论框架保留原始文献 + 当代检验/综述。
5. 群体统计结论不得解释为个体诊断；本库只做证据编目，不生成个体干预规则。

## 文献筛选原则

- 优先同行评议、高质量系统综述/Meta 分析、方法严谨的实验与纵向研究。
- 经典研究不受年份限制；前沿研究重点覆盖近五年（尤其 2024–2026）。
- 预印本单独标记，不作为正式证据。
- 宁缺毋滥：不编造数据凑数；无法核实的关键字段置 NULL 并注明待读全文。
"""


def write_taxonomy(docs_dir: Path) -> Path:
    return _write(docs_dir, "research-taxonomy.md", TAXONOMY_MD)


def write_methodology(conn, docs_dir: Path, config) -> Path:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    topics = load_yaml(PROJECT_ROOT / "config" / "topics.yaml")
    query_lines = []
    for domain, block in (topics.get("domains") or {}).items():
        for q in block.get("queries") or []:
            spec = q.get("openalex") or q.get("eric") or q.get("europepmc") or {}
            desc = spec.get("search") or spec.get("query") or json.dumps(spec.get("filter") or {}, ensure_ascii=False)
            query_lines.append(f"- `{q.get('id')}`（{DOMAIN_LABELS_ZH.get(domain, domain)}）: {desc}")
    md = f"""# 采集方法与可重复执行说明（methodology）

> 生成日期：{now}。本文档说明 research-library 首批采集的数据来源、检索词、筛选规则、下载策略、
> 去重逻辑、版权处理与质量限制；所有步骤可由 CLI 重复执行并增量更新。

## 1. 数据来源与优先级

- **发现与开放全文定位**：OpenAlex（`api.openalex.org`，polite pool，mailto 标识）
- **DOI 与出版元数据核验**：Crossref（`api.crossref.org`）
- **领域补充检索**：ERIC（`api.ies.ed.gov/eric/`）、Europe PMC（`ebi.ac.uk/europepmc/webservices/rest`）
- **OA 定位补充**：Unpaywall（`api.unpaywall.org/v2/<doi>`，仅新版按 DOI 查询接口）
- **机构报告**：National Academies Press、EEF、WWC(IES)、OECD、UNICEF 官方页面
- **中文/中国研究**：经 OpenAlex/Crossref 检索中国主题的英文与中文文献；CNKI/万方无开放 API，
  只保留书目元数据并进入人工下载队列，不绕过任何访问控制。

## 2. 检索词与查询（topics.yaml，共 {len(query_lines)} 条）

{chr(10).join(query_lines)}

## 3. 筛选规则（discover.run_topics / promote_candidates）

- 排除：无标题/无作者/无年份、撤稿记录、editorial/letter/erratum/paratext、年份越界。
- 每条查询最多入库 {10} 条候选；按领域配额（topics.yaml `quota`）用打分器择优转正：
  Meta 分析 +3.5、系统综述 +3.0、RCT +2.2、2024+ 新近 +1.0、高被引 +1.5、
  开放获取 +0.6、期刊同行评议 +0.8、AI 领域 2024+ 额外 +1.5；预印本 -1.0。
- 未入选候选保留 `record_status='rejected'` 供审计。

## 4. 下载策略（acquisition.py）

1. 仅尝试官方 API 标注为开放获取的 URL：Europe PMC（PMCID 全文库）、OpenAlex OA location、
   Unpaywall `url_for_pdf`、Crossref 全文链接、ERIC 官方文件库、机构官方页面。
2. 下载校验：HTTP 200 → Content-Type 检查（拒绝 text/html）→ `%PDF-` 文件头 → 体积下限
   → `%%EOF` 尾标记 → 页数扫描（含对象流解压）→ SHA-256 → 跨文献重复内容检测。
3. 记录：最终 URL、来源、时间、版本（published/accepted/submitted，来自 API 元数据）、
   许可证（API 提供；未知记 `license_unknown`，不臆断可再分发）。
4. 失败重试：指数退避（2/5/10s），尊重 Retry-After；每次尝试写入 download_log。
5. 原始 PDF 仅保存在本地 `data/research-library/pdf/`，不提交公共仓库。

## 5. 去重逻辑（dedup.py）

- **DOI 精确匹配**（规范化小写）→ 合并进已有条目。
- 无 DOI：规范化标题全等 + 年份一致 + 第一作者姓氏一致 → 保守合并。
- 相似度 ≥0.93 且（≥0.98 或同第一作者姓氏）→ **不合并**，标记 `human_review_required`。
- 合并冲突（如年份不一致）写入 `conflicting_metadata` 并转人工复核。

## 6. 版权处理

- 开放获取 ≠ 可自由再分发：许可证逐条记录，未知记 `license_unknown`。
- 付费文献只保存书目信息与官方链接；PDF 一律人工经机构订阅获取。
- 不访问 Sci-Hub/LibGen 等侵权来源；不绕过付费墙、验证码或访问控制。

## 7. 质量限制与人工复核

- `metadata_status`：crossref_verified / no_doi_source_only / conflict / api_error。
- 研究方法、样本量、效应量等高级字段默认 NULL，需阅读全文后人工填写（review_status）。
- 撤稿状态来自 Crossref `update-to` 与 OpenAlex `is_retracted`；未查到撤稿不代表无其他争议。

## 8. 可重复执行

```bash
# 环境：Python 3.11+（无需第三方依赖）
export RESEARCH_LIBRARY_DATA_DIR=<数据目录>   # 可选，默认 <repo>/data/research-library
python -m research_library discover   # 种子+主题检索+引用扩展+择优入库
python -m research_library verify     # Crossref 核验 + OpenAlex 回填
python -m research_library acquire    # 合法开放 PDF 下载与校验
python -m research_library export     # CSV/JSONL/BibTeX
python -m research_library docs       # 重新生成 docs/research/*.md
python -m research_library status     # 当前建设状态
```

API 缓存（{config.cache_dir}）默认 7 天 TTL；删除缓存即可强制重新拉取。
数据库 WAL 模式，进程中断可安全重跑；所有命令幂等（跳过已完成条目）。
"""
    return _write(docs_dir, "methodology.md", md)


def write_all(conn, docs_dir: Path, config) -> dict:
    return {
        "literature-catalog.md": write_catalog(conn, docs_dir),
        "manual-download-queue.md": write_manual_queue(conn, docs_dir),
        "acquisition-report.md": write_acquisition_report(conn, docs_dir, config),
        "research-taxonomy.md": write_taxonomy(docs_dir),
        "methodology.md": write_methodology(conn, docs_dir, config),
    }
