"""Tests for scrapers/bonfire.py - Bonfire API scraper."""

import json
import logging
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch, call

sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx
import pytest

from lib.storage import OpportunityStore
from scrapers.bonfire import BonfireScraper, PORTAL_DELAY_SECONDS

# ---------------------------------------------------------------------------
# Mock JSON responses
# ---------------------------------------------------------------------------

SINGLE_PORTAL_RESPONSE = {
    "success": 1,
    "message": "Success",
    "payload": {
        "projects": {
            "103907": {
                "ProjectID": "103907",
                "ReferenceID": "2026010099",
                "ProjectName": "Cybersecurity Assessment Services",
                "DateClose": "2026-03-20 21:00:00",
                "DepartmentID": "45",
            },
            "103908": {
                "ProjectID": "103908",
                "ReferenceID": "2026010100",
                "ProjectName": "Office Furniture Supply",
                "DateClose": "2026-04-01 17:00:00",
                "DepartmentID": "12",
            },
        }
    },
}

MULTI_MATCH_RESPONSE = {
    "success": 1,
    "message": "Success",
    "payload": {
        "projects": {
            "200001": {
                "ProjectID": "200001",
                "ReferenceID": "REF-001",
                "ProjectName": "Identity Management Platform Upgrade",
                "DateClose": "2026-05-15 18:00:00",
                "DepartmentID": "10",
            },
            "200002": {
                "ProjectID": "200002",
                "ReferenceID": "REF-002",
                "ProjectName": "Network Security Monitoring Services",
                "DateClose": "2026-06-01 21:00:00",
                "DepartmentID": "20",
            },
            "200003": {
                "ProjectID": "200003",
                "ReferenceID": "REF-003",
                "ProjectName": "Janitorial Cleaning Services",
                "DateClose": "2026-04-10 17:00:00",
                "DepartmentID": "30",
            },
        }
    },
}

SUCCESS_ZERO_RESPONSE = {
    "success": 0,
    "message": "Portal temporarily unavailable",
    "payload": {},
}

EMPTY_PROJECTS_RESPONSE = {
    "success": 1,
    "message": "Success",
    "payload": {
        "projects": {},
    },
}


def _mock_httpx_response(data: dict, status_code: int = 200) -> MagicMock:
    """Build a mock httpx.Response that returns JSON data."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = data
    resp.text = json.dumps(data)
    return resp


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def store(tmp_path):
    s = OpportunityStore(db_path=tmp_path / "test.db")
    yield s
    s.close()


@pytest.fixture
def single_portal_scraper(store):
    """Scraper configured with a single test portal."""
    cfg = {"portals": ["testuni"]}
    s = BonfireScraper(store=store, config=cfg, delay_seconds=0, max_retries=0)
    yield s
    s.close()


@pytest.fixture
def two_portal_scraper(store):
    """Scraper configured with two portals."""
    cfg = {"portals": ["portal_a", "portal_b"]}
    s = BonfireScraper(store=store, config=cfg, delay_seconds=0, max_retries=0)
    yield s
    s.close()


@pytest.fixture
def three_portal_scraper(store):
    """Scraper configured with three portals."""
    cfg = {"portals": ["alpha", "beta", "gamma"]}
    s = BonfireScraper(store=store, config=cfg, delay_seconds=0, max_retries=0)
    yield s
    s.close()


# ---------------------------------------------------------------------------
# 1. Single portal JSON parsing
# ---------------------------------------------------------------------------

class TestSinglePortalParsing:
    def test_parses_json_and_returns_results(self, single_portal_scraper, store):
        with patch.object(BonfireScraper, "get", return_value=_mock_httpx_response(SINGLE_PORTAL_RESPONSE)):
            stats = single_portal_scraper.scrape()
        portal_results = stats["portal_results"]
        assert len(portal_results) == 1
        assert portal_results[0]["portal"] == "testuni"
        assert portal_results[0]["status"] == "success"
        # 2 projects found, only 1 matches (Cybersecurity)
        assert portal_results[0]["records_found"] == 2
        # Top-level stats aggregated
        assert stats["records_found"] == 2

    def test_non_matching_projects_not_stored(self, single_portal_scraper, store):
        with patch.object(BonfireScraper, "get", return_value=_mock_httpx_response(SINGLE_PORTAL_RESPONSE)):
            single_portal_scraper.scrape()
        notices = store.get_all_notices()
        titles = [n["title"] for n in notices]
        assert any("Cybersecurity" in t for t in titles)
        assert not any("Furniture" in t for t in titles)


# ---------------------------------------------------------------------------
# 2. Project fields extracted correctly
# ---------------------------------------------------------------------------

class TestProjectFields:
    def test_project_id_name_dateclose_extracted(self, single_portal_scraper, store):
        with patch.object(BonfireScraper, "get", return_value=_mock_httpx_response(SINGLE_PORTAL_RESPONSE)):
            single_portal_scraper.scrape()
        notice = store.get_notice_by_source("bonfire", "testuni-103907")
        assert notice is not None
        assert notice["title"] == "Cybersecurity Assessment Services"
        assert notice["closing_date"] == "2026-03-20 21:00:00"

    def test_raw_json_contains_project_data(self, single_portal_scraper, store):
        with patch.object(BonfireScraper, "get", return_value=_mock_httpx_response(SINGLE_PORTAL_RESPONSE)):
            single_portal_scraper.scrape()
        notice = store.get_notice_by_source("bonfire", "testuni-103907")
        raw = json.loads(notice["raw_json"])
        assert raw["ProjectID"] == "103907"
        assert raw["ReferenceID"] == "2026010099"
        assert raw["DepartmentID"] == "45"


# ---------------------------------------------------------------------------
# 3. Classification with title_only=True
# ---------------------------------------------------------------------------

class TestTitleOnlyClassification:
    def test_classify_called_with_title_only(self, single_portal_scraper, store):
        with patch.object(BonfireScraper, "get", return_value=_mock_httpx_response(SINGLE_PORTAL_RESPONSE)):
            with patch("scrapers.bonfire.classify_opportunity", wraps=__import__("lib.keywords", fromlist=["classify_opportunity"]).classify_opportunity) as mock_classify:
                single_portal_scraper.scrape()
                # Verify title_only=True was passed for every call
                for c in mock_classify.call_args_list:
                    assert c.kwargs.get("title_only") is True

    def test_raw_json_has_title_only_flag(self, single_portal_scraper, store):
        with patch.object(BonfireScraper, "get", return_value=_mock_httpx_response(SINGLE_PORTAL_RESPONSE)):
            single_portal_scraper.scrape()
        notice = store.get_notice_by_source("bonfire", "testuni-103907")
        raw = json.loads(notice["raw_json"])
        assert raw["title_only"] is True


# ---------------------------------------------------------------------------
# 4. Matches stored, non-matches skipped
# ---------------------------------------------------------------------------

class TestMatchStorage:
    def test_matches_stored_nonmatches_skipped(self, single_portal_scraper, store):
        with patch.object(BonfireScraper, "get", return_value=_mock_httpx_response(MULTI_MATCH_RESPONSE)):
            single_portal_scraper.scrape()
        notices = store.get_all_notices()
        titles = [n["title"] for n in notices]
        # Cyber and identity should match; janitorial should not
        assert any("Identity Management" in t for t in titles)
        assert any("Network Security" in t for t in titles)
        assert not any("Janitorial" in t for t in titles)

    def test_records_matched_count(self, single_portal_scraper, store):
        with patch.object(BonfireScraper, "get", return_value=_mock_httpx_response(MULTI_MATCH_RESPONSE)):
            stats = single_portal_scraper.scrape()
        portal_results = stats["portal_results"]
        assert portal_results[0]["records_matched"] >= 2  # identity + network security
        assert portal_results[0]["records_found"] == 3


# ---------------------------------------------------------------------------
# 5. source_id format is "{portal}-{ProjectID}"
# ---------------------------------------------------------------------------

class TestSourceIdFormat:
    def test_source_id_format(self, single_portal_scraper, store):
        with patch.object(BonfireScraper, "get", return_value=_mock_httpx_response(SINGLE_PORTAL_RESPONSE)):
            single_portal_scraper.scrape()
        notices = store.get_all_notices()
        for notice in notices:
            assert notice["source_id"].startswith("testuni-")
            # ProjectID portion should be numeric
            parts = notice["source_id"].split("-", 1)
            assert len(parts) == 2
            assert parts[0] == "testuni"
            assert parts[1].isdigit()

    def test_source_id_unique_across_portals(self, two_portal_scraper, store):
        """Same ProjectID on different portals should produce different source_ids."""
        with patch.object(BonfireScraper, "get", return_value=_mock_httpx_response(SINGLE_PORTAL_RESPONSE)):
            two_portal_scraper.scrape()
        notices = store.get_all_notices()
        source_ids = [n["source_id"] for n in notices]
        # Each portal should have stored matching projects with its own prefix
        portal_a_ids = [sid for sid in source_ids if sid.startswith("portal_a-")]
        portal_b_ids = [sid for sid in source_ids if sid.startswith("portal_b-")]
        assert len(portal_a_ids) >= 1
        assert len(portal_b_ids) >= 1
        # No overlap
        assert not set(portal_a_ids) & set(portal_b_ids)


# ---------------------------------------------------------------------------
# 6. Portal failure isolated
# ---------------------------------------------------------------------------

class TestPortalFailureIsolation:
    def test_one_portal_fails_others_succeed(self, two_portal_scraper, store):
        call_count = 0

        def mock_get(url, **kwargs):
            nonlocal call_count
            call_count += 1
            if "portal_a" in url:
                raise httpx.ConnectError("DNS resolution failed")
            return _mock_httpx_response(SINGLE_PORTAL_RESPONSE)

        with patch.object(BonfireScraper, "get", side_effect=mock_get):
            with patch("scrapers.bonfire.time.sleep"):
                stats = two_portal_scraper.scrape()

        portal_results = stats["portal_results"]
        # portal_a should have errored
        assert portal_results[0]["status"] == "error"
        assert portal_results[0]["portal"] == "portal_a"
        # portal_b should have succeeded
        assert portal_results[1]["status"] == "success"
        assert portal_results[1]["portal"] == "portal_b"
        assert portal_results[1]["records_found"] == 2

        # Notices should still exist from portal_b
        notices = store.get_all_notices()
        assert len(notices) >= 1


# ---------------------------------------------------------------------------
# 7. success=0 response handled
# ---------------------------------------------------------------------------

class TestSuccessZero:
    def test_success_zero_handled_gracefully(self, single_portal_scraper, store):
        with patch.object(BonfireScraper, "get", return_value=_mock_httpx_response(SUCCESS_ZERO_RESPONSE)):
            stats = single_portal_scraper.scrape()
        portal_results = stats["portal_results"]
        assert portal_results[0]["status"] == "success"
        assert portal_results[0]["records_found"] == 0
        assert portal_results[0]["records_matched"] == 0
        assert stats["records_found"] == 0
        # No notices stored
        notices = store.get_all_notices()
        assert len(notices) == 0


# ---------------------------------------------------------------------------
# 8. Empty projects dict handled
# ---------------------------------------------------------------------------

class TestEmptyProjects:
    def test_empty_projects_handled(self, single_portal_scraper, store):
        with patch.object(BonfireScraper, "get", return_value=_mock_httpx_response(EMPTY_PROJECTS_RESPONSE)):
            stats = single_portal_scraper.scrape()
        portal_results = stats["portal_results"]
        assert portal_results[0]["records_found"] == 0
        assert portal_results[0]["records_matched"] == 0
        assert portal_results[0]["records_new"] == 0
        assert stats["records_found"] == 0
        notices = store.get_all_notices()
        assert len(notices) == 0


# ---------------------------------------------------------------------------
# 9. Source run logged per portal
# ---------------------------------------------------------------------------

class TestSourceRunPerPortal:
    def test_source_run_per_portal(self, two_portal_scraper, store):
        with patch.object(BonfireScraper, "get", return_value=_mock_httpx_response(SINGLE_PORTAL_RESPONSE)):
            with patch("scrapers.bonfire.time.sleep"):
                two_portal_scraper.scrape()

        run_a = store.get_latest_run("bonfire-portal_a")
        run_b = store.get_latest_run("bonfire-portal_b")
        assert run_a is not None
        assert run_b is not None
        assert run_a["status"] == "success"
        assert run_b["status"] == "success"

    def test_failed_portal_run_logged_as_error(self, two_portal_scraper, store):
        def mock_get(url, **kwargs):
            if "portal_a" in url:
                raise httpx.ConnectError("connection refused")
            return _mock_httpx_response(SINGLE_PORTAL_RESPONSE)

        with patch.object(BonfireScraper, "get", side_effect=mock_get):
            with patch("scrapers.bonfire.time.sleep"):
                two_portal_scraper.scrape()

        run_a = store.get_latest_run("bonfire-portal_a")
        assert run_a["status"] == "error"
        assert "connection refused" in run_a["error_message"]


# ---------------------------------------------------------------------------
# 10. All portals fail -> logs CRITICAL
# ---------------------------------------------------------------------------

class TestAllPortalsFail:
    def test_all_portals_fail_logs_critical(self, three_portal_scraper, store, caplog):
        def mock_get(url, **kwargs):
            raise httpx.ConnectError("DNS failure")

        with patch.object(BonfireScraper, "get", side_effect=mock_get):
            with patch("scrapers.bonfire.time.sleep"):
                with caplog.at_level(logging.CRITICAL, logger="scrapers.bonfire"):
                    stats = three_portal_scraper.scrape()

        portal_results = stats["portal_results"]
        # All portals should be errors
        assert all(r["status"] == "error" for r in portal_results)
        # CRITICAL log message should be present
        assert any("All 3 portals failed" in r.message for r in caplog.records if r.levelno == logging.CRITICAL)

    def test_all_portals_fail_no_mark_success(self, three_portal_scraper, store):
        def mock_get(url, **kwargs):
            raise httpx.ConnectError("DNS failure")

        with patch.object(BonfireScraper, "get", side_effect=mock_get):
            with patch("scrapers.bonfire.time.sleep"):
                three_portal_scraper.scrape()

        assert three_portal_scraper.last_run is None


# ---------------------------------------------------------------------------
# 11. 2-second delay between portals
# ---------------------------------------------------------------------------

class TestInterPortalDelay:
    def test_sleep_called_between_portals(self, three_portal_scraper, store):
        with patch.object(BonfireScraper, "get", return_value=_mock_httpx_response(EMPTY_PROJECTS_RESPONSE)):
            with patch("scrapers.bonfire.time.sleep") as mock_sleep:
                three_portal_scraper.scrape()
        # Should have slept between portals (n-1 times for n portals)
        assert mock_sleep.call_count == 2
        for c in mock_sleep.call_args_list:
            assert c.args[0] == PORTAL_DELAY_SECONDS

    def test_no_sleep_before_first_portal(self, single_portal_scraper, store):
        with patch.object(BonfireScraper, "get", return_value=_mock_httpx_response(EMPTY_PROJECTS_RESPONSE)):
            with patch("scrapers.bonfire.time.sleep") as mock_sleep:
                single_portal_scraper.scrape()
        # Single portal: no inter-portal sleep
        mock_sleep.assert_not_called()


# ---------------------------------------------------------------------------
# 12. Scraper name attribute
# ---------------------------------------------------------------------------

class TestScraperName:
    def test_scraper_name(self, single_portal_scraper):
        assert single_portal_scraper.name == "bonfire"

    def test_scraper_name_class_attribute(self):
        assert BonfireScraper.name == "bonfire"


# ---------------------------------------------------------------------------
# Additional edge-case tests
# ---------------------------------------------------------------------------

class TestAdditionalEdgeCases:
    def test_403_response_handled(self, single_portal_scraper, store):
        """Portal returning 403 should be caught and logged as error."""
        def mock_get(url, **kwargs):
            resp = MagicMock(spec=httpx.Response)
            resp.status_code = 403
            resp.raise_for_status.side_effect = httpx.HTTPStatusError(
                "Forbidden", request=MagicMock(), response=resp,
            )
            raise resp.raise_for_status.side_effect

        with patch.object(BonfireScraper, "get", side_effect=mock_get):
            stats = single_portal_scraper.scrape()
        portal_results = stats["portal_results"]
        assert portal_results[0]["status"] == "error"
        run = store.get_latest_run("bonfire-testuni")
        assert run["status"] == "error"

    def test_json_parse_error_handled(self, single_portal_scraper, store):
        """Invalid JSON response should be caught as error."""
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 200
        resp.json.side_effect = json.JSONDecodeError("bad json", "", 0)

        with patch.object(BonfireScraper, "get", return_value=resp):
            stats = single_portal_scraper.scrape()
        portal_results = stats["portal_results"]
        assert portal_results[0]["status"] == "error"

    def test_mark_success_called_on_partial_success(self, two_portal_scraper, store):
        """If at least one portal succeeds, _mark_success should be called."""
        def mock_get(url, **kwargs):
            if "portal_a" in url:
                raise httpx.ConnectError("fail")
            return _mock_httpx_response(SINGLE_PORTAL_RESPONSE)

        with patch.object(BonfireScraper, "get", side_effect=mock_get):
            with patch("scrapers.bonfire.time.sleep"):
                two_portal_scraper.scrape()

        assert two_portal_scraper.last_run is not None

    def test_dedup_on_second_run(self, single_portal_scraper, store):
        """Second run with same data should produce 0 new records."""
        with patch.object(BonfireScraper, "get", return_value=_mock_httpx_response(SINGLE_PORTAL_RESPONSE)):
            stats1 = single_portal_scraper.scrape()
            stats2 = single_portal_scraper.scrape()
        assert stats1["portal_results"][0]["records_new"] >= 1
        assert stats2["portal_results"][0]["records_new"] == 0
