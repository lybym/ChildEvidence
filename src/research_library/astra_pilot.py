"""CE-06 Astra Research Reviewer Pilot runner (Issue #10).

Deterministic local orchestration for the first-paper pilot:
condition prechecks (permission / version / scope / environment / model
identity / input availability), protected-asset hash snapshots, staged
minimal packages via :mod:`research_library.model_access`, candidate review
validation via :mod:`research_library.review_contract`, and the Issue-mandated
artifact set under ``data/review/astra-pilot/<run_id>/``.

No network, no model call, no database writes, no policy activation. The
actual model identity is recorded only when the caller supplies both an id
and a verifiable evidence pointer; otherwise it stays ``unknown`` and the
attempt records BLOCKED — never a synthetic research PASS. Blocked, ready,
completed and failed are all honest outcomes of a recorded attempt.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

from . import model_access
from . import review_contract as contract
from .config import PROJECT_ROOT, default_data_dir

ISSUE_URL = "https://github.com/lybym/ChildEvidence/issues/10"
AUDIT_SCHEMA = "astra-pilot-audit/1"
SCREENING_SCHEMA = "astra-pilot-screening/1"
WORK_FIELDS = ("internal_id", "doi", "title", "language", "publication_year", "metadata_status",
               "license", "pdf_version", "local_pdf_path", "sha256", "access_status")
# Issue #10 artifact contract: data/review/astra-pilot/<run_id>/
ARTIFACTS = ("review.json", "review.md", "provenance.json", "validation.json",
             "screening.json", "evidence-card.md", "appraisal.md", "uncertainty.md", "audit.json")
BLOCKED = "blocked"
READY = "ready_for_reviewer_session"
COMPLETED = "completed"
FAILED = "failed"
FAIL_CODES = {
    "citation": "hallucinated_or_unverifiable_citation",
    "policy": "unauthorized_content_use",
    "identity": "model_identity_inconsistency",
    "scope": "scope_binding_violation",
    "provenance": "provenance_violation",
    "review": "review_contract_violation",
    "source": "provenance_violation",
    "package": "package_binding_violation",
    "passes": "passes_contract_violation",
    "finding": "unsupported_fact",
    "assessment": "assessment_contract_violation",
}
APPRAISAL_DIMENSIONS = ("样本", "干预", "对照", "测量", "偏倚", "年龄适用性", "家庭情境",
                        "学习行为", "情绪调节", "相关与因果区分", "证据充分性")


class PilotError(ValueError):
    pass


def now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def output_root():
    data = default_data_dir()
    return data.parent / "review/astra-pilot" if data.name == "research-library" else data / "review/astra-pilot"


def load_work(library_db, work_id):
    """Read-only whitelisted metadata for one Work; never the abstract."""
    uri = Path(library_db).resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as conn:
        conn.execute("PRAGMA query_only=ON")
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT " + ",".join(WORK_FIELDS) + " FROM works WHERE internal_id=?",
                           (work_id,)).fetchone()
    return dict(row) if row else None


def latest_registration(work_id, pdf_sha256, directory):
    """Latest registry decision for (work, pdf sha) or None; read-only."""
    path = Path(directory) / "permissions.json"
    if not path.exists():
        return None
    records = model_access.read(path)
    if not isinstance(records, list):
        raise ValueError("invalid registry")
    for record in records:
        model_access.check_record(record)
    matches = [r for r in records if r["work_id"] == work_id and r["pdf_sha256"] == pdf_sha256]
    return matches[-1] if matches else None


def precheck(work_id, *, mode="appraise", scope="article_text", environment=None,
             requested_model_id=None, model_id=None, model_identity_evidence=None,
             pdf=None, source=None, ranges=None, library_db=None, access_directory=None):
    """Read-only condition confirmation; returns (conditions, work)."""
    library_db = Path(library_db) if library_db else default_data_dir() / "library.sqlite"
    access_directory = Path(access_directory) if access_directory else model_access.root()
    conditions = []

    def add(cid, ok, detail):
        conditions.append({"id": cid, "status": "pass" if ok else "missing", "detail": detail})

    work = None
    if not Path(library_db).exists():
        add("work_in_library", False, "library database not found")
    else:
        try:
            work = load_work(library_db, work_id)
            add("work_in_library", work is not None,
                "metadata_status=" + str(work["metadata_status"]) if work else "work not found in library")
        except sqlite3.Error as error:
            add("work_in_library", False, "library unreadable: " + str(error))

    pdf_path = Path(pdf) if pdf else (Path(work["local_pdf_path"]) if work and work.get("local_pdf_path") else None)
    pdf_digest = None
    if pdf_path is None:
        add("original_available", False, "no original PDF path (library record has none, none supplied)")
    elif not pdf_path.exists():
        add("original_available", False, "original PDF missing")
    else:
        pdf_digest = model_access.sha(pdf_path)
        add("original_available", True, "sha256=" + pdf_digest)
    if work is None or pdf_digest is None:
        add("original_version_matches_library", False, "cannot compare without pdf and library record")
    elif not work.get("sha256"):
        add("original_version_matches_library", False, "library record has no sha256")
    else:
        add("original_version_matches_library", pdf_digest == work["sha256"],
            "pdf sha256 vs library recorded sha256")

    record, registry_error = None, None
    if pdf_digest:
        try:
            record = latest_registration(work_id, pdf_digest, access_directory)
        except (OSError, ValueError, TypeError) as error:
            registry_error = str(error)
    if not pdf_digest:
        add("permission_registered", False, "cannot look up registration without the original PDF hash")
    elif registry_error:
        add("permission_registered", False, "registry unreadable: " + registry_error)
    elif record is None:
        add("permission_registered", False, "no registration recorded for this work/pdf sha")
    else:
        ok = record["decision"] == "allowed" and record["policy_version"] == model_access.POLICY_VERSION
        add("permission_registered", ok,
            "latest decision=" + record["decision"] + "; policy=" + record["policy_version"])

    add("mode_supported", mode in model_access.MODES, "mode=" + str(mode))
    add("policy_active", bool(model_access.POLICY_ACTIVE), "CE-POL-01 egress gate read at precheck time")

    env_ok = isinstance(environment, str) and bool(environment.strip())
    detail = "service/environment pointer supplied" if env_ok else "no confirmed service/environment pointer"
    if env_ok and record is not None and not registry_error and record["codex_environment"] != environment:
        env_ok, detail = False, "environment does not match the registered decision"
    add("environment_confirmed", env_ok, detail)

    if record is None:
        add("scope_registered", False, "no registration to bind scope")
    else:
        add("scope_registered", scope in record["scope"], "registered scopes=" + ",".join(record["scope"]))

    add("model_request_recorded", isinstance(requested_model_id, str) and bool(requested_model_id.strip()),
        "requested target model recorded verbatim" if requested_model_id else "no requested model recorded")
    verified_identity = (isinstance(model_id, str) and bool(model_id.strip())
                         and isinstance(model_identity_evidence, str) and bool(model_identity_evidence.strip()))
    add("model_identity_verifiable", verified_identity,
        "verified with runtime evidence pointer" if verified_identity
        else "unverifiable; recorded as unknown and never claimed")

    source_path = Path(source) if source else None
    source_ok = bool(source_path and source_path.exists() and source_path.suffix == ".txt")
    add("derivative_text_available", source_ok,
        "locally verified UTF-8 .txt derivative" if source_ok else "no .txt derivative supplied")

    spans_valid = isinstance(ranges, list) and bool(ranges) and all(
        isinstance(s, list) and len(s) == 2 and all(type(n) is int for n in s) and 0 <= s[0] < s[1]
        for s in ranges)
    add("selection_ranges_available", spans_valid,
        "non-empty integer character ranges" if spans_valid else "no valid selection ranges supplied")

    if source_ok and pdf_digest and record is not None:
        try:
            source_digest = model_access.sha(source_path)
            binding = next((s for s in record["sources"]
                            if s["sha256"] == source_digest and s["scope"] == scope), None)
            add("derivative_registered", binding is not None,
                "derivative sha/scope binding present in registration")
        except OSError as error:
            add("derivative_registered", False, "derivative unreadable: " + str(error))
    else:
        add("derivative_registered", False, "needs derivative text, pdf hash and registration")
    return conditions, work


def missing_reasons(conditions):
    return [c["id"] for c in conditions if c["status"] != "pass"]


def protected_assets(*, pdf_path=None, library_db=None, access_directory=None, out_root=None):
    """Hash every asset the pilot must not modify (Issue #10 验收 #4)."""
    library_db = Path(library_db) if library_db else default_data_dir() / "library.sqlite"
    access_directory = Path(access_directory) if access_directory else model_access.root()
    out_root = Path(out_root) if out_root else output_root()
    paths = [library_db, library_db.parent.parent / "review/annotations.sqlite"]
    if pdf_path:
        paths.append(Path(pdf_path))
    if (access_directory / "permissions.json").exists():
        paths.append(access_directory / "permissions.json")
    if access_directory.exists():
        paths += sorted(p for p in access_directory.rglob("audit/*") if p.is_file())
    if out_root.exists():
        paths += sorted(p for p in out_root.rglob("*") if p.is_file())
    paths += sorted(p for p in (PROJECT_ROOT / "exports").glob("*") if p.is_file())
    return {str(p): model_access.sha(p) for p in paths if p.exists()}


def verify_protected(before):
    return [path for path, digest in before.items()
            if not Path(path).exists() or model_access.sha(path) != digest]


def _require_safe_output_root(out_root, data_dir, access_directory):
    resolved = Path(out_root).resolve()
    for forbidden in (Path(data_dir).resolve(), Path(access_directory).resolve()):
        if resolved == forbidden or resolved.is_relative_to(forbidden):
            raise PilotError("output root must stay outside the library data and model-access directories")


def _write_json(path, payload):
    with Path(path).open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def _write_text(path, text):
    with Path(path).open("x", encoding="utf-8") as stream:
        stream.write(text)


def _artifact_hashes(directory):
    return {name: contract.file_hash(Path(directory) / name)
            for name in ARTIFACTS if (Path(directory) / name).exists()}


def _base_audit(run_id, *, work_id, mode, scope, environment, requested_model_id, model_id,
                model_identity_evidence, conditions, policy_active, work):
    verified = (isinstance(model_id, str) and bool(model_id.strip())
                and isinstance(model_identity_evidence, str) and bool(model_identity_evidence.strip()))
    return {
        "schema": AUDIT_SCHEMA,
        "run_id": run_id,
        "issue_url": ISSUE_URL,
        "created_at": now_utc(),
        "work_id": work_id,
        "mode": mode,
        "scope": scope,
        "requested_model_id": requested_model_id,
        "actual_model_id": model_id if isinstance(model_id, str) and model_id.strip() else None,
        "model_identity_evidence": model_identity_evidence if verified else None,
        "actual_identity_status": "verified" if verified else "unknown",
        "model_review_performed": False,
        "policy_version": model_access.POLICY_VERSION,
        "policy_active_at_precheck": bool(policy_active),
        "environment": environment,
        "library_metadata": ({key: work.get(key) for key in
                              ("internal_id", "doi", "title", "language", "publication_year",
                               "metadata_status", "license", "pdf_version")} if work else None),
        "conditions": conditions,
        "verdict": None,
        "blocked_reasons": [],
        "fail_codes": [],
        "package": None,
        "protected_modified": [],
        "notes": ("deterministic local orchestration only; no model call, no network, no database "
                  "writes; BLOCKED is an honest recorded outcome, never a tool failure or a research PASS"),
    }


def _blocked_uncertainties(audit):
    return ["evidence_insufficient", "original_unavailable"] + list(audit["blocked_reasons"])


def screening_payload(audit, review):
    relevance = review["assessments"]["relevance"] if review and review["mode"] == "screen" else None
    return {
        "schema": SCREENING_SCHEMA,
        "run_id": audit["run_id"],
        "issue_url": ISSUE_URL,
        "work_id": audit["work_id"],
        "mode": audit["mode"],
        "verdict": audit["verdict"],
        "screening_decision": relevance,
        "note": ("screening decision from the validated review envelope (AI draft)"
                 if relevance is not None else
                 ("screening not performed: pilot " + audit["verdict"])),
        "ai_source": True,
        "label_tier": "silver",
        "maturity_level": "L0",
        "human_review_status": "not_reviewed",
        "allowed_for_agent_release": False,
    }


def evidence_card_md(audit, review):
    meta = audit.get("library_metadata") or {}
    lines = ["# Evidence Card（silver 草稿载体 — 非证据结论）", "",
             "- run_id: " + audit["run_id"],
             "- issue: " + ISSUE_URL,
             "- work_id: " + audit["work_id"],
             "- verdict: " + audit["verdict"],
             "- label_tier: silver · maturity_level: L0 · human_review_status: not_reviewed · "
             "allowed_for_agent_release: false", "",
             "## 元数据标识（本地库只读元数据，未发送给模型）", ""]
    if meta:
        lines.append("- DOI: %s；标题: %s；metadata_status: %s"
                     % (meta.get("doi") or "unknown", meta.get("title") or "unknown",
                        meta.get("metadata_status") or "unknown"))
    else:
        lines.append("- unknown（库记录不可用）")
    lines += ["", "## 适用边界", ""]
    if review:
        lines.append("- " + (review.get("summary") or "unknown"))
        appraisal = (review.get("assessments") or {}).get("appraisal")
        lines.append("- appraisal（AI 草稿，silver/L0，未人工复核）: " + (appraisal or "null"))
    else:
        lines.append("- 未开展（blocked）：无任何适用范围结论。")
    lines += ["", "## 偏倚与局限", ""]
    if review:
        findings = review.get("findings") or []
        lines += [f"- {finding['field']}: {finding['value'] if finding['value'] is not None else 'unknown'}"
                  for finding in findings]
        if not findings:
            lines.append("- unknown（envelope 无 findings）")
    else:
        lines.append("- 未开展（blocked）：未读取原文，无偏倚或方法学结论；不虚构样本、效应、DOI、页码。")
    lines += ["", "## 不确定性", ""]
    for code in (review.get("uncertainties") if review else None) or _blocked_uncertainties(audit):
        lines.append("- " + code)
    lines += ["", "## 未决问题", ""]
    if audit["verdict"] == BLOCKED:
        for reason in audit["blocked_reasons"]:
            lines.append("- " + reason)
    lines += ["- 人工复核未完成（not_reviewed）；本卡片不得进入任何知识包或 Agent 行为。",
              "- 结构与本地文本匹配不等于原文真核验；GS-D3（Astra 限定）等治理决定未落，本卡片不预设结论。"]
    return "\n".join(lines) + "\n"


def appraisal_md(audit, review):
    lines = ["# Appraisal（方法学评价草稿载体 — silver/L0）", "",
             "- run_id: " + audit["run_id"],
             "- issue: " + ISSUE_URL,
             "- verdict: " + audit["verdict"], ""]
    if review:
        appraisal = (review.get("assessments") or {}).get("appraisal")
        lines += ["评价内容为已通过契约校验的 review envelope 原文，本工具不生成评价结论：",
                  "- appraisal: " + (appraisal or "null")]
    else:
        lines.append("各维度均未开展（blocked），一律保持 null，不虚构任何评价：")
        lines += [f"- {dimension}: null（未开展）" for dimension in APPRAISAL_DIMENSIONS]
    lines += ["", "AI 草稿始终 silver/L0、not_reviewed；AI 复核与人工复核分别留痕，"
              "不得用 AI 一致性冒充人工完成。"]
    return "\n".join(lines) + "\n"


def uncertainty_md(audit, review):
    codes = (review.get("uncertainties") if review else None) or _blocked_uncertainties(audit)
    lines = ["# Uncertainty Register（未决状态登记 — unknown 保持 unknown）", "",
             "- run_id: " + audit["run_id"],
             "- verdict: " + audit["verdict"], "",
             "| code | 状态 |", "|---|---|"]
    for code in codes:
        lines.append("| " + code + " | unresolved |")
    if audit["actual_identity_status"] != "verified":
        lines.append("| model_identity_unknown | unresolved（实际模型身份无可核验依据，记录为 unknown） |")
    lines += ["", "全部条目保持 unresolved；不得以任何自动结论关闭。"]
    return "\n".join(lines) + "\n"


def _error_codes(errors):
    codes = []
    for error in errors:
        for prefix, code in FAIL_CODES.items():
            if error.startswith(prefix + ":"):
                codes.append(code)
                break
        else:
            codes.append("review_contract_violation")
    return codes


def _finish(audit, before, *, target=None, marker=None, library_db=None, out_root=None):
    """Verify protected assets, finalize the verdict, persist the audit."""
    audit["protected_before"] = dict(before)
    changed = verify_protected(before)
    audit["protected_modified"] = changed
    audit["protected_after"] = {path: model_access.sha(path) for path in before if Path(path).exists()}
    audit["protected_inputs_unchanged"] = not changed
    if changed:
        audit["verdict"] = FAILED
        audit["fail_codes"] = sorted(set(audit.get("fail_codes", []) + ["protected_asset_modified"]))
    if target is not None and audit["verdict"] == BLOCKED:
        target = Path(target)
        envelope = {"written": False, "note": "library record unavailable; envelope not written"}
        if audit["library_metadata"] and Path(library_db).exists():
            try:
                source = contract.preflight(library_db, "sqlite_metadata", selector=audit["work_id"],
                                            license_id=audit["library_metadata"].get("license") or "license_unknown",
                                            access_basis="public_metadata")
                review, prov = contract.make_demo(audit["mode"], [source], run_id=audit["run_id"])
                contract.finalize(review, prov, output_root=Path(out_root))
                envelope = {"written": True,
                            "note": "deterministic demo envelope (no model call, no content sent)"}
            except (OSError, ValueError, TypeError, KeyError, sqlite3.Error) as error:
                envelope = {"written": False, "note": "envelope not written: " + str(error)}
        audit["review_envelope"] = envelope
        if not (target / "review.json").exists():
            target.mkdir(parents=True, exist_ok=True)
        _write_json(target / "screening.json", screening_payload(audit, None))
        _write_text(target / "evidence-card.md", evidence_card_md(audit, None))
        _write_text(target / "appraisal.md", appraisal_md(audit, None))
        _write_text(target / "uncertainty.md", uncertainty_md(audit, None))
        audit["artifacts"] = _artifact_hashes(target)
        _write_json(target / "audit.json", audit)
    elif target is not None:
        audit["artifacts"] = _artifact_hashes(target)
        _write_json(Path(target) / "audit.json", audit)
    if marker is not None:
        _write_json(marker, audit)
    return audit


def run_attempt(work_id, *, mode="appraise", scope="article_text", environment=None,
                requested_model_id=None, model_id=None, model_identity_evidence=None,
                pdf=None, source=None, ranges=None, library_db=None, access_directory=None,
                out_root=None):
    """One pilot attempt: precheck, then blocked artifacts or package staging.

    All-or-nothing condition gate: any missing condition records BLOCKED with
    the full reason list (the acceptance path demanded by Issue #10), and the
    deterministic demo envelope keeps the record honest without any model call.
    """
    library_db = Path(library_db) if library_db else default_data_dir() / "library.sqlite"
    data_dir = library_db.parent
    access_directory = Path(access_directory) if access_directory else model_access.root()
    out_root = Path(out_root) if out_root else output_root()
    _require_safe_output_root(out_root, data_dir, access_directory)
    conditions, work = precheck(work_id, mode=mode, scope=scope, environment=environment,
                                requested_model_id=requested_model_id, model_id=model_id,
                                model_identity_evidence=model_identity_evidence, pdf=pdf,
                                source=source, ranges=ranges, library_db=library_db,
                                access_directory=access_directory)
    pdf_path = Path(pdf) if pdf else (Path(work["local_pdf_path"]) if work and work.get("local_pdf_path") else None)
    run_id = "ce06-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    before = protected_assets(pdf_path=pdf_path, library_db=library_db,
                              access_directory=access_directory, out_root=out_root)
    audit = _base_audit(run_id, work_id=work_id, mode=mode, scope=scope, environment=environment,
                        requested_model_id=requested_model_id, model_id=model_id,
                        model_identity_evidence=model_identity_evidence, conditions=conditions,
                        policy_active=model_access.POLICY_ACTIVE, work=work)
    reasons = missing_reasons(conditions)
    if reasons:
        audit["verdict"] = BLOCKED
        audit["blocked_reasons"] = reasons
        return _finish(audit, before, target=out_root / run_id, library_db=library_db, out_root=out_root)
    prepare_result = model_access.prepare(work_id, pdf_path, Path(source), scope, ranges, mode,
                                          environment, model_id=model_id,
                                          requested_model_id=requested_model_id,
                                          directory=access_directory)
    if prepare_result["decision"] != "allowed":
        audit["verdict"] = BLOCKED
        audit["blocked_reasons"] = ["package_preparation_blocked: " + prepare_result["reason"]]
        out_root.mkdir(parents=True, exist_ok=True)
        return _finish(audit, before, marker=out_root / (run_id + ".blocked.json"))
    binding = model_access.verify_package(prepare_result["package_path"])
    audit["package"] = {"run_id": prepare_result["run_id"], "path": prepare_result["package_path"],
                        "output_sha256": prepare_result["output_sha256"], "binding_verified": True,
                        "model_id": binding["model_id"], "requested_model_id": binding["requested_model_id"]}
    audit["verdict"] = READY
    audit["next_step"] = ("run the child-evidence-reviewer session on the package only, then "
                          "`complete --run-id <run_id> --review <candidate.json> --provenance <candidate.json>`")
    out_root.mkdir(parents=True, exist_ok=True)
    return _finish(audit, before, marker=out_root / (run_id + ".ready.json"))


def complete(run_id, review_path, provenance_path, *, library_db=None, access_directory=None,
             out_root=None):
    """Validate a reviewer-session candidate and finalize the run artifacts."""
    library_db = Path(library_db) if library_db else default_data_dir() / "library.sqlite"
    access_directory = Path(access_directory) if access_directory else model_access.root()
    out_root = Path(out_root) if out_root else output_root()
    _require_safe_output_root(out_root, library_db.parent, access_directory)
    marker = out_root / (run_id + ".ready.json")
    if not marker.exists():
        raise PilotError("no ready marker for run " + run_id)
    ready = model_access.read(marker)
    if ready.get("verdict") != READY:
        raise PilotError("run " + run_id + " is not awaiting a reviewer session")
    before = dict(ready.get("protected_before", {}))
    review = contract.read_json(review_path)
    provenance = contract.read_json(provenance_path)
    audit = dict(ready)
    audit["created_at"] = now_utc()
    audit.pop("next_step", None)
    fail_codes = []
    expected = {"label_tier": "silver", "maturity_level": "L0", "human_review_status": "not_reviewed"}
    for field, value in expected.items():
        if review.get(field) != value:
            fail_codes.append("gold_upgrade_attempted")
    if review.get("allowed_for_agent_release") is not False:
        fail_codes.append("gold_upgrade_attempted")
    if review.get("run_id") != run_id or provenance.get("run_id") != run_id:
        fail_codes.append("run_id_mismatch")
    errors = [] if fail_codes else contract.validate(review, provenance)
    if fail_codes or errors:
        audit["verdict"] = FAILED
        audit["fail_codes"] = sorted(set(fail_codes + _error_codes(errors)))
        audit["validation"] = {"validator_version": contract.VERSION, "errors": errors}
        out_root.mkdir(parents=True, exist_ok=True)
        return _finish(audit, before, marker=out_root / (run_id + ".failed.json"))
    changed = verify_protected(before)
    if changed:
        audit["verdict"] = FAILED
        audit["fail_codes"] = ["protected_asset_modified"]
        audit["protected_modified"] = changed
        out_root.mkdir(parents=True, exist_ok=True)
        return _finish(audit, before, marker=out_root / (run_id + ".failed.json"))
    target = contract.finalize(review, provenance, output_root=out_root)
    audit["verdict"] = COMPLETED
    audit["model_review_performed"] = bool(review.get("model_review_performed"))
    audit["review_envelope"] = {"written": True,
                                "note": "validated candidate finalized via research_library.review_contract"}
    audit["validation"] = {"validator_version": contract.VERSION, "errors": []}
    _write_json(target / "screening.json", screening_payload(audit, review))
    _write_text(target / "evidence-card.md", evidence_card_md(audit, review))
    _write_text(target / "appraisal.md", appraisal_md(audit, review))
    _write_text(target / "uncertainty.md", uncertainty_md(audit, review))
    return _finish(audit, before, target=target)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument("--work-id", required=True)
    shared.add_argument("--mode", default="appraise", choices=sorted(model_access.MODES))
    shared.add_argument("--scope", default="article_text", choices=sorted(model_access.SCOPES))
    shared.add_argument("--environment")
    shared.add_argument("--requested-model-id")
    shared.add_argument("--model-id")
    shared.add_argument("--model-identity-evidence")
    shared.add_argument("--pdf")
    shared.add_argument("--source")
    shared.add_argument("--ranges", help="JSON file with [[start, end], ...] character ranges")
    shared.add_argument("--library-db")
    shared.add_argument("--access-dir")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("precheck", parents=[shared],
                   help="read-only condition check; exit 0 iff every condition passes")
    run_parser = sub.add_parser("run", parents=[shared],
                                help="attempt the pilot; exit 0 when the attempt is recorded (blocked/ready)")
    run_parser.add_argument("--out-root")
    complete_parser = sub.add_parser("complete", help="validate a candidate and finalize the run")
    complete_parser.add_argument("--run-id", required=True)
    complete_parser.add_argument("--review", required=True)
    complete_parser.add_argument("--provenance", required=True)
    complete_parser.add_argument("--out-root")
    complete_parser.add_argument("--library-db")
    complete_parser.add_argument("--access-dir")
    args = parser.parse_args(argv)
    ranges = model_access.read(args.ranges) if getattr(args, "ranges", None) else None
    try:
        if args.command == "precheck":
            conditions, _work = precheck(args.work_id, mode=args.mode, scope=args.scope,
                                         environment=args.environment,
                                         requested_model_id=args.requested_model_id,
                                         model_id=args.model_id,
                                         model_identity_evidence=args.model_identity_evidence,
                                         pdf=args.pdf, source=args.source, ranges=ranges,
                                         library_db=args.library_db, access_directory=args.access_dir)
            payload = {"issue_url": ISSUE_URL, "work_id": args.work_id,
                       "conditions": conditions, "missing": missing_reasons(conditions)}
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0 if not payload["missing"] else 2
        if args.command == "run":
            audit = run_attempt(args.work_id, mode=args.mode, scope=args.scope,
                                environment=args.environment, requested_model_id=args.requested_model_id,
                                model_id=args.model_id, model_identity_evidence=args.model_identity_evidence,
                                pdf=args.pdf, source=args.source, ranges=ranges,
                                library_db=args.library_db, access_directory=args.access_dir,
                                out_root=args.out_root)
            print(json.dumps(audit, ensure_ascii=False, indent=2))
            return 2 if audit["verdict"] == FAILED else 0
        audit = complete(args.run_id, args.review, args.provenance, library_db=args.library_db,
                         access_directory=args.access_dir, out_root=args.out_root)
        print(json.dumps(audit, ensure_ascii=False, indent=2))
        return 2 if audit["verdict"] == FAILED else 0
    except (PilotError, OSError, ValueError, TypeError, KeyError) as error:
        print(json.dumps({"decision": "invalid_local_input", "error": str(error)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
