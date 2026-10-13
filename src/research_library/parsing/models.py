"""Docling model-weights download into the authorized local cache.

This is the ONLY command in the parsing feature that may touch the network,
and it must be invoked explicitly (``research parse models``). Scope is
limited to the weights the configured pipeline actually runs (issue #3
authorization): the layout model and TableFormer. OCR / picture-classifier /
code-formula model families stay un-downloaded unless a future, separately
authorized decision enables them. Weights come from the Docling-pinned
Hugging Face repositories.

Everything is written inside a user-designated artifacts directory (default:
CHILDEVIDENCE_PARSING_MODELS_DIR or <data>/parse-models). PDF files and their
content are never transmitted. After download, every file is hashed into
models-manifest.json so offline runs can verify what they load.

The download mechanism reuses Docling's own downloader (so repo ids, pinned
revisions and directory layout stay exactly what docling expects); this
module only adds the cache location, the mirror endpoint and the integrity
manifest.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_HF_ENDPOINT = "https://hf-mirror.com"  # POC-audited mirror for this machine


def _hash_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def build_manifest(artifacts_dir: Path) -> dict:
    files = {}
    for p in sorted(Path(artifacts_dir).rglob("*")):
        if p.is_file() and p.name != "models-manifest.json":
            files[str(p.relative_to(artifacts_dir)).replace("\\", "/")] = {
                "sha256": _hash_file(p),
                "size_bytes": p.stat().st_size,
            }
    return {
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "docling pinned model repositories (downloaded via docling's own downloader)",
        "endpoint_env": os.environ.get("HF_ENDPOINT"),
        "docling_version": _docling_version(),
        "files": files,
        "verification": (
            "verify with: research parse models --verify-only --artifacts-dir <dir> "
            "(recomputes every file hash and compares to this manifest)"
        ),
    }


def _docling_version() -> str | None:
    try:
        import docling
        return getattr(docling, "__version__", None)
    except Exception:
        return None


def verify_manifest(artifacts_dir: Path) -> tuple[bool, list[str]]:
    """Recompute hashes and compare against models-manifest.json."""
    mf_path = Path(artifacts_dir) / "models-manifest.json"
    if not mf_path.exists():
        return False, ["models-manifest.json not found; run 'research parse models' first"]
    manifest = json.loads(mf_path.read_text(encoding="utf-8"))
    problems = []
    for rel, meta in (manifest.get("files") or {}).items():
        p = Path(artifacts_dir) / rel
        if not p.exists():
            problems.append(f"missing file: {rel}")
            continue
        if _hash_file(p) != meta.get("sha256"):
            problems.append(f"hash mismatch: {rel}")
    return (not problems), problems


def download_models(artifacts_dir: Path, *, hf_endpoint: str | None = None) -> dict:
    """Download Docling runtime weights into artifacts_dir (explicit network op)."""
    artifacts_dir = Path(artifacts_dir)
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    # Keep every HF cache inside the authorized directory as well.
    os.environ["HF_HOME"] = str(artifacts_dir / "hf-home")
    os.environ.setdefault("HF_ENDPOINT", hf_endpoint or DEFAULT_HF_ENDPOINT)
    # The mirror endpoint cannot serve the Xet CAS protocol (cas-server
    # 401s); force the classic HTTP download path. Integrity is enforced by
    # the per-file SHA-256 manifest written below either way.
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
    # This command is the explicit authorization boundary: disable offline guards.
    os.environ.pop("HF_HUB_OFFLINE", None)
    os.environ.pop("TRANSFORMERS_OFFLINE", None)

    via = None
    # Strategy 1: docling's own CLI tool module (keeps repo pins with docling).
    # Only the model families the configured pipeline runs: layout +
    # tableformer (OCR is disabled in this pipeline; enrichment families are
    # separate opt-in decisions).
    r = subprocess.run(
        [sys.executable, "-m", "docling.cli.tools", "models", "download",
         "--output-dir", str(artifacts_dir), "layout", "tableformer"],
        capture_output=True, text=True,
    )
    if r.returncode == 0:
        via = "docling.cli.tools models download (layout,tableformer)"
    else:
        # Strategy 2: docling's programmatic downloader, same pins and scope.
        try:
            from docling.utils.model_downloader import download_models as _dl  # type: ignore

            _dl(
                output_dir=artifacts_dir,
                with_layout=True,
                with_tableformer=True,
                with_tableformer_v2=False,
                with_code_formula=False,
                with_picture_classifier=False,
                with_rapidocr=False,
                with_easyocr=False,
            )
            via = "docling.utils.model_downloader (layout,tableformer)"
        except Exception as e:
            raise RuntimeError(
                "Docling model download failed via both strategies. "
                f"cli.tools rc={r.returncode} stderr_tail={r.stderr[-800:]!r}; "
                f"model_downloader error={e!r}"
            ) from e

    manifest = build_manifest(artifacts_dir)
    manifest["downloaded_via"] = via
    (artifacts_dir / "models-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    return {
        "artifacts_dir": str(artifacts_dir),
        "via": via,
        "hf_endpoint": os.environ.get("HF_ENDPOINT"),
        "files": len(manifest["files"]),
        "total_bytes": sum(m["size_bytes"] for m in manifest["files"].values()),
        "manifest": str(artifacts_dir / "models-manifest.json"),
    }
