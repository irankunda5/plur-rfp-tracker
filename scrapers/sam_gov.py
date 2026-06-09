"""SAM.gov API scraper - fetches federal opportunities and contract awards."""

import logging
import re
from datetime import datetime, timedelta, timezone

from scrapers.base import BaseScraper
from lib.keywords import classify_opportunity, NAICS_CODES as NAICS_CODES_MAP
from lib.storage import OpportunityStore

logger = logging.getLogger(__name__)

OPPORTUNITIES_URL = "https://api.sam.gov/opportunities/v2/search"
AWARDS_URL = "https://api.sam.gov/contract-awards/v1/search"

# NAICS codes to query individually for opportunities (derived from lib.keywords)
NAICS_CODES = list(NAICS_CODES_MAP.keys())

# Opportunity ptype filter: o=solicitation, p=presolicitation, k=combined
PTYPE = "o,p,k"

# Regex to scrub API key from any string before logging
_API_KEY_PATTERN = re.compile(r"api_key=[^&\s]+")


def _scrub_api_key(text: str) -> str:
    """Remove api_key parameter value from a string."""
    return _API_KEY_PATTERN.sub("api_key=***REDACTED***", text)


class SAMGovScraper(BaseScraper):
    """Scraper for SAM.gov Opportunities and Contract Awards APIs."""

    name = "sam_gov"
    url = OPPORTUNITIES_URL

    def __init__(
        self,
        store: OpportunityStore,
        api_key: str | None = None,
        config: dict | None = None,
        lookback_days: int = 7,
        **kwargs,
    ):
        super().__init__(config=config, **kwargs)
        self._store = store
        self._api_key = api_key
        self._lookback_days = lookback_days

    def _ensure_api_key(self) -> str:
        """Return the API key or raise RuntimeError if not set."""
        if self._api_key:
            return self._api_key
        raise RuntimeError(
            "SAM_GOV_API_KEY environment variable is not set. "
            "Register for an API key at https://api.sam.gov and set the "
            "SAM_GOV_API_KEY env var before running this scraper."
        )

    def _date_range(self) -> tuple[str, str]:
        """Return (posted_from, posted_to) as MM/dd/yyyy strings."""
        today = datetime.now(timezone.utc).date()
        from_date = today - timedelta(days=self._lookback_days)
        return from_date.strftime("%m/%d/%Y"), today.strftime("%m/%d/%Y")

    def _awards_date_param(self) -> str:
        """Return lastModifiedDate param as [MM/DD/YYYY,] for awards API."""
        today = datetime.now(timezone.utc).date()
        from_date = today - timedelta(days=self._lookback_days)
        return f"[{from_date.strftime('%m/%d/%Y')},]"

    # ------------------------------------------------------------------
    # Opportunities API
    # ------------------------------------------------------------------

    def fetch_opportunities(self, api_key: str) -> list[dict]:
        """Fetch opportunities from SAM.gov, one call per NAICS code."""
        posted_from, posted_to = self._date_range()
        all_opps: list[dict] = []

        for naics in NAICS_CODES:
            params = {
                "api_key": api_key,
                "postedFrom": posted_from,
                "postedTo": posted_to,
                "ncode": naics,
                "ptype": PTYPE,
                "limit": "1000",
            }
            logger.info(
                "[%s] Fetching opportunities for NAICS %s",
                self.name, naics,
            )
            try:
                resp = self.get(OPPORTUNITIES_URL, params=params)
            except Exception as exc:
                safe_msg = _scrub_api_key(str(exc))
                logger.error(
                    "[%s] Error fetching NAICS %s: %s",
                    self.name, naics, safe_msg,
                )
                raise RuntimeError(safe_msg) from exc

            data = resp.json()
            opps = data.get("opportunitiesData", [])
            if opps is None:
                opps = []
            logger.info(
                "[%s] NAICS %s returned %d opportunities",
                self.name, naics, len(opps),
            )
            all_opps.extend(opps)

        return all_opps

    # ------------------------------------------------------------------
    # Contract Awards API
    # ------------------------------------------------------------------

    def fetch_awards(self, api_key: str) -> list[dict]:
        """Fetch contract awards from SAM.gov, all NAICS in one call."""
        naics_param = "~".join(NAICS_CODES)
        params = {
            "api_key": api_key,
            "naicsCode": naics_param,
            "lastModifiedDate": self._awards_date_param(),
            "modificationNumber": "0",
            "limit": "100",
        }
        logger.info("[%s] Fetching contract awards", self.name)
        try:
            resp = self.get(AWARDS_URL, params=params)
        except Exception as exc:
            safe_msg = _scrub_api_key(str(exc))
            logger.error(
                "[%s] Error fetching awards: %s",
                self.name, safe_msg,
            )
            raise RuntimeError(safe_msg) from exc

        data = resp.json()
        awards = data.get("data", [])
        if awards is None:
            awards = []
        logger.info(
            "[%s] Awards returned %d records",
            self.name, len(awards),
        )
        return awards

    # ------------------------------------------------------------------
    # Processing
    # ------------------------------------------------------------------

    def _process_record(
        self,
        record: dict,
        source_id_key: str,
        title_key: str = "title",
        description_key: str = "description",
        buyer_key: str = "",
        closing_date_key: str = "",
        url_key: str = "",
        notice_type_key: str = "",
        fallback_source_id_key: str = "",
        default_notice_type: str = "",
    ) -> dict | None:
        """Classify a record (opportunity or award) and store if matched.

        Returns {"is_new": bool, "classification": dict} or None if skipped.
        """
        title = record.get(title_key, "") or ""
        description = record.get(description_key, "") or ""
        source_id = record.get(source_id_key, "") or ""
        if not source_id and fallback_source_id_key:
            source_id = record.get(fallback_source_id_key, "") or ""
        buyer = (record.get(buyer_key, "") or "") if buyer_key else ""
        closing_date = (record.get(closing_date_key) or None) if closing_date_key else None
        url = (record.get(url_key, "") or "") if url_key else ""
        notice_type = (record.get(notice_type_key, "") or "") if notice_type_key else default_notice_type

        if not source_id or not title:
            return None

        result = classify_opportunity(title, description)

        if result["tier"] == 0:
            return None

        is_new, _ = self._store.add_notice(
            source=self.name,
            source_id=source_id,
            title=title,
            description=description,
            buyer=buyer,
            closing_date=closing_date,
            url=url,
            notice_type=notice_type,
            product_type=result.get("product_type", ""),
            vendor_flags=result.get("vendor_flags", []),
            classification=result,
            raw_json=record,
        )
        return {"is_new": is_new, "classification": result}

    def _process_opportunity(self, opp: dict) -> dict | None:
        """Classify an opportunity and store if matched."""
        return self._process_record(
            opp,
            source_id_key="noticeId",
            fallback_source_id_key="solicitationNumber",
            description_key="description",
            buyer_key="organizationId",
            closing_date_key="responseDeadLine",
            url_key="uiLink",
            notice_type_key="type",
        )

    def _process_award(self, award: dict) -> dict | None:
        """Classify a contract award and store if matched."""
        return self._process_record(
            award,
            source_id_key="awardID",
            description_key="description",
            buyer_key="contractingDepartmentName",
            closing_date_key="approvedDate",
            default_notice_type="Award",
        )

    # ------------------------------------------------------------------
    # Main scrape
    # ------------------------------------------------------------------

    def scrape(self) -> dict:
        """Fetch opportunities and awards, classify, and store matches.

        Returns:
            Stats dict: {"records_found": int, "records_matched": int, "records_new": int}
        """
        api_key = self._ensure_api_key()
        run_id = self._store.start_run(self.name)
        stats = {"records_found": 0, "records_matched": 0, "records_new": 0}

        try:
            # Fetch opportunities (one call per NAICS code)
            opportunities = self.fetch_opportunities(api_key)
            stats["records_found"] += len(opportunities)

            for opp in opportunities:
                processed = self._process_opportunity(opp)
                if processed:
                    stats["records_matched"] += 1
                    if processed["is_new"]:
                        stats["records_new"] += 1

            # Fetch awards (1 call)
            awards = self.fetch_awards(api_key)
            stats["records_found"] += len(awards)

            for award in awards:
                processed = self._process_award(award)
                if processed:
                    stats["records_matched"] += 1
                    if processed["is_new"]:
                        stats["records_new"] += 1

            self._store.end_run(
                run_id,
                records_found=stats["records_found"],
                records_new=stats["records_new"],
                records_matched=stats["records_matched"],
                status="success",
            )
            self._mark_success()
            logger.info(
                "[%s] Found %d records, %d matched, %d new",
                self.name, stats["records_found"],
                stats["records_matched"], stats["records_new"],
            )
            return stats

        except Exception as exc:
            safe_msg = _scrub_api_key(str(exc))
            logger.error("[%s] Scrape failed: %s", self.name, safe_msg)
            self._store.end_run(
                run_id, status="error", error_message=safe_msg,
            )
            raise


def main():
    """CLI entry point for standalone execution."""
    import argparse
    import os
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    parser = argparse.ArgumentParser(description="SAM.gov API scraper")
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    parser.parse_args()

    api_key = os.environ.get("SAM_GOV_API_KEY")

    from config import DATA_DIR
    store = OpportunityStore(db_path=DATA_DIR / "rfp.db")
    try:
        scraper = SAMGovScraper(store=store, api_key=api_key, delay_seconds=1.5)
        stats = scraper.scrape()
        logger.info("Scrape complete: %s", stats)
    finally:
        store.close()

    sys.exit(0)


if __name__ == "__main__":
    main()
