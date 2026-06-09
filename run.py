"""Phase 4 CLI runner - orchestrates RFP scraper execution."""

import argparse
import importlib
import logging
import os
import re
import sys
import time
from pathlib import Path

import config
from config import SCRAPER_CONFIGS, DATA_DIR, V2_SOURCES, V2_MODE, get_production_v2_sources, discover_v2_configs
from lib.storage import OpportunityStore, _now_iso

# Regex to scrub API keys from logged exception messages
_API_KEY_PATTERN = re.compile(r"api_key=[^&\s]+")

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Scraper registry: name -> (module_path, class_name)
# ---------------------------------------------------------------------------

SCRAPER_MAP = {
    "canadabuys": ("scrapers.canadabuys", "CanadaBuysScraper"),
    "canadabuys_search": ("scrapers.canadabuys_search", "CanadaBuysSearchScraper"),
    "bonfire": ("scrapers.bonfire", "BonfireScraper"),
    "sam_gov": ("scrapers.sam_gov", "SAMGovScraper"),
    "sasktenders": ("scrapers.sasktenders", "SaskTendersScraper"),
}


# ---------------------------------------------------------------------------
# Lazy import helper
# ---------------------------------------------------------------------------

def _load_scraper_class(name: str):
    """Dynamically import and return the scraper class for *name*."""
    module_path, class_name = SCRAPER_MAP[name]
    module = importlib.import_module(module_path)
    return getattr(module, class_name)


# ---------------------------------------------------------------------------
# Single-scraper execution
# ---------------------------------------------------------------------------

def run_scraper(name: str, store: OpportunityStore) -> dict:
    """Instantiate and run a single scraper, returning a normalised stats dict.

    All scrapers accept store in __init__ and scrape() takes no arguments,
    returning {"records_found": int, "records_matched": int, "records_new": int}.

    Returns:
        {"records_found": int, "records_matched": int, "records_new": int}

    Raises on failure so the caller can handle it.
    """
    # Check if this is a v2 config-driven source
    # Either explicitly in V2_SOURCES or discovered via V2_MODE
    all_v2_sources = discover_v2_configs()
    if name in V2_SOURCES or (V2_MODE and name in all_v2_sources):
        logger.info(f"Running {name} via v2 config-driven pipeline")
        from lib.extraction.runtime import run_v2_source
        return run_v2_source(name, store)

    # Legacy v1 scraper path
    cfg = SCRAPER_CONFIGS.get(name, {})
    extra = cfg.get("extra", {})

    cls = _load_scraper_class(name)
    scraper = cls(store=store, config=extra, delay_seconds=0)

    try:
        result = scraper.scrape()
        return {
            "records_found": result.get("records_found", 0),
            "records_matched": result.get("records_matched", 0),
            "records_new": result.get("records_new", 0),
        }
    finally:
        scraper.close()


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def _print_new_notices(store: OpportunityStore, run_start: str) -> None:
    """Print notices added during this run."""
    rows = store._conn.execute(
        """SELECT source, title, buyer, closing_date, url
           FROM notices WHERE fetch_timestamp >= ?
           ORDER BY closing_date ASC""",
        (run_start,),
    ).fetchall()
    if not rows:
        return
    logger.info("=" * 70)
    logger.info("NEW NOTICES THIS RUN: %d", len(rows))
    logger.info("=" * 70)
    for r in rows:
        closing = r["closing_date"] or "no date"
        logger.info(
            "  [%s] %s | %s | closes %s\n    %s",
            r["source"], r["title"], r["buyer"], closing, r["url"],
        )
    logger.info("=" * 70)


def run_all(names: list[str], store: OpportunityStore) -> int:
    """Run the given list of scrapers in sequence.

    Args:
        names: Scraper names to execute.
        store: Shared OpportunityStore.

    Returns:
        Exit code: 0 if all succeed, 1 if any fail.
    """
    run_start = _now_iso()
    total_scrapers = 0
    total_found = 0
    total_matched = 0
    total_new = 0
    total_errors = 0
    had_failure = False

    for name in names:
        total_scrapers += 1
        t0 = time.time()
        try:
            stats = run_scraper(name, store)
            elapsed = time.time() - t0
            found = stats["records_found"]
            matched = stats["records_matched"]
            new = stats["records_new"]
            total_found += found
            total_matched += matched
            total_new += new
            logger.info(
                "%s: %.1fs, %d found, %d matched",
                name, elapsed, found, matched,
            )
        except Exception as exc:
            elapsed = time.time() - t0
            safe_msg = _API_KEY_PATTERN.sub("api_key=***REDACTED***", str(exc))
            logger.error("%s: failed after %.1fs: %s", name, elapsed, safe_msg)
            total_errors += 1
            had_failure = True

    logger.info(
        "Totals: %d scrapers run, %d found, %d matched, %d new, %d errors",
        total_scrapers, total_found, total_matched, total_new, total_errors,
    )

    if total_new > 0:
        _print_new_notices(store, run_start)

    return 1 if had_failure else 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    """Build and return the argument parser."""
    parser = argparse.ArgumentParser(
        description="RFP Tracker CLI runner",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run all enabled scrapers once and exit",
    )
    parser.add_argument(
        "--scraper",
        type=str,
        metavar="NAME",
        help="Run a single scraper by name (e.g. canadabuys)",
    )
    parser.add_argument(
        "--digest",
        action="store_true",
        help="Generate and send digest (placeholder)",
    )
    parser.add_argument(
        "--test-slack",
        action="store_true",
        help="Send a test Slack message (placeholder)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns the process exit code."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    # Create data/log directories if they don't exist
    if hasattr(config, "setup_dirs"):
        config.setup_dirs()

    parser = build_parser()
    args = parser.parse_args(argv)

    # -- Placeholder commands ------------------------------------------------
    if args.digest:
        print("digest not implemented yet")
        return 0

    if args.test_slack:
        print("slack not implemented yet")
        return 0

    # -- Determine which scrapers to run -------------------------------------
    db_path = DATA_DIR / "rfp.db"
    store = OpportunityStore(db_path=db_path)

    try:
        if args.scraper:
            # Check if scraper exists in v1 or v2
            all_v2_sources = discover_v2_configs()  # All v2 configs regardless of status
            if args.scraper not in SCRAPER_MAP and args.scraper not in all_v2_sources:
                logger.error("Unknown scraper: %s", args.scraper)
                logger.info("Available v1 scrapers: %s", list(SCRAPER_MAP.keys()))
                logger.info("Available v2 sources: %s", all_v2_sources)
                return 1
            names = [args.scraper]
        elif args.once:
            # V2 mode: run production-ready v2 configs
            if V2_MODE or V2_SOURCES:
                if V2_SOURCES:
                    # Explicit v2 sources specified
                    names = list(V2_SOURCES)
                else:
                    # V2_MODE without explicit sources: run all production-ready
                    names = get_production_v2_sources()
                    
                if not names:
                    logger.warning("No v2 sources to run (V2_MODE=%s, V2_SOURCES=%s)", V2_MODE, V2_SOURCES)
                    logger.info("Available production v2 sources: %s", get_production_v2_sources())
                    return 0
            else:
                # v1 mode (default): run enabled v1 scrapers
                names = [
                    name
                    for name, cfg in SCRAPER_CONFIGS.items()
                    if cfg.get("enabled") and name in SCRAPER_MAP
                ]
        else:
            parser.print_help()
            return 0

        # Run scrapers
        exit_code = run_all(names, store)

        # NEW: HubSpot sync (decoupled from scraping)
        # Feature-flagged: only runs if env vars are set
        hubspot_api_key = os.environ.get("HUBSPOT_API_KEY")
        hubspot_object_type_id = os.environ.get("HUBSPOT_OBJECT_TYPE_ID")

        if hubspot_api_key and hubspot_object_type_id:
            logger.info("Starting HubSpot sync...")
            try:
                from lib.output.hubspot import HubSpotClient, HubSpotSync

                with HubSpotClient(
                    api_key=hubspot_api_key,
                    object_type_id=hubspot_object_type_id,
                ) as client:
                    syncer = HubSpotSync(db_path=db_path, hubspot_client=client)
                    stats = syncer.sync_pending(batch_size=100)
                    logger.info(
                        f"HubSpot sync complete: {stats['synced']} synced, "
                        f"{stats['failed']} failed"
                    )
            except Exception as e:
                # Don't fail the entire run if HubSpot sync fails
                logger.error(f"HubSpot sync failed: {e}", exc_info=True)
                logger.warning("Scraping succeeded, but HubSpot sync failed")
        else:
            logger.debug(
                "HUBSPOT_API_KEY or HUBSPOT_OBJECT_TYPE_ID not set, skipping HubSpot sync"
            )

        return exit_code
    finally:
        store.close()


if __name__ == "__main__":
    sys.exit(main())
