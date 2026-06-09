"""CanadaBuys website search scraper - searches open tenders by keyword.

Complements the CSV scraper (which catches daily deltas/amendments) by
searching the full CanadaBuys tender listing via the website search interface.
"""

import logging
import re
import sys
from urllib.parse import urlencode

from bs4 import BeautifulSoup

from scrapers.base import BaseScraper
from lib.keywords import classify_opportunity
from lib.storage import OpportunityStore

logger = logging.getLogger(__name__)

BASE_URL = "https://canadabuys.canada.ca/en/tender-opportunities"

# Search terms targeting IT/cyber procurement relevant to PLUR's ICP.
DEFAULT_SEARCH_TERMS = [
    "cybersecurity",
    "cyber security",
    "information technology",
    "IT security",
    "network security",
    "cloud services",
    "managed services",
    "identity management",
    "access management",
    "firewall",
    "data protection",
    "vulnerability",
    "threat detection",
    "SOC",
    "penetration testing",
    "security assessment",
    "GRC",
    "compliance",
    "disaster recovery",
    "IT infrastructure",
]

# Maximum pages to follow per search term (safety valve).
MAX_PAGES_PER_TERM = 10

# Items per page (max supported by the site).
ITEMS_PER_PAGE = 200


class CanadaBuysSearchScraper(BaseScraper):
    """Scraper for CanadaBuys website search (HTML parsing)."""

    name = "canadabuys_search"
    url = BASE_URL

    def __init__(self, store=None, config: dict | None = None, **kwargs):
        self._store = store
        # Default to 2s between requests (polite crawling)
        kwargs.setdefault("delay_seconds", 2.0)
        super().__init__(config=config, **kwargs)
        self._search_terms = (config or {}).get("search_terms", DEFAULT_SEARCH_TERMS)

    # ------------------------------------------------------------------
    # URL building
    # ------------------------------------------------------------------

    @staticmethod
    def build_search_url(words: str, page: int = 0, statuses: list[str] | None = None) -> str:
        """Build a CanadaBuys search URL.

        Args:
            words: Search keywords.
            page: Zero-based page number.
            statuses: Status codes to filter by. Defaults to ["87"] (open).
                Known codes: 87=Open, 1920=Awarded, 1921=Cancelled, 1922=Expired.

        Returns:
            Full URL string.
        """
        if statuses is None:
            statuses = ["87"]
        params = {
            "words": words,
            "items_per_page": str(ITEMS_PER_PAGE),
        }
        for code in statuses:
            params[f"status[{code}]"] = code
        url = f"{BASE_URL}?{urlencode(params)}"
        if page > 0:
            # CanadaBuys pagination format: page=,N,0,0
            url += f"&page=%2C{page}%2C0%2C0"
        return url

    # ------------------------------------------------------------------
    # HTML parsing
    # ------------------------------------------------------------------

    @staticmethod
    def parse_search_results(html_or_soup) -> list[dict]:
        """Parse tender listings from a CanadaBuys search results page.

        Args:
            html_or_soup: Raw HTML string or pre-parsed BeautifulSoup object.

        Returns a list of dicts with keys:
            source_id, title, category, closing_date, buyer, url
        """
        if isinstance(html_or_soup, BeautifulSoup):
            soup = html_or_soup
        else:
            soup = BeautifulSoup(html_or_soup, "html.parser")
        view = soup.find(class_="view-search-opportunities")
        if not view:
            return []

        table = view.find("table")
        if not table:
            return []

        tbody = table.find("tbody")
        if not tbody:
            return []

        results = []
        for tr in tbody.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) < 5:
                continue

            # Column 0: Title with link
            title_td = tds[0]
            link = title_td.find("a")
            if not link:
                continue

            href = link.get("href", "")
            title = link.get_text(strip=True)

            # Extract source_id from href: /en/tender-opportunities/tender-notice/<id>
            source_id = ""
            if "/tender-notice/" in href:
                source_id = href.split("/tender-notice/")[-1]

            if not source_id or not title:
                continue

            # Column 1: Category
            category = tds[1].get_text(strip=True)

            # Column 3: Closing date (normalize 2026/04/10 -> 2026-04-10)
            closing_date_raw = tds[3].get_text(strip=True)
            closing_date = closing_date_raw.replace("/", "-") if closing_date_raw else ""

            # Column 4: Organization (buyer)
            buyer = tds[4].get_text(strip=True)

            # Build full URL
            full_url = f"https://canadabuys.canada.ca{href}" if href.startswith("/") else href

            results.append({
                "source_id": source_id,
                "title": title,
                "category": category,
                "closing_date": closing_date,
                "buyer": buyer,
                "url": full_url,
            })

        return results

    @staticmethod
    def has_next_page(html_or_soup) -> bool:
        """Check whether the search results page has a next-page link."""
        if isinstance(html_or_soup, BeautifulSoup):
            soup = html_or_soup
        else:
            soup = BeautifulSoup(html_or_soup, "html.parser")
        pager = soup.find(class_="pager")
        if not pager:
            return False
        return bool(pager.find("a"))

    @staticmethod
    def get_total_count(html: str) -> int:
        """Extract the total result count from the search page."""
        soup = BeautifulSoup(html, "html.parser")
        el = soup.find(class_="search-total-count")
        if not el:
            return 0
        text = el.get_text(strip=True).replace(",", "")
        try:
            return int(text)
        except ValueError:
            return 0

    # ------------------------------------------------------------------
    # Search execution
    # ------------------------------------------------------------------

    def search_term(self, term: str, seen_ids: set[str], statuses: list[str] | None = None) -> list[dict]:
        """Search for a single term across all pages. Returns new results.

        Args:
            term: Search keyword string.
            seen_ids: Set of source_ids already collected (for cross-term dedup).
            statuses: Status codes to filter by. Defaults to ["87"] (open).

        Returns:
            List of result dicts not already in seen_ids.
        """
        new_results = []

        for page in range(MAX_PAGES_PER_TERM):
            url = self.build_search_url(term, page=page, statuses=statuses)
            logger.debug("[%s] Fetching: %s", self.name, url)

            resp = self.get(url)
            soup = BeautifulSoup(resp.text, "html.parser")
            results = self.parse_search_results(soup)

            if not results:
                logger.debug("[%s] No results on page %d for '%s'", self.name, page, term)
                break

            for r in results:
                if r["source_id"] not in seen_ids:
                    seen_ids.add(r["source_id"])
                    new_results.append(r)

            # Check for more pages (reuse parsed soup)
            if not self.has_next_page(soup):
                break

            logger.debug(
                "[%s] Page %d for '%s': %d results, has next page",
                self.name, page, term, len(results),
            )

        return new_results

    # ------------------------------------------------------------------
    # Main scrape
    # ------------------------------------------------------------------

    def scrape(self) -> dict:
        """Search all terms, classify results, store matches.

        Returns:
            Stats dict with keys: records_found, records_matched, records_new.
        """
        store = self._store
        run_id = store.start_run(self.name)
        stats = {"records_found": 0, "records_matched": 0, "records_new": 0}

        try:
            # Collect all unique results across search terms
            seen_ids: set[str] = set()
            all_results: list[dict] = []

            # Pass 1: Open tenders
            for term in self._search_terms:
                logger.info("[%s] Searching for: %s", self.name, term)
                term_results = self.search_term(term, seen_ids)
                all_results.extend(term_results)
                logger.info(
                    "[%s] '%s': %d new results (total unique: %d)",
                    self.name, term, len(term_results), len(seen_ids),
                )

            # Pass 2: Closed tenders (awarded + expired) for historical intel
            closed_statuses = ["1920", "1922"]  # Awarded, Expired
            for term in self._search_terms:
                logger.info("[%s] Searching closed for: %s", self.name, term)
                term_results = self.search_term(term, seen_ids, statuses=closed_statuses)
                all_results.extend(term_results)
                logger.info(
                    "[%s] '%s' (closed): %d new results (total unique: %d)",
                    self.name, term, len(term_results), len(seen_ids),
                )

            stats["records_found"] = len(all_results)

            # Classify and store
            for r in all_results:
                classification = classify_opportunity(r["title"], "")

                if classification["tier"] == 0:
                    continue

                stats["records_matched"] += 1

                is_new, _notice_id = store.add_notice(
                    source=self.name,
                    source_id=r["source_id"],
                    title=r["title"],
                    description="",
                    buyer=r["buyer"],
                    closing_date=r["closing_date"] or None,
                    url=r["url"],
                    notice_type=r.get("category", ""),
                    product_type=classification.get("product_type", ""),
                    vendor_flags=classification.get("vendor_flags", []),
                    classification=classification,
                    raw_json=r,
                )

                if is_new:
                    stats["records_new"] += 1

            store.end_run(
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
            store.end_run(run_id, status="error", error_message=str(exc))
            raise


# ------------------------------------------------------------------
# CLI entry point
# ------------------------------------------------------------------

def main():
    """CLI entry point for standalone execution."""
    import argparse
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    parser = argparse.ArgumentParser(description="CanadaBuys website search scraper")
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    parser.add_argument(
        "--terms", nargs="+", default=None,
        help="Override search terms (space-separated)",
    )
    args = parser.parse_args()

    from config import DATA_DIR
    db_path = DATA_DIR / "rfp.db"
    config = {}
    if args.terms is not None:
        config["search_terms"] = args.terms

    with OpportunityStore(db_path=db_path) as store:
        scraper = CanadaBuysSearchScraper(store=store, config=config)
        try:
            stats = scraper.scrape()
            logger.info("Scrape complete: %s", stats)
        finally:
            scraper.close()

    sys.exit(0)


if __name__ == "__main__":
    main()
