"""SaskTenders HTML scraper - fetches open tenders from Saskatchewan procurement."""

import logging
import sys

from bs4 import BeautifulSoup

from scrapers.base import BaseScraper
from lib.keywords import classify_opportunity
from lib.storage import OpportunityStore

logger = logging.getLogger(__name__)

SEARCH_URL = "https://sasktenders.ca/content/public/Search.aspx?statusId=-2"
BASE_URL = "https://sasktenders.ca"


class SaskTendersScraper(BaseScraper):
    name = "sasktenders"
    url = SEARCH_URL

    def __init__(self, store: OpportunityStore, config: dict | None = None, **kwargs):
        super().__init__(config=config, **kwargs)
        self._store = store

    def fetch_html(self) -> str:
        """Fetch the search results page."""
        resp = self.get(self.url)
        return resp.text

    def parse_html(self, html: str) -> list[dict]:
        """Parse the HTML table into a list of tender dicts."""
        soup = BeautifulSoup(html, "html.parser")
        tenders = []

        table = soup.find("table")
        if not table:
            logger.warning("[%s] No table found in HTML", self.name)
            return []

        rows = table.find_all("tr")
        for row in rows[1:]:  # skip header
            cells = row.find_all("td")
            if len(cells) < 4:
                continue

            link_tag = cells[0].find("a")
            tender_id = cells[0].get_text(strip=True)
            href = link_tag["href"] if link_tag and link_tag.get("href") else ""
            title = cells[1].get_text(strip=True)
            org = cells[2].get_text(strip=True)
            closing = cells[3].get_text(strip=True)

            if href and not href.startswith("http"):
                href = BASE_URL + href

            tenders.append({
                "tender_id": tender_id,
                "title": title,
                "organization": org,
                "closing_date": closing,
                "url": href,
            })

        return tenders

    def scrape(self) -> dict:
        """Fetch HTML, classify tenders, store matches.

        Returns:
            Stats dict: {"records_found": int, "records_matched": int, "records_new": int}
        """
        run_id = self._store.start_run(self.name)
        stats = {"records_found": 0, "records_matched": 0, "records_new": 0}
        try:
            html = self.fetch_html()
            tenders = self.parse_html(html)
            stats["records_found"] = len(tenders)

            for t in tenders:
                title = t["title"]
                if not title or not t["tender_id"]:
                    continue

                result = classify_opportunity(title, title_only=True)

                if result["tier"] == 0:
                    continue

                stats["records_matched"] += 1

                is_new, notice_id = self._store.add_notice(
                    source=self.name,
                    source_id=t["tender_id"],
                    title=title,
                    description="",
                    buyer=t["organization"],
                    closing_date=t["closing_date"],
                    url=t["url"],
                    notice_type="tender",
                    product_type=result.get("product_type", ""),
                    vendor_flags=result.get("vendor_flags", []),
                    classification=result,
                    raw_json=t,
                )
                if is_new:
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
                "[%s] Found %d tenders, %d matched, %d new",
                self.name, stats["records_found"],
                stats["records_matched"], stats["records_new"],
            )
            return stats

        except Exception as exc:
            logger.error("[%s] Scrape failed: %s", self.name, exc)
            self._store.end_run(run_id, status="error", error_message=str(exc))
            raise


def main():
    """CLI entry point for standalone execution."""
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    parser = argparse.ArgumentParser(description="SaskTenders HTML scraper")
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    args = parser.parse_args()

    from config import DATA_DIR
    store = OpportunityStore(db_path=DATA_DIR / "rfp.db")
    try:
        scraper = SaskTendersScraper(store=store, delay_seconds=0)
        stats = scraper.scrape()
        logger.info("Scrape complete: %s", stats)
    finally:
        store.close()

    sys.exit(0)


if __name__ == "__main__":
    main()
