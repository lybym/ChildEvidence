"""Blind human review tooling for CE-02 (A2, 80-item enriched sample).

离线盲法人工复核的存储与流程语义。设计边界（全部为硬约束）：

- **与主事实源严格隔离**：标注数据保存在独立 SQLite 文件
  （默认 ``<data_dir>/review/annotations.sqlite``）。本模块不导入
  ``research_library.db``、不读写 ``library.sqlite``、不迁移主库 schema
  （AGENTS #1/#11）；主库回写属于人工阶段，本模块只提供映射表（见
  ``CATALOG_MAPPING``），不执行任何主库写入。
- **盲法（ANNOTATION_GUIDE §2，DRAFT v1.1）**：标注库中不存在也不导入
  ``historical_label`` / ``stratum`` / 模型得分与排名。导入只接受白名单列；
  输入含泄漏列且非空时 fail-closed 拒绝（``BlindLeakError``）。
- **追加式审计（AGENTS #2）**：``annotation_events`` 只追加；数据库触发器
  拒绝 UPDATE/DELETE，修改通过 amendment 事件留痕。
- **标签层级（RESEARCH_METHODOLOGY §7，DRAFT v1.1）**：脚本录入的人工判定
  一律 ``provisional``/``single_human``。**不存在任何把 provisional 自动升为
  gold 的代码路径**；gold 只能经 ``record_signoff`` 登记人工签署凭据
  （独立复核一致或裁决完成 + 知识负责人签署文件），即 LT-03 的机器校验。
- **DRAFT 边界（AGENTS #23）**：本模块实现的是 DRAFT v1.1 规程的离线工具
  载体；规程未经人工批准前不生效，工具不得、也不会代填任何判定。
"""

from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1

STORE_FILENAME = "annotations.sqlite"

# 决策值域（ANNOTATION_GUIDE §3，标注阶段语义；回写映射见 CATALOG_MAPPING）
DECISIONS = ("relevant", "boundary", "not_relevant", "undecided")

# 置信度值域
CONFIDENCE_LEVELS = ("high", "medium", "low")

# 理由代码表（ANNOTATION_GUIDE §5，与 SCREENING_PROTOCOL §4 对齐；DRAFT v1.1）
REASON_CODES = {
    "relevant": ("A01", "A02", "A03"),
    "boundary": ("B01", "B02", "B03"),
    "not_relevant": ("R01", "R02", "R03", "R04", "R05", "R06"),
    "undecided": ("P01", "U01"),
}

# 轨道 A（catalog 层）回写映射（ANNOTATION_GUIDE §1）。工具不执行回写；
# boundary/undecided 保守映射为 pending，由人工阶段决定，禁止脚本自动定论。
CATALOG_MAPPING = {
    "relevant": "ingested",
    "not_relevant": "rejected",
    "boundary": "pending",
    "undecided": "pending",
}

# 盲法导入白名单：只有这些列会进入标注库。
BLIND_COLUMNS = (
    "queue_id",
    "sample_id",
    "doi",
    "title",
    "abstract",
    "language",
    "publication_year",
    "review_task",
)

# 泄漏列：任何一列存在且非空 → 拒绝导入（fail-closed）。
LEAK_COLUMNS = (
    "historical_label",
    "stratum",
    "model_score",
    "asreview_score",
    "asreview_rank",
    "model_rank",
    "rank",
    "score",
    "relevance_order",
)

# 判定预填列：上游不得替审核者预填这些内容。
# （review_status=pending 是合法的队列初始状态，不算预填。）
PREFILL_COLUMNS = ("gold_label", "reviewer", "decision", "reason_code", "reason_text")


class ReviewError(Exception):
    """Base class for user-facing review tool errors."""


class BlindLeakError(ReviewError):
    """Import payload carries blinded-out information (historical labels etc.)."""


class DuplicateSubmissionError(ReviewError):
    """The same reviewer already submitted a judgement for this item."""


class NotLockedError(ReviewError):
    """Unblinding audit attempted before all labels are locked."""


class GateViolationError(ReviewError):
    """A human-permission gate was violated (e.g. gold without sign-off)."""


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Store schema (independent of the main library database)
# ---------------------------------------------------------------------------

STORE_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS queue_items (
  queue_id TEXT PRIMARY KEY,
  sample_id TEXT NOT NULL,
  doi TEXT,
  title TEXT NOT NULL,
  abstract TEXT,
  language TEXT,
  publication_year INTEGER,
  review_task TEXT,
  imported_at TEXT NOT NULL,
  source_csv TEXT NOT NULL,
  source_sha256 TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS annotation_events (
  event_id INTEGER PRIMARY KEY AUTOINCREMENT,
  queue_id TEXT NOT NULL REFERENCES queue_items(queue_id),
  event_kind TEXT NOT NULL,
  decision TEXT,
  reason_code TEXT,
  reason_text TEXT,
  confidence TEXT,
  notes TEXT,
  reviewer_id TEXT,
  reviewed_at TEXT NOT NULL,
  label_tier TEXT NOT NULL DEFAULT 'provisional',
  produced_by_kind TEXT NOT NULL DEFAULT 'single_human',
  ai_assisted INTEGER NOT NULL DEFAULT 0,
  adjudicator_id TEXT,
  sign_off_by TEXT,
  sign_off_date TEXT,
  evidence_file TEXT,
  payload TEXT
);

CREATE TABLE IF NOT EXISTS review_state (
  queue_id TEXT PRIMARY KEY REFERENCES queue_items(queue_id),
  status TEXT NOT NULL DEFAULT 'pending',
  decision TEXT,
  reason_code TEXT,
  reason_text TEXT,
  confidence TEXT,
  notes TEXT,
  reviewer_id TEXT,
  reviewed_at TEXT,
  label_tier TEXT,
  produced_by_kind TEXT,
  updated_at TEXT
);

CREATE TABLE IF NOT EXISTS session_state (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  paused INTEGER NOT NULL DEFAULT 0,
  last_queue_id TEXT,
  last_action_at TEXT,
  note TEXT
);

CREATE TABLE IF NOT EXISTS disagreements (
  queue_id TEXT PRIMARY KEY REFERENCES queue_items(queue_id),
  reviewer_a TEXT NOT NULL,
  decision_a TEXT NOT NULL,
  reason_code_a TEXT,
  reviewer_b TEXT NOT NULL,
  decision_b TEXT NOT NULL,
  reason_code_b TEXT,
  registered_at TEXT NOT NULL,
  resolution TEXT,
  adjudicator_id TEXT
);

CREATE TRIGGER IF NOT EXISTS annotation_events_no_update
BEFORE UPDATE ON annotation_events
BEGIN
  SELECT RAISE(ABORT, 'annotation_events is append-only: write an amendment event instead');
END;

CREATE TRIGGER IF NOT EXISTS annotation_events_no_delete
BEFORE DELETE ON annotation_events
BEGIN
  SELECT RAISE(ABORT, 'annotation_events is append-only: history cannot be erased');
END;

CREATE TRIGGER IF NOT EXISTS disagreements_no_delete
BEFORE DELETE ON disagreements
BEGIN
  SELECT RAISE(ABORT, 'disagreements is append-only: record a resolution instead');
END;
"""

# schema_meta -> value key for the store schema version
_META_SCHEMA_VERSION = "schema_version"


def default_store_path(data_dir: Path) -> Path:
    """Independent annotation store location (never the main library.sqlite)."""
    return Path(data_dir) / "review" / STORE_FILENAME


def connect_store(store_path: Path) -> sqlite3.Connection:
    """Open (or create) the annotation store with append-only guards."""
    store_path = Path(store_path)
    store_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(store_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(STORE_SCHEMA)
    row = conn.execute(
        "SELECT value FROM schema_meta WHERE key=?", (_META_SCHEMA_VERSION,)
    ).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO schema_meta (key, value) VALUES (?,?)",
            (_META_SCHEMA_VERSION, str(SCHEMA_VERSION)),
        )
    elif int(row["value"]) > SCHEMA_VERSION:
        conn.close()
        raise ReviewError(
            f"annotation store schema_version {row['value']} is newer than "
            f"supported {SCHEMA_VERSION}"
        )
    conn.execute(
        "INSERT INTO session_state (id, paused) VALUES (1, 0) "
        "ON CONFLICT(id) DO NOTHING"
    )
    conn.commit()
    return conn


def migrate_store(store_path: Path) -> int:
    """Idempotent schema (re)build for an existing store; returns schema_version.

    v1 is the initial layout, so "migration" is the guarded CREATE IF NOT
    EXISTS pass plus the version stamp. Forward migration for future versions
    belongs in this function (AGENTS #11 applies to this store's own layout).
    """
    conn = connect_store(store_path)
    try:
        row = conn.execute(
            "SELECT value FROM schema_meta WHERE key=?", (_META_SCHEMA_VERSION,)
        ).fetchone()
        version = int(row["value"]) if row else SCHEMA_VERSION
        events = conn.execute("SELECT COUNT(*) AS n FROM annotation_events").fetchone()["n"]
        if events == 0:
            conn.execute(
                "INSERT OR REPLACE INTO schema_meta (key, value) VALUES (?,?)",
                (_META_SCHEMA_VERSION, str(SCHEMA_VERSION)),
            )
            version = SCHEMA_VERSION
        conn.commit()
        return version
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Blind import (read-only consumer of the blinded CSV)
# ---------------------------------------------------------------------------

def _cell(value) -> str:
    return (value or "").strip()


def import_blinded_csv(store_path: Path, csv_path: Path, *, force: bool = False) -> dict:
    """Import the blinded review queue (read-only w.r.t. the CSV file).

    Fail-closed rules:
    - any LEAK_COLUMNS cell with a non-empty value -> BlindLeakError;
    - any PREFILL_COLUMNS cell with a non-empty value -> BlindLeakError
      (an upstream party must not pre-fill judgements);
    - importing a *different* queue into a non-empty store is refused
      (one store, one frozen queue snapshot).
    Re-importing the identical CSV is an idempotent no-op.
    """
    csv_path = Path(csv_path)
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        fieldnames = [fn.strip() for fn in (reader.fieldnames or [])]
        missing = [c for c in ("queue_id", "sample_id", "title", "review_task") if c not in fieldnames]
        if missing:
            raise ReviewError(f"blinded CSV missing required columns: {missing}")
        rows = list(reader)

    sha = hashlib.sha256(csv_path.read_bytes()).hexdigest()

    # Leak detection before anything touches the store.
    for idx, row in enumerate(rows, start=2):  # header is line 1
        for col in LEAK_COLUMNS:
            for key in row:
                if key and key.strip().lower() == col and _cell(row.get(key)):
                    raise BlindLeakError(
                        f"blinded CSV row {idx} column '{col}' is non-empty; "
                        "this file is not the blinded view (historical labels / "
                        "strata / model order must never reach the annotation store)"
                    )
        for col in PREFILL_COLUMNS:
            for key in row:
                if key and key.strip().lower() == col and _cell(row.get(key)):
                    raise BlindLeakError(
                        f"blinded CSV row {idx} column '{col}' is pre-filled; "
                        "judgement fields must stay empty in a blinded queue"
                    )

    conn = connect_store(store_path)
    try:
        existing_sources = {
            r["source_sha256"]: r["source_csv"]
            for r in conn.execute("SELECT DISTINCT source_sha256, source_csv FROM queue_items")
        }
        count = conn.execute("SELECT COUNT(*) AS n FROM queue_items").fetchone()["n"]
        if count and sha in existing_sources:
            return {"imported": 0, "skipped": count, "idempotent": True, "total": count}
        if count and sha not in existing_sources and not force:
            raise ReviewError(
                "store already holds a different queue snapshot; refusing to mix "
                "queues (use a fresh store)"
            )

        imported = 0
        seen_ids: set[str] = set()
        for idx, row in enumerate(rows, start=2):
            qid = _cell(row.get("queue_id"))
            if not qid:
                raise ReviewError(f"blinded CSV row {idx}: empty queue_id")
            if qid in seen_ids:
                raise ReviewError(f"blinded CSV row {idx}: duplicate queue_id {qid!r}")
            seen_ids.add(qid)
            year_raw = _cell(row.get("publication_year"))
            year = int(year_raw) if year_raw.isdigit() else None
            conn.execute(
                "INSERT INTO queue_items (queue_id, sample_id, doi, title, abstract, "
                "language, publication_year, review_task, imported_at, source_csv, "
                "source_sha256) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    qid,
                    _cell(row.get("sample_id")) or qid,
                    _cell(row.get("doi")) or None,
                    _cell(row.get("title")),
                    _cell(row.get("abstract")) or None,
                    _cell(row.get("language")) or None,
                    year,
                    _cell(row.get("review_task")),
                    now_iso(),
                    str(csv_path),
                    sha,
                ),
            )
            imported += 1
        conn.commit()
        return {"imported": imported, "skipped": 0, "idempotent": False, "total": imported}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Judgement entry (append-only events; provisional tier enforced)
# ---------------------------------------------------------------------------

def _validate_judgement(decision: str, reason_code: str, reason_text: str,
                        confidence: str) -> None:
    if decision not in DECISIONS:
        raise ReviewError(
            f"decision must be one of {DECISIONS}, got {decision!r}"
        )
    allowed_codes = REASON_CODES[decision]
    if reason_code not in allowed_codes:
        raise ReviewError(
            f"reason code {reason_code!r} is not valid for decision {decision!r} "
            f"(allowed: {allowed_codes}); see ANNOTATION_GUIDE §5"
        )
    if not reason_text or len(reason_text.strip()) < 2:
        raise ReviewError("reason_text is mandatory (one sentence) for every decision")
    if confidence not in CONFIDENCE_LEVELS:
        raise ReviewError(f"confidence must be one of {CONFIDENCE_LEVELS}, got {confidence!r}")


def _require_item(conn: sqlite3.Connection, queue_id: str) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM queue_items WHERE queue_id=?", (queue_id,)
    ).fetchone()
    if row is None:
        raise ReviewError(f"unknown queue_id {queue_id!r} (import the blinded CSV first)")
    return row


def _latest_human_event(conn: sqlite3.Connection, queue_id: str, reviewer_id: str):
    return conn.execute(
        "SELECT * FROM annotation_events WHERE queue_id=? AND reviewer_id=? "
        "AND event_kind IN ('judgement','amendment') ORDER BY event_id DESC LIMIT 1",
        (queue_id, reviewer_id),
    ).fetchone()


def judge(store_path: Path, queue_id: str, *, reviewer_id: str, decision: str,
          reason_code: str, reason_text: str, confidence: str = "medium",
          notes: str | None = None, amend: bool = False) -> dict:
    """Append one human judgement; the item becomes a provisional human label.

    No code path in this module can set label_tier above 'provisional' here.
    """
    if not reviewer_id or len(reviewer_id.strip()) < 2:
        raise ReviewError("reviewer_id is mandatory (audit trail, ANNOTATION_GUIDE §3)")
    reviewer_id = reviewer_id.strip()
    _validate_judgement(decision, reason_code, reason_text.strip(), confidence)

    conn = connect_store(store_path)
    try:
        _require_item(conn, queue_id)
        state = conn.execute(
            "SELECT status FROM review_state WHERE queue_id=?", (queue_id,)
        ).fetchone()
        if state is not None and state["status"] == "locked":
            raise NotLockedError(
                f"queue_id {queue_id!r} is locked; labels are fixed after the lock "
                "(adjudicate/amend BEFORE locking, then audit)"
            )
        prev = _latest_human_event(conn, queue_id, reviewer_id)
        if prev is not None and not amend:
            raise DuplicateSubmissionError(
                f"queue_id {queue_id!r} already has a judgement by {reviewer_id!r}; "
                "use amend=True (--amend) to append a correction (originals are kept)"
            )
        if amend and prev is None:
            raise ReviewError(
                f"queue_id {queue_id!r} has no prior judgement by {reviewer_id!r} "
                "to amend; submit the first judgement without --amend"
            )
        reviewed_at = now_iso()
        event_kind = "amendment" if amend else "judgement"
        payload = None
        if amend and prev is not None:
            payload = json.dumps(
                {"amends_event_id": prev["event_id"], "previous_decision": prev["decision"]},
                ensure_ascii=False,
            )
        cur = conn.execute(
            "INSERT INTO annotation_events (queue_id, event_kind, decision, "
            "reason_code, reason_text, confidence, notes, reviewer_id, reviewed_at, "
            "label_tier, produced_by_kind, ai_assisted, payload) "
            "VALUES (?,?,?,?,?,?,?,?,?,'provisional','single_human',0,?)",
            (queue_id, event_kind, decision, reason_code, reason_text.strip(),
             confidence, notes, reviewer_id, reviewed_at, payload),
        )
        conn.execute(
            "INSERT INTO review_state (queue_id, status, decision, reason_code, "
            "reason_text, confidence, notes, reviewer_id, reviewed_at, label_tier, "
            "produced_by_kind, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(queue_id) DO UPDATE SET status=excluded.status, "
            "decision=excluded.decision, reason_code=excluded.reason_code, "
            "reason_text=excluded.reason_text, confidence=excluded.confidence, "
            "notes=excluded.notes, reviewer_id=excluded.reviewer_id, "
            "reviewed_at=excluded.reviewed_at, label_tier=excluded.label_tier, "
            "produced_by_kind=excluded.produced_by_kind, updated_at=excluded.updated_at",
            (queue_id, "submitted", decision, reason_code, reason_text.strip(),
             confidence, notes, reviewer_id, reviewed_at, "provisional",
             "single_human", now_iso()),
        )
        conn.execute(
            "UPDATE session_state SET last_queue_id=?, last_action_at=?, paused=0 "
            "WHERE id=1",
            (queue_id, reviewed_at),
        )
        conn.commit()
        return {"event_id": cur.lastrowid, "event_kind": event_kind,
                "label_tier": "provisional", "reviewer_id": reviewer_id}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Session flow: next / pause / resume / progress / pending
# ---------------------------------------------------------------------------

def next_item(store_path: Path) -> dict | None:
    """Next pending item in queue order (blind: only blinded fields are exposed)."""
    conn = connect_store(store_path)
    try:
        row = conn.execute(
            "SELECT q.queue_id, q.sample_id, q.doi, q.title, q.abstract, q.language, "
            "q.publication_year, q.review_task "
            "FROM queue_items q LEFT JOIN review_state s ON s.queue_id = q.queue_id "
            "WHERE s.queue_id IS NULL OR s.status='pending' "
            "ORDER BY q.queue_id LIMIT 1"
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def pause(store_path: Path, note: str | None = None) -> dict:
    conn = connect_store(store_path)
    try:
        last = conn.execute(
            "SELECT queue_id FROM review_state ORDER BY updated_at DESC LIMIT 1"
        ).fetchone()
        at = now_iso()
        conn.execute(
            "UPDATE session_state SET paused=1, last_queue_id=?, last_action_at=?, "
            "note=? WHERE id=1",
            (last["queue_id"] if last else None, at, note),
        )
        conn.commit()
        remaining = conn.execute(
            "SELECT COUNT(*) AS n FROM queue_items q LEFT JOIN review_state s "
            "ON s.queue_id=q.queue_id WHERE s.queue_id IS NULL OR s.status='pending'"
        ).fetchone()["n"]
        nxt = conn.execute(
            "SELECT q.queue_id FROM queue_items q LEFT JOIN review_state s "
            "ON s.queue_id=q.queue_id WHERE s.queue_id IS NULL OR s.status='pending' "
            "ORDER BY q.queue_id LIMIT 1"
        ).fetchone()
        return {"paused": True, "resume_point": nxt["queue_id"] if nxt else None,
                "last_queue_id": last["queue_id"] if last else None,
                "remaining": remaining, "at": at}
    finally:
        conn.close()


def resume(store_path: Path) -> dict:
    conn = connect_store(store_path)
    try:
        row = conn.execute("SELECT * FROM session_state WHERE id=1").fetchone()
        conn.execute("UPDATE session_state SET paused=0 WHERE id=1")
        conn.commit()
        nxt = next_item(store_path)
        return {
            "was_paused": bool(row and row["paused"]),
            "resume_point": row["last_queue_id"] if row else None,
            "note": row["note"] if row else None,
            "next_queue_id": nxt["queue_id"] if nxt else None,
        }
    finally:
        conn.close()


def progress(store_path: Path) -> dict:
    conn = connect_store(store_path)
    try:
        total = conn.execute("SELECT COUNT(*) AS n FROM queue_items").fetchone()["n"]
        done = conn.execute(
            "SELECT COUNT(*) AS n FROM review_state WHERE status='submitted'"
        ).fetchone()["n"]
        undecided = conn.execute(
            "SELECT COUNT(*) AS n FROM review_state WHERE decision='undecided'"
        ).fetchone()["n"]
        locked = conn.execute(
            "SELECT COUNT(*) AS n FROM review_state WHERE status='locked'"
        ).fetchone()["n"]
        disagree = conn.execute("SELECT COUNT(*) AS n FROM disagreements").fetchone()["n"]
        paused = conn.execute(
            "SELECT paused FROM session_state WHERE id=1"
        ).fetchone()
        return {
            "total": total,
            "submitted": done,
            "remaining": total - done,
            "undecided": undecided,
            "locked": locked,
            "disagreements": disagree,
            "paused": bool(paused and paused["paused"]),
            "complete": total > 0 and done == total,
        }
    finally:
        conn.close()


def pending_queue(store_path: Path) -> list[dict]:
    """Undecided / P01 items awaiting full-text or a second pass (never dropped)."""
    conn = connect_store(store_path)
    try:
        rows = conn.execute(
            "SELECT q.queue_id, q.title, s.decision, s.reason_code, s.reason_text, "
            "s.reviewer_id, s.reviewed_at FROM queue_items q "
            "JOIN review_state s ON s.queue_id=q.queue_id "
            "WHERE s.decision='undecided' ORDER BY q.queue_id"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Second-reviewer comparison, disagreements, adjudication, sign-off
# ---------------------------------------------------------------------------

def compare_reviewers(store_path: Path) -> dict:
    """Compare independent judgements per item; register disagreements.

    一致 → 不动作（供人工走签署流程）；不一致 → 登记（保留双方原始意见，
    不覆盖），等待第三人裁决或知识负责人处理（ANNOTATION_GUIDE §7）。
    """
    conn = connect_store(store_path)
    try:
        events = conn.execute(
            "SELECT queue_id, reviewer_id, decision, reason_code, reviewed_at "
            "FROM annotation_events WHERE event_kind IN ('judgement','amendment') "
            "ORDER BY event_id"
        ).fetchall()
        by_item: dict[str, dict[str, dict]] = {}
        for ev in events:
            by_item.setdefault(ev["queue_id"], {})[ev["reviewer_id"]] = {
                "decision": ev["decision"],
                "reason_code": ev["reason_code"],
                "reviewed_at": ev["reviewed_at"],
            }
        new_disagreements = []
        agreements = 0
        for qid, reviewers in sorted(by_item.items()):
            if len(reviewers) < 2:
                continue
            ids = sorted(reviewers)
            a, b = reviewers[ids[0]], reviewers[ids[1]]
            if a["decision"] == b["decision"]:
                agreements += 1
                # independent double review with matching decisions satisfies the
                # independent_double_human gold flow (LT-03); the tier itself stays
                # provisional until the human sign-off is recorded.
                conn.execute(
                    "UPDATE review_state SET produced_by_kind="
                    "'independent_double_human', updated_at=? WHERE queue_id=?",
                    (now_iso(), qid),
                )
                continue
            known = conn.execute(
                "SELECT 1 FROM disagreements WHERE queue_id=?", (qid,)
            ).fetchone()
            if known:
                continue
            conn.execute(
                "INSERT INTO disagreements (queue_id, reviewer_a, decision_a, "
                "reason_code_a, reviewer_b, decision_b, reason_code_b, registered_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (qid, ids[0], a["decision"], a["reason_code"],
                 ids[1], b["decision"], b["reason_code"], now_iso()),
            )
            new_disagreements.append(qid)
        total_disagreements = conn.execute(
            "SELECT COUNT(*) AS n FROM disagreements"
        ).fetchone()["n"]
        conn.commit()
        return {
            "items_with_two_reviewers": sum(1 for v in by_item.values() if len(v) >= 2),
            "agreements": agreements,
            "new_disagreements": new_disagreements,
            "total_disagreements": total_disagreements,
        }
    finally:
        conn.close()


def list_disagreements(store_path: Path) -> list[dict]:
    conn = connect_store(store_path)
    try:
        rows = conn.execute("SELECT * FROM disagreements ORDER BY queue_id").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def record_adjudication(store_path: Path, queue_id: str, *, adjudicator_id: str,
                        decision: str, reason_code: str, reason_text: str,
                        notes: str | None = None) -> dict:
    """Register a third-party adjudication result (a human action, recorded verbatim).

    登记的是人工裁决**结果**：原始双方意见保留在 disagreements 表中不动。
    tier 仍为 provisional，直到知识负责人签署（record_signoff）。
    """
    if not adjudicator_id or len(adjudicator_id.strip()) < 2:
        raise ReviewError("adjudicator_id is mandatory")
    adjudicator_id = adjudicator_id.strip()
    _validate_judgement(decision, reason_code, reason_text.strip(), "medium")

    conn = connect_store(store_path)
    try:
        _require_item(conn, queue_id)
        state = conn.execute(
            "SELECT status FROM review_state WHERE queue_id=?", (queue_id,)
        ).fetchone()
        if state is not None and state["status"] == "locked":
            raise NotLockedError(
                f"queue_id {queue_id!r} is locked; adjudication must complete "
                "BEFORE the lock (unblinding audit depends on fixed labels)"
            )
        dis = conn.execute(
            "SELECT * FROM disagreements WHERE queue_id=?", (queue_id,)
        ).fetchone()
        if dis is None:
            raise ReviewError(
                f"no registered disagreement for {queue_id!r}; adjudication follows "
                "a registered disagreement (ANNOTATION_GUIDE §7)"
            )
        reviewed_at = now_iso()
        conn.execute(
            "INSERT INTO annotation_events (queue_id, event_kind, decision, "
            "reason_code, reason_text, notes, reviewer_id, reviewed_at, "
            "label_tier, produced_by_kind, adjudicator_id) "
            "VALUES (?,?,?,?,?,?,?,?,'provisional','adjudicated_human',?)",
            (queue_id, "adjudication", decision, reason_code, reason_text.strip(),
             notes, adjudicator_id, reviewed_at, adjudicator_id),
        )
        conn.execute(
            "UPDATE disagreements SET resolution=?, adjudicator_id=? WHERE queue_id=?",
            (decision, adjudicator_id, queue_id),
        )
        conn.execute(
            "UPDATE review_state SET status='submitted', decision=?, "
            "reason_code=?, reason_text=?, reviewer_id=?, reviewed_at=?, "
            "label_tier='provisional', produced_by_kind='adjudicated_human', "
            "updated_at=? WHERE queue_id=?",
            (decision, reason_code, reason_text.strip(), adjudicator_id,
             reviewed_at, now_iso(), queue_id),
        )
        conn.commit()
        return {"queue_id": queue_id, "resolution": decision,
                "adjudicator_id": adjudicator_id, "label_tier": "provisional"}
    finally:
        conn.close()


def record_signoff(store_path: Path, queue_id: str, *, sign_off_by: str,
                   sign_off_date: str, evidence_file: Path | str) -> dict:
    """Record a knowledge-owner human sign-off that qualifies a label as gold.

    唯一的人工 Gold 通道（LT-03，机器校验形态）：
    - 该条目必须已满足 gold_flow：独立双人一致（independent_double_human）
      或已登记裁决（adjudicated_human）；
    - 必须提供真实存在的签署凭据文件（批准清单/审计记录），文件由人工维护；
    - 校验通过后写 signoff 事件并把该条目标签定为 gold。除此之外**不存在**
      任何把 provisional 升为 gold 的代码路径。
    """
    import re

    if not sign_off_by or len(sign_off_by.strip()) < 2:
        raise ReviewError("sign_off_by (knowledge owner) is mandatory")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", sign_off_date or ""):
        raise ReviewError("sign_off_date must be YYYY-MM-DD")
    evidence = Path(evidence_file)
    if not evidence.is_file():
        raise GateViolationError(
            f"sign-off evidence file not found: {evidence}; gold requires a real "
            "human sign-off record (approval checklist or audit record)"
        )

    conn = connect_store(store_path)
    try:
        _require_item(conn, queue_id)
        state = conn.execute(
            "SELECT * FROM review_state WHERE queue_id=?", (queue_id,)
        ).fetchone()
        if state is None or state["status"] not in ("submitted", "locked"):
            raise GateViolationError(
                f"queue_id {queue_id!r} has no submitted human judgement to sign off"
            )
        kind = state["produced_by_kind"]
        if kind not in ("adjudicated_human", "independent_double_human"):
            raise GateViolationError(
                f"gold flow not satisfied for {queue_id!r}: produced_by_kind="
                f"{kind!r}; need independent double review (consistent) or a "
                "recorded adjudication before sign-off (LT-03)"
            )
        if kind == "independent_double_human":
            # confirm two independent humans agreed with no registered disagreement
            dis = conn.execute(
                "SELECT 1 FROM disagreements WHERE queue_id=?", (queue_id,)
            ).fetchone()
            if dis:
                raise GateViolationError(
                    f"queue_id {queue_id!r} has an unresolved disagreement; "
                    "adjudication must complete first"
                )
        at = now_iso()
        conn.execute(
            "INSERT INTO annotation_events (queue_id, event_kind, decision, "
            "reason_code, reason_text, reviewer_id, reviewed_at, label_tier, "
            "produced_by_kind, sign_off_by, sign_off_date, evidence_file) "
            "VALUES (?,?,?,?,?,?,?,?, 'gold', ?, ?, ?)",
            (queue_id, "signoff", state["decision"], state["reason_code"],
             state["reason_text"], state["reviewer_id"], at, kind,
             sign_off_by.strip(), sign_off_date, str(evidence)),
        )
        conn.execute(
            "UPDATE review_state SET label_tier='gold', updated_at=? "
            "WHERE queue_id=?",
            (at, queue_id),
        )
        conn.commit()
        return {"queue_id": queue_id, "label_tier": "gold",
                "sign_off_by": sign_off_by.strip(), "sign_off_date": sign_off_date}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Lock (precondition of unblinding) and audit
# ---------------------------------------------------------------------------

def lock_queue(store_path: Path, *, confirmed_by: str) -> dict:
    """Lock all submitted labels (a human action) so unblinding may proceed."""
    if not confirmed_by or len(confirmed_by.strip()) < 2:
        raise ReviewError("confirmed_by is mandatory for the lock decision")
    conn = connect_store(store_path)
    try:
        total = conn.execute("SELECT COUNT(*) AS n FROM queue_items").fetchone()["n"]
        submitted = conn.execute(
            "SELECT COUNT(*) AS n FROM review_state WHERE status='submitted'"
        ).fetchone()["n"]
        if total == 0 or submitted != total:
            raise NotLockedError(
                f"cannot lock: {submitted}/{total} items submitted; complete the "
                "blind pass first (undecided items are submitted too)"
            )
        at = now_iso()
        conn.execute(
            "UPDATE review_state SET status='locked', updated_at=? "
            "WHERE status='submitted'",
            (at,),
        )
        conn.execute(
            "INSERT INTO annotation_events (queue_id, event_kind, reviewer_id, "
            "reviewed_at, label_tier, produced_by_kind, payload) "
            "SELECT queue_id, 'lock', ?, ?, label_tier, produced_by_kind, NULL "
            "FROM review_state",
            (confirmed_by.strip(), at),
        )
        conn.commit()
        return {"locked": total, "confirmed_by": confirmed_by.strip(), "at": at}
    finally:
        conn.close()


def _negative_result_hit(text: str) -> bool:
    t = (text or "").lower()
    markers = ("no significant", "not significant", "n.s.", "no evidence",
               "did not differ", "无显著", "未达显著", "没有显著")
    return any(m in t for m in markers)


def _stratum_of(item: dict, keyed_row: dict) -> str:
    """Approximate protective-layer assignment (SCREENING_PROTOCOL §6.4 proxies)."""
    lang = (keyed_row.get("stratum") or item.get("language") or "").lower()
    if "zh" in lang or "chinese" in lang or "cn" == lang:
        return "chinese"
    year = item.get("publication_year") or 0
    try:
        year = int(year)
    except (TypeError, ValueError):
        year = 0
    if year and year <= 2000:
        return "classic_pre2000"
    blob = f"{item.get('title') or ''} {item.get('abstract') or ''}"
    if _negative_result_hit(blob):
        return "negative_result"
    return "general"


def run_audit(store_path: Path, keyed_csv_path: Path, outdir: Path, *,
              extrapolation_note: str | None = None) -> dict:
    """Post-lock unblinding audit: join fixed human labels with the keyed CSV.

    边界（全部写进报告）：
    - 前置：全部条目已锁定（lock_queue）；否则拒绝（NotLockedError）——
      解盲只发生在标注固定之后（ANNOTATION_GUIDE §2.3）。
    - 只读 join：历史标签（proxy 层）与本审计**不写回** review_state / 主库，
      原决策保留不覆盖。
    - A2 为富集样本：默认仅报告 A2 样本结果；外推全库误拒率必须人工提供
      抽样概率与分层加权方法（extrapolation_note），否则报告保持
      "不得外推总体" 的声明。
    - 分层为 SCREENING_PROTOCOL §6.4 保护层的机械近似（中文/经典(≤2000)/
      负面结果关键词），报告中声明为近似、供人工修正。
    - 本工具不训练任何模型：ASReview proxy 性能补充分析只能单独引用
      人工 Gold 子样本，禁止回训后在同批条目报告无偏性能（Issue #2 边界）。
    """
    stats = progress(store_path)
    if not (stats["total"] > 0 and stats["locked"] == stats["total"]):
        raise NotLockedError(
            f"unblinding audit refused: {stats['locked']}/{stats['total']} items "
            "locked; all labels must be locked (fixed) before unblinding"
        )

    keyed_csv_path = Path(keyed_csv_path)
    with open(keyed_csv_path, "r", encoding="utf-8-sig", newline="") as fh:
        keyed = {r["queue_id"]: r for r in csv.DictReader(fh)}

    conn = connect_store(store_path)
    try:
        items = conn.execute(
            "SELECT q.queue_id, q.sample_id, q.doi, q.title, q.abstract, q.language, "
            "q.publication_year, s.decision, s.reason_code, s.reviewed_at, "
            "s.reviewer_id, s.label_tier FROM queue_items q "
            "JOIN review_state s ON s.queue_id=q.queue_id ORDER BY q.queue_id"
        ).fetchall()
    finally:
        conn.close()

    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    rows_out = []
    buckets: dict[str, dict[str, int]] = {}
    for it in items:
        item = dict(it)
        krow = keyed.get(item["queue_id"])
        if krow is None:
            raise ReviewError(
                f"keyed CSV lacks queue_id {item['queue_id']!r}; refusing a partial audit"
            )
        hist = _cell(krow.get("historical_label"))
        hist_label = {"1": "ingested", "0": "rejected"}.get(hist, hist or "unknown")
        stratum = _cell(krow.get("stratum")) or "unknown"
        agree = (item["decision"] == "relevant" and hist_label == "ingested") or (
            item["decision"] == "not_relevant" and hist_label == "rejected"
        )
        if item["decision"] in ("undecided", "boundary"):
            relation = "human_undecided_or_boundary"
        elif agree:
            relation = "consistent"
        else:
            relation = "inconsistent"
        layer = _stratum_of(item, krow)
        b = buckets.setdefault(layer, {"consistent": 0, "inconsistent": 0,
                                       "human_undecided_or_boundary": 0})
        b[relation] += 1
        rows_out.append({
            "queue_id": item["queue_id"],
            "stratum_keyed": stratum,
            "protective_layer_proxy": layer,
            "historical_label": hist_label,
            "human_decision": item["decision"],
            "relation": relation,
            "label_tier": item["label_tier"],
            "reviewer_id": item["reviewer_id"],
            "reviewed_at": item["reviewed_at"],
        })

    audit_path = outdir / "audit-results.jsonl"
    with open(audit_path, "w", encoding="utf-8", newline="") as fh:
        for r in rows_out:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    total = len(rows_out)
    counts = {"consistent": 0, "inconsistent": 0, "human_undecided_or_boundary": 0}
    for r in rows_out:
        counts[r["relation"]] += 1

    lines = [
        "# CE-02 解盲审计报告（A2 80 项富集样本）",
        "",
        f"- 生成时间：{now_iso()}（本地工具，无网络访问）",
        f"- 样本：A2 盲法队列 {total} 项（含 54 项历史拒收；富集样本，**不得**直接外推全库 393 项误拒率）",
        f"- 人工标签层级：provisional（单人标注，未经第二人独立验证；Gold 须另行签署流程）",
        "",
        "## 总体对照（历史 proxy vs 人工 provisional）",
        "",
        f"- 一致：{counts['consistent']}",
        f"- 不一致（原决策保留，仅登记）：{counts['inconsistent']}",
        f"- 人工 undecided/boundary：{counts['human_undecided_or_boundary']}",
        "",
        "## 保护层近似分层（SCREENING_PROTOCOL §6.4 的机械近似，供人工修正）",
        "",
        "| 层 | 一致 | 不一致 | undecided/boundary |",
        "|---|---|---|---|",
    ]
    for layer in sorted(buckets):
        b = buckets[layer]
        lines.append(f"| {layer} | {b['consistent']} | {b['inconsistent']} | {b['human_undecided_or_boundary']} |")
    lines += [
        "",
        "## 统计外推边界",
        "",
        "- 本报告只描述 A2 样本本身；**不得**宣称全库误拒率。",
        "- 如需外推：必须由人工提供抽样概率、分层加权方法与置信区间，"
        "并在下方补充说明（留空则维持不外推声明）。",
        "",
        extrapolation_note or "> 外推说明：**未提供**——维持“仅报告 A2 样本结果”的边界。",
        "",
        "## ASReview proxy 性能补充分析边界",
        "",
        "- 本工具不训练、不回训任何模型。",
        "- 任何基于历史 proxy 的性能补充分析必须：单独报告人工 Gold 子样本；"
        "**禁止**用人工复核数据回训模型后再在同批条目上报告无偏性能。",
        "",
        "## 隐私与收录",
        "",
        "- 审计输出含 reviewer_id 与历史标签，默认保存在 gitignored 数据目录，"
        "是否收录 Git 须按许可与隐私审查决定（AGENTS #8）。",
        "- 原始决策保留不覆盖；不一致条目仅为登记，不构成任何自动改判。",
        "",
    ]
    report_path = outdir / "audit-report.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")

    return {
        "total": total,
        "counts": counts,
        "buckets": buckets,
        "audit_results": str(audit_path),
        "audit_report": str(report_path),
    }


# ---------------------------------------------------------------------------
# Export (provisional labels + full audit trail; no blinded-out data)
# ---------------------------------------------------------------------------

EXPORT_COLUMNS = (
    "queue_id", "sample_id", "doi", "title", "review_task",
    "decision", "reason_code", "reason_text", "confidence", "notes",
    "reviewer_id", "reviewed_at", "label_tier", "produced_by_kind",
)


def export_annotations(store_path: Path, outdir: Path) -> dict:
    """Export current labels + the append-only event stream for hand-off.

    导出物不含 historical_label/stratum/模型排名（标注库中本就不存在）；
    导出 README 显式声明单人标注边界与 HUMAN_REVIEW_PENDING 状态。
    """
    conn = connect_store(store_path)
    try:
        rows = conn.execute(
            "SELECT q.queue_id, q.sample_id, q.doi, q.title, q.review_task, "
            "s.decision, s.reason_code, s.reason_text, s.confidence, s.notes, "
            "s.reviewer_id, s.reviewed_at, s.label_tier, s.produced_by_kind "
            "FROM queue_items q LEFT JOIN review_state s "
            "ON s.queue_id=q.queue_id ORDER BY q.queue_id"
        ).fetchall()
        events = conn.execute(
            "SELECT * FROM annotation_events ORDER BY event_id"
        ).fetchall()
    finally:
        conn.close()

    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    csv_path = outdir / "annotations.csv"
    with open(csv_path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(EXPORT_COLUMNS)
        for r in rows:
            writer.writerow([r[c] for c in EXPORT_COLUMNS])

    jsonl_path = outdir / "annotations-events.jsonl"
    with open(jsonl_path, "w", encoding="utf-8", newline="") as fh:
        for ev in events:
            fh.write(json.dumps(dict(ev), ensure_ascii=False) + "\n")

    submitted = sum(1 for r in rows if r["decision"])
    total = len(rows)
    gold = sum(1 for r in rows if r["label_tier"] == "gold")
    provisional = sum(1 for r in rows if r["label_tier"] == "provisional")
    lines = [
        "# CE-02 标注导出（provisional human labels）",
        "",
        f"- 导出时间：{now_iso()}",
        f"- 完成度：{submitted}/{total}"
        + ("" if submitted == total and total > 0 else "  **HUMAN_REVIEW_PENDING**"),
        f"- 层级分布：provisional={provisional}, gold={gold}"
        + ("；即使全部提交，独立复核/分歧裁决/知识负责人签署完成前，"
           "本导出仍是人工阶段的**中间产物**（HUMAN_REVIEW_PENDING）"
           if submitted == total and total > 0 else ""),
        "- 标签层级：单人标注封顶 `provisional`——**单人标注，未经第二人独立验证**"
        "（ANNOTATION_GUIDE §7.5，DRAFT v1.1）；",
        f"- gold 条目数：{gold}（只可能来自人工签署流程 record-signoff，"
        "本工具无任何自动升 Gold 路径）；",
        "- 本导出不含 historical_label / stratum / 模型得分或排名（盲法保证）；",
        "- 原始事件流（annotations-events.jsonl）为追加式审计记录，修改以 "
        "amendment 事件留痕；",
        "- 主事实源（library.sqlite / works.record_status）未接触；回写属人工阶段。",
    ]
    readme_path = outdir / "README-EXPORT.md"
    readme_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    return {
        "csv": str(csv_path),
        "events": str(jsonl_path),
        "readme": str(readme_path),
        "submitted": submitted,
        "total": total,
        "gold": gold,
        "human_review_pending": not (total > 0 and submitted == total),
    }
