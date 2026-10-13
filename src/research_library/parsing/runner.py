"""Subprocess runner for isolated parser execution.

Usage (internal, called by pipeline.py):
    python -m research_library.parsing.runner <spec.json>

Spec JSON:
    {"pdf_path": str, "parser": str, "options": dict, "out_json": str,
     "models_dir": str|null, "offline": bool}

Writes the adapter intermediate document to out_json. On failure writes
out_json + ".error" with {"error_type", "message"} and exits non-zero.
This module runs INSIDE the child process; it keeps the parent's Python
environment free of docling imports and enables hard timeout enforcement.

Peak memory is self-measured here (own-process psapi query after parsing)
and attached as "_peak_memory_mb": the child is the authoritative source.
Cross-process queries from the parent can be virtualized under sandboxed
environments (they then report plausible-looking garbage, which must not
reach the provenance record — an honest null is used instead).
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 1:
        print("usage: python -m research_library.parsing.runner <spec.json>", file=sys.stderr)
        return 2
    spec_path = Path(argv[0])
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    out_json = Path(spec["out_json"])
    err_json = Path(str(out_json) + ".error")
    try:
        if spec.get("parser_module"):
            # documented test/debug hook: load a Parser class from a file
            import importlib.util

            mspec = importlib.util.spec_from_file_location(
                "_ce03_test_parser", spec["parser_module"])
            mod = importlib.util.module_from_spec(mspec)
            mspec.loader.exec_module(mod)
            adapter = getattr(mod, "Parser")()
        else:
            from .adapters import get_adapter

            adapter = get_adapter(
                spec["parser"],
                models_dir=Path(spec["models_dir"]) if spec.get("models_dir") else None,
                offline=bool(spec.get("offline", True)),
            )
        inter = adapter.parse(Path(spec["pdf_path"]), spec.get("options") or {})
        if isinstance(inter, dict):
            from .memory import get_self_peak_memory_mb

            peak = get_self_peak_memory_mb()
            if peak is not None:
                # consumed by normalize_intermediate -> provenance.peak_memory_mb
                inter["_peak_memory_mb"] = peak
        out_json.write_text(json.dumps(inter, ensure_ascii=False), encoding="utf-8")
        return 0
    except Exception as e:  # noqa: BLE001 - child boundary: report and exit
        err_json.write_text(
            json.dumps({
                "error_type": type(e).__name__,
                "message": str(e)[:2000],
                "traceback": traceback.format_exc()[-4000:],
            }, ensure_ascii=False),
            encoding="utf-8",
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
