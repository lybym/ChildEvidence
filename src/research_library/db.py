"""SQLite storage: schema, connection and small helpers.

The SQLite database at data/research-library/library.sqlite is the source of
truth. JSON-encoded TEXT columns hold arrays/objects. All timestamps are
UTC ISO-8601 strings.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS works (
  internal_id TEXT PRIMARY KEY,
  doi TEXT COLLATE NOCASE UNIQUE,
  pmid TEXT,
  pmcid TEXT,
  openalex_id TEXT UNIQUE,
  eric_id TEXT,
  s2_id TEXT,
  title TEXT NOT NULL,
  authors TEXT NOT NULL DEFAULT '[]',
  publication_date TEXT,
  publication_year INTEGER,
  journal_or_publisher TEXT,
  volume TEXT,
  issue TEXT,
  pages TEXT,
  issn TEXT DEFAULT '[]',
  language TEXT,
  abstract TEXT,
  document_type TEXT,
  research_domains TEXT DEFAULT '[]',
  topic_tags TEXT DEFAULT '[]',
  theoretical_frameworks TEXT DEFAULT '[]',
  study_design TEXT,
  population TEXT,
  participant_age_range TEXT,
  sample_size INTEGER,
  geographic_context TEXT,
  peer_review_status TEXT,
  metadata_status TEXT DEFAULT 'unverified',
  cited_by_count INTEGER,
  discovery_source TEXT,
  query_key TEXT,
  research_question TEXT,
  main_findings TEXT,
  effect_size TEXT,
  limitations TEXT,
  evidence_category TEXT,
  applicability_to_lumithink TEXT,
  review_status TEXT DEFAULT 'unreviewed',
  reviewer_notes TEXT,
  access_status TEXT DEFAULT 'pending',
  source_urls TEXT DEFAULT '[]',
  canonical_url TEXT,
  pdf_url TEXT,
  local_pdf_path TEXT,
  pdf_version TEXT,
  license TEXT,
  sha256 TEXT,
  pdf_file_size INTEGER,
  pdf_page_count INTEGER,
  discovered_at TEXT,
  last_checked_at TEXT,
  downloaded_at TEXT,
  retrieval_errors TEXT DEFAULT '[]',
  retraction_status TEXT DEFAULT 'unknown',
  expression_of_concern INTEGER DEFAULT 0,
  conflicting_metadata TEXT,
  unverified_claims TEXT,
  human_review_required INTEGER DEFAULT 0,
  title_norm TEXT,
  first_author_surname TEXT,
  record_status TEXT DEFAULT 'candidate',
  merge_conflict INTEGER DEFAULT 0,
  raw_sources TEXT DEFAULT '{}',
  ingestion_notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_works_title_norm ON works(title_norm);
CREATE INDEX IF NOT EXISTS idx_works_record_status ON works(record_status);
CREATE INDEX IF NOT EXISTS idx_works_access ON works(access_status);
CREATE INDEX IF NOT EXISTS idx_works_year ON works(publication_year);

CREATE TABLE IF NOT EXISTS manual_queue (
  internal_id TEXT PRIMARY KEY REFERENCES works(internal_id),
  priority INTEGER DEFAULT 5,
  reason TEXT,
  search_hint TEXT,
  created_at TEXT
);

CREATE TABLE IF NOT EXISTS download_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  internal_id TEXT,
  url TEXT,
  attempt INTEGER,
  status TEXT,
  http_status INTEGER,
  content_type TEXT,
  file_size INTEGER,
  sha256 TEXT,
  message TEXT,
  at TEXT
);

CREATE TABLE IF NOT EXISTS api_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source TEXT,
  endpoint TEXT,
  http_status INTEGER,
  ok INTEGER,
  ms INTEGER,
  at TEXT,
  error TEXT
);

CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT,
  started_at TEXT,
  finished_at TEXT,
  notes TEXT
);
"""

JSON_FIELDS = {
    "authors", "issn", "research_domains", "topic_tags", "theoretical_frameworks",
    "source_urls", "retrieval_errors",
}
JSON_OBJECT_FIELDS = {"raw_sources"}


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def connect(db_path: Path) -> sqlite3.Connection:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def get_work(conn: sqlite3.Connection, internal_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM works WHERE internal_id=?", (internal_id,)).fetchone()


def find_by_doi(conn: sqlite3.Connection, doi: str) -> sqlite3.Row | None:
    if not doi:
        return None
    return conn.execute("SELECT * FROM works WHERE doi=?", (doi,)).fetchone()


def update_work(conn: sqlite3.Connection, internal_id: str, **fields) -> None:
    if not fields:
        return
    cols, vals = [], []
    for k, v in fields.items():
        if k not in WORK_COLUMNS:
            raise KeyError(f"unknown work column: {k}")
        if k in JSON_FIELDS or k in JSON_OBJECT_FIELDS:
            v = json.dumps(v, ensure_ascii=False) if v is not None else None
        cols.append(f"{k}=?")
        vals.append(v)
    vals.append(internal_id)
    conn.execute(f"UPDATE works SET {', '.join(cols)} WHERE internal_id=?", vals)
    conn.commit()


WORK_COLUMNS = [
    "internal_id", "doi", "pmid", "pmcid", "openalex_id", "eric_id", "s2_id",
    "title", "authors", "publication_date", "publication_year",
    "journal_or_publisher", "volume", "issue", "pages", "issn", "language",
    "abstract", "document_type", "research_domains", "topic_tags",
    "theoretical_frameworks", "study_design", "population",
    "participant_age_range", "sample_size", "geographic_context",
    "peer_review_status", "metadata_status", "cited_by_count",
    "discovery_source", "query_key",
    "research_question", "main_findings", "effect_size",
    "limitations", "evidence_category", "applicability_to_lumithink",
    "review_status", "reviewer_notes", "access_status", "source_urls",
    "canonical_url", "pdf_url", "local_pdf_path", "pdf_version", "license",
    "sha256", "pdf_file_size", "pdf_page_count", "discovered_at",
    "last_checked_at", "downloaded_at", "retrieval_errors",
    "retraction_status", "expression_of_concern", "conflicting_metadata",
    "unverified_claims", "human_review_required", "title_norm",
    "first_author_surname", "record_status", "merge_conflict", "raw_sources",
    "ingestion_notes",
]


def row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    for k in list(d.keys()):
        if k in JSON_FIELDS or k in JSON_OBJECT_FIELDS:
            try:
                d[k] = json.loads(d[k]) if d[k] else ([] if k in JSON_FIELDS else {})
            except (TypeError, json.JSONDecodeError):
                d[k] = [] if k in JSON_FIELDS else {}
    return d


def append_json_list(conn, internal_id: str, field: str, values: list, *, unique: bool = True) -> None:
    if field not in JSON_FIELDS:
        raise KeyError(field)
    row = get_work(conn, internal_id)
    current = json.loads(row[field]) if row[field] else []
    for v in values:
        if v is None:
            continue
        if unique and v in current:
            continue
        current.append(v)
    update_work(conn, internal_id, **{field: current})


def log_download(conn, internal_id, url, attempt, status, http_status, content_type,
                 file_size, sha256, message) -> None:
    conn.execute(
        "INSERT INTO download_log (internal_id, url, attempt, status, http_status, content_type,"
        " file_size, sha256, message, at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (internal_id, url, attempt, status, http_status, content_type, file_size, sha256, message, now_iso()),
    )
    conn.commit()


def start_run(conn, kind: str) -> int:
    cur = conn.execute("INSERT INTO runs (kind, started_at) VALUES (?,?)", (kind, now_iso()))
    conn.commit()
    return cur.lastrowid


def finish_run(conn, run_id: int, notes: str = "") -> None:
    conn.execute("UPDATE runs SET finished_at=?, notes=? WHERE id=?", (now_iso(), notes, run_id))
    conn.commit()
