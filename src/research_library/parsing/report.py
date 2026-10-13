"""Reproducible parse task reports (aggregate only — no document text).

Metrics discipline (issue #3, hard rules):

- "存在率" (field presence, e.g. bbox_presence_rate) and "定位准确率"
  (localization accuracy) are reported SEPARATELY. The parse layer only
  measures presence; accuracy stays null and is delegated to CE-04.
- Any parser-vs-parser comparison is labeled as a relative-between-parsers
  metric with its reference source; it is never "accuracy against the
  original text".
- Aggregates are computed from the versioned artifacts, so the same output
  directory always produces the same report (reproducibility).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


def scan_artifacts(output_root: Path) -> list[dict]:
    """Collect (result, run_meta, dir) across the versioned artifact store."""
    root = Path(output_root)
    out = []
    if not root.exists():
        return out
    for sha_dir in sorted(root.iterdir()):
        if not sha_dir.is_dir() or sha_dir.name.startswith("."):
            continue
        for art_dir in sorted(sha_dir.iterdir()):
            if not art_dir.is_dir() or art_dir.name.startswith("."):
                continue
            rp = art_dir / "result.json"
            mp = art_dir / "run-meta.json"
            if not rp.exists():
                continue
            try:
                result = json.loads(rp.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            meta = None
            if mp.exists():
                try:
                    meta = json.loads(mp.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    meta = None
            out.append({"result": result, "meta": meta, "dir": art_dir})
    return out


def build_report(output_root: Path, *, manifest_entries: list[dict] | None = None) -> dict:
    arts = scan_artifacts(output_root)
    # keep only the latest artifact per source sha (by produced_at)
    latest_by_sha: dict[str, dict] = {}
    for a in arts:
        sha = (a["result"].get("source") or {}).get("sha256")
        if not sha:
            continue
        prev = latest_by_sha.get(sha)
        if prev is None or _produced(a) >= _produced(prev):
            latest_by_sha[sha] = a

    declared = {}
    for e in (manifest_entries or []):
        sha = e.get("sha256")
        if sha:
            declared[sha] = e

    docs = []
    status_counts: dict[str, int] = {}
    parser_counts: dict[str, int] = {}
    issue_tally: dict[str, int] = {}
    lang_counts: dict[str, int] = {}
    category_counts: dict[str, int] = {}
    durations = []
    mems = []
    unlocatable_pages = 0
    paragraphs_total = 0
    paragraphs_unlocatable = 0
    tables_total = 0
    tables_with_bbox = 0
    bbox_rate_sum = 0.0
    docs_with_paras = 0

    for sha, a in sorted(latest_by_sha.items()):
        r = a["result"]
        status = r.get("status")
        status_counts[status] = status_counts.get(status, 0) + 1
        parser_name = (r.get("parser") or {}).get("name")
        parser_counts[parser_name] = parser_counts.get(parser_name, 0) + 1
        loc = r.get("localization_summary") or {}
        pt = loc.get("paragraphs_total") or 0
        pt_bbox = loc.get("paragraphs_with_bbox") or 0
        paragraphs_total += pt
        paragraphs_unlocatable += pt - pt_bbox
        tables_total += loc.get("tables_total") or 0
        tables_with_bbox += loc.get("tables_with_bbox") or 0
        if pt:
            docs_with_paras += 1
            bbox_rate_sum += loc.get("bbox_presence_rate") or 0.0
        pages_no_text = sum(
            1 for p in r.get("pages", []) if not p.get("text_present"))
        unlocatable_pages += pages_no_text
        for issue in r.get("issues", []):
            issue_tally[issue.get("code")] = issue_tally.get(issue.get("code"), 0) + 1
        lang = r.get("language")
        lang_counts[lang] = lang_counts.get(lang, 0) + 1
        decl = declared.get(sha) or {}
        cat = decl.get("category") or "undeclared"
        category_counts[cat] = category_counts.get(cat, 0) + 1
        d = (r.get("provenance") or {}).get("duration_sec")
        m = (r.get("provenance") or {}).get("peak_memory_mb")
        if d is not None:
            durations.append(d)
        if m is not None:
            mems.append(m)
        docs.append({
            "document_id": r.get("document_id"),
            "sha256_12": sha[:12],
            "status": status,
            "parser": parser_name,
            "page_count": r.get("page_count"),
            "language_detected": lang,
            "category_declared": decl.get("category"),
            "paragraphs_total": pt,
            "paragraphs_with_bbox": pt_bbox,
            "tables_total": loc.get("tables_total"),
            "tables_with_bbox": loc.get("tables_with_bbox"),
            "pages_without_text_layer": pages_no_text,
            "issue_codes": [i.get("code") for i in r.get("issues", [])],
            "duration_sec": d,
            "peak_memory_mb": m,
            "failure_reasons": [
                {"code": fr.get("code"), "parser": fr.get("parser")}
                for fr in (r.get("failure_reasons") or [])
            ],
            "artifact_dir": str(a["dir"]),
        })

    def _agg(values):
        if not values:
            return None
        return {
            "mean": round(sum(values) / len(values), 2),
            "min": round(min(values), 2),
            "max": round(max(values), 2),
            "total": round(sum(values), 2),
        }

    report = {
        "report_generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "output_root": str(output_root),
        "documents_in_artifact_store": len(latest_by_sha),
        "status_counts": status_counts,
        "parser_counts": parser_counts,
        "language_detected_counts": lang_counts,
        "category_declared_counts": category_counts,
        "issues": issue_tally,
        "localization": {
            "paragraphs_total": paragraphs_total,
            "paragraphs_with_bbox": paragraphs_total - paragraphs_unlocatable,
            "paragraphs_without_bbox": paragraphs_unlocatable,
            "tables_total": tables_total,
            "tables_with_bbox": tables_with_bbox,
            "pages_without_text_layer": unlocatable_pages,
            "bbox_presence_rate_aggregate": (
                round((paragraphs_total - paragraphs_unlocatable) / paragraphs_total, 6)
                if paragraphs_total else None
            ),
            "localization_accuracy": None,
            "metric_scope_note": (
                "存在率 (field presence) only. 定位准确率 (accuracy vs the true "
                "position in the original PDF) is NOT measured here; it requires "
                "the CE-04 independent human gold benchmark. The POC 12/12 AI "
                "spot-check is not human gold, and no >=95% production claim is "
                "made. Pages without a text layer and items without bbox are "
                "counted as not-localizable, not as wrong."
            ),
        },
        "runtime": {
            "duration_sec": _agg(durations),
            "peak_memory_mb": _agg(mems),
        },
        "documents": docs,
    }
    return report


def _produced(a: dict) -> str:
    return (a["result"].get("provenance") or {}).get("produced_at_utc") or ""


def render_markdown(report: dict) -> str:
    """Render the aggregate report as Markdown (no document text, IDs only)."""
    lines: list[str] = []
    lines.append("# 解析任务报告（聚合统计，不含文档文本）")
    lines.append("")
    lines.append(f"- 生成时间（UTC）: {report['report_generated_utc']}")
    lines.append(f"- 产物根目录: `{report['output_root']}`")
    lines.append(f"- 覆盖文档数（按源 SHA 去重，取最新产物）: {report['documents_in_artifact_store']}")
    lines.append("")
    lines.append("## 状态与解析器")
    lines.append("")
    lines.append("| 维度 | 值 | 数量 |")
    lines.append("|---|---|---:|")
    for k, v in sorted(report["status_counts"].items()):
        lines.append(f"| status | {k} | {v} |")
    for k, v in sorted((report["parser_counts"] or {}).items()):
        lines.append(f"| parser | {k} | {v} |")
    for k, v in sorted((report["language_detected_counts"] or {}).items()):
        lines.append(f"| language_detected | {k} | {v} |")
    for k, v in sorted((report["category_declared_counts"] or {}).items()):
        lines.append(f"| category_declared | {k} | {v} |")
    lines.append("")
    lines.append("## 定位字段存在率（非定位准确率）")
    lines.append("")
    loc = report["localization"]
    lines.append(f"- paragraphs_total: {loc['paragraphs_total']}")
    lines.append(f"- paragraphs_with_bbox: {loc['paragraphs_with_bbox']}")
    lines.append(f"- paragraphs_without_bbox（不可定位条目）: {loc['paragraphs_without_bbox']}")
    lines.append(f"- tables_total / tables_with_bbox: {loc['tables_total']} / {loc['tables_with_bbox']}")
    lines.append(f"- pages_without_text_layer: {loc['pages_without_text_layer']}")
    lines.append(f"- bbox_presence_rate (aggregate): {loc['bbox_presence_rate_aggregate']}")
    lines.append(f"- localization_accuracy: **{loc['localization_accuracy']}**（解析层不测量；"
                 "需 CE-04 独立人工 Gold；POC 12/12 AI 目检非人工 Gold；不声称生产级 ≥95%）")
    lines.append("")
    lines.append(f"> {loc['metric_scope_note']}")
    lines.append("")
    lines.append("## 质量标记（issue codes）")
    lines.append("")
    if report["issues"]:
        lines.append("| issue code | 文档数 |")
        lines.append("|---|---:|")
        for k, v in sorted(report["issues"].items()):
            lines.append(f"| {k} | {v} |")
    else:
        lines.append("（无）")
    lines.append("")
    lines.append("## 运行开销")
    lines.append("")
    rt = report["runtime"]
    for key in ("duration_sec", "peak_memory_mb"):
        agg = rt.get(key)
        lines.append(f"- {key}: " + (json.dumps(agg) if agg else "n/a"))
    lines.append("")
    lines.append("## 逐文档（仅 ID/状态/计数，不含文本）")
    lines.append("")
    lines.append("| document_id | sha12 | status | parser | pages | paras(bbox) | tables(bbox) | issues | duration_s |")
    lines.append("|---|---|---|---|---:|---|---|---|---:|")
    for d in report["documents"]:
        lines.append(
            f"| {d['document_id']} | {d['sha256_12']} | {d['status']} | {d['parser']} "
            f"| {d['page_count']} | {d['paragraphs_total']}({d['paragraphs_with_bbox']}) "
            f"| {d['tables_total']}({d['tables_with_bbox']}) "
            f"| {','.join(d['issue_codes']) or '-'} | {d['duration_sec']} |")
    lines.append("")
    lines.append("## 参照来源声明")
    lines.append("")
    lines.append("- 本报告全部指标由版本化解析产物计算，可重复生成。")
    lines.append("- 本报告不包含任何解析器间相对覆盖率指标；如需对比 pypdf/pdfplumber "
                 "参照口径，必须显式标注\"解析器间相对指标（参照：xxx），非原文正确率\""
                 "（POC 归档报告 §v1.1 解读边界）。")
    lines.append("- 35 份原始 PDF 与 library.sqlite 在本流程中不被修改（解析为只读输入）。")
    return "\n".join(lines) + "\n"
