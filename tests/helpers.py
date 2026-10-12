"""Shared test helpers: minimal valid PDFs and workspace-local temp dirs.

Note: the DSH sandbox denies writes inside tempfile.mkdtemp() directories, so
tests create fresh directories under research-library/.tmp-test/ instead.
"""

import shutil
import uuid
from pathlib import Path

TEST_TMP_ROOT = Path(__file__).resolve().parent.parent / ".tmp-test"


def make_tmp_dir(prefix: str = "t-") -> Path:
    TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
    d = TEST_TMP_ROOT / f"{prefix}{uuid.uuid4().hex[:8]}"
    d.mkdir(parents=True, exist_ok=False)
    return d


PDF_TEMPLATE = """%PDF-1.4
{pad}%PDF-pad
1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj
2 0 obj << /Type /Pages /Kids [{kids}] /Count {count} >> endobj
{pages}trailer << /Root 1 0 R /Size {size} >>
%%EOF
"""


def make_pdf(pages: int = 1) -> bytes:
    """Build a tiny valid-looking PDF with `pages` page objects (raw scan).

    Padding comment lines are placed between the header and the objects so the
    %%EOF marker stays in the file tail (required by validate_pdf).
    """
    kids = " ".join(f"{3 + i} 0 R" for i in range(pages))
    page_objs = []
    for i in range(pages):
        obj_num = 3 + i
        page_objs.append(
            f"{obj_num} 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] >> endobj\n"
        )
    pad = "%" + "0" * (8 * 1024) + "\n"
    body = PDF_TEMPLATE.format(
        kids=kids,
        count=pages,
        pages="".join(page_objs),
        size=3 + pages,
        pad=pad,
    )
    return body.encode("latin-1")


JUNK_BYTES = b"this is not a pdf at all. " * 500
HTML_BYTES = (b"<html><head><title>Login</title></head><body>"
              b"Please sign in to download the PDF.</body></html>" * 40)
