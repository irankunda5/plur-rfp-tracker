"""SQLite-backed opportunity store with linked deduplication."""

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

try:
    from rapidfuzz import fuzz
    _HAVE_RAPIDFUZZ = True
except ImportError:
    _HAVE_RAPIDFUZZ = False

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path(__file__).parent.parent / "data" / "rfp.db"
FUZZY_TITLE_THRESHOLD = 85

# Characters that have special meaning in Slack/markdown and must be escaped
# in user-provided content to prevent injection.
_MD_ESCAPE_CHARS = str.maketrans({
    "@": "\\@",
    "<": "&lt;",
    ">": "&gt;",
    "*": "\\*",
    "_": "\\_",
    "~": "\\~",
    "`": "\\`",
})


def _escape_markdown(text: str) -> str:
    """Escape markdown/Slack special characters in external text."""
    if not text:
        return text
    return text.translate(_MD_ESCAPE_CHARS)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS notices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    buyer TEXT NOT NULL DEFAULT '',
    closing_date TEXT,
    url TEXT NOT NULL DEFAULT '',
    notice_type TEXT NOT NULL DEFAULT '',
    product_type TEXT NOT NULL DEFAULT '',
    vendor_flags TEXT NOT NULL DEFAULT '[]',
    classification_json TEXT NOT NULL DEFAULT '{}',
    solicitation_number TEXT,
    raw_json TEXT,
    fetch_timestamp TEXT NOT NULL,
    UNIQUE(source, source_id)
);

CREATE TABLE IF NOT EXISTS notice_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    notice_a_id INTEGER NOT NULL REFERENCES notices(id),
    notice_b_id INTEGER NOT NULL REFERENCES notices(id),
    link_type TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 1.0,
    match_reason TEXT NOT NULL DEFAULT '',
    manual_override INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS source_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT,
    records_found INTEGER NOT NULL DEFAULT 0,
    records_new INTEGER NOT NULL DEFAULT 0,
    records_matched INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'running',
    error_message TEXT,
    last_nonzero_run TEXT
);

CREATE INDEX IF NOT EXISTS idx_notices_source_id ON notices(source, source_id);
CREATE INDEX IF NOT EXISTS idx_notices_fetch ON notices(fetch_timestamp);
CREATE INDEX IF NOT EXISTS idx_notice_links_a ON notice_links(notice_a_id);
CREATE INDEX IF NOT EXISTS idx_notice_links_b ON notice_links(notice_b_id);
CREATE INDEX IF NOT EXISTS idx_source_runs_source ON source_runs(source);
CREATE INDEX IF NOT EXISTS idx_notices_solicitation ON notices(solicitation_number);
CREATE INDEX IF NOT EXISTS idx_notices_closing_date ON notices(closing_date);
CREATE INDEX IF NOT EXISTS idx_notices_buyer ON notices(buyer);
"""


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

class OpportunityStore:
    """SQLite-backed store with linked deduplication.

    Deduplication strategy:
    1. Exact (source, source_id) pair - same opp from the same portal.
    2. Fuzzy title match - same buyer + title similarity >= threshold,
       creates a notice_link (cross_source) instead of collapsing.
    """

    def __init__(self, db_path: Path | str = DEFAULT_DB_PATH):
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self):
        if self._conn:
            self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    # ------------------------------------------------------------------
    # Notice CRUD
    # ------------------------------------------------------------------

    def add_notice(
        self,
        source: str,
        source_id: str,
        title: str,
        description: str = "",
        buyer: str = "",
        closing_date: str | None = None,
        url: str = "",
        notice_type: str = "",
        product_type: str = "",
        vendor_flags: list[str] | None = None,
        classification: dict | None = None,
        raw_json: dict | str | None = None,
        solicitation_number: str | None = None,
    ) -> tuple[bool, int]:
        """Add a notice if not a duplicate.

        Returns:
            (is_new, notice_id) - is_new is True if newly inserted.
        """
        vendor_flags = vendor_flags or []
        classification = classification or {}
        fetch_ts = _now_iso()

        # Check exact dup
        existing = self._conn.execute(
            "SELECT id FROM notices WHERE source = ? AND source_id = ?",
            (source, source_id),
        ).fetchone()
        if existing:
            return (False, existing["id"])

        # Insert + link check in a single transaction
        raw_str = json.dumps(raw_json) if isinstance(raw_json, dict) else raw_json
        cur = self._conn.execute(
            """INSERT INTO notices
               (source, source_id, title, description, buyer, closing_date,
                url, notice_type, product_type, vendor_flags,
                classification_json, solicitation_number, raw_json,
                fetch_timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                source, source_id, title, description, buyer, closing_date,
                url, notice_type, product_type, json.dumps(vendor_flags),
                json.dumps(classification), solicitation_number, raw_str,
                fetch_ts,
            ),
        )
        new_id = cur.lastrowid

        # Check for fuzzy cross-source duplicates and create links
        self._check_cross_source_link(new_id, source, buyer, title)

        # Single commit for insert + any link
        self._conn.commit()

        return (True, new_id)

    def _check_cross_source_link(
        self, notice_id: int, source: str, buyer: str, title: str
    ) -> None:
        """Check if a similar notice exists from a different source; if so, link them."""
        if not _HAVE_RAPIDFUZZ or not buyer:
            return

        buyer_norm = buyer.lower().strip()
        title_norm = title.lower().strip()

        rows = self._conn.execute(
            """SELECT id, source, buyer, title FROM notices
               WHERE id != ? AND source != ? AND LOWER(TRIM(buyer)) = ?""",
            (notice_id, source, buyer_norm),
        ).fetchall()

        for row in rows:
            score = fuzz.token_sort_ratio(title_norm, row["title"].lower().strip())
            if score >= FUZZY_TITLE_THRESHOLD:
                # Insert link directly (no commit) to stay in add_notice transaction
                self._conn.execute(
                    """INSERT INTO notice_links
                       (notice_a_id, notice_b_id, link_type, confidence, match_reason)
                       VALUES (?, ?, ?, ?, ?)""",
                    (row["id"], notice_id, "cross_source",
                     score / 100.0, f"fuzzy_title_score={score}"),
                )
                break

    def add_amendment_link(
        self, original_id: int, amendment_id: int, reason: str = ""
    ) -> None:
        """Create an amendment link between two notices."""
        self.add_link(original_id, amendment_id, "amendment", confidence=1.0, match_reason=reason)

    def add_link(
        self,
        notice_a_id: int,
        notice_b_id: int,
        link_type: str,
        confidence: float = 1.0,
        match_reason: str = "",
    ) -> None:
        """Insert a notice_links row."""
        self._conn.execute(
            """INSERT INTO notice_links
               (notice_a_id, notice_b_id, link_type, confidence, match_reason)
               VALUES (?, ?, ?, ?, ?)""",
            (notice_a_id, notice_b_id, link_type, confidence, match_reason),
        )
        self._conn.commit()

    def get_notice(self, notice_id: int) -> Optional[dict]:
        row = self._conn.execute(
            "SELECT * FROM notices WHERE id = ?", (notice_id,)
        ).fetchone()
        return dict(row) if row else None

    def get_notice_by_source(self, source: str, source_id: str) -> Optional[dict]:
        row = self._conn.execute(
            "SELECT * FROM notices WHERE source = ? AND source_id = ?",
            (source, source_id),
        ).fetchone()
        return dict(row) if row else None

    def find_by_solicitation_number(
        self, source: str, solicitation_number: str
    ) -> Optional[int]:
        """Return the notice ID for a given source + solicitation number.

        Uses the idx_notices_solicitation index. Returns None if not found.
        """
        row = self._conn.execute(
            "SELECT id FROM notices WHERE source = ? AND solicitation_number = ?",
            (source, solicitation_number),
        ).fetchone()
        return row["id"] if row else None

    def get_links(self, notice_id: int) -> list[dict]:
        rows = self._conn.execute(
            """SELECT * FROM notice_links
               WHERE notice_a_id = ? OR notice_b_id = ?""",
            (notice_id, notice_id),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_all_notices(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM notices ORDER BY fetch_timestamp DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Source runs
    # ------------------------------------------------------------------

    def start_run(self, source: str) -> int:
        """Record the start of a scraper run. Returns run_id."""
        cur = self._conn.execute(
            "INSERT INTO source_runs (source, start_time, status) VALUES (?, ?, 'running')",
            (source, _now_iso()),
        )
        self._conn.commit()
        return cur.lastrowid

    def end_run(
        self,
        run_id: int,
        records_found: int = 0,
        records_new: int = 0,
        records_matched: int = 0,
        status: str = "success",
        error_message: str | None = None,
    ) -> None:
        """Record the end of a scraper run."""
        end_time = _now_iso()
        self._conn.execute(
            """UPDATE source_runs SET
               end_time = ?, records_found = ?, records_new = ?,
               records_matched = ?, status = ?, error_message = ?
               WHERE id = ?""",
            (end_time, records_found, records_new, records_matched, status, error_message, run_id),
        )
        # Update last_nonzero_run only if records were found
        if records_found > 0:
            self._conn.execute(
                "UPDATE source_runs SET last_nonzero_run = ? WHERE id = ?",
                (end_time, run_id),
            )
        self._conn.commit()

    def get_run(self, run_id: int) -> Optional[dict]:
        row = self._conn.execute(
            "SELECT * FROM source_runs WHERE id = ?", (run_id,)
        ).fetchone()
        return dict(row) if row else None

    def get_latest_run(self, source: str) -> Optional[dict]:
        row = self._conn.execute(
            "SELECT * FROM source_runs WHERE source = ? ORDER BY start_time DESC LIMIT 1",
            (source,),
        ).fetchone()
        return dict(row) if row else None

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def get_new_since(self, since: datetime) -> list[dict]:
        """Return notices fetched after *since* (UTC-aware datetime)."""
        since_iso = since.isoformat()
        rows = self._conn.execute(
            "SELECT * FROM notices WHERE fetch_timestamp >= ? ORDER BY fetch_timestamp",
            (since_iso,),
        ).fetchall()
        return [dict(r) for r in rows]

    def export_digest(self, since: datetime) -> str:
        """Build a markdown digest of new notices since *since*."""
        new_notices = self.get_new_since(since)
        if not new_notices:
            return ""

        tier_labels = {1: "Cyber (T1)", 2: "IAM/Identity (T2)", 3: "Broader IT (T3)", 0: "Unclassified"}
        by_tier: dict[int, list[dict]] = {}

        for notice in new_notices:
            cls = json.loads(notice.get("classification_json", "{}") or "{}")
            tier = cls.get("tier", 0)
            by_tier.setdefault(tier, []).append(notice)

        since_str = since.strftime("%Y-%m-%d %H:%M UTC")
        lines = [f"## RFP Digest - New since {since_str}", ""]

        for tier in sorted(by_tier.keys()):
            notices = by_tier[tier]
            label = tier_labels.get(tier, f"Tier {tier}")
            lines.append(f"### {label} ({len(notices)} new)")
            lines.append("")
            for n in notices:
                cls = json.loads(n.get("classification_json", "{}") or "{}")
                keywords = cls.get("matched_keywords", [])
                closing = f" - Closes {n['closing_date']}" if n.get("closing_date") else ""
                kw_str = ", ".join(keywords[:5]) if keywords else "none"
                safe_title = _escape_markdown(n['title'])
                safe_buyer = _escape_markdown(n['buyer'])
                lines += [
                    f"**{safe_title}**",
                    f"Buyer: {safe_buyer} | Source: {n['source']}{closing}",
                    f"Keywords: {kw_str}",
                    f"URL: {n['url']}",
                    "",
                ]

        return "\n".join(lines).rstrip() + "\n"

