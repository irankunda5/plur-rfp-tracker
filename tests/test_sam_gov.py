"""Tests for scrapers/sam_gov.py - SAM.gov API scraper."""

import json
import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, call

sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx
import pytest
from lib.storage import OpportunityStore
from scrapers.sam_gov import SAMGovScraper, NAICS_CODES, OPPORTUNITIES_URL, AWARDS_URL

NUM_NAICS = len(NAICS_CODES)


# ---------------------------------------------------------------------------
# Mock response data
# ---------------------------------------------------------------------------

MOCK_OPPORTUNITY_RESPONSE = {
    "totalRecords": 2,
    "opportunitiesData": [
        {
            "noticeId": "abc123",
            "title": "Cybersecurity Assessment Services",
            "solicitationNumber": "W91QUZ-26-R-0001",
            "postedDate": "2026-03-19",
            "type": "Solicitation",
            "naicsCode": "541512",
            "responseDeadLine": "2026-04-19",
            "description": "The Department of Defense requires cybersecurity assessment and penetration testing services.",
            "uiLink": "https://sam.gov/opp/abc123/view",
            "organizationId": "100000000",
        },
        {
            "noticeId": "xyz789",
            "title": "Office Furniture Procurement",
            "solicitationNumber": "W91QUZ-26-R-0099",
            "postedDate": "2026-03-19",
            "type": "Solicitation",
            "naicsCode": "541512",
            "responseDeadLine": "2026-04-30",
            "description": "Purchase of standard office furniture and desks for the headquarters.",
            "uiLink": "https://sam.gov/opp/xyz789/view",
            "organizationId": "100000001",
        },
    ],
}

MOCK_OPPORTUNITY_EMPTY = {
    "totalRecords": 0,
    "opportunitiesData": [],
}

MOCK_AWARDS_RESPONSE = {
    "totalRecords": 1,
    "data": [
        {
            "awardID": "def456",
            "title": "Endpoint Protection Platform",
            "naicsCode": "541512",
            "recipientName": "CrowdStrike Inc",
            "dollarsObligated": 500000,
            "approvedDate": "2026-03-18",
            "contractingDepartmentName": "Department of Defense",
        },
    ],
}

MOCK_AWARDS_EMPTY = {
    "totalRecords": 0,
    "data": [],
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def store(tmp_path):
    s = OpportunityStore(db_path=tmp_path / "test.db")
    yield s
    s.close()


@pytest.fixture
def scraper(store):
    s = SAMGovScraper(
        store=store,
        api_key="test-key-abc123",
        delay_seconds=0,
        max_retries=0,
    )
    yield s
    s.close()


def _mock_json_response(data, status_code=200):
    """Create a mock httpx.Response that returns JSON data."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = data
    resp.text = json.dumps(data)
    resp.headers = {}
    return resp


# ---------------------------------------------------------------------------
# 1. Test missing API key exits with clear error
# ---------------------------------------------------------------------------

class TestMissingAPIKey:
    def test_missing_api_key_raises(self, store):
        """Scraper should raise RuntimeError when no API key."""
        scraper = SAMGovScraper(
            store=store, api_key=None, delay_seconds=0, max_retries=0,
        )
        with pytest.raises(RuntimeError) as exc_info:
            scraper.scrape()
        assert "SAM_GOV_API_KEY" in str(exc_info.value)

    def test_missing_api_key_message_is_helpful(self, store):
        """Error message should mention how to get a key."""
        scraper = SAMGovScraper(
            store=store, api_key=None, delay_seconds=0, max_retries=0,
        )
        with pytest.raises(RuntimeError) as exc_info:
            scraper.scrape()
        assert "api.sam.gov" in str(exc_info.value)


# ---------------------------------------------------------------------------
# 2. Test opportunities API URL construction
# ---------------------------------------------------------------------------

class TestOpportunitiesURLConstruction:
    @patch.object(SAMGovScraper, "get")
    def test_opportunities_url_params(self, mock_get, scraper):
        """Verify correct params are sent for opportunities API."""
        mock_get.return_value = _mock_json_response(MOCK_OPPORTUNITY_EMPTY)
        scraper.fetch_opportunities("test-key")

        # Should have been called once per NAICS code
        assert mock_get.call_count == NUM_NAICS

        # Check first call params
        first_call = mock_get.call_args_list[0]
        assert first_call[0][0] == OPPORTUNITIES_URL
        params = first_call[1]["params"]
        assert params["api_key"] == "test-key"
        assert params["ncode"] == NAICS_CODES[0]
        assert params["ptype"] == "o,p,k"
        assert params["limit"] == "1000"
        assert "postedFrom" in params
        assert "postedTo" in params

    @patch.object(SAMGovScraper, "get")
    def test_date_format_mm_dd_yyyy(self, mock_get, scraper):
        """Date params should be in MM/dd/yyyy format."""
        mock_get.return_value = _mock_json_response(MOCK_OPPORTUNITY_EMPTY)
        scraper.fetch_opportunities("test-key")

        params = mock_get.call_args_list[0][1]["params"]
        # Check date format (MM/dd/yyyy)
        posted_from = params["postedFrom"]
        posted_to = params["postedTo"]
        # Should contain slashes and be 10 chars (e.g. 03/19/2026)
        assert len(posted_from) == 10
        assert posted_from[2] == "/"
        assert posted_from[5] == "/"
        assert len(posted_to) == 10


# ---------------------------------------------------------------------------
# 3. Test 4 NAICS calls made for opportunities
# ---------------------------------------------------------------------------

class TestNAICSCalls:
    @patch.object(SAMGovScraper, "get")
    def test_naics_calls_per_code(self, mock_get, scraper):
        """Opportunities API should make one call per NAICS code."""
        mock_get.return_value = _mock_json_response(MOCK_OPPORTUNITY_EMPTY)
        scraper.fetch_opportunities("test-key")

        assert mock_get.call_count == NUM_NAICS
        naics_called = []
        for c in mock_get.call_args_list:
            naics_called.append(c[1]["params"]["ncode"])
        assert naics_called == NAICS_CODES


# ---------------------------------------------------------------------------
# 4. Test awards API with pipe-delimited NAICS
# ---------------------------------------------------------------------------

class TestAwardsURL:
    @patch.object(SAMGovScraper, "get")
    def test_awards_naics_tilde_delimited(self, mock_get, scraper):
        """Awards API should use tilde-delimited NAICS codes."""
        mock_get.return_value = _mock_json_response(MOCK_AWARDS_EMPTY)
        scraper.fetch_awards("test-key")

        assert mock_get.call_count == 1
        first_call = mock_get.call_args_list[0]
        assert first_call[0][0] == AWARDS_URL
        params = first_call[1]["params"]
        assert params["naicsCode"] == "~".join(NAICS_CODES)

    @patch.object(SAMGovScraper, "get")
    def test_awards_modification_number_zero(self, mock_get, scraper):
        """Awards API should filter modificationNumber=0."""
        mock_get.return_value = _mock_json_response(MOCK_AWARDS_EMPTY)
        scraper.fetch_awards("test-key")

        params = mock_get.call_args_list[0][1]["params"]
        assert params["modificationNumber"] == "0"

    @patch.object(SAMGovScraper, "get")
    def test_awards_last_modified_date_format(self, mock_get, scraper):
        """Awards API lastModifiedDate should be [MM/DD/YYYY,] format."""
        mock_get.return_value = _mock_json_response(MOCK_AWARDS_EMPTY)
        scraper.fetch_awards("test-key")

        params = mock_get.call_args_list[0][1]["params"]
        lmd = params["lastModifiedDate"]
        assert lmd.startswith("[")
        assert lmd.endswith(",]")


# ---------------------------------------------------------------------------
# 5. Test opportunity parsing
# ---------------------------------------------------------------------------

class TestOpportunityParsing:
    @patch.object(SAMGovScraper, "get")
    def test_parses_opportunity_fields(self, mock_get, scraper, store):
        """Parsed opportunity should map fields correctly to storage."""
        # Return cyber opportunity for all NAICS calls, empty for awards
        mock_get.return_value = _mock_json_response(MOCK_OPPORTUNITY_EMPTY)

        # Process a single cyber opportunity directly
        opp = MOCK_OPPORTUNITY_RESPONSE["opportunitiesData"][0]
        result = scraper._process_opportunity(opp)

        assert result is not None
        notice = store.get_notice_by_source("sam_gov", "abc123")
        assert notice is not None
        assert notice["title"] == "Cybersecurity Assessment Services"
        assert notice["url"] == "https://sam.gov/opp/abc123/view"
        assert notice["closing_date"] == "2026-04-19"
        assert notice["buyer"] == "100000000"
        assert notice["notice_type"] == "Solicitation"

    @patch.object(SAMGovScraper, "get")
    def test_parses_award_fields(self, mock_get, scraper, store):
        """Parsed award should map fields correctly to storage."""
        mock_get.return_value = _mock_json_response(MOCK_AWARDS_EMPTY)

        award = MOCK_AWARDS_RESPONSE["data"][0]
        result = scraper._process_award(award)

        assert result is not None
        notice = store.get_notice_by_source("sam_gov", "def456")
        assert notice is not None
        assert notice["title"] == "Endpoint Protection Platform"
        assert notice["buyer"] == "Department of Defense"
        assert notice["notice_type"] == "Award"


# ---------------------------------------------------------------------------
# 6. Test classification and storage of matches
# ---------------------------------------------------------------------------

class TestClassificationStorage:
    @patch.object(SAMGovScraper, "get")
    def test_cyber_opportunity_stored(self, mock_get, scraper, store):
        """Cybersecurity opportunity should be classified and stored."""
        def side_effect(url, **kwargs):
            if "opportunities" in url:
                return _mock_json_response(MOCK_OPPORTUNITY_RESPONSE)
            else:
                return _mock_json_response(MOCK_AWARDS_EMPTY)

        mock_get.side_effect = side_effect
        stats = scraper.scrape()

        # The cyber opp should match; the furniture one should not
        assert stats["records_matched"] >= 1
        notices = store.get_all_notices()
        titles = [n["title"] for n in notices]
        assert "Cybersecurity Assessment Services" in titles

    @patch.object(SAMGovScraper, "get")
    def test_classification_has_tier(self, mock_get, scraper, store):
        """Stored classification should include tier info."""
        opp = MOCK_OPPORTUNITY_RESPONSE["opportunitiesData"][0]
        scraper._process_opportunity(opp)

        notice = store.get_notice_by_source("sam_gov", "abc123")
        cls = json.loads(notice["classification_json"])
        assert cls["tier"] >= 1
        assert "cybersecurity" in [kw.lower() for kw in cls["matched_keywords"]] or len(cls["matched_keywords"]) > 0

    @patch.object(SAMGovScraper, "get")
    def test_award_with_vendor_detected(self, mock_get, scraper, store):
        """Award mentioning CrowdStrike should have vendor_flags."""
        # The award title is "Endpoint Protection Platform" which matches
        # broader IT keywords. The recipientName won't be in title/desc
        # so let's create an award with vendor name in description.
        award = {
            "awardID": "vendor789",
            "title": "CrowdStrike Endpoint Protection Platform",
            "naicsCode": "541512",
            "recipientName": "CrowdStrike Inc",
            "dollarsObligated": 500000,
            "approvedDate": "2026-03-18",
            "contractingDepartmentName": "Department of Defense",
            "description": "CrowdStrike Falcon endpoint detection and response solution.",
        }
        result = scraper._process_award(award)
        assert result is not None
        notice = store.get_notice_by_source("sam_gov", "vendor789")
        cls = json.loads(notice["classification_json"])
        assert "CrowdStrike" in cls["vendor_flags"]


# ---------------------------------------------------------------------------
# 7. Test non-matches not stored
# ---------------------------------------------------------------------------

class TestNonMatchesNotStored:
    def test_furniture_not_stored(self, scraper, store):
        """Non-cyber opportunity (furniture) should not be stored."""
        opp = MOCK_OPPORTUNITY_RESPONSE["opportunitiesData"][1]  # Furniture
        result = scraper._process_opportunity(opp)

        assert result is None
        notices = store.get_all_notices()
        titles = [n["title"] for n in notices]
        assert "Office Furniture Procurement" not in titles

    @patch.object(SAMGovScraper, "get")
    def test_scrape_only_stores_matches(self, mock_get, scraper, store):
        """Full scrape should only store matching opportunities."""
        def side_effect(url, **kwargs):
            if "opportunities" in url:
                return _mock_json_response(MOCK_OPPORTUNITY_RESPONSE)
            else:
                return _mock_json_response(MOCK_AWARDS_EMPTY)

        mock_get.side_effect = side_effect
        scraper.scrape()

        notices = store.get_all_notices()
        for n in notices:
            cls = json.loads(n["classification_json"])
            assert cls["tier"] > 0, f"Non-match stored: {n['title']}"


# ---------------------------------------------------------------------------
# 8. Test API key NOT in any log output
# ---------------------------------------------------------------------------

class TestAPIKeyNotLogged:
    @patch.object(SAMGovScraper, "get")
    def test_api_key_not_in_logs(self, mock_get, scraper, store, caplog):
        """API key must never appear in log output."""
        api_key = "test-key-abc123"

        def side_effect(url, **kwargs):
            if "opportunities" in url:
                return _mock_json_response(MOCK_OPPORTUNITY_RESPONSE)
            else:
                return _mock_json_response(MOCK_AWARDS_RESPONSE)

        mock_get.side_effect = side_effect

        with caplog.at_level(logging.DEBUG):
            scraper.scrape()

        for record in caplog.records:
            assert api_key not in record.getMessage(), (
                f"API key found in log message: {record.getMessage()}"
            )

    @patch.object(SAMGovScraper, "get")
    def test_api_key_not_in_error_logs(self, mock_get, scraper, store, caplog):
        """API key must not appear in error log messages either."""
        api_key = "test-key-abc123"

        def side_effect(url, **kwargs):
            raise httpx.HTTPStatusError(
                f"403 Forbidden for url {OPPORTUNITIES_URL}?api_key={api_key}",
                request=MagicMock(),
                response=MagicMock(status_code=403),
            )

        mock_get.side_effect = side_effect

        with caplog.at_level(logging.DEBUG):
            with pytest.raises(RuntimeError):
                scraper.scrape()

        for record in caplog.records:
            assert api_key not in record.getMessage(), (
                f"API key found in error log: {record.getMessage()}"
            )

    @patch.object(SAMGovScraper, "get")
    def test_api_key_not_in_exception_message(self, mock_get, scraper, store):
        """API key must not appear in the re-raised exception message."""
        api_key = "test-key-abc123"

        def side_effect(url, **kwargs):
            raise httpx.HTTPStatusError(
                f"403 Forbidden for url {OPPORTUNITIES_URL}?api_key={api_key}",
                request=MagicMock(),
                response=MagicMock(status_code=403),
            )

        mock_get.side_effect = side_effect

        with pytest.raises(RuntimeError) as exc_info:
            scraper.scrape()

        assert api_key not in str(exc_info.value), (
            f"API key found in exception: {exc_info.value}"
        )


# ---------------------------------------------------------------------------
# 9. Test 403 error handling
# ---------------------------------------------------------------------------

class TestErrorHandling:
    @patch.object(SAMGovScraper, "get")
    def test_403_invalid_key(self, mock_get, scraper, store):
        """403 response should raise RuntimeError and log run as error."""
        mock_get.side_effect = httpx.HTTPStatusError(
            "403 Forbidden",
            request=MagicMock(),
            response=MagicMock(status_code=403),
        )
        with pytest.raises(RuntimeError):
            scraper.scrape()

        run = store.get_latest_run("sam_gov")
        assert run is not None
        assert run["status"] == "error"

    @patch.object(SAMGovScraper, "get")
    def test_error_run_logged(self, mock_get, scraper, store):
        """Errors during scrape should be recorded in source_runs."""
        mock_get.side_effect = Exception("Connection refused")
        with pytest.raises(Exception, match="Connection refused"):
            scraper.scrape()

        run = store.get_latest_run("sam_gov")
        assert run["status"] == "error"
        assert "Connection refused" in run["error_message"]


# ---------------------------------------------------------------------------
# 10. Test 0 results handling
# ---------------------------------------------------------------------------

class TestZeroResults:
    @patch.object(SAMGovScraper, "get")
    def test_zero_opportunities(self, mock_get, scraper, store):
        """Scraper should handle 0 opportunities gracefully."""
        def side_effect(url, **kwargs):
            if "opportunities" in url:
                return _mock_json_response(MOCK_OPPORTUNITY_EMPTY)
            else:
                return _mock_json_response(MOCK_AWARDS_EMPTY)

        mock_get.side_effect = side_effect
        stats = scraper.scrape()

        assert stats["records_found"] == 0
        assert stats["records_matched"] == 0
        assert stats["records_new"] == 0
        run = store.get_latest_run("sam_gov")
        assert run["status"] == "success"
        assert run["records_found"] == 0

    @patch.object(SAMGovScraper, "get")
    def test_none_opportunities_data(self, mock_get, scraper, store):
        """Scraper should handle None opportunitiesData gracefully."""
        response_with_none = {"totalRecords": 0, "opportunitiesData": None}

        def side_effect(url, **kwargs):
            if "opportunities" in url:
                return _mock_json_response(response_with_none)
            else:
                return _mock_json_response(MOCK_AWARDS_EMPTY)

        mock_get.side_effect = side_effect
        stats = scraper.scrape()

        assert stats["records_found"] == 0

    @patch.object(SAMGovScraper, "get")
    def test_none_awards_data(self, mock_get, scraper, store):
        """Scraper should handle None awards data gracefully."""
        response_with_none = {"totalRecords": 0, "data": None}

        def side_effect(url, **kwargs):
            if "opportunities" in url:
                return _mock_json_response(MOCK_OPPORTUNITY_EMPTY)
            else:
                return _mock_json_response(response_with_none)

        mock_get.side_effect = side_effect
        stats = scraper.scrape()

        assert stats["records_found"] == 0


# ---------------------------------------------------------------------------
# 11. Test source_run logging
# ---------------------------------------------------------------------------

class TestSourceRunLogging:
    @patch.object(SAMGovScraper, "get")
    def test_successful_run_logged(self, mock_get, scraper, store):
        """Successful scrape should log a source run with correct counts."""
        def side_effect(url, **kwargs):
            if "opportunities" in url:
                return _mock_json_response(MOCK_OPPORTUNITY_RESPONSE)
            else:
                return _mock_json_response(MOCK_AWARDS_RESPONSE)

        mock_get.side_effect = side_effect
        scraper.scrape()

        run = store.get_latest_run("sam_gov")
        assert run is not None
        assert run["source"] == "sam_gov"
        assert run["status"] == "success"
        # 2 opps per NAICS call * NUM_NAICS calls + 1 award
        assert run["records_found"] >= 1
        assert run["records_matched"] >= 1
        assert run["end_time"] is not None

    @patch.object(SAMGovScraper, "get")
    def test_run_start_and_end_recorded(self, mock_get, scraper, store):
        """Both start_time and end_time should be recorded."""
        def side_effect(url, **kwargs):
            if "opportunities" in url:
                return _mock_json_response(MOCK_OPPORTUNITY_EMPTY)
            else:
                return _mock_json_response(MOCK_AWARDS_EMPTY)

        mock_get.side_effect = side_effect
        scraper.scrape()

        run = store.get_latest_run("sam_gov")
        assert run["start_time"] is not None
        assert run["end_time"] is not None

    @patch.object(SAMGovScraper, "get")
    def test_error_run_has_error_message(self, mock_get, scraper, store):
        """Failed scrape should log error message in source run."""
        mock_get.side_effect = RuntimeError("API down")
        with pytest.raises(RuntimeError, match="API down"):
            scraper.scrape()

        run = store.get_latest_run("sam_gov")
        assert run["status"] == "error"
        assert "API down" in run["error_message"]


# ---------------------------------------------------------------------------
# 12. Test scraper name attribute
# ---------------------------------------------------------------------------

class TestScraperName:
    def test_scraper_name(self, scraper):
        """Scraper name should be 'sam_gov'."""
        assert scraper.name == "sam_gov"

    def test_scraper_name_used_in_storage(self, scraper, store):
        """Notices should be stored with source='sam_gov'."""
        opp = MOCK_OPPORTUNITY_RESPONSE["opportunitiesData"][0]
        scraper._process_opportunity(opp)

        notice = store.get_notice_by_source("sam_gov", "abc123")
        assert notice is not None
        assert notice["source"] == "sam_gov"


# ---------------------------------------------------------------------------
# Additional edge-case tests
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_missing_title_skipped(self, scraper, store):
        """Opportunity with empty title should be skipped."""
        opp = {
            "noticeId": "no-title-1",
            "title": "",
            "description": "Cybersecurity services",
        }
        result = scraper._process_opportunity(opp)
        assert result is None

    def test_missing_source_id_skipped(self, scraper, store):
        """Opportunity with no noticeId or solicitationNumber should be skipped."""
        opp = {
            "title": "Cybersecurity Assessment",
            "description": "Important cybersecurity work",
        }
        result = scraper._process_opportunity(opp)
        assert result is None

    @patch.object(SAMGovScraper, "get")
    def test_dedup_on_second_scrape(self, mock_get, scraper, store):
        """Second scrape of same data should not create duplicate notices."""
        def side_effect(url, **kwargs):
            if "opportunities" in url:
                return _mock_json_response(MOCK_OPPORTUNITY_RESPONSE)
            else:
                return _mock_json_response(MOCK_AWARDS_RESPONSE)

        mock_get.side_effect = side_effect
        stats1 = scraper.scrape()
        stats2 = scraper.scrape()

        # Second run should find 0 new
        assert stats2["records_new"] == 0
        notices = store.get_all_notices()
        # Count should not double
        unique_ids = {n["source_id"] for n in notices}
        assert len(notices) == len(unique_ids)

    @patch.object(SAMGovScraper, "get")
    def test_lookback_days_configurable(self, mock_get, store):
        """lookback_days parameter should be respected."""
        scraper = SAMGovScraper(
            store=store,
            api_key="test-key",
            lookback_days=14,
            delay_seconds=0,
            max_retries=0,
        )
        mock_get.return_value = _mock_json_response(MOCK_OPPORTUNITY_EMPTY)
        scraper.fetch_opportunities("test-key")

        # The date range should span 14 days
        params = mock_get.call_args_list[0][1]["params"]
        from datetime import datetime, timedelta, timezone
        today = datetime.now(timezone.utc).date()
        expected_from = (today - timedelta(days=14)).strftime("%m/%d/%Y")
        assert params["postedFrom"] == expected_from
        scraper.close()
