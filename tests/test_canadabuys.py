"""Tests for scrapers/canadabuys.py - CanadaBuys CSV scraper."""

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from lib.storage import OpportunityStore
from scrapers.canadabuys import CanadaBuysScraper

FIXTURE_DIR = Path(__file__).parent / "fixtures"
FIXTURE_CSV = FIXTURE_DIR / "canadabuys_sample.csv"


@pytest.fixture
def store(tmp_path):
    s = OpportunityStore(db_path=tmp_path / "test.db")
    yield s
    s.close()


@pytest.fixture
def scraper(store):
    s = CanadaBuysScraper(store=store, delay_seconds=0, max_retries=0)
    yield s
    s.close()


@pytest.fixture
def csv_text():
    return FIXTURE_CSV.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# CSV parsing
# ---------------------------------------------------------------------------

class TestParseCSV:
    def test_parse_returns_list_of_dicts(self, scraper, csv_text):
        tenders = scraper.parse_csv(csv_text)
        assert isinstance(tenders, list)
        assert len(tenders) == 5  # 5 data rows

    def test_parse_extracts_title(self, scraper, csv_text):
        tenders = scraper.parse_csv(csv_text)
        titles = [t.get("title-titre-eng", "") for t in tenders]
        assert "Cybersecurity Assessment Services for Federal Networks" in titles

    def test_parse_extracts_source_id(self, scraper, csv_text):
        tenders = scraper.parse_csv(csv_text)
        sol_nums = [t.get("solicitationNumber-numeroSollicitation", "") for t in tenders]
        assert "SOL-900001" in sol_nums

    def test_parse_extracts_buyer(self, scraper, csv_text):
        tenders = scraper.parse_csv(csv_text)
        orgs = [t.get("contractingEntityName-nomEntitContractante-eng", "") for t in tenders]
        assert "Public Services and Procurement Canada" in orgs

    def test_parse_handles_bom(self, scraper):
        bom_csv = "\ufeffsolicitationNumber,title,description,organizationName\nBOM-001,SIEM Deployment,Deploy SIEM,Test Org\n"
        tenders = scraper.parse_csv(bom_csv)
        assert len(tenders) == 1

    def test_parse_empty_csv_returns_empty(self, scraper):
        tenders = scraper.parse_csv("solicitationNumber,title\n")
        assert tenders == []


# ---------------------------------------------------------------------------
# UNSPSC extraction
# ---------------------------------------------------------------------------

class TestUNSPSC:
    def test_single_unspsc_code(self, scraper):
        row = {"unspsc": "81112200"}
        codes = scraper._extract_unspsc(row)
        assert codes == ["81112200"]

    def test_multivalue_newline_separated(self, scraper):
        row = {"unspsc": "81112200\n43232300"}
        codes = scraper._extract_unspsc(row)
        assert "81112200" in codes
        assert "43232300" in codes

    def test_empty_unspsc(self, scraper):
        row = {"unspsc": ""}
        codes = scraper._extract_unspsc(row)
        assert codes == []

    def test_missing_unspsc_key(self, scraper):
        row = {}
        codes = scraper._extract_unspsc(row)
        assert codes == []


# ---------------------------------------------------------------------------
# Classification integration
# ---------------------------------------------------------------------------

class TestClassification:
    def test_cyber_tender_matched(self, scraper, csv_text):
        tenders = scraper.parse_csv(csv_text)
        from lib.keywords import classify_opportunity
        cyber = [t for t in tenders if t["solicitationNumber-numeroSollicitation"] == "SOL-900001"][0]
        result = classify_opportunity(cyber["title-titre-eng"], cyber["tenderDescription-descriptionAppelOffres-eng"])
        assert result["tier"] == 1

    def test_furniture_not_matched(self, scraper, csv_text):
        tenders = scraper.parse_csv(csv_text)
        from lib.keywords import classify_opportunity
        furniture = [t for t in tenders if t["solicitationNumber-numeroSollicitation"] == "SOL-900004"][0]
        result = classify_opportunity(furniture["title-titre-eng"], furniture["tenderDescription-descriptionAppelOffres-eng"])
        assert result["tier"] == 0

    def test_guard_services_not_matched(self, scraper, csv_text):
        from lib.keywords import classify_opportunity
        result = classify_opportunity(
            "Security Guard Services for Government Buildings",
            "Provision of guard services including armoured car transport and locksmith services",
        )
        assert result["tier"] == 0


# ---------------------------------------------------------------------------
# Scrape with mock HTTP
# ---------------------------------------------------------------------------

class TestScrapeIntegration:
    def test_scrape_stores_matches(self, scraper, store, csv_text):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = csv_text
        mock_resp.headers = {"ETag": '"test-etag"'}

        with patch.object(scraper, "get", return_value=mock_resp):
            stats = scraper.scrape()

        assert isinstance(stats, dict)
        assert stats["records_matched"] > 0
        all_notices = store.get_all_notices()
        assert len(all_notices) > 0

    def test_scrape_ignores_tier0(self, scraper, store, csv_text):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = csv_text
        mock_resp.headers = {}

        with patch.object(scraper, "get", return_value=mock_resp):
            scraper.scrape()

        notices = store.get_all_notices()
        for n in notices:
            import json
            cls = json.loads(n["classification_json"])
            assert cls["tier"] > 0

    def test_scrape_logs_source_run(self, scraper, store, csv_text):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = csv_text
        mock_resp.headers = {}

        with patch.object(scraper, "get", return_value=mock_resp):
            scraper.scrape()

        run = store.get_latest_run("canadabuys")
        assert run is not None
        assert run["status"] == "success"
        assert run["records_found"] > 0

    def test_scrape_304_not_modified(self, scraper, store):
        mock_resp = MagicMock()
        mock_resp.status_code = 304
        mock_resp.headers = {}

        with patch.object(scraper, "get", return_value=mock_resp):
            results = scraper.scrape()

        assert results["records_found"] == 0
        run = store.get_latest_run("canadabuys")
        assert run["status"] == "success"

    def test_scrape_error_logged(self, scraper, store):
        with patch.object(scraper, "get", side_effect=Exception("Connection failed")):
            with pytest.raises(Exception):
                scraper.scrape()

        run = store.get_latest_run("canadabuys")
        assert run["status"] == "error"
        assert "Connection failed" in run["error_message"]


# ---------------------------------------------------------------------------
# ETag / conditional GET
# ---------------------------------------------------------------------------

class TestETag:
    def test_etag_stored(self, scraper, csv_text):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = csv_text
        mock_resp.headers = {"ETag": '"abc123"'}

        with patch.object(scraper, "get", return_value=mock_resp):
            scraper.fetch_csv()

        assert scraper._etag == '"abc123"'

    def test_etag_sent_on_next_request(self, scraper, csv_text):
        scraper._etag = '"cached-etag"'

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = csv_text
        mock_resp.headers = {"ETag": '"new-etag"'}

        with patch.object(scraper, "get", return_value=mock_resp) as mock_get:
            scraper.fetch_csv()

        call_kwargs = mock_get.call_args
        assert call_kwargs[1]["headers"]["If-None-Match"] == '"cached-etag"'


# ---------------------------------------------------------------------------
# curl fallback
# ---------------------------------------------------------------------------

class TestCurlFallback:
    def test_curl_fallback_triggered_on_small_response(self, scraper, csv_text):
        """When httpx returns <100KB, fetch_csv should fall back to curl."""
        # httpx returns a tiny (truncated) response
        tiny_resp = MagicMock()
        tiny_resp.status_code = 200
        tiny_resp.text = "truncated,data\n"  # well under 100KB
        tiny_resp.headers = {}

        with patch.object(scraper, "get", return_value=tiny_resp), \
             patch.object(scraper, "_fetch_csv_via_curl", return_value=csv_text) as mock_curl:
            result = scraper.fetch_csv()

        mock_curl.assert_called_once_with(scraper.url)
        assert result == csv_text

    def test_curl_fallback_not_triggered_on_large_response(self, scraper, csv_text):
        """When httpx returns >=100KB, curl fallback must not be invoked."""
        # Pad csv_text to exceed the threshold
        big_text = csv_text + ("x" * 200_000)
        big_resp = MagicMock()
        big_resp.status_code = 200
        big_resp.text = big_text
        big_resp.headers = {}

        with patch.object(scraper, "get", return_value=big_resp), \
             patch.object(scraper, "_fetch_csv_via_curl") as mock_curl:
            result = scraper.fetch_csv()

        mock_curl.assert_not_called()
        assert result == big_text

    def test_fetch_csv_via_curl_returns_text(self, scraper, csv_text, tmp_path):
        """_fetch_csv_via_curl writes to a temp file and reads it back correctly."""
        # Write fixture CSV to a temp file and simulate curl writing it there
        def fake_run(cmd, **kwargs):
            # cmd is ["curl", "-s", "--compressed", "-o", tmpfile, url]
            out_path = cmd[4]
            Path(out_path).write_text(csv_text, encoding="utf-8")
            result = MagicMock()
            result.returncode = 0
            result.stderr = b""
            return result

        with patch("scrapers.canadabuys.subprocess.run", side_effect=fake_run):
            text = scraper._fetch_csv_via_curl(scraper.url)

        assert "Cybersecurity" in text

    def test_fetch_csv_via_curl_raises_on_failure(self, scraper):
        """_fetch_csv_via_curl raises RuntimeError when curl exits non-zero."""
        fail_result = MagicMock()
        fail_result.returncode = 6  # curl: couldn't resolve host
        fail_result.stderr = b"Could not resolve host"

        with patch("scrapers.canadabuys.subprocess.run", return_value=fail_result), \
             patch("tempfile.NamedTemporaryFile"):
            with pytest.raises(RuntimeError, match="curl failed"):
                scraper._fetch_csv_via_curl(scraper.url)

    def test_curl_fallback_not_triggered_on_304(self, scraper):
        """304 responses must return None without attempting curl fallback."""
        resp_304 = MagicMock()
        resp_304.status_code = 304
        resp_304.headers = {}

        with patch.object(scraper, "get", return_value=resp_304), \
             patch.object(scraper, "_fetch_csv_via_curl") as mock_curl:
            result = scraper.fetch_csv()

        mock_curl.assert_not_called()
        assert result is None
