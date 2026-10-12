"""PDF validation: header sniffing, EOF check, size floor, page-count scan.

Pure standard library. The page counter scans raw bytes and (when needed)
inflated object streams; it is a best-effort check, and `method` records how
the count was obtained. When the count cannot be determined, page_count is
None and validation still passes on header/EOF/size — the acquisition record
notes the reduced check level.
"""

from __future__ import annotations

import hashlib
import re
import zlib
from pathlib import Path

MIN_PDF_SIZE = 8192

PAGE_RE = re.compile(rb"/Type\s*/Page(?![s\w])")
STREAM_RE = re.compile(rb"stream\r?\n")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(256 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sniff_pdf(path: Path) -> bool:
    with open(path, "rb") as f:
        head = f.read(1024)
    return head.lstrip().startswith(b"%PDF-")


def has_eof_marker(path: Path) -> bool:
    size = Path(path).stat().st_size
    with open(path, "rb") as f:
        if size > 2048:
            f.seek(-2048, 2)
        tail = f.read(2048)
    return b"%%EOF" in tail


def count_pages(path: Path):
    """Return (count|None, method)."""
    data = Path(path).read_bytes()
    raw_count = len(PAGE_RE.findall(data))
    if raw_count > 0:
        return raw_count, "raw_scan"
    total = 0
    found_any = False
    for m in STREAM_RE.finditer(data):
        start = m.end()
        end = data.find(b"endstream", start)
        if end == -1:
            continue
        raw = data[start:end].rstrip(b"\r\n")
        if len(raw) > 8 * 1024 * 1024:
            continue
        try:
            dec = zlib.decompress(raw)
        except Exception:
            continue
        found_any = True
        total += len(PAGE_RE.findall(dec))
    if found_any and total > 0:
        return total, "objstm_scan"
    return None, "undetermined"


def validate_pdf(path: Path, *, min_size: int = MIN_PDF_SIZE) -> dict:
    """Validate a candidate PDF file. Never raises for ordinary failures."""
    result = {
        "path": str(path),
        "is_pdf": False,
        "has_eof": False,
        "size": None,
        "page_count": None,
        "page_count_method": None,
        "checks": [],
        "ok": False,
    }
    p = Path(path)
    if not p.exists() or not p.is_file():
        result["checks"].append("missing_file")
        return result
    size = p.stat().st_size
    result["size"] = size
    if not sniff_pdf(p):
        result["checks"].append("no_pdf_header")
        return result
    result["is_pdf"] = True
    result["checks"].append("pdf_header_ok")
    if size < min_size:
        result["checks"].append("too_small")
        return result
    result["checks"].append("size_ok")
    if not has_eof_marker(p):
        result["checks"].append("no_eof_marker")
        return result
    result["has_eof"] = True
    result["checks"].append("eof_ok")
    count, method = count_pages(p)
    result["page_count"] = count
    result["page_count_method"] = method
    if count is not None and count < 1:
        result["checks"].append("zero_pages")
        return result
    if count is None:
        result["checks"].append("page_count_undetermined")
    else:
        result["checks"].append("page_count_ok")
    result["ok"] = True
    return result
