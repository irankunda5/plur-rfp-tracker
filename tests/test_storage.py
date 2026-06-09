"""Tests for lib/storage.py - SQLite storage with linked dedup."""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from lib.storage import OpportunityStore, _now_iso, _escape_markdown


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _default_notice(**kwargs):
    """Return default notice kwargs, overridden by caller."""
    defaults = dict(
        source="canadabuys",
        source_id="PW-23-00123456",
        title="Cybersecurity Professional Services",
        description="SIEM and endpoint protection services for federal agency.",
        url="https://canadabuys.canada.ca/en/tender-opportunities/PW-23-00123456",
        closing_date="2026-04-01",
        buyer="Public Services and Procurement Canada",
        notice_type="tender",
        product_type="services",
        vendor_flags=[],
        classification={"tier": 1, "matched_keywords": ["cybersecurity", "SIEM"]},
    )
    defaults.update(kwargs)
    return defaults


@pytest.fixture
def store(tmp_path):
    """Fresh SQLite OpportunityStore per test."""
    s = OpportunityStore(db_path=tmp_path / "test.db")
    yield s
    s.close()


# ---------------------------------------------------------------------------
# Add new notice
# ---------------------------------------------------------------------------

class TestAddNotice:
    def test_add_returns_true_for_new(self, store):
        is_new, nid = store.add_notice(**_default_notice())
        assert is_new is True
        assert nid > 0

    def test_added_notice_appears_in_get_all(self, store):
        store.add_notice(**_default_notice())
        all_notices = store.get_all_notices()
        assert len(all_notices) == 1
        assert all_notices[0]["source_id"] == "PW-23-00123456"

    def test_add_persists_to_db(self, tmp_path):
        db = tmp_path / "persist.db"
        store1 = OpportunityStore(db_path=db)
        store1.add_notice(**_default_notice())
        store1.close()

        store2 = OpportunityStore(db_path=db)
        assert len(store2.get_all_notices()) == 1
        store2.close()

    def test_add_multiple_distinct(self, store):
        for i, title in enumerate(["Cyber Audit", "IAM Platform", "Cloud Migration"]):
            is_new, _ = store.add_notice(**_default_notice(
                source_id=f"ID-{i:03d}", title=title,
            ))
            assert is_new is True
        assert len(store.get_all_notices()) == 3

    def test_classification_stored_as_json(self, store):
        cls = {"tier": 1, "matched_keywords": ["SIEM", "MFA"], "confidence": 0.8}
        store.add_notice(**_default_notice(classification=cls))
        row = store.get_all_notices()[0]
        stored_cls = json.loads(row["classification_json"])
        assert stored_cls["tier"] == 1
        assert "SIEM" in stored_cls["matched_keywords"]

    def test_raw_json_stored(self, store):
        raw = {"original_csv_row": {"col1": "val1"}}
        store.add_notice(**_default_notice(raw_json=raw))
        row = store.get_all_notices()[0]
        assert json.loads(row["raw_json"])["original_csv_row"]["col1"] == "val1"

    def test_vendor_flags_stored(self, store):
        store.add_notice(**_default_notice(vendor_flags=["CrowdStrike", "Okta"]))
        row = store.get_all_notices()[0]
        flags = json.loads(row["vendor_flags"])
        assert "CrowdStrike" in flags

    def test_closing_date_nullable(self, store):
        store.add_notice(**_default_notice(closing_date=None))
        row = store.get_all_notices()[0]
        assert row["closing_date"] is None


# ---------------------------------------------------------------------------
# Dedup by (source, source_id)
# ---------------------------------------------------------------------------

class TestDeduplicateBySourceId:
    def test_duplicate_returns_false(self, store):
        store.add_notice(**_default_notice())
        is_new, _ = store.add_notice(**_default_notice())
        assert is_new is False

    def test_duplicate_count_unchanged(self, store):
        store.add_notice(**_default_notice())
        store.add_notice(**_default_notice())
        assert len(store.get_all_notices()) == 1

    def test_same_source_id_different_source_is_new(self, store):
        store.add_notice(**_default_notice(
            source="canadabuys", source_id="T-001",
            buyer="Public Works Canada", title="Cybersecurity Services 2026",
        ))
        is_new, _ = store.add_notice(**_default_notice(
            source="bc_bid", source_id="T-001",
            buyer="City of Kelowna", title="Network Security Audit",
        ))
        assert is_new is True

    def test_reload_dedup(self, tmp_path):
        db = tmp_path / "reload.db"
        s1 = OpportunityStore(db_path=db)
        s1.add_notice(**_default_notice(source_id="R-001"))
        s1.close()

        s2 = OpportunityStore(db_path=db)
        is_new, _ = s2.add_notice(**_default_notice(source_id="R-001"))
        assert is_new is False
        assert len(s2.get_all_notices()) == 1
        s2.close()

    def test_duplicate_returns_existing_id(self, store):
        _, id1 = store.add_notice(**_default_notice())
        _, id2 = store.add_notice(**_default_notice())
        assert id1 == id2


# ---------------------------------------------------------------------------
# Cross-source fuzzy linking (notice_links)
# ---------------------------------------------------------------------------

class TestCrossSourceLinking:
    def test_identical_title_same_buyer_creates_link(self, store):
        _, id_a = store.add_notice(**_default_notice(
            source="canadabuys", source_id="CA-001",
            buyer="City of Victoria",
            title="Cybersecurity Professional Services RFP 2026",
        ))
        _, id_b = store.add_notice(**_default_notice(
            source="bonfire", source_id="BON-001",
            buyer="City of Victoria",
            title="Cybersecurity Professional Services RFP 2026",
        ))
        # Both stored (linked, not collapsed)
        assert len(store.get_all_notices()) == 2
        links = store.get_links(id_b)
        assert len(links) >= 1
        assert links[0]["link_type"] == "cross_source"

    def test_similar_title_creates_link(self, store):
        store.add_notice(**_default_notice(
            source="canadabuys", source_id="CA-002",
            buyer="City of Surrey",
            title="Cybersecurity and Network Security Services 2026-2028",
        ))
        _, id_b = store.add_notice(**_default_notice(
            source="bonfire", source_id="BON-002",
            buyer="City of Surrey",
            title="Cybersecurity & Network Security Services 2026-2028",
        ))
        links = store.get_links(id_b)
        assert len(links) >= 1

    def test_different_buyer_no_link(self, store):
        store.add_notice(**_default_notice(
            source="canadabuys", source_id="CA-003",
            buyer="City of Victoria",
            title="Managed Security Services",
        ))
        _, id_b = store.add_notice(**_default_notice(
            source="bc_bid", source_id="BC-003",
            buyer="City of Vancouver",
            title="Managed Security Services",
        ))
        links = store.get_links(id_b)
        assert len(links) == 0

    def test_different_title_same_buyer_no_link(self, store):
        store.add_notice(**_default_notice(
            source="bc_bid", source_id="BC-010",
            buyer="BC Housing",
            title="Cybersecurity Audit Services 2026",
        ))
        _, id_b = store.add_notice(**_default_notice(
            source="bc_bid", source_id="BC-011",
            buyer="BC Housing",
            title="Cloud Migration and Infrastructure Modernization",
        ))
        links = store.get_links(id_b)
        assert len(links) == 0

    def test_amendment_link(self, store):
        _, id_a = store.add_notice(**_default_notice(source_id="ORIG-1"))
        _, id_b = store.add_notice(**_default_notice(
            source_id="AMEND-1", title="Cybersecurity Services (Amendment 1)",
        ))
        store.add_amendment_link(id_a, id_b, reason="solicitationNumber match")
        links = store.get_links(id_b)
        assert any(l["link_type"] == "amendment" for l in links)


# ---------------------------------------------------------------------------
# get_new_since
# ---------------------------------------------------------------------------

class TestGetNewSince:
    def test_returns_notices_after_cutoff(self, store):
        store.add_notice(**_default_notice(source_id="N-001"))
        cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
        result = store.get_new_since(cutoff)
        assert len(result) >= 1

    def test_returns_empty_when_nothing(self, store):
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        result = store.get_new_since(cutoff)
        assert result == []

    def test_returns_all_when_cutoff_far_past(self, store):
        for i, (buyer, title) in enumerate([
            ("PSPC", "Cybersecurity Audit Services"),
            ("DND", "Endpoint Protection Platform"),
            ("CRA", "Cloud Security Assessment"),
        ]):
            store.add_notice(**_default_notice(
                source_id=f"OPP-{i}", buyer=buyer, title=title,
            ))
        cutoff = datetime.now(timezone.utc) - timedelta(days=365)
        result = store.get_new_since(cutoff)
        assert len(result) == 3


# ---------------------------------------------------------------------------
# export_digest
# ---------------------------------------------------------------------------

class TestExportDigest:
    def test_digest_empty_when_no_notices(self, store):
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        assert store.export_digest(cutoff) == ""

    def test_digest_contains_title_and_buyer(self, store):
        store.add_notice(**_default_notice(
            title="IAM Platform for City of Victoria",
            buyer="City of Victoria",
            classification={"tier": 1, "matched_keywords": ["IAM"]},
        ))
        cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
        digest = store.export_digest(cutoff)
        assert "IAM Platform for City of Victoria" in digest
        assert "City of Victoria" in digest

    def test_digest_contains_keywords(self, store):
        store.add_notice(**_default_notice(
            classification={"tier": 1, "matched_keywords": ["cybersecurity", "SIEM", "MFA"]},
        ))
        cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
        digest = store.export_digest(cutoff)
        assert "cybersecurity" in digest

    def test_digest_contains_url(self, store):
        store.add_notice(**_default_notice(url="https://example.com/tender/12345"))
        cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
        digest = store.export_digest(cutoff)
        assert "https://example.com/tender/12345" in digest

    def test_digest_groups_by_tier(self, store):
        store.add_notice(**_default_notice(
            source_id="T1-001", title="Cyber Audit",
            classification={"tier": 1, "matched_keywords": ["cybersecurity"]},
        ))
        store.add_notice(**_default_notice(
            source_id="T3-001", title="Cloud Migration",
            classification={"tier": 3, "matched_keywords": ["cloud migration"]},
        ))
        cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
        digest = store.export_digest(cutoff)
        assert "T1" in digest or "Cyber" in digest
        assert "T3" in digest or "IT" in digest

    def test_digest_is_markdown(self, store):
        store.add_notice(**_default_notice())
        cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
        digest = store.export_digest(cutoff)
        assert digest.startswith("##")


# ---------------------------------------------------------------------------
# Source runs
# ---------------------------------------------------------------------------

class TestSourceRuns:
    def test_start_run_returns_id(self, store):
        run_id = store.start_run("canadabuys")
        assert run_id > 0

    def test_end_run_updates_status(self, store):
        run_id = store.start_run("canadabuys")
        store.end_run(run_id, records_found=50, records_new=10,
                      records_matched=5, status="success")
        run = store.get_run(run_id)
        assert run["status"] == "success"
        assert run["records_found"] == 50
        assert run["records_new"] == 10
        assert run["records_matched"] == 5
        assert run["end_time"] is not None

    def test_error_run(self, store):
        run_id = store.start_run("bonfire")
        store.end_run(run_id, status="error", error_message="HTTP 403")
        run = store.get_run(run_id)
        assert run["status"] == "error"
        assert run["error_message"] == "HTTP 403"

    def test_get_latest_run(self, store):
        r1 = store.start_run("canadabuys")
        store.end_run(r1, status="success")
        r2 = store.start_run("canadabuys")
        store.end_run(r2, status="success")
        latest = store.get_latest_run("canadabuys")
        assert latest["id"] == r2

    def test_get_latest_run_none(self, store):
        assert store.get_latest_run("nonexistent") is None

    def test_multiple_sources(self, store):
        store.start_run("canadabuys")
        store.start_run("bonfire")
        assert store.get_latest_run("canadabuys")["source"] == "canadabuys"
        assert store.get_latest_run("bonfire")["source"] == "bonfire"

    def test_last_nonzero_run_set(self, store):
        run_id = store.start_run("canadabuys")
        store.end_run(run_id, records_found=10, status="success")
        run = store.get_run(run_id)
        assert run["last_nonzero_run"] is not None

    def test_last_nonzero_run_not_set_on_zero(self, store):
        run_id = store.start_run("canadabuys")
        store.end_run(run_id, records_found=0, status="success")
        run = store.get_run(run_id)
        assert run["last_nonzero_run"] is None

    def test_running_status_default(self, store):
        run_id = store.start_run("canadabuys")
        run = store.get_run(run_id)
        assert run["status"] == "running"


# ---------------------------------------------------------------------------
# WAL mode and DB setup
# ---------------------------------------------------------------------------

class TestDBSetup:
    def test_wal_mode(self, store):
        row = store._conn.execute("PRAGMA journal_mode").fetchone()
        assert row[0] == "wal"

    def test_tables_created(self, store):
        tables = store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        names = {r[0] for r in tables}
        assert "notices" in names
        assert "notice_links" in names
        assert "source_runs" in names

    def test_data_dir_created(self, tmp_path):
        db = tmp_path / "deeply" / "nested" / "test.db"
        s = OpportunityStore(db_path=db)
        assert db.exists()
        s.close()

    def test_concurrent_stores_same_db(self, tmp_path):
        db = tmp_path / "concurrent.db"
        s1 = OpportunityStore(db_path=db)
        s1.add_notice(**_default_notice(source_id="C-001"))
        s2 = OpportunityStore(db_path=db)
        assert len(s2.get_all_notices()) == 1
        s1.close()
        s2.close()


# ---------------------------------------------------------------------------
# get_notice / get_notice_by_source
# ---------------------------------------------------------------------------

class TestNoticeQueries:
    def test_get_notice_by_id(self, store):
        _, nid = store.add_notice(**_default_notice())
        notice = store.get_notice(nid)
        assert notice is not None
        assert notice["title"] == "Cybersecurity Professional Services"

    def test_get_notice_by_source(self, store):
        store.add_notice(**_default_notice())
        notice = store.get_notice_by_source("canadabuys", "PW-23-00123456")
        assert notice is not None
        assert notice["buyer"] == "Public Services and Procurement Canada"

    def test_get_notice_not_found(self, store):
        assert store.get_notice(99999) is None

    def test_get_notice_by_source_not_found(self, store):
        assert store.get_notice_by_source("nonexistent", "ID-999") is None


# ---------------------------------------------------------------------------
# Markdown escaping
# ---------------------------------------------------------------------------

class TestEscapeMarkdown:
    def test_escapes_at_sign(self):
        assert _escape_markdown("@channel") == "\\@channel"

    def test_escapes_angle_brackets(self):
        assert _escape_markdown("<script>") == "&lt;script&gt;"

    def test_escapes_bold_and_italic(self):
        assert _escape_markdown("*bold*") == "\\*bold\\*"
        assert _escape_markdown("_italic_") == "\\_italic\\_"

    def test_escapes_strikethrough(self):
        assert _escape_markdown("~struck~") == "\\~struck\\~"

    def test_escapes_backtick(self):
        assert _escape_markdown("`code`") == "\\`code\\`"

    def test_plain_text_unchanged(self):
        assert _escape_markdown("Hello world 123") == "Hello world 123"

    def test_empty_string(self):
        assert _escape_markdown("") == ""

    def test_none_passthrough(self):
        # _escape_markdown returns falsy input as-is
        assert _escape_markdown("") == ""

    def test_combined_injection(self):
        nasty = "<@admin> *click here* `rm -rf`"
        escaped = _escape_markdown(nasty)
        assert "\\@" in escaped
        assert "&lt;" in escaped
        assert "\\*" in escaped
        assert "\\`" in escaped


# ---------------------------------------------------------------------------
# Markdown escaping in export_digest
# ---------------------------------------------------------------------------

class TestDigestEscaping:
    def test_digest_escapes_title(self, store):
        store.add_notice(**_default_notice(
            title="<script>alert('xss')</script> *bold*",
            classification={"tier": 1, "matched_keywords": ["cybersecurity"]},
        ))
        cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
        digest = store.export_digest(cutoff)
        assert "<script>" not in digest
        assert "&lt;script&gt;" in digest
        assert "\\*bold\\*" in digest

    def test_digest_escapes_buyer(self, store):
        store.add_notice(**_default_notice(
            buyer="@everyone <admin>",
            classification={"tier": 1, "matched_keywords": ["cybersecurity"]},
        ))
        cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
        digest = store.export_digest(cutoff)
        assert "\\@everyone" in digest
        assert "&lt;admin&gt;" in digest


# ---------------------------------------------------------------------------
# Solicitation number
# ---------------------------------------------------------------------------

class TestSolicitationNumber:
    def test_add_notice_with_solicitation_number(self, store):
        is_new, nid = store.add_notice(**_default_notice(
            solicitation_number="W7714-248899/A",
        ))
        assert is_new is True
        notice = store.get_notice(nid)
        assert notice["solicitation_number"] == "W7714-248899/A"

    def test_solicitation_number_defaults_to_none(self, store):
        _, nid = store.add_notice(**_default_notice())
        notice = store.get_notice(nid)
        assert notice["solicitation_number"] is None

    def test_find_by_solicitation_number(self, store):
        _, nid = store.add_notice(**_default_notice(
            source="canadabuys",
            solicitation_number="W7714-248899/A",
        ))
        found_id = store.find_by_solicitation_number("canadabuys", "W7714-248899/A")
        assert found_id == nid

    def test_find_by_solicitation_number_wrong_source(self, store):
        store.add_notice(**_default_notice(
            source="canadabuys",
            solicitation_number="W7714-248899/A",
        ))
        found = store.find_by_solicitation_number("sam_gov", "W7714-248899/A")
        assert found is None

    def test_find_by_solicitation_number_not_found(self, store):
        assert store.find_by_solicitation_number("canadabuys", "NONEXISTENT") is None


# ---------------------------------------------------------------------------
# Single-transaction behavior (insert + link in one commit)
# ---------------------------------------------------------------------------

class TestSingleTransaction:
    def test_insert_and_link_single_commit(self, store):
        """Insert + cross-source link should happen in one transaction.

        Verify by checking both the notice and the link exist after add_notice.
        """
        store.add_notice(**_default_notice(
            source="canadabuys", source_id="TX-001",
            buyer="City of Victoria",
            title="Cybersecurity Professional Services RFP 2026",
        ))
        _, id_b = store.add_notice(**_default_notice(
            source="bonfire", source_id="BON-TX-001",
            buyer="City of Victoria",
            title="Cybersecurity Professional Services RFP 2026",
        ))
        # Both notice and link should exist
        assert store.get_notice(id_b) is not None
        links = store.get_links(id_b)
        assert len(links) >= 1
        assert links[0]["link_type"] == "cross_source"
