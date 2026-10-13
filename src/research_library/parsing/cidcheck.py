"""Text-quality heuristics: CID mojibake, suspicious scripts, zero-text pages.

Pure standard library. These checks *flag* problems for human review; they
never "fix" text and never decide that a document is correct. Heuristics are
conservative: a flag is a warning signal, not a verdict.
"""

from __future__ import annotations

# Unicode blocks that are strong mojibake signals in CJK text-extraction
# pipelines when they appear in documents that should be zh/en content.
_PUA_RANGES = ((0xE000, 0xF8FF),)           # Private Use Area
_REPLACEMENT_CHAR = "\ufffd"                # U+FFFD, typical lossy-mapping marker
_SUSPICIOUS_SCRIPT_RANGES = (
    (0x0F00, 0x0FFF),   # Tibetan: observed in POC pypdf CID garbage
    (0x1B000, 0x1B0FF), # Kana supplement: rare, typical of broken CMaps
    (0x2F800, 0x2FA1F), # CJK compat ideographs supplement: rare
)

MIN_CHARS_FOR_RATIO = 200  # below this, ratio-based flags are noisy -> count-based

# A page with fewer printable chars than this is treated as text-less for
# text-layer heuristics (headings/numbers only pages still count as some text).
ZERO_TEXT_PAGE_CHARS = 1
# A document with fewer total chars than this is "no_text_extracted".
ZERO_TEXT_DOC_CHARS = 50


def _in_ranges(ch: str, ranges) -> bool:
    o = ord(ch)
    return any(lo <= o <= hi for lo, hi in ranges)


def char_ratio(text: str, ranges) -> float:
    if not text:
        return 0.0
    hits = sum(1 for ch in text if _in_ranges(ch, ranges))
    return hits / len(text)


def count_char(text: str, ch: str) -> int:
    return text.count(ch)


def page_text_issues(text: str) -> list[str]:
    """Return issue codes for one page of extracted text (may be empty)."""
    issues: list[str] = []
    if len(text) < ZERO_TEXT_PAGE_CHARS:
        # Caller decides whether empty text on this page is expected; here we
        # only mark it so pages without any text layer get flagged upstream.
        issues.append("page_no_text")
        return issues
    n_repl = count_char(text, _REPLACEMENT_CHAR)
    if n_repl > 0 and (n_repl / len(text) > 0.005 or len(text) < MIN_CHARS_FOR_RATIO):
        issues.append("replacement_chars")
    pua_ratio = char_ratio(text, _PUA_RANGES)
    if pua_ratio > 0.01 or (pua_ratio > 0 and len(text) < MIN_CHARS_FOR_RATIO):
        issues.append("pua_chars")
    if any(_in_ranges(ch, _SUSPICIOUS_SCRIPT_RANGES) for ch in text):
        issues.append("suspicious_script_mix")
    return issues


def looks_cjk(text: str) -> bool:
    """Heuristic: does the text look Chinese (CJK ideograph ratio)?"""
    if not text:
        return False
    cjk = sum(1 for ch in text if 0x4E00 <= ord(ch) <= 0x9FFF)
    return cjk / len(text) > 0.10


def looks_english(text: str) -> bool:
    if not text:
        return False
    latin = sum(1 for ch in text if ("a" <= ch <= "z") or ("A" <= ch <= "Z"))
    return latin / len(text) > 0.40


def document_language(pages_text: list[str]) -> str:
    """Best-effort language label for the whole document (never a claim)."""
    joined = "\n".join(pages_text)
    cjk = looks_cjk(joined)
    en = looks_english(joined)
    if cjk and en:
        return "mixed"
    if cjk:
        return "zh"
    if en:
        return "en"
    return "unknown"


def document_issues(pages_issues: list[list[str]], total_chars: int) -> list[dict]:
    """Aggregate page-level issue flags into document-level records."""
    out: list[dict] = []
    tally: dict[str, int] = {}
    for page_issues in pages_issues:
        for code in page_issues:
            if code == "page_no_text":
                continue  # handled via pages[].text_present, not an aggregate issue
            tally[code] = tally.get(code, 0) + 1
    for code, n_pages in sorted(tally.items()):
        out.append({
            "code": code,
            "scope": "document",
            "pages_affected": n_pages,
            "detail": {
                "replacement_chars": "U+FFFD replacement characters found (lossy CID mapping suspected)",
                "pua_chars": "Private-Use-Area characters found (unmapped glyphs suspected)",
                "suspicious_script_mix": "unexpected script blocks found (broken CMap suspected)",
            }.get(code, code),
        })
    if total_chars < ZERO_TEXT_DOC_CHARS:
        out.append({
            "code": "no_text_extracted",
            "scope": "document",
            "pages_affected": sum(1 for pi in pages_issues if "page_no_text" in pi),
            "detail": "total extracted text below threshold; scanned pages or extraction failure suspected",
        })
    return out
