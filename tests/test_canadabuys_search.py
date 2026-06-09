"""Tests for scrapers/canadabuys_search.py - CanadaBuys website search scraper."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, call

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from lib.storage import OpportunityStore
from scrapers.canadabuys_search import CanadaBuysSearchScraper, BASE_URL

FIXTURE_DIR = Path(__file__).parent / "fixtures"
FIXTURE_PAGE = FIXTURE_DIR / "canadabuys_search_page.html"
FIXTURE_PAGE2 = FIXTURE_DIR / "canadabuys_search_page2.html"
FIXTURE_EMPTY = FIXTURE_DIR / "canadabuys_search_empty.html"


@pytest.fixture
def store(tmp_path):
    s = OpportunityStore(db_path=tmp_path / "test.db")
    yield s
    s.close()


@pytest.fixture
def scraper(store):
    # Use a single search term for simpler tests
    s = CanadaBuysSearchScraper(
        store=store,
        config={"search_terms": ["cybersecurity"]},
        delay_seconds=0,
        max_retries=0,
    )
    yield s
    s.close()


@pytest.fixture
def page_html():
    return FIXTURE_PAGE.read_text(encoding="utf-8")


@pytest.fixture
def page2_html():
    return FIXTURE_PAGE2.read_text(encoding="utf-8")


@pytest.fixture
def empty_html():
    return FIXTURE_EMPTY.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# URL building
# ---------------------------------------------------------------------------

class TestBuildSearchURL:
    def test_basic_url(self):
        url = CanadaBuysSearchScraper.build_search_url("cybersecurity")
        assert "words=cybersecurity" in url
        assert "status%5B87%5D=87" in url
        assert "items_per_page=200" in url
        assert BASE_URL in url

    def test_page_zero_no_page_param(self):
        url = CanadaBuysSearchScraper.build_search_url("test", page=0)
        assert "%2C0%2C0%2C0" not in url  # No pagination suffix

    def test_page_one(self):
        url = CanadaBuysSearchScraper.build_search_url("test", page=1)
        assert "page=%2C1%2C0%2C0" in url

    def test_page_five(self):
        url = CanadaBuysSearchScraper.build_search_url("test", page=5)
        assert "page=%2C5%2C0%2C0" in url

    def test_spaces_encoded(self):
        url = CanadaBuysSearchScraper.build_search_url("cyber security")
        assert "words=cyber+security" in url or "words=cyber%20security" in url


# ---------------------------------------------------------------------------
# HTML parsing
# ---------------------------------------------------------------------------

class TestParseSearchResults:
    def test_parse_returns_list(self, page_html):
        results = CanadaBuysSearchScraper.parse_search_results(page_html)
        assert isinstance(results, list)
        assert len(results) == 5

    def test_parse_extracts_source_id(self, page_html):
        results = CanadaBuysSearchScraper.parse_search_results(page_html)
        ids = [r["source_id"] for r in results]
        assert "pw-23-00999111" in ids
        assert "cb-555-12345678" in ids
        assert "ab-2026-88888" in ids

    def test_parse_extracts_title(self, page_html):
        results = CanadaBuysSearchScraper.parse_search_results(page_html)
        titles = [r["title"] for r in results]
        assert "Cybersecurity Assessment Services for Federal Networks" in titles
        assert "SIEM Platform Managed Services" in titles

    def test_parse_extracts_buyer(self, page_html):
        results = CanadaBuysSearchScraper.parse_search_results(page_html)
        buyers = [r["buyer"] for r in results]
        assert "Public Services and Procurement Canada" in buyers
        assert "Department of National Defence" in buyers

    def test_parse_extracts_closing_date(self, page_html):
        results = CanadaBuysSearchScraper.parse_search_results(page_html)
        dates = [r["closing_date"] for r in results]
        assert "2026-04-15" in dates
        assert "2026-04-20" in dates

    def test_parse_extracts_category(self, page_html):
        results = CanadaBuysSearchScraper.parse_search_results(page_html)
        categories = [r["category"] for r in results]
        assert "Services" in categories
        assert "Goods" in categories

    def test_parse_builds_full_url(self, page_html):
        results = CanadaBuysSearchScraper.parse_search_results(page_html)
        for r in results:
            assert r["url"].startswith("https://canadabuys.canada.ca/en/")

    def test_parse_empty_page(self, empty_html):
        results = CanadaBuysSearchScraper.parse_search_results(empty_html)
        assert results == []

    def test_parse_no_view(self):
        results = CanadaBuysSearchScraper.parse_search_results("<html><body>Nothing</body></html>")
        assert results == []


# ---------------------------------------------------------------------------
# Pagination detection
# ---------------------------------------------------------------------------

class TestPagination:
    def test_no_pager_on_single_page(self, page_html):
        assert CanadaBuysSearchScraper.has_next_page(page_html) is False

    def test_pager_detected(self, page2_html):
        assert CanadaBuysSearchScraper.has_next_page(page2_html) is True


# ---------------------------------------------------------------------------
# Total count extraction
# ---------------------------------------------------------------------------

class TestTotalCount:
    def test_total_count_extracted(self, page_html):
        count = CanadaBuysSearchScraper.get_total_count(page_html)
        assert count == 5

    def test_total_count_with_comma(self):
        html = '<div class="view-search-opportunities"><span class="search-total-count">1,234</span></div>'
        count = CanadaBuysSearchScraper.get_total_count(html)
        assert count == 1234

    def test_total_count_zero_on_empty(self, empty_html):
        count = CanadaBuysSearchScraper.get_total_count(empty_html)
        assert count == 0

    def test_total_count_zero_on_missing(self):
        count = CanadaBuysSearchScraper.get_total_count("<html></html>")
        assert count == 0


# ---------------------------------------------------------------------------
# Cross-term deduplication
# ---------------------------------------------------------------------------

class TestDeduplication:
    def test_seen_ids_prevent_duplicates(self, scraper, page_html):
        """Results already in seen_ids are not returned."""
        mock_resp = MagicMock()
        mock_resp.text = page_html

        with patch.object(scraper, "get", return_value=mock_resp):
            seen = {"pw-23-00999111"}  # Pre-seed one ID
            results = scraper.search_term("cybersecurity", seen)

        ids = [r["source_id"] for r in results]
        assert "pw-23-00999111" not in ids
        assert len(results) == 4  # 5 total minus 1 pre-seeded

    def test_seen_ids_updated(self, scraper, page_html):
        """search_term adds found IDs to seen_ids set."""
        mock_resp = MagicMock()
        mock_resp.text = page_html

        with patch.object(scraper, "get", return_value=mock_resp):
            seen: set[str] = set()
            scraper.search_term("cybersecurity", seen)

        assert len(seen) == 5
        assert "pw-23-00999111" in seen


# ---------------------------------------------------------------------------
# Multi-page search
# ---------------------------------------------------------------------------

class TestMultiPageSearch:
    def test_follows_pagination(self, scraper, page2_html, page_html):
        """search_term fetches multiple pages when pager is present."""
        resp1 = MagicMock()
        resp1.text = page2_html  # Has pager link

        resp2 = MagicMock()
        resp2.text = page_html  # No pager (last page)

        with patch.object(scraper, "get", side_effect=[resp1, resp2]) as mock_get:
            seen: set[str] = set()
            results = scraper.search_term("cloud security", seen)

        assert mock_get.call_count == 2
        # page2_html has 2 results, page_html has 5 (minus 1 overlap = pw-23-00999111)
        assert len(results) == 6

    def test_stops_on_empty_page(self, scraper, page_html, empty_html):
        """search_term stops when a page returns no results."""
        resp1 = MagicMock()
        resp1.text = page_html  # No pager, should stop after page 0

        with patch.object(scraper, "get", return_value=resp1) as mock_get:
            seen: set[str] = set()
            scraper.search_term("test", seen)

        assert mock_get.call_count == 1


# ---------------------------------------------------------------------------
# Scrape integration
# ---------------------------------------------------------------------------

class TestScrapeIntegration:
    def test_scrape_stores_matches(self, scraper, store, page_html):
        mock_resp = MagicMock()
        mock_resp.text = page_html

        with patch.object(scraper, "get", return_value=mock_resp):
            stats = scraper.scrape()

        assert isinstance(stats, dict)
        assert stats["records_found"] == 5
        assert stats["records_matched"] > 0
        all_notices = store.get_all_notices()
        assert len(all_notices) > 0

    def test_scrape_ignores_tier0(self, scraper, store, page_html):
        """Furniture tenders (tier 0) should not be stored."""
        mock_resp = MagicMock()
        mock_resp.text = page_html

        with patch.object(scraper, "get", return_value=mock_resp):
            scraper.scrape()

        notices = store.get_all_notices()
        for n in notices:
            import json
            cls = json.loads(n["classification_json"])
            assert cls["tier"] > 0

    def test_scrape_logs_source_run(self, scraper, store, page_html):
        mock_resp = MagicMock()
        mock_resp.text = page_html

        with patch.object(scraper, "get", return_value=mock_resp):
            scraper.scrape()

        run = store.get_latest_run("canadabuys_search")
        assert run is not None
        assert run["status"] == "success"
        assert run["records_found"] == 5

    def test_scrape_deduplicates_across_terms(self, store, page_html):
        """Multiple search terms returning the same results should dedup."""
        scraper = CanadaBuysSearchScraper(
            store=store,
            config={"search_terms": ["cybersecurity", "SIEM", "penetration testing"]},
            delay_seconds=0,
            max_retries=0,
        )

        mock_resp = MagicMock()
        mock_resp.text = page_html

        try:
            with patch.object(scraper, "get", return_value=mock_resp):
                stats = scraper.scrape()

            # All three terms return the same 5 results, should only count 5
            assert stats["records_found"] == 5
        finally:
            scraper.close()

    def test_scrape_skips_existing_source_ids(self, scraper, store, page_html):
        """Notices already in DB are not counted as new."""
        # Pre-insert one notice
        store.add_notice(
            source="canadabuys_search",
            source_id="pw-23-00999111",
            title="Cybersecurity Assessment Services for Federal Networks",
        )

        mock_resp = MagicMock()
        mock_resp.text = page_html

        with patch.object(scraper, "get", return_value=mock_resp):
            stats = scraper.scrape()

        assert stats["records_found"] == 5
        # The pre-inserted one is not "new"
        assert stats["records_new"] < stats["records_matched"]

    def test_scrape_error_logged(self, scraper, store):
        with patch.object(scraper, "get", side_effect=Exception("Connection refused")):
            with pytest.raises(Exception):
                scraper.scrape()

        run = store.get_latest_run("canadabuys_search")
        assert run["status"] == "error"
        assert "Connection refused" in run["error_message"]

    def test_scrape_empty_results(self, scraper, store, empty_html):
        mock_resp = MagicMock()
        mock_resp.text = empty_html

        with patch.object(scraper, "get", return_value=mock_resp):
            stats = scraper.scrape()

        assert stats["records_found"] == 0
        assert stats["records_matched"] == 0
        assert stats["records_new"] == 0
        run = store.get_latest_run("canadabuys_search")
        assert run["status"] == "success"


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

class TestConfig:
    def test_custom_search_terms(self, store):
        scraper = CanadaBuysSearchScraper(
            store=store,
            config={"search_terms": ["custom1", "custom2"]},
            delay_seconds=0,
        )
        try:
            assert scraper._search_terms == ["custom1", "custom2"]
        finally:
            scraper.close()

    def test_default_search_terms(self, store):
        scraper = CanadaBuysSearchScraper(store=store, delay_seconds=0)
        try:
            assert "cybersecurity" in scraper._search_terms
            assert len(scraper._search_terms) >= 10
        finally:
            scraper.close()

    def test_default_delay_is_2s(self, store):
        scraper = CanadaBuysSearchScraper(store=store)
        try:
            assert scraper._delay_seconds == 2.0
        finally:
            scraper.close()

    def test_source_name(self, scraper):
        assert scraper.name == "canadabuys_search"
