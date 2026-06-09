"""Bonfire API scraper - polls BonfireHub portals for open procurement opportunities."""

import logging
import sys
import time
from datetime import datetime, timezone

from scrapers.base import BaseScraper
from lib.keywords import classify_opportunity
from lib.storage import OpportunityStore
from config import SCRAPER_CONFIGS

logger = logging.getLogger(__name__)

API_PATH = "/PublicPortal/getOpenPublicOpportunitiesSectionData"
PORTAL_DELAY_SECONDS = 2.0


def _portal_url(portal: str) -> str:
    """Build the full API URL for a given Bonfire portal slug."""
    return f"https://{portal}.bonfirehub.ca{API_PATH}"


class BonfireScraper(BaseScraper):
    name = "bonfire"
    url = "https://bonfirehub.ca"

    def __init__(self, store: OpportunityStore, config: dict | None = None, **kwargs):
        super().__init__(config=config, **kwargs)
        self._store = store
        cfg = config or SCRAPER_CONFIGS.get("bonfire", {}).get("extra", {})
        self._portals: list[str] = cfg.get("portals", [])

    def _scrape_portal(self, portal: str) -> tuple[int, int, int]:
        """Scrape a single Bonfire portal.

        Returns:
            (records_found, records_new, records_matched) for this portal.
        """
        url = _portal_url(portal)
        resp = self.get(url)
        data = resp.json()

        if not data.get("success"):
            logger.warning(
                "[%s] Portal %s returned success=0: %s",
                self.name, portal, data.get("message", "unknown"),
            )
            return (0, 0, 0)

        projects = data.get("payload", {}).get("projects", {})
        if not projects:
            logger.info("[%s] Portal %s has no open projects", self.name, portal)
            return (0, 0, 0)

        records_found = len(projects)
        records_new = 0
        records_matched = 0

        for project_id, project in projects.items():
            title = project.get("ProjectName", "")
            if not title:
                continue

            result = classify_opportunity(title=title, title_only=True)

            if result["tier"] == 0:
                continue

            records_matched += 1

            source_id = f"{portal}-{project.get('ProjectID', project_id)}"
            closing_date = project.get("DateClose")
            opp_url = f"https://{portal}.bonfirehub.ca/portal/?tab=openOpportunities"

            raw_json = {
                "portal": portal,
                "title_only": True,
                **project,
            }

            is_new, notice_id = self._store.add_notice(
                source=self.name,
                source_id=source_id,
                title=title,
                description="",
                buyer=portal,
                closing_date=closing_date,
                url=opp_url,
                notice_type="",
                product_type=result.get("product_type", ""),
                vendor_flags=result.get("vendor_flags", []),
                classification=result,
                raw_json=raw_json,
            )
            if is_new:
                records_new += 1

        return (records_found, records_new, records_matched)

    def scrape(self) -> dict:
        """Poll all configured Bonfire portals and store matching opportunities.

        Returns:
            Stats dict: {"records_found": int, "records_matched": int, "records_new": int,
                         "portal_results": list[dict]}
        """
        portal_results = []
        all_failed = True
        total_found = 0
        total_new = 0
        total_matched = 0

        for i, portal in enumerate(self._portals):
            # Inter-portal delay (skip before the first portal)
            if i > 0:
                time.sleep(PORTAL_DELAY_SECONDS)

            run_id = self._store.start_run(f"bonfire-{portal}")
            try:
                found, new, matched = self._scrape_portal(portal)
                self._store.end_run(
                    run_id,
                    records_found=found,
                    records_new=new,
                    records_matched=matched,
                    status="success",
                )
                total_found += found
                total_new += new
                total_matched += matched
                all_failed = False
                portal_results.append({
                    "portal": portal,
                    "records_found": found,
                    "records_new": new,
                    "records_matched": matched,
                    "status": "success",
                })
                logger.info(
                    "[%s] Portal %s: %d found, %d matched, %d new",
                    self.name, portal, found, matched, new,
                )
            except Exception as exc:
                logger.error(
                    "[%s] Portal %s failed: %s", self.name, portal, exc,
                )
                self._store.end_run(
                    run_id, status="error", error_message=str(exc),
                )
                portal_results.append({
                    "portal": portal,
                    "records_found": 0,
                    "records_new": 0,
                    "records_matched": 0,
                    "status": "error",
                    "error": str(exc),
                })
                continue

        if all_failed and self._portals:
            logger.critical(
                "[%s] All %d portals failed", self.name, len(self._portals),
            )

        if not all_failed:
            self._mark_success()

        logger.info(
            "[%s] Scrape complete: %d portals, %d found, %d matched, %d new",
            self.name, len(self._portals), total_found, total_matched, total_new,
        )
        return {
            "records_found": total_found,
            "records_matched": total_matched,
            "records_new": total_new,
            "portal_results": portal_results,
        }


def main():
    """CLI entry point for standalone execution."""
    import argparse
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    parser = argparse.ArgumentParser(description="Bonfire API scraper")
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    args = parser.parse_args()

    from config import DATA_DIR, SCRAPER_CONFIGS
    bonfire_cfg = SCRAPER_CONFIGS.get("bonfire", {}).get("extra", {})
    store = OpportunityStore(db_path=DATA_DIR / "rfp.db")
    try:
        scraper = BonfireScraper(store=store, config=bonfire_cfg, delay_seconds=0)
        stats = scraper.scrape()
        logger.info("Scrape complete: %s", stats)
    finally:
        store.close()

    sys.exit(0)


if __name__ == "__main__":
    main()
