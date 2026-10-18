#!/usr/bin/env python3
"""Thin CLI adapter for the child-evidence-reviewer Skill.

All business validation lives in the testable research core
(``research_library.review_contract``); this script only parses arguments,
prints JSON and maps exit codes. No model, network, parser or database writes.
preflight emits policy/hashes, never source text. finalize creates a fresh run.
Schema validation and quote matching do not establish scientific correctness.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import sys

SKILL_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = SKILL_ROOT.parents[2]
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from research_library.review_contract import (  # noqa: E402
    DEFAULT_SKILL_ROOT,
    FORCE_UNRESOLVED,
    KINDS,
    PERFORMED_EXECUTION_KINDS,
    PROTOCOLS,
    PROVENANCE_KEYS,
    REASONS,
    SOURCE_KEYS,
    VERSION,
    ReviewValidationError,
    canonical,
    citation_errors,
    default_output_root,
    digest,
    file_hash,
    finalize,
    frozen_files,
    input_digest,
    make_demo,
    output_digest,
    package_binding_errors,
    policy,
    preflight,
    read_json,
    schema_errors,
    selected_metadata,
    source_material,
    validate,
    verified_package,
)


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
