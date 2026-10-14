"""CE-POL-01 local permission registry and staged minimal text packages.

No network or database writes. Activation requires an approved code change;
neither an environment variable nor a registry entry activates egress.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from uuid import uuid4

from .config import default_data_dir

POLICY_VERSION = "CE-POL-01-draft-2026-10-14"
POLICY_ACTIVE = False  # Formal approval AND code acceptance are still pending.
MODES = {"screen", "appraise", "extract", "challenge", "audit"}
SCOPES = {"metadata", "abstract", "article_text"}


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1048576), b""):
            h.update(block)
    return h.hexdigest()


def read(path):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result
    return json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("invalid number")))


def root():
    return default_data_dir().parent / "review/model-access" if default_data_dir().name == "research-library" else default_data_dir() / "review/model-access"


def check_record(record):
    required = {"work_id", "pdf_sha256", "source_url", "rights_basis", "scope", "decision",
                "confirmed_by", "confirmed_at", "policy_version", "codex_environment", "sources"}
    if not isinstance(record, dict) or set(record) != required:
        raise ValueError("invalid permission fields")
    for key in required - {"scope", "sources"}:
        if not isinstance(record[key], str) or not record[key].strip():
            raise ValueError("missing confirmation")
    if record["decision"] not in {"allowed", "needs_verification", "restricted"}:
        raise ValueError("invalid decision")
    if not record["source_url"].startswith("https://") or len(record["pdf_sha256"]) != 64 or any(c not in "0123456789abcdef" for c in record["pdf_sha256"]):
        raise ValueError("invalid binding")
    datetime.fromisoformat(record["confirmed_at"].replace("Z", "+00:00"))
    if not isinstance(record["scope"], list) or not record["scope"] or any(s not in SCOPES for s in record["scope"]):
        raise ValueError("invalid scope")
    if not isinstance(record["sources"], list) or not record["sources"]:
        raise ValueError("missing source bindings")
    seen = set()
    for source in record["sources"]:
        if not isinstance(source, dict) or set(source) != {"sha256", "scope", "ranges"} or source["scope"] not in record["scope"]:
            raise ValueError("invalid source")
        token = source["sha256"]
        if not isinstance(token, str) or len(token) != 64 or any(c not in "0123456789abcdef" for c in token) or token in seen:
            raise ValueError("invalid source hash")
        seen.add(token)
        if not isinstance(source["ranges"], list) or not source["ranges"]:
            raise ValueError("missing allowed ranges")
        for span in source["ranges"]:
            if not isinstance(span, list) or len(span) != 2 or any(type(n) is not int for n in span) or not 0 <= span[0] < span[1]:
                raise ValueError("invalid range")


def register(record, directory=None):
    """Append immutable decisions; a later restricted decision revokes earlier access."""
    check_record(record)
    directory = Path(directory) if directory else root()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "permissions.json"
    records = read(path) if path.exists() else []
    if not isinstance(records, list):
        raise ValueError("invalid registry")
    for previous in records:
        check_record(previous)
    records.append(record)
    temporary = directory / (uuid4().hex + ".tmp")
    try:
        temporary.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def prepare(work_id, pdf, source, scope, spans, mode, environment, model_id=None, directory=None):
    """Verify every run locally; return paths/hashes only, never source text.

    Source is a locally prepared UTF-8 derivative whose exact bytes and allowed
    offsets the owner checked against the PDF. Raw PDF/Docling/review containers
    are not accepted. This is provenance binding, not parser accuracy attestation.
    """
    if not isinstance(spans, list) or any(not isinstance(s, list) or len(s) != 2 or any(type(n) is not int for n in s) for s in spans):
        spans = []  # Never copy arbitrary supplied content into the audit log.
    directory = Path(directory) if directory else root()
    run = uuid4().hex
    result = {"run_id": run, "work_id": work_id, "decision": "blocked", "reason": "invalid_or_unregistered",
              "policy_version": POLICY_VERSION, "mode": mode, "model_id": model_id,
              "environment": environment, "scope": scope, "pdf_sha256": None,
              "source_sha256": None, "ranges": spans, "output_sha256": None,
              "time": datetime.now(timezone.utc).isoformat()}
    try:
        records = read(directory / "permissions.json")
        if not isinstance(records, list):
            raise ValueError("invalid registry")
        for record in records:
            check_record(record)
        result["pdf_sha256"], result["source_sha256"] = sha(pdf), sha(source)
        matches = [r for r in records if r["work_id"] == work_id and r["pdf_sha256"] == result["pdf_sha256"]]
        record = matches[-1] if matches else None
        if record and record["decision"] == "allowed" and record["policy_version"] == POLICY_VERSION and record["codex_environment"] == environment and mode in MODES and scope in record["scope"]:
            binding = next((s for s in record["sources"] if s["sha256"] == result["source_sha256"] and s["scope"] == scope), None)
            if not isinstance(spans, list) or not spans or not binding or Path(source).suffix != ".txt":
                raise ValueError("invalid selection")
            text = Path(source).read_text(encoding="utf-8")
            for span in spans:
                if not isinstance(span, list) or len(span) != 2 or any(type(n) is not int for n in span) or not 0 <= span[0] < span[1] <= len(text) or not any(a <= span[0] < span[1] <= b for a, b in binding["ranges"]):
                    raise ValueError("outside allowed scope")
            result["reason"] = "policy_not_active"
            if POLICY_ACTIVE:
                package = {"work_id": work_id, "pdf_sha256": result["pdf_sha256"], "source_sha256": result["source_sha256"],
                           "scope": scope, "mode": mode, "source_url": record["source_url"], "rights_basis": record["rights_basis"],
                           "segments": [{"start": a, "end": b, "text": text[a:b]} for a, b in spans]}
                target = directory / "packages" / run
                target.mkdir(parents=True, exist_ok=False)
                path = target / "content.json"
                path.write_text(json.dumps(package, ensure_ascii=False), encoding="utf-8")
                path.chmod(0o444)
                result.update(decision="allowed", reason="registered_scope", output_sha256=sha(path), package_path=str(path))
    except (OSError, ValueError, TypeError, KeyError, StopIteration):
        pass
    directory.mkdir(parents=True, exist_ok=True)
    audit = directory / "audit"
    audit.mkdir(exist_ok=True)
    with (audit / (run + ".json")).open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    reg = sub.add_parser("register")
    reg.add_argument("--record", required=True)
    prep = sub.add_parser("prepare")
    for name in ("work-id", "pdf", "source", "scope", "mode", "environment", "ranges"):
        prep.add_argument("--" + name, required=True)
    prep.add_argument("--model-id")
    args = parser.parse_args(argv)
    try:
        if args.command == "register":
            register(read(args.record))
            print('{"registered": true, "egress_enabled": false}')
            return 0
        result = prepare(args.work_id, args.pdf, args.source, args.scope, read(args.ranges), args.mode, args.environment, args.model_id)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result["decision"] == "allowed" else 2
    except (OSError, ValueError, TypeError, KeyError):
        print('{"decision": "blocked", "reason": "invalid_local_input"}')
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
