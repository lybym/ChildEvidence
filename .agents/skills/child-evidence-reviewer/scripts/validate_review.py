#!/usr/bin/env python3
"""Local deterministic checks only. No model, network, parser or database writes.

preflight emits policy/hashes, never source text. finalize creates a fresh run.
Schema validation and quote matching do not establish scientific correctness.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
from datetime import datetime, timezone
from uuid import uuid4

SKILL_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = SKILL_ROOT.parents[2]
VERSION = "0.1.0"
PROTOCOLS = ("AGENTS.md", "RESEARCH_METHODOLOGY.md", "SCREENING_PROTOCOL.md",
             "ANNOTATION_GUIDE.md", "KNOWLEDGE_GOVERNANCE.md")
KINDS = ("sqlite_metadata", "blinded_metadata", "pdf", "docling", "text",
         "rq", "review", "evidence_card")
META_FIELDS = ("internal_id", "doi", "title", "language", "publication_year", "metadata_status", "license")
BLIND_FIELDS = ("queue_id", "sample_id", "doi", "title", "language", "publication_year", "review_task")
LEAK_FIELDS = ("historical_label", "stratum", "model_score", "asreview_score", "asreview_rank",
               "model_rank", "rank", "score", "relevance_order", "gold_label", "reviewer",
               "decision", "reason_code", "reason_text")
SOURCE_KEYS = {"source_id", "kind", "path", "selector", "sha256", "selection_hash",
               "content_class", "license", "access_basis", "model_access_allowed", "policy_reason"}
PROVENANCE_KEYS = {"schema_version", "run_id", "sources", "protocol_files", "skill_files",
                   "scope", "input_hash", "model_identity_evidence", "model_content_source_ids"}
REASONS = {"relevant": {"A01", "A02", "A03"}, "boundary": {"B01", "B02", "B03"},
           "not_relevant": {"R01", "R02", "R03", "R04", "R05", "R06"},
           "undecided": {"P01", "U01"}, "not_assessed": {"P01", "U01"}}
FORCE_UNRESOLVED = {"evidence_insufficient", "original_unavailable", "methodology_unknown",
                    "substantive_disagreement", "important_counterevidence", "child_safety",
                    "serious_bias", "citation_unverified", "rq_not_approved"}


class ReviewValidationError(ValueError):
    pass


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_json(path):
    def no_duplicates(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ReviewValidationError("duplicate JSON key")
            result[key] = value
        return result
    return json.loads(Path(path).read_text(encoding="utf-8-sig"), object_pairs_hook=no_duplicates,
                      parse_constant=lambda _: (_ for _ in ()).throw(ReviewValidationError("nonfinite JSON")))


def schema_errors(value, schema, path="$", root=None):
    """Implement every assertion keyword used by our standalone JSON Schema."""
    root = root or schema
    errors = []
    if "anyOf" in schema:
        if not any(not schema_errors(value, sub, path, root) for sub in schema["anyOf"]):
            errors.append(path + ": no anyOf branch matches")
        return errors
    expected = schema.get("type")
    types = [expected] if isinstance(expected, str) else expected
    matches = {"object": isinstance(value, dict), "array": isinstance(value, list),
               "string": isinstance(value, str), "integer": type(value) is int,
               "boolean": type(value) is bool, "null": value is None}
    if types and not any(matches.get(t, False) for t in types):
        return [path + ": incorrect type"]
    if "const" in schema and (value != schema["const"] or type(value) is not type(schema["const"])):
        errors.append(path + ": wrong const")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(path + ": invalid enum")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            errors.append(path + ": too short")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errors.append(path + ": invalid pattern")
    if type(value) is int and value < schema.get("minimum", value):
        errors.append(path + ": below minimum")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            errors.append(path + ": too few items")
        for index, item in enumerate(value):
            errors += schema_errors(item, schema.get("items", {}), f"{path}[{index}]", root)
    if isinstance(value, dict):
        props = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                errors.append(path + ": missing " + key)
        if schema.get("additionalProperties") is False and set(value) - set(props):
            errors.append(path + ": unknown properties")
        for key in set(value) & set(props):
            errors += schema_errors(value[key], props[key], path + "." + key, root)
    return errors


def selected_metadata(path, kind, selector):
    """Only selected rows and whitelisted metadata; never abstract/history/ranking."""
    if not selector:
        raise ReviewValidationError("explicit selector required")
    if kind == "sqlite_metadata":
        uri = Path(path).resolve().as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True)) as conn:
            conn.execute("PRAGMA query_only=ON")
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT " + ",".join(META_FIELDS) + " FROM works WHERE internal_id=?",
                               (selector,)).fetchone()
            if row is None:
                raise ReviewValidationError("selected work not found")
            return dict(row)
    if kind == "blinded_metadata":
        with Path(path).open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if not {"queue_id", "sample_id", "title"}.issubset(reader.fieldnames or []):
                raise ReviewValidationError("missing blinded columns")
            found = []
            for row in reader:
                if any((row.get(key) or "").strip() for key in LEAK_FIELDS):
                    raise ReviewValidationError("blinded input contains labels/ranking/prefill")
                if row.get("queue_id") == selector:
                    found.append({key: row.get(key) for key in BLIND_FIELDS})
            if len(found) != 1:
                raise ReviewValidationError("selected blinded item missing or duplicated")
            return found[0]
    if kind == "rq":
        data = read_json(path)
        items = data if isinstance(data, list) else data.get("research_questions", data.get("examples", [data]))
        found = [item for item in items if item.get("rq_id") == selector]
        if len(found) != 1:
            raise ReviewValidationError("selected RQ missing or duplicated")
        return found[0]
    return None


def policy(kind, license_id, access_basis):
    # Immutable current-policy boundary: no flag authorizes abstracts/PDF/derivatives.
    if kind not in ("sqlite_metadata", "blinded_metadata", "rq"):
        return False, "current_policy_blocks_abstract_fulltext_and_derivatives"
    if access_basis not in ("public_metadata", "repository_governance"):
        return False, "access_basis_unknown_or_restricted"
    if license_id not in ("CC0-1.0", "CC-BY-4.0", "CC-BY-SA-4.0", "MIT", "public-domain"):
        return False, "license_unknown_or_not_allowlisted"
    return True, "metadata_or_governance_only_no_abstract"


def preflight(path, kind, *, selector=None, license_id="license_unknown", access_basis="unknown"):
    path = Path(path).resolve()
    if kind not in KINDS or not path.is_file():
        raise ReviewValidationError("unknown kind or missing source")
    metadata = selected_metadata(path, kind, selector) if kind in ("sqlite_metadata", "blinded_metadata", "rq") else None
    allowed, reason = policy(kind, license_id, access_basis)
    # A command-line license is a claim, never authority to relabel an input.
    if kind == "sqlite_metadata" and metadata.get("license") != license_id:
        allowed, reason = False, "license_does_not_match_source_record"
    if kind == "blinded_metadata":
        allowed, reason = False, "blinded_csv_has_no_field_level_license_evidence"
    if kind == "rq" and (access_basis != "repository_governance" or not path.is_relative_to(PROJECT_ROOT / "docs/governance")):
        allowed, reason = False, "not_a_repository_governance_source"
    return {"source_id": "source-" + uuid4().hex[:12], "kind": kind, "path": str(path),
            "selector": selector, "sha256": file_hash(path), "selection_hash": digest(metadata) if metadata is not None else None,
            "content_class": "metadata" if kind in ("sqlite_metadata", "blinded_metadata") else "governance" if kind == "rq" else "restricted_content",
            "license": license_id, "access_basis": access_basis, "model_access_allowed": allowed, "policy_reason": reason}


def frozen_files():
    files = list(PROTOCOLS) + [str(p.relative_to(PROJECT_ROOT)).replace("\\", "/")
                              for p in sorted((PROJECT_ROOT / "docs/governance/contracts").glob("*.json"))]
    protocols = {rel: file_hash(PROJECT_ROOT / rel) for rel in files}
    skills = {str(p.relative_to(SKILL_ROOT)).replace("\\", "/"): file_hash(p)
              for p in sorted(SKILL_ROOT.rglob("*")) if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"}
    return protocols, skills


def input_digest(provenance):
    return digest({key: provenance[key] for key in ("sources", "protocol_files", "skill_files", "scope")})


def output_digest(review):
    return digest({key: value for key, value in review.items() if key != "output_hash"})


def source_material(source):
    kind, path = source["kind"], Path(source["path"])
    if kind in ("sqlite_metadata", "blinded_metadata", "rq"):
        return selected_metadata(path, kind, source["selector"])
    if kind == "docling":
        # Existing CE-03 validation, without importing an optional PDF parser.
        from research_library.parsing.schema import validate_result
        data = read_json(path)
        if validate_result(data):
            raise ReviewValidationError("invalid CE-03 artifact")
        return data
    if kind == "text":
        return path.read_text(encoding="utf-8")
    return None


def citation_errors(citation, source):
    errors = []
    if citation["source_hash"] != source["sha256"]:
        return ["citation: source hash mismatch"]
    loc = citation["locator"]
    if loc["char_end"] <= loc["char_start"]:
        errors.append("citation: invalid character interval")
    material = source_material(source)
    text = None
    actual_doi = None
    if source["kind"] in ("sqlite_metadata", "blinded_metadata", "rq"):
        actual_doi = material.get("doi")
        if loc["field"] not in material or loc["paragraph_id"] is not None or loc["physical_page_no"] is not None or loc["printed_page_no"] is not None:
            errors.append("citation: invalid metadata locator")
        else:
            text = str(material[loc["field"]]) if material[loc["field"]] is not None else None
    elif source["kind"] == "docling":
        paragraphs = [p for p in material.get("paragraphs", []) if p.get("paragraph_id") == loc["paragraph_id"]]
        if len(paragraphs) != 1:
            errors.append("citation: paragraph missing or ambiguous")
        else:
            paragraph = paragraphs[0]
            text = paragraph["text"]
            physical = paragraph.get("physical_page_no")
            pages = [p for p in material["pages"] if p["physical_page_no"] == physical]
            printed = pages[0].get("printed_page_no") if pages else None
            if loc["field"] is not None or physical is None or loc["physical_page_no"] != physical or loc["printed_page_no"] != printed:
                errors.append("citation: incorrect physical/printed page")
    elif source["kind"] == "text":
        text = material
        if any(loc[key] is not None for key in ("field", "paragraph_id", "physical_page_no", "printed_page_no")):
            errors.append("citation: text has no verified page locator")
    if citation["doi"] is not None:
        if not re.fullmatch(r"10\.\d{4,9}/\S+", citation["doi"], re.I) or citation["doi"] != actual_doi:
            errors.append("citation: DOI not supported by selected source")
    if text is None:
        if citation["verification_status"] != "unverified":
            errors.append("citation: no text available for matching")
    elif loc["char_end"] > len(text) or text[loc["char_start"]:loc["char_end"]] != citation["quote"]:
        errors.append("citation: quote/character interval does not match local text")
    return errors


def validate(review, provenance, *, require_current=True):
    errors = schema_errors(review, read_json(SKILL_ROOT / "schemas/review-result.schema.json"))
    if errors:
        return errors
    if not isinstance(provenance, dict) or set(provenance) != PROVENANCE_KEYS:
        return ["provenance: incorrect fields"]
    if (type(provenance["schema_version"]) is not int or not isinstance(provenance["run_id"], str)
            or not isinstance(provenance["scope"], dict) or not isinstance(provenance["input_hash"], str)
            or not isinstance(provenance["model_content_source_ids"], list)
            or any(not isinstance(sid, str) for sid in provenance["model_content_source_ids"])
            or provenance["model_identity_evidence"] is not None and not isinstance(provenance["model_identity_evidence"], str)
            or any(not isinstance(provenance[key], dict) or any(not isinstance(k, str) or not isinstance(v, str)
                for k, v in provenance[key].items()) for key in ("protocol_files", "skill_files"))):
        return ["provenance: incorrect types"]
    if provenance["schema_version"] != 1 or provenance["run_id"] != review["run_id"] or provenance["scope"] != review["scope"]:
        errors.append("provenance: identity/scope mismatch")
    if not isinstance(provenance["sources"], list) or not provenance["sources"]:
        return errors + ["provenance: sources required"]
    sources = {}
    for source in provenance["sources"]:
        if not isinstance(source, dict) or set(source) != SOURCE_KEYS:
            return errors + ["source: incorrect fields"]
        if (any(not isinstance(source[key], str) for key in ("source_id", "kind", "path", "sha256", "content_class", "license", "access_basis", "policy_reason"))
                or source["selector"] is not None and not isinstance(source["selector"], str)
                or source["selection_hash"] is not None and not isinstance(source["selection_hash"], str)
                or type(source["model_access_allowed"]) is not bool):
            return errors + ["source: incorrect types"]
        if source["source_id"] in sources:
            errors.append("source: duplicate id")
        sources[source["source_id"]] = source
        try:
            refreshed = preflight(source["path"], source["kind"], selector=source["selector"],
                                  license_id=source["license"], access_basis=source["access_basis"])
            if any(refreshed[key] != source[key] for key in SOURCE_KEYS - {"source_id"}):
                errors.append("source: fingerprint/policy changed")
        except (OSError, ValueError, sqlite3.Error, KeyError, TypeError):
            errors.append("source: unavailable/invalid input")
    try:
        protocols, skills = frozen_files()
        if require_current and (provenance["protocol_files"] != protocols or provenance["skill_files"] != skills):
            errors.append("provenance: frozen protocol/skill hash mismatch")
        if provenance["input_hash"] != input_digest(provenance) or review["input_hash"] != provenance["input_hash"]:
            errors.append("provenance: input hash mismatch")
        if review["output_hash"] != output_digest(review):
            errors.append("review: output hash mismatch")
    except (OSError, ValueError, TypeError):
        errors.append("provenance: cannot verify hashes")
    sent = provenance["model_content_source_ids"]
    if not isinstance(sent, list) or any(sid not in sources or not sources[sid]["model_access_allowed"] for sid in sent):
        errors.append("policy: unapproved content sent to model")
    if review["model_review_performed"]:
        if review["execution_kind"] != "codex_session" or review["model_identity_status"] == "not_called":
            errors.append("identity: inconsistent model execution")
        if review["model_identity_status"] == "verified" and (not review["model_id"] or not provenance["model_identity_evidence"]):
            errors.append("identity: claimed model lacks runtime evidence")
        if review["model_identity_status"] == "unknown" and (review["model_id"] is not None or review["model_version"] is not None):
            errors.append("identity: unknown model must not invent id/version")
    elif review["execution_kind"] != "deterministic_demo" or review["model_identity_status"] != "not_called" or review["model_id"] is not None or review["model_version"] is not None or sent:
        errors.append("identity: deterministic demo cannot claim a model call")
    scope = review["scope"]
    if scope["track"] == "catalog" and (scope["rq_id"] is not None or scope["rq_version"] is not None):
        errors.append("scope: catalog cannot carry RQ")
    if scope["track"] == "review":
        if not scope["rq_id"] or not scope["rq_version"]:
            errors.append("scope: review requires RQ id/version")
        rq_sources = [source for source in sources.values() if source["kind"] == "rq" and source["selector"] == scope["rq_id"]]
        if len(rq_sources) != 1:
            errors.append("scope: selected RQ source required")
        else:
            try:
                rq = source_material(rq_sources[0])
                if rq.get("version") != scope["rq_version"]:
                    errors.append("scope: RQ version mismatch")
                if (rq.get("status") != "active" or not rq.get("approved_by")) and ("rq_not_approved" not in review["uncertainties"] or review["review_status"] == "ai_reviewed"):
                    errors.append("scope: unapproved RQ must remain unresolved")
            except (OSError, ValueError, TypeError, KeyError):
                errors.append("scope: invalid RQ input")
    if not set(review["reason_codes"]).issubset(REASONS[review["recommendation"]]):
        errors.append("review: reason codes incompatible with recommendation")
    if review["mode"] != "screen" and review["recommendation"] != "not_assessed":
        errors.append("review: non-screen cannot make screening decision")

    def check_result(result):
        result_errors = []
        citations = {c["citation_id"]: c for c in result["supporting_sources"]}
        if len(citations) != len(result["supporting_sources"]):
            result_errors.append("citation: duplicate citation id")
        for citation in citations.values():
            if citation["source_id"] not in sources:
                result_errors.append("citation: missing supporting source")
            else:
                try:
                    result_errors += citation_errors(citation, sources[citation["source_id"]])
                except (OSError, ValueError, TypeError, KeyError, ImportError, sqlite3.Error):
                    result_errors.append("citation: cannot verify source")
            if citation["verification_status"] == "unverified" and "citation_unverified" not in result["uncertainties"]:
                result_errors.append("citation: unverified reference requires uncertainty")
        for finding in result["findings"]:
            if finding["value"] is not None and (not finding["citation_ids"] or any(cid not in citations for cid in finding["citation_ids"])):
                result_errors.append("finding: unsupported fact must be null")
        return result_errors

    errors += check_result(review)
    passes = review["passes"]
    if passes["enabled"]:
        if not review["model_review_performed"]:
            errors.append("passes: deterministic demo cannot claim independent model passes")
        if passes["isolation"] != "separate_contexts" or passes["a"] is None or passes["b"] is None:
            errors.append("passes: two separate original contexts required")
        else:
            a, b = passes["a"], passes["b"]
            if a["context_id"] == b["context_id"]:
                errors.append("passes: contexts are not independent")
            for result in (a, b):
                errors += check_result(result)
                if result["input_hash"] != review["input_hash"] or result["result_hash"] != digest({k: v for k, v in result.items() if k != "result_hash"}):
                    errors.append("passes: original result hash/input mismatch")
            if any(a[key] != b[key] for key in ("recommendation", "findings", "assessments")):
                if not passes["differences"] or "substantive_disagreement" not in review["uncertainties"]:
                    errors.append("passes: substantive disagreement must be retained")
            if not set(a["uncertainties"] + b["uncertainties"]).issubset(set(review["uncertainties"])):
                errors.append("passes: original uncertainties omitted")
    elif passes["isolation"] != "not_used" or passes["a"] is not None or passes["b"] is not None or passes["differences"]:
        errors.append("passes: disabled passes must be empty")
    if review["review_status"] == "ai_reviewed":
        if not review["model_review_performed"] or not sent or not review["supporting_sources"] or FORCE_UNRESOLVED & set(review["uncertainties"]):
            errors.append("review: unresolved conditions cannot claim completed AI review")
        if review["mode"] in ("appraise", "extract") and not any(source["kind"] in ("docling", "pdf", "text") and source["source_id"] in sent for source in sources.values()):
            errors.append("review: appraisal/extraction requires authorized original text")
        mode_field = {"screen": "relevance", "appraise": "appraisal", "extract": "evidence_relation",
                      "challenge": "challenge_findings", "audit": "audit_issues"}[review["mode"]]
        if review["assessments"][mode_field] is None:
            errors.append("review: selected mode assessment missing")
    return errors


def make_demo(mode, sources, *, run_id=None):
    """A blocked/abstaining engineering example, never a scientific AI review."""
    run_id = run_id or "demo-" + uuid4().hex
    scope = {"work_ids": [s["selector"] for s in sources if s["kind"] in ("sqlite_metadata", "blinded_metadata")],
             "track": "catalog", "rq_id": None, "rq_version": None, "prior_run_ids": []}
    protocols, skills = frozen_files()
    prov = {"schema_version": 1, "run_id": run_id, "sources": sources, "protocol_files": protocols,
            "skill_files": skills, "scope": scope, "input_hash": "", "model_identity_evidence": None,
            "model_content_source_ids": []}
    prov["input_hash"] = input_digest(prov)
    review = {"schema_version": 1, "run_id": run_id, "mode": mode,
              "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "scope": scope,
              "reviewer_type": "ai_model", "requested_model_id": "gpt-6-astra", "model_id": None,
              "model_version": None, "model_identity_status": "not_called", "model_review_performed": False,
              "execution_kind": "deterministic_demo", "skill_version": VERSION, "protocol_version": "DRAFT v1.1",
              "protocol_status": "draft_not_effective", "input_hash": prov["input_hash"], "output_hash": "",
              "recommendation": "undecided" if mode == "screen" else "not_assessed", "reason_codes": ["U01"],
              "supporting_sources": [], "findings": [],
              "assessments": {"relevance": None, "appraisal": None, "evidence_relation": None,
                              "challenge_findings": [], "audit_issues": []},
              "uncertainties": ["evidence_insufficient", "original_unavailable"],
              "review_status": "blocked" if any(not s["model_access_allowed"] for s in sources) else "unresolved",
              "label_tier": "silver", "maturity_level": "L0", "human_review_status": "not_reviewed",
              "allowed_for_agent_release": False,
              "passes": {"enabled": False, "isolation": "not_used", "a": None, "b": None, "differences": []},
              "summary": "确定性来源/许可/结构演示。未调用模型，未读取原文到模型，未开展 Astra 科研审查；无科研结论。"}
    review["output_hash"] = output_digest(review)
    return review, prov


def default_output_root():
    data = os.environ.get("CHILDEVIDENCE_DATA_DIR")
    return Path(data) / "review/ai-review" if data else PROJECT_ROOT / "data/review/ai-review"


def finalize(review, provenance, output_root=None):
    errors = validate(review, provenance)
    if errors:
        raise ReviewValidationError("validation failed: " + "; ".join(errors))
    root = Path(output_root) if output_root else default_output_root()
    target = root / review["run_id"]
    # Reject writing into source trees/databases/PDF locations, even with --out-root.
    protected = [Path(s["path"]).resolve() for s in provenance["sources"]]
    if any(target.resolve() == path or target.resolve() in path.parents for path in protected):
        raise ReviewValidationError("output would contain/overwrite a source")
    if root.resolve() != default_output_root().resolve() and any(root.resolve().is_relative_to(path.parent) for path in protected):
        raise ReviewValidationError("custom output must be outside original source directories")
    target.mkdir(parents=True, exist_ok=False)
    validation = {"valid": True, "errors": [], "validator_version": VERSION, "review_hash": review["output_hash"],
                  "provenance_hash": digest(provenance), "limits": "structure/hash/local-text matching only; not expert Gold or original-PDF truth"}
    report = (f"# AI Review {review['run_id']}\n\nMode: {review['mode']} · Status: {review['review_status']} · silver/L0\n\n"
              f"Model: {review['model_id'] or 'unknown / not called'}; actual model review: {review['model_review_performed']}\n\n"
              f"Scope: {canonical(review['scope'])}\n\n"
              f"{review['summary']}\n\nUncertainties: {', '.join(review['uncertainties']) or 'none declared'}\n\n"
              "DRAFT v1.1 remains unapproved. No human identity, Gold or release eligibility.\n")
    report += "\n## Mode assessments\n\n" + canonical(review["assessments"]) + "\n\n## Findings\n\n"
    for finding in review["findings"]:
        report += f"- {finding['field']}: {finding['value'] if finding['value'] is not None else 'unknown'}; citations: {', '.join(finding['citation_ids'])}\n"
    report += "\n## Source positions (local matching is not original-PDF truth)\n\n"
    for citation in review["supporting_sources"]:
        report += f"- {citation['citation_id']} / {citation['source_id']}: {canonical(citation['locator'])}; {citation['verification_status']}\n"
    report += "\n## Pass differences\n\n"
    report += "\n".join("- " + item for item in review["passes"]["differences"]) or "Pass comparison not used / no declared differences."
    for name, value in (("review.json", review), ("provenance.json", provenance)):
        with (target / name).open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    with (target / "review.md").open("x", encoding="utf-8") as stream:
        stream.write(report)
    # Hash byte-exact artifacts separately from the canonical semantic hashes.
    validation["artifact_sha256"] = {name: file_hash(target / name) for name in ("review.json", "provenance.json", "review.md")}
    # validation.json is written once last; it cannot hash itself without a cycle.
    with (target / "validation.json").open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(validation, ensure_ascii=False, indent=2) + "\n")
    return target


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("preflight", "demo"):
        p = sub.add_parser(command)
        p.add_argument("--source", required=True)
        p.add_argument("--kind", choices=KINDS, required=True)
        p.add_argument("--selector")
        p.add_argument("--license", default="license_unknown")
        p.add_argument("--access-basis", choices=("public_metadata", "repository_governance", "institution_subscription", "unknown"), default="unknown")
        if command == "demo":
            p.add_argument("--mode", choices=("screen", "appraise", "extract", "challenge", "audit"), required=True)
            p.add_argument("--out-root")
    for command in ("validate", "finalize"):
        p = sub.add_parser(command)
        p.add_argument("--review", required=True)
        p.add_argument("--provenance", required=True)
        if command == "finalize":
            p.add_argument("--out-root")
        else:
            p.add_argument("--historical", action="store_true", help="check frozen manifest without requiring current protocol/skill bytes")
    args = parser.parse_args(argv)
    try:
        if args.command in ("preflight", "demo"):
            source = preflight(args.source, args.kind, selector=args.selector, license_id=args.license, access_basis=args.access_basis)
            if args.command == "preflight":
                print(json.dumps(source, ensure_ascii=False, indent=2))
                return 0 if source["model_access_allowed"] else 2
            review, provenance = make_demo(args.mode, [source])
            target = finalize(review, provenance, args.out_root)
            print(json.dumps({"run_id": review["run_id"], "output": str(target), "status": review["review_status"], "model_review_performed": False}))
            return 0
        review, provenance = read_json(args.review), read_json(args.provenance)
        if args.command == "finalize":
            target = finalize(review, provenance, args.out_root)
            print(json.dumps({"output": str(target), "valid": True}))
            return 0
        errors = validate(review, provenance, require_current=not args.historical)
        print(json.dumps({"valid": not errors, "errors": errors, "historical_mode": args.historical,
                          "limits": "historical mode does not attest current protocol or validate an unavailable original version"}, ensure_ascii=False))
        return 2 if errors else 0
    except (OSError, ValueError, TypeError, KeyError, sqlite3.Error):
        # Do not echo source text, secret values or arbitrary exception payloads.
        print(json.dumps({"valid": False, "errors": ["missing, invalid, blocked or conflicting input/output; run local checks"]}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
