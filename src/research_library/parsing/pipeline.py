"""Parse pipeline: integrity -> parse -> normalize -> validate -> versioned output.

Pipeline stages per document (issue #3):

1. integrity: header/EOF/size checks + SHA-256; optional expected-SHA compare
   (manifest / library) — mismatch fails before any parsing.
2. parse via primary adapter (Docling); on failure, optional configured
   fallback (pdfplumber). The fallback state is explicit: status=fallback with
   the primary failure recorded. Nothing is silently substituted.
3. normalize to the ce03-parse v1 schema (provenance, honest nulls, flags).
4. validate the normalized result (structural self-consistency).
5. apply human page-map corrections (printed pages; physical page untouched).
6. write artifacts atomically to a content-addressed output directory:
   <output_root>/<sha256:12>/<artifact_id>/ with result.json, page-map.json
   and run-meta.json.

Idempotency / resume: an artifact_id is derived from source SHA + actual
parser identity (name/version/models) + effective options. Re-running skips
documents whose existing valid artifact matches (unless --force); failed or
invalid existing artifacts are rebuilt. Corrupt/foreign artifact files are
treated as absent with a warning (cache pollution policy).
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from ..pdfcheck import sha256_file, validate_pdf
from .adapters import AdapterError, ParseTimeout, get_adapter, known_parsers
from .adapters.normalize import options_hash
from .cidcheck import page_text_issues
from .config import ParsingConfig
from .memory import get_memory_info_mb, get_self_peak_memory_mb
from .page_map import apply_corrections, corrections_for_document, sync_pages_from_map
from .schema import validate_result


class PipelineError(Exception):
    pass


# --------------------------------------------------------------------------
# identity
# --------------------------------------------------------------------------

def probe_parser_identity(parser_name: str, cfg: ParsingConfig) -> dict:
    """Lightweight parser identity probe (version + models) without parsing."""
    adapter = get_adapter(parser_name, models_dir=cfg.models_dir, offline=cfg.offline)
    info = {"name": parser_name, "parser_version": None, "model_versions": {}}
    probe = getattr(adapter, "probe", None)
    if probe is not None:
        info.update(probe() or {})
    return info


def compute_artifact_id(source_sha256: str, parser_identity: dict, effective_options: dict) -> str:
    material = {
        "source_sha256": source_sha256,
        "parser_name": parser_identity.get("name"),
        "parser_version": parser_identity.get("parser_version"),
        "model_versions": parser_identity.get("model_versions") or {},
        "options": effective_options,
    }
    payload = json.dumps(material, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return "pa-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _identity_from_intermediate(inter: dict) -> dict:
    p = inter.get("parser") or {}
    return {
        "name": p.get("name"),
        "parser_version": p.get("parser_version"),
        "model_versions": p.get("model_versions") or {},
    }


# --------------------------------------------------------------------------
# artifact IO
# --------------------------------------------------------------------------

def _artifact_dir(cfg: ParsingConfig, sha: str, artifact_id: str) -> Path:
    return cfg.output_root / sha[:12] / artifact_id


def _load_existing_result(a_dir: Path) -> tuple[dict | None, str | None]:
    """Load existing result.json; returns (result, pollution_note)."""
    p = a_dir / "result.json"
    if not p.exists():
        return None, None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None, "existing result.json unreadable (cache pollution); rebuilding"
    if not isinstance(data, dict) or not isinstance(data.get("schema"), dict):
        return None, "existing result.json is not a parse result (cache pollution); rebuilding"
    return data, None


def _identity_matches(stored: dict, probe: dict, options_h: str) -> bool:
    """Does a stored artifact come from exactly the parser we would run now?"""
    p = stored.get("parser") or {}
    return (
        p.get("name") == probe.get("name")
        and p.get("parser_version") == probe.get("parser_version")
        and (p.get("model_versions") or {}) == (probe.get("model_versions") or {})
        and p.get("options_hash") == options_h
    )


def _find_existing_valid(
    cfg: ParsingConfig, sha: str, artifact_id: str, probe: dict
) -> tuple[dict | None, Path | None, str | None]:
    """Find a reusable valid artifact for this source under the sha directory.

    Matches by artifact_id OR by full parser identity (robust to identity
    drift between the pre-parse probe and a previous run). Returns
    (result, dir, pollution_note).
    """
    options_h = options_hash(cfg.effective_options())
    sha_dir = cfg.output_root / sha[:12]
    if not sha_dir.is_dir():
        return None, None, None
    fallback_note = None
    for art_dir in sorted(sha_dir.iterdir()):
        if not art_dir.is_dir() or art_dir.name.startswith("."):
            continue
        existing, note = _load_existing_result(art_dir)
        if existing is None:
            if note and note.startswith("existing result.json unreadable"):
                # unreadable content in a directory that may not even be ours
                fallback_note = fallback_note or note
            continue
        same_id = (existing.get("artifact") or {}).get("artifact_id") == artifact_id
        if not same_id and not _identity_matches(existing, probe, options_h):
            continue
        errors = validate_result(existing)
        if not errors and existing.get("status") in ("ok", "degraded", "fallback"):
            return existing, art_dir, None
        if errors:
            fallback_note = fallback_note or (
                f"existing artifact failed validation ({len(errors)} errors); rebuilding")
    return None, None, fallback_note


def _write_atomic(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


# --------------------------------------------------------------------------
# single document
# --------------------------------------------------------------------------

def run_document(
    pdf_path: Path,
    cfg: ParsingConfig,
    *,
    document_id: str | None = None,
    expected_sha256: str | None = None,
    force: bool = False,
    probe_cache: dict | None = None,
) -> dict:
    """Parse one document. Returns an outcome dict (also written as run-meta)."""
    started = time.perf_counter()
    pdf_path = Path(pdf_path)
    outcome: dict = {
        "document_id": document_id,
        "pdf_path": str(pdf_path),
        "status": "failed",
        "action": None,          # parsed | skipped | failed | integrity_failed
        "artifact_id": None,
        "output_dir": None,
        "sha256": None,
        "parser": None,
        "duration_sec": None,
        "warnings": [],
        "failure_reasons": [],
    }

    # ---- stage 1: integrity --------------------------------------------
    if not pdf_path.exists():
        outcome["failure_reasons"].append(
            {"stage": "integrity", "code": "missing_file", "message": f"file not found: {pdf_path}"})
        outcome["action"] = "integrity_failed"
        return outcome
    sha = sha256_file(pdf_path)
    outcome["sha256"] = sha
    v = validate_pdf(pdf_path)
    if not v["ok"]:
        outcome["failure_reasons"].append(
            {"stage": "integrity", "code": "invalid_pdf",
             "message": f"PDF validation failed: {v['checks']}"})
        outcome["action"] = "integrity_failed"
        return outcome
    if expected_sha256 and expected_sha256.lower() != sha:
        outcome["failure_reasons"].append(
            {"stage": "integrity", "code": "sha_mismatch",
             "message": f"expected sha256 {expected_sha256} but file has {sha}"})
        outcome["action"] = "integrity_failed"
        return outcome

    # ---- identity + skip check ------------------------------------------
    probe_cache = probe_cache if probe_cache is not None else {}
    primary = cfg.primary_parser
    if primary not in probe_cache:
        probe_cache[primary] = probe_parser_identity(primary, cfg)
    probe = probe_cache[primary]
    artifact_id = compute_artifact_id(sha, probe, cfg.effective_options())
    a_dir = _artifact_dir(cfg, sha, artifact_id)
    outcome["artifact_id"] = artifact_id
    outcome["output_dir"] = str(a_dir)

    if not force:
        existing, existing_dir, pollution_note = _find_existing_valid(
            cfg, sha, artifact_id, probe)
        if pollution_note:
            outcome["warnings"].append(pollution_note)
        if existing is not None:
            outcome["artifact_id"] = existing.get("artifact", {}).get("artifact_id") or artifact_id
            outcome["output_dir"] = str(existing_dir)
            outcome["status"] = existing["status"]
            outcome["action"] = "skipped"
            outcome["parser"] = (existing.get("parser") or {}).get("name")
            outcome["duration_sec"] = round(time.perf_counter() - started, 3)
            return outcome

    # ---- stage 2+3: parse + normalize ------------------------------------
    inter = None
    used_parser = primary
    failure_reasons: list[dict] = []
    parse_started = time.perf_counter()
    parse_options = cfg.effective_options()
    try:
        inter = _run_adapter(primary, pdf_path, parse_options, cfg)
    except Exception as e:  # noqa: BLE001 - any primary failure goes to fallback policy
        failure_reasons.append(_reason_from_exception(primary, e))
        if cfg.fallback_enabled and cfg.fallback_parser and cfg.fallback_parser != primary:
            used_parser = cfg.fallback_parser
            try:
                inter = _run_adapter(cfg.fallback_parser, pdf_path, parse_options, cfg)
            except Exception as e2:  # noqa: BLE001
                failure_reasons.append(_reason_from_exception(cfg.fallback_parser, e2))
                inter = None
        if inter is None:
            outcome["status"] = "failed"
            outcome["failure_reasons"] = failure_reasons
            outcome["action"] = "failed"
            outcome["duration_sec"] = round(time.perf_counter() - started, 3)
            _write_run_meta(a_dir, outcome)
            return outcome
    parse_duration = time.perf_counter() - parse_started

    status = "ok"
    if used_parser != primary:
        status = "fallback"

    source_ctx = {
        "path": str(pdf_path),
        "file_name": pdf_path.name,
        "size_bytes": v["size"],
        "sha256": sha,
        "header_ok": v["is_pdf"],
        "eof_ok": v["has_eof"],
        "validated": True,
    }
    actual_identity = _identity_from_intermediate(inter)
    actual_artifact_id = compute_artifact_id(sha, actual_identity, cfg.effective_options())
    if actual_artifact_id != artifact_id:
        # environment drifted between probe and parse; use the actual identity
        artifact_id = actual_artifact_id
        a_dir = _artifact_dir(cfg, sha, artifact_id)
        outcome["artifact_id"] = artifact_id
        outcome["output_dir"] = str(a_dir)

    try:
        from .adapters.normalize import normalize_intermediate

        result = normalize_intermediate(
            inter,
            source=source_ctx,
            document_id=document_id or pdf_path.stem,
            options=cfg.effective_options(),
            status=status,
            failure_reasons=failure_reasons,
            duration_sec=parse_duration,
            peak_memory_mb=inter.pop("_peak_memory_mb", None),
        )
    except Exception as e:  # noqa: BLE001 - normalization must not crash the batch
        outcome["status"] = "failed"
        outcome["failure_reasons"] = failure_reasons + [
            {"stage": "normalize", "code": "normalize_error", "message": repr(e)[:500]}]
        outcome["action"] = "failed"
        outcome["duration_sec"] = round(time.perf_counter() - started, 3)
        _write_run_meta(a_dir, outcome)
        return outcome

    # ---- stage 5: human page-map corrections -----------------------------
    page_map = _build_page_map(cfg, result)
    sync_pages_from_map(result, page_map)
    if page_map.get("manual_corrections_applied"):
        result["artifact"]["page_map_applied"] = {
            "applied": len(page_map["manual_corrections_applied"]),
            "source": "manual corrections file",
        }

    # ---- stage 4: validate -----------------------------------------------
    errors = validate_result(result)
    if errors:
        result["status"] = "failed"
        result["failure_reasons"].append({
            "stage": "validate", "code": "validation_failed",
            "message": "; ".join(errors[:10])[:1000],
        })

    result["artifact"]["artifact_id"] = artifact_id
    result["artifact"]["output_dir"] = str(a_dir)

    # ---- stage 6: write artifacts -----------------------------------------
    a_dir.mkdir(parents=True, exist_ok=True)
    _write_atomic(a_dir / "result.json", json.dumps(result, ensure_ascii=False, indent=1))
    _write_atomic(a_dir / "page-map.json", json.dumps(page_map, ensure_ascii=False, indent=1))
    outcome["status"] = result["status"]
    outcome["action"] = "parsed"
    outcome["parser"] = used_parser
    outcome["duration_sec"] = round(time.perf_counter() - started, 3)
    # preserve earlier pipeline warnings (e.g. cache pollution) + result warnings
    outcome["warnings"] = (outcome["warnings"] + result.get("warnings", []))[:20]
    _write_run_meta(a_dir, outcome)

    # ---- cross-check review tasks (optional) -------------------------------
    if cfg.cross_check and result["status"] in ("ok", "degraded"):
        _cross_check(pdf_path, cfg, result, a_dir, outcome)
    return outcome


# --------------------------------------------------------------------------
def _run_adapter(parser_name: str, pdf_path: Path, options: dict, cfg: ParsingConfig,
                 parser_module: str | None = None) -> dict:
    """Run one adapter, honoring the configured execution mode.

    parser_module: optional absolute path to a Python file exposing a Parser
    class with parse()/parse_to_file() — a documented test/debug hook so the
    subprocess runner can execute stub parsers without installing them.
    """
    if cfg.execution == "inprocess":
        if parser_module:
            adapter = _load_module_parser(parser_module)
        else:
            adapter = get_adapter(parser_name, models_dir=cfg.models_dir, offline=cfg.offline)
        inter = adapter.parse(pdf_path, options)
        peak = get_self_peak_memory_mb()
        if peak is not None:
            inter["_peak_memory_mb"] = peak
        return inter

    # subprocess mode: hard timeout + optional memory cap (Windows).
    # Scratch files live under the output root (writable), never next to the
    # source PDF — inputs are treated as strictly read-only.
    scratch = cfg.output_root / ".scratch"
    scratch.mkdir(parents=True, exist_ok=True)
    spec = {
        "pdf_path": str(pdf_path),
        "parser": parser_name,
        "parser_module": parser_module,
        "options": options,
        "out_json": str(scratch / f"{os.getpid()}-{parser_name}.out.json"),
        "models_dir": str(cfg.models_dir) if cfg.models_dir else None,
        "offline": cfg.offline,
    }
    tmp_spec = scratch / f"{os.getpid()}-{parser_name}.spec.json"
    tmp_spec.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
    out_json = Path(spec["out_json"])
    err_json = Path(str(out_json) + ".error")
    try:
        env = dict(os.environ)
        src_dir = str(Path(__file__).resolve().parents[2])
        env["PYTHONPATH"] = src_dir + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        proc = subprocess.Popen(
            [sys.executable, "-m", "research_library.parsing.runner", str(tmp_spec)],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            cwd=str(Path(__file__).resolve().parents[3]),
            env=env,
        )
        deadline = time.monotonic() + cfg.timeout_sec
        while proc.poll() is None:
            if time.monotonic() > deadline:
                proc.kill()
                proc.wait(timeout=10)
                raise ParseTimeout(
                    f"parser {parser_name} exceeded timeout of {cfg.timeout_sec}s; process killed")
            if cfg.max_memory_mb:
                cur, _peak = get_memory_info_mb(proc.pid)
                if cur is not None and cur > cfg.max_memory_mb:
                    proc.kill()
                    proc.wait(timeout=10)
                    raise AdapterError(
                        f"parser {parser_name} exceeded memory cap {cfg.max_memory_mb}MB; killed")
            time.sleep(0.5)
        stderr_tail = b""
        try:
            stderr_tail = (proc.stderr.read() or b"")[-2000:]
        except Exception:
            pass
        if proc.returncode != 0 or not out_json.exists():
            detail = ""
            if err_json.exists():
                try:
                    detail = json.loads(err_json.read_text(encoding="utf-8")).get("message", "")
                except Exception:
                    detail = "unreadable error file"
            raise AdapterError(
                f"parser {parser_name} subprocess failed (exit={proc.returncode}): "
                f"{detail or stderr_tail.decode('utf-8', 'replace')}"
            )
        # peak-memory REPORTING is the child's job (runner.py measures itself
        # after parsing and attaches "_peak_memory_mb"); a parent-side
        # cross-process psapi read can be virtualized under sandboxed
        # environments and then fabricate plausible-looking garbage, so the
        # parent never invents a number.
        return json.loads(out_json.read_text(encoding="utf-8"))
    finally:
        for p in (tmp_spec, out_json, err_json):
            try:
                p.unlink()
            except OSError:
                pass


def _load_module_parser(module_path: str):
    """Load a parser class from a Python file (test/debug hook)."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("_ce03_test_parser", module_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return getattr(mod, "Parser")()


def _reason_from_exception(parser_name: str, e: Exception) -> dict:
    code = "parse_error"
    if isinstance(e, ParseTimeout):
        code = "timeout"
    elif type(e).__name__ == "DependencyMissing":
        code = "dependency_missing"
    elif type(e).__name__ == "ModelUnavailable":
        code = "model_unavailable"
    elif type(e).__name__ == "AdapterError":
        code = "adapter_error"
    return {
        "stage": "parse",
        "parser": parser_name,
        "code": code,
        "message": str(e)[:500],
    }


def _build_page_map(cfg: ParsingConfig, result: dict) -> dict:
    from .page_map import empty_page_map

    doc_id = result.get("document_id") or result["source"]["file_name"]
    pm = empty_page_map(result["page_count"])
    pm["document_id"] = doc_id
    pm["source_sha256"] = result["source"]["sha256"]
    corrections, src = corrections_for_document(cfg.corrections_dir, str(doc_id))
    if corrections:
        pm = apply_corrections(pm, corrections, source_file=src)
    return pm


def _cross_check(pdf_path: Path, cfg: ParsingConfig, result: dict, a_dir: Path, outcome: dict) -> None:
    """Run the secondary parser and record divergences as review tasks.

    Policy: conflicts are NEVER auto-resolved ("pick the correct one"); they
    produce a human review task file.
    """
    secondary = cfg.fallback_parser
    if not secondary or secondary == (result.get("parser") or {}).get("name"):
        return
    try:
        inter2 = _run_adapter(secondary, pdf_path, cfg.effective_options(), cfg)
    except Exception as e:  # noqa: BLE001 - cross-check is advisory
        outcome["warnings"].append(f"cross-check with {secondary} failed: {e!r}"[:300])
        return
    divergences = []
    if inter2.get("page_count") != result.get("page_count"):
        divergences.append({
            "type": "page_count_mismatch",
            "primary": result.get("page_count"),
            "secondary": inter2.get("page_count"),
        })
    else:
        prim_pages = {p["physical_page_no"]: p.get("char_count", 0) for p in result["pages"]}
        sec_pages = {p["physical_page_no"]: len(p.get("text") or "") for p in inter2["pages"]}
        for pno, pc in prim_pages.items():
            sc = sec_pages.get(pno, 0)
            if max(pc, sc) > 200 and (min(pc, sc) / max(pc, sc)) < 0.5:
                divergences.append({
                    "type": "page_text_volume_divergence",
                    "physical_page_no": pno,
                    "primary_chars": pc,
                    "secondary_chars": sc,
                })
    if divergences:
        qdir = cfg.review_queue_dir
        qdir.mkdir(parents=True, exist_ok=True)
        task = {
            "type": "cross_check_divergence",
            "document_id": result.get("document_id"),
            "source_sha256": result["source"]["sha256"],
            "primary_parser": (result.get("parser") or {}).get("name"),
            "secondary_parser": secondary,
            "divergences": divergences,
            "artifact_dir": str(a_dir),
            "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "policy": "conflicts are never auto-resolved; a human decides",
        }
        qfile = qdir / f"{result['source']['sha256'][:12]}-{result.get('document_id')}.json"
        _write_atomic(qfile, json.dumps(task, ensure_ascii=False, indent=1))
        outcome["warnings"].append(
            f"cross-check divergence recorded as review task: {qfile.name}")


def _write_run_meta(a_dir: Path, outcome: dict) -> None:
    try:
        a_dir.mkdir(parents=True, exist_ok=True)
        meta = dict(outcome)
        meta["written_utc"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        _write_atomic(a_dir / "run-meta.json", json.dumps(meta, ensure_ascii=False, indent=1))
    except OSError:
        pass


# --------------------------------------------------------------------------
# batch
# --------------------------------------------------------------------------

def load_manifest(path: Path) -> list[dict]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    docs = data.get("documents") if isinstance(data, dict) else data
    if not isinstance(docs, list):
        raise ValueError("manifest must be a JSON object with 'documents' or a JSON list")
    return docs


def resolve_manifest_path(entry: dict, input_root: str | None) -> Path:
    for key in ("copy_path", "source_path", "path"):
        raw = entry.get(key)
        if not raw:
            continue
        p = Path(raw)
        if input_root:
            # remap the recorded prefix onto the given root (manifests carry
            # machine-specific absolute paths)
            p = Path(input_root) / Path(raw).name
        if p.exists():
            return p
    raise FileNotFoundError(
        f"no accessible PDF path for manifest entry {entry.get('document_id')!r}"
    )


def run_batch(
    entries: list[dict],
    cfg: ParsingConfig,
    *,
    force: bool = False,
    limit: int | None = None,
    input_root: str | None = None,
) -> dict:
    """Parse a batch of manifest-style entries; returns the batch summary."""
    probe_cache: dict = {}
    summary = {
        "started_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total": 0,
        "parsed": 0,
        "skipped": 0,
        "failed": 0,
        "integrity_failed": 0,
        "status_counts": {},
        "outcomes": [],
    }
    if limit is not None:
        entries = entries[:limit]
    summary["total"] = len(entries)
    for entry in entries:
        try:
            pdf_path = resolve_manifest_path(entry, input_root)
        except FileNotFoundError as e:
            summary["failed"] += 1
            summary["outcomes"].append({
                "document_id": entry.get("document_id"),
                "status": "failed", "action": "integrity_failed",
                "failure_reasons": [{"stage": "resolve", "code": "missing_file", "message": str(e)}],
            })
            continue
        outcome = run_document(
            pdf_path, cfg,
            document_id=entry.get("document_id"),
            expected_sha256=entry.get("sha256"),
            force=force,
            probe_cache=probe_cache,
        )
        summary["outcomes"].append(outcome)
        action = outcome.get("action")
        if action == "skipped":
            summary["skipped"] += 1
        elif action == "parsed":
            summary["parsed"] += 1
        elif action == "integrity_failed":
            summary["integrity_failed"] += 1
        else:
            summary["failed"] += 1
        st = outcome.get("status")
        summary["status_counts"][st] = summary["status_counts"].get(st, 0) + 1
    summary["finished_utc"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return summary
