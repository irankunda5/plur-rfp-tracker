"""Tests for scrapers/sasktenders.py - SaskTenders HTML scraper."""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx
import pytest
from lib.storage import OpportunityStore
from scrapers.sasktenders import SaskTendersScraper

FIXTURE_DIR = Path(__file__).parent / "fixtures"
SAMPLE_HTML = (FIXTURE_DIR / "sasktenders_sample.html").read_text()

# HTML with no table at all
EMPTY_PAGE_HTML = "<html><body><p>No results found.</p></body></html>"

# HTML with a table but no data rows
EMPTY_TABLE_HTML = """<html><body>
<table class="table" id="tenderResults">
<thead><tr><th>Competition Number</th><th>Title</th><th>Organization</th>
<th>Closing Date</th><th>Status</th></tr></thead>
<tbody></tbody>
</table></body></html>"""


@pytest.fixture
def store(tmp_path):
    s = OpportunityStore(db_path=tmp_path / "test.db")
    yield s
    s.close()


@pytest.fixture
def scraper(store):
    s = SaskTendersScraper(store=store, delay_seconds=0, max_retries=0)
    yield s
    s.close()


def _mock_response(text, status_code=200, headers=None):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.text = text
    resp.headers = headers or {}
    return resp


# ---------------------------------------------------------------------------
# 1. HTML table parsing
# ---------------------------------------------------------------------------

class TestParseHTML:
    def test_parse_returns_all_rows(self, scraper):
        """All 5 rows from the fixture are parsed."""
        tenders = scraper.parse_html(SAMPLE_HTML)
        assert len(tenders) == 5

    def test_parse_extracts_fields(self, scraper):
        """Each parsed tender has the expected keys."""
        tenders = scraper.parse_html(SAMPLE_HTML)
        first = tenders[0]
        assert "tender_id" in first
        assert "title" in first
        assert "organization" in first
        assert "closing_date" in first
        assert "url" in first

    def test_parse_title_text(self, scraper):
        """Title text is extracted correctly from table cells."""
        tenders = scraper.parse_html(SAMPLE_HTML)
        titles = [t["title"] for t in tenders]
        assert "Cybersecurity Assessment Services" in titles
        assert "Network Infrastructure Upgrade" in titles
        assert "Identity Governance and Administration Solution" in titles
        assert "Office Furniture Supply" in titles
        assert "Road Maintenance Equipment" in titles


# ---------------------------------------------------------------------------
# 2. Classification filters correctly (IT stored, non-IT skipped)
# ---------------------------------------------------------------------------

class TestClassificationFilter:
    @patch.object(SaskTendersScraper, "fetch_html")
    def test_it_matches_stored_non_it_skipped(self, mock_fetch, scraper, store):
        """IT/cyber tenders are stored; non-IT tenders are skipped."""
        mock_fetch.return_value = SAMPLE_HTML
        scraper.scrape()
        notices = store.get_all_notices()
        stored_titles = [n["title"] for n in notices]
        # IT/cyber matches should be stored
        assert "Cybersecurity Assessment Services" in stored_titles
        assert "Network Infrastructure Upgrade" in stored_titles
        assert "Identity Governance and Administration Solution" in stored_titles
        # Non-IT should NOT be stored
        assert "Office Furniture Supply" not in stored_titles
        assert "Road Maintenance Equipment" not in stored_titles

    @patch.object(SaskTendersScraper, "fetch_html")
    def test_correct_match_count(self, mock_fetch, scraper, store):
        """3 out of 5 rows should match (2 IT/cyber + 1 IAM)."""
        mock_fetch.return_value = SAMPLE_HTML
        stats = scraper.scrape()
        assert stats["records_matched"] == 3


# ---------------------------------------------------------------------------
# 3. source_id extracted from competition number
# ---------------------------------------------------------------------------

class TestSourceId:
    def test_source_id_from_competition_number(self, scraper):
        """tender_id field contains the competition number text."""
        tenders = scraper.parse_html(SAMPLE_HTML)
        ids = [t["tender_id"] for t in tenders]
        assert "SK-2026-0101" in ids
        assert "SK-2026-0102" in ids
        assert "SK-2026-0103" in ids

    @patch.object(SaskTendersScraper, "fetch_html")
    def test_source_id_stored_in_db(self, mock_fetch, scraper, store):
        """Competition number is used as source_id in the database."""
        mock_fetch.return_value = SAMPLE_HTML
        scraper.scrape()
        notice = store.get_notice_by_source("sasktenders", "SK-2026-0101")
        assert notice is not None
        assert notice["source_id"] == "SK-2026-0101"


# ---------------------------------------------------------------------------
# 4. buyer extracted from organization column
# ---------------------------------------------------------------------------

class TestBuyer:
    def test_buyer_parsed(self, scraper):
        """Organization column is parsed as the buyer field."""
        tenders = scraper.parse_html(SAMPLE_HTML)
        orgs = [t["organization"] for t in tenders]
        assert "Saskatchewan Health Authority" in orgs
        assert "Ministry of SaskBuilds and Procurement" in orgs
        assert "University of Regina" in orgs

    @patch.object(SaskTendersScraper, "fetch_html")
    def test_buyer_stored_in_db(self, mock_fetch, scraper, store):
        """Buyer field is persisted to the database."""
        mock_fetch.return_value = SAMPLE_HTML
        scraper.scrape()
        notice = store.get_notice_by_source("sasktenders", "SK-2026-0101")
        assert notice["buyer"] == "Saskatchewan Health Authority"


# ---------------------------------------------------------------------------
# 5. closing_date parsed
# ---------------------------------------------------------------------------

class TestClosingDate:
    def test_closing_date_parsed(self, scraper):
        """Closing date text is extracted from the table."""
        tenders = scraper.parse_html(SAMPLE_HTML)
        dates = [t["closing_date"] for t in tenders]
        assert "Apr 15, 2026" in dates
        assert "Apr 22, 2026" in dates

    @patch.object(SaskTendersScraper, "fetch_html")
    def test_closing_date_stored_in_db(self, mock_fetch, scraper, store):
        """Closing date is persisted to the database."""
        mock_fetch.return_value = SAMPLE_HTML
        scraper.scrape()
        notice = store.get_notice_by_source("sasktenders", "SK-2026-0101")
        assert notice["closing_date"] == "Apr 15, 2026"


# ---------------------------------------------------------------------------
# 6. Empty results handling (no rows in table)
# ---------------------------------------------------------------------------

class TestEmptyResults:
    def test_no_table_returns_empty(self, scraper):
        """Page with no table returns empty list."""
        tenders = scraper.parse_html(EMPTY_PAGE_HTML)
        assert tenders == []

    def test_empty_tbody_returns_empty(self, scraper):
        """Table with empty tbody returns empty list."""
        tenders = scraper.parse_html(EMPTY_TABLE_HTML)
        assert tenders == []

    @patch.object(SaskTendersScraper, "fetch_html")
    def test_scrape_empty_page_no_error(self, mock_fetch, scraper, store):
        """Scraping a page with no results completes without error."""
        mock_fetch.return_value = EMPTY_PAGE_HTML
        stats = scraper.scrape()
        assert stats["records_found"] == 0
        assert stats["records_matched"] == 0
        assert stats["records_new"] == 0
        run = store.get_latest_run("sasktenders")
        assert run["status"] == "success"
        assert run["records_found"] == 0


# ---------------------------------------------------------------------------
# 7. Network error handling
# ---------------------------------------------------------------------------

class TestNetworkError:
    @patch.object(SaskTendersScraper, "fetch_html")
    def test_network_error_raises(self, mock_fetch, scraper, store):
        """Network errors propagate as exceptions."""
        mock_fetch.side_effect = httpx.ConnectError("Connection refused")
        with pytest.raises(httpx.ConnectError):
            scraper.scrape()

    @patch.object(SaskTendersScraper, "fetch_html")
    def test_network_error_logged_in_run(self, mock_fetch, scraper, store):
        """Network errors are recorded in the source_run table."""
        mock_fetch.side_effect = httpx.ConnectError("Connection refused")
        with pytest.raises(httpx.ConnectError):
            scraper.scrape()
        run = store.get_latest_run("sasktenders")
        assert run["status"] == "error"
        assert "Connection refused" in run["error_message"]

    @patch.object(SaskTendersScraper, "fetch_html")
    def test_generic_exception_logged(self, mock_fetch, scraper, store):
        """Generic exceptions are also recorded in source_run."""
        mock_fetch.side_effect = ValueError("Unexpected HTML structure")
        with pytest.raises(ValueError):
            scraper.scrape()
        run = store.get_latest_run("sasktenders")
        assert run["status"] == "error"
        assert "Unexpected HTML structure" in run["error_message"]


# ---------------------------------------------------------------------------
# 8. Source run logging
# ---------------------------------------------------------------------------

class TestSourceRunLogging:
    @patch.object(SaskTendersScraper, "fetch_html")
    def test_source_run_created(self, mock_fetch, scraper, store):
        """A source_run record is created for each scrape."""
        mock_fetch.return_value = SAMPLE_HTML
        scraper.scrape()
        run = store.get_latest_run("sasktenders")
        assert run is not None
        assert run["source"] == "sasktenders"

    @patch.object(SaskTendersScraper, "fetch_html")
    def test_source_run_records_found(self, mock_fetch, scraper, store):
        """source_run records the total number of rows found."""
        mock_fetch.return_value = SAMPLE_HTML
        scraper.scrape()
        run = store.get_latest_run("sasktenders")
        assert run["records_found"] == 5

    @patch.object(SaskTendersScraper, "fetch_html")
    def test_source_run_records_matched(self, mock_fetch, scraper, store):
        """source_run records the number of classified matches."""
        mock_fetch.return_value = SAMPLE_HTML
        scraper.scrape()
        run = store.get_latest_run("sasktenders")
        assert run["records_matched"] == 3

    @patch.object(SaskTendersScraper, "fetch_html")
    def test_source_run_records_new(self, mock_fetch, scraper, store):
        """source_run records the number of newly stored notices."""
        mock_fetch.return_value = SAMPLE_HTML
        scraper.scrape()
        run = store.get_latest_run("sasktenders")
        assert run["records_new"] == 3

    @patch.object(SaskTendersScraper, "fetch_html")
    def test_source_run_success_status(self, mock_fetch, scraper, store):
        """Successful scrape results in 'success' status."""
        mock_fetch.return_value = SAMPLE_HTML
        scraper.scrape()
        run = store.get_latest_run("sasktenders")
        assert run["status"] == "success"

    @patch.object(SaskTendersScraper, "fetch_html")
    def test_source_run_dedup_second_run(self, mock_fetch, scraper, store):
        """Second run with same data yields 0 new records."""
        mock_fetch.return_value = SAMPLE_HTML
        scraper.scrape()
        scraper.scrape()
        runs = store._conn.execute(
            "SELECT * FROM source_runs WHERE source = ? ORDER BY start_time",
            ("sasktenders",),
        ).fetchall()
        assert len(runs) == 2
        second_run = dict(runs[1])
        assert second_run["records_new"] == 0
        assert second_run["records_matched"] == 3


# ---------------------------------------------------------------------------
# 9. Scraper name attribute
# ---------------------------------------------------------------------------

class TestScraperName:
    def test_name_attribute(self, scraper):
        """Scraper has correct name attribute."""
        assert scraper.name == "sasktenders"

    def test_name_is_class_attribute(self):
        """name is defined as a class attribute on the class."""
        assert SaskTendersScraper.name == "sasktenders"

    def test_url_attribute(self, scraper):
        """Scraper has the correct URL attribute."""
        assert "sasktenders.ca" in scraper.url
        assert "statusId=-2" in scraper.url


# ---------------------------------------------------------------------------
# 10. title_only mode used for classification
# ---------------------------------------------------------------------------

class TestTitleOnlyMode:
    @patch.object(SaskTendersScraper, "fetch_html")
    def test_title_only_classification(self, mock_fetch, scraper, store):
        """classify_opportunity is called with title_only=True."""
        mock_fetch.return_value = SAMPLE_HTML
        with patch(
            "scrapers.sasktenders.classify_opportunity",
            wraps=__import__(
                "lib.keywords", fromlist=["classify_opportunity"]
            ).classify_opportunity,
        ) as mock_classify:
            scraper.scrape()
            # Every call should have title_only=True
            assert mock_classify.call_count >= 5
            for call in mock_classify.call_args_list:
                assert call.kwargs.get("title_only") is True

    @patch.object(SaskTendersScraper, "fetch_html")
    def test_description_always_empty(self, mock_fetch, scraper, store):
        """Stored notices have empty description (no login-gated content)."""
        mock_fetch.return_value = SAMPLE_HTML
        scraper.scrape()
        notices = store.get_all_notices()
        for notice in notices:
            assert notice["description"] == ""


# ---------------------------------------------------------------------------
# Additional: URL construction, classification tiers, mark_success
# ---------------------------------------------------------------------------

class TestURLConstruction:
    def test_relative_url_resolved(self, scraper):
        """Relative hrefs are resolved to absolute URLs."""
        tenders = scraper.parse_html(SAMPLE_HTML)
        for t in tenders:
            assert t["url"].startswith("https://sasktenders.ca/")

    def test_url_contains_detail_path(self, scraper):
        """URLs point to the tender detail page."""
        tenders = scraper.parse_html(SAMPLE_HTML)
        first = tenders[0]
        assert "TenderDetail" in first["url"]


class TestClassificationTier:
    @patch.object(SaskTendersScraper, "fetch_html")
    def test_cyber_tier1_stored(self, mock_fetch, scraper, store):
        """Cybersecurity title produces tier 1 classification."""
        mock_fetch.return_value = SAMPLE_HTML
        scraper.scrape()
        notice = store.get_notice_by_source("sasktenders", "SK-2026-0101")
        cls = json.loads(notice["classification_json"])
        assert cls["tier"] == 1
        assert "cybersecurity" in [kw.lower() for kw in cls["matched_keywords"]]

    @patch.object(SaskTendersScraper, "fetch_html")
    def test_iam_tier2_stored(self, mock_fetch, scraper, store):
        """IAM/identity governance title produces tier 2 classification."""
        mock_fetch.return_value = SAMPLE_HTML
        scraper.scrape()
        notice = store.get_notice_by_source("sasktenders", "SK-2026-0103")
        cls = json.loads(notice["classification_json"])
        assert cls["tier"] == 2

    @patch.object(SaskTendersScraper, "fetch_html")
    def test_broader_it_tier3_stored(self, mock_fetch, scraper, store):
        """Broader IT title produces tier 3 classification."""
        mock_fetch.return_value = SAMPLE_HTML
        scraper.scrape()
        notice = store.get_notice_by_source("sasktenders", "SK-2026-0102")
        cls = json.loads(notice["classification_json"])
        assert cls["tier"] == 3


class TestMarkSuccess:
    @patch.object(SaskTendersScraper, "fetch_html")
    def test_last_run_set_on_success(self, mock_fetch, scraper):
        """_mark_success sets last_run timestamp after successful scrape."""
        mock_fetch.return_value = SAMPLE_HTML
        assert scraper.last_run is None
        scraper.scrape()
        assert scraper.last_run is not None

    @patch.object(SaskTendersScraper, "fetch_html")
    def test_last_run_not_set_on_error(self, mock_fetch, scraper):
        """last_run remains None if scrape fails."""
        mock_fetch.side_effect = Exception("fail")
        with pytest.raises(Exception):
            scraper.scrape()
        assert scraper.last_run is None
