"""CanadaBuys CSV scraper - fetches open tender notices from Canadian federal procurement."""

import csv
import io
import logging
import subprocess
import sys
import tempfile

from scrapers.base import BaseScraper
from lib.keywords import classify_opportunity
from lib.storage import OpportunityStore

logger = logging.getLogger(__name__)

CSV_URL = "https://canadabuys.canada.ca/opendata/pub/newTenderNotice-nouvelAvisAppelOffres.csv"

# CanadaBuys bilingual column names
COL_REFERENCE = "referenceNumber-numeroReference"
COL_TITLE = "title-titre-eng"
COL_DESCRIPTION = "tenderDescription-descriptionAppelOffres-eng"
COL_BUYER = "contractingEntityName-nomEntitContractante-eng"
COL_CLOSING_DATE = "tenderClosingDate-appelOffresDateCloture"
COL_URL = "noticeURL-URLavis-eng"
COL_NOTICE_TYPE = "noticeType-avisType-eng"
COL_SOLICITATION = "solicitationNumber-numeroSollicitation"
COL_UNSPSC = "unspsc"
COL_AMENDMENT_DATE = "amendmentDate-dateModification"
COL_GSIN = "gsin-nibs"

REQUIRED_COLUMNS = {
    COL_REFERENCE, COL_TITLE, COL_DESCRIPTION, COL_BUYER,
    COL_CLOSING_DATE, COL_URL, COL_NOTICE_TYPE, COL_SOLICITATION,
    COL_UNSPSC, COL_AMENDMENT_DATE,
}


class CanadaBuysScraper(BaseScraper):
    """Scraper for the CanadaBuys open-data CSV feed."""

    name = "canadabuys"
    url = CSV_URL

    def __init__(self, store=None, config: dict | None = None, **kwargs):
        self._store = store
        super().__init__(config=config, **kwargs)
        self._etag: str | None = None

    # ------------------------------------------------------------------
    # CSV fetch with ETag / conditional GET
    # ------------------------------------------------------------------

    # Minimum expected size for the open tenders CSV (which is ~6MB in production).
    # Anything below this threshold suggests httpx silently truncated the response,
    # a known VPS SSL/encoding issue.
    _CSV_MIN_BYTES = 100_000  # 100 KB

    def _fetch_csv_via_curl(self, url: str) -> str:
        """Fetch CSV using subprocess curl, bypassing httpx SSL/encoding issues.

        Returns the CSV text. Raises on curl failure.
        """
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
            tmp_path = tmp.name

        result = subprocess.run(
            ["curl", "-s", "--compressed", "-o", tmp_path, url],
            capture_output=True,
            timeout=120,
        )
        if result.returncode != 0:
            stderr = result.stderr.decode(errors="replace")
            raise RuntimeError(f"curl failed (exit {result.returncode}): {stderr}")

        with open(tmp_path, encoding="utf-8-sig", errors="replace") as fh:
            text = fh.read()

        import os
        os.unlink(tmp_path)

        return text

    def fetch_csv(self) -> str | None:
        """Fetch the CSV, using ETag for conditional GET.

        Returns CSV text or None if 304 Not Modified.

        httpx fallback: if the response body is suspiciously small (< _CSV_MIN_BYTES),
        retries via subprocess curl which handles VPS SSL/encoding issues correctly.

        Note: ETag is stored on the instance but is never persisted between runs
        (fresh instance each scrape). It functions as a within-session dedup guard
        only - it will never actually produce a 304 in normal operation.
        """
        headers = {}
        if self._etag:
            headers["If-None-Match"] = self._etag

        resp = self.get(self.url, headers=headers)

        if resp.status_code == 304:
            logger.info("[%s] CSV not modified (304)", self.name)
            return None

        # Store ETag for next fetch
        new_etag = resp.headers.get("ETag")
        if new_etag:
            self._etag = new_etag

        text = resp.text
        byte_len = len(text.encode("utf-8", errors="replace"))

        if byte_len < self._CSV_MIN_BYTES:
            logger.warning(
                "[%s] httpx response suspiciously small (%d bytes, expected >%d). "
                "Falling back to curl.",
                self.name, byte_len, self._CSV_MIN_BYTES,
            )
            text = self._fetch_csv_via_curl(self.url)
            logger.info(
                "[%s] curl fallback succeeded (%d bytes)",
                self.name, len(text.encode("utf-8", errors="replace")),
            )
        else:
            logger.debug("[%s] httpx fetch OK (%d bytes)", self.name, byte_len)

        return text

    # ------------------------------------------------------------------
    # CSV parsing
    # ------------------------------------------------------------------

    def parse_csv(self, csv_text: str) -> list[dict]:
        """Parse the CanadaBuys CSV into a list of row dicts.

        Handles BOM (utf-8-sig) by stripping the U+FEFF prefix if present.
        """
        # Strip BOM if present (handles utf-8-sig encoded text)
        if csv_text.startswith("\ufeff"):
            csv_text = csv_text[1:]

        reader = csv.DictReader(io.StringIO(csv_text), delimiter=",")
        return list(reader)

    def _validate_columns(self, row: dict) -> bool:
        """Check that the CSV row contains the required columns."""
        return REQUIRED_COLUMNS.issubset(row.keys())

    # ------------------------------------------------------------------
    # Field extraction helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _cell(row: dict, col: str) -> str:
        """Extract a trimmed string value from a CSV row, treating None as empty."""
        return (row.get(col, "") or "").strip()

    def _extract_unspsc(self, row: dict) -> list[str]:
        """Extract UNSPSC codes from multi-value field (newline-separated)."""
        raw = row.get(COL_UNSPSC, "") or ""
        if not raw.strip():
            return []
        # UNSPSC field uses newline separators within quoted CSV fields
        return [code.strip() for code in raw.split("\n") if code.strip()]

    def _extract_gsin(self, row: dict) -> list[str]:
        """Extract GSIN codes from multi-value field (newline-separated)."""
        raw = row.get(COL_GSIN, "") or ""
        if not raw.strip():
            return []
        return [code.strip() for code in raw.split("\n") if code.strip()]

    def _detect_amendment(self, row: dict, notice_id: int) -> None:
        """Check if this tender is an amendment and link to the original.

        An amendment is detected when amendmentDate is non-empty AND a notice
        with the same solicitationNumber already exists in the DB.
        Uses find_by_solicitation_number() for indexed lookup.
        """
        amendment_date = self._cell(row, COL_AMENDMENT_DATE)
        if not amendment_date:
            return

        sol_num = self._cell(row, COL_SOLICITATION)
        if not sol_num:
            return

        original_id = self._store.find_by_solicitation_number(self.name, sol_num)
        if original_id is not None and original_id != notice_id:
            self._store.add_amendment_link(
                original_id, notice_id,
                reason=f"same_solicitation_number={sol_num}",
            )
            logger.debug(
                "[%s] Amendment link: notice %d -> %d (sol=%s)",
                self.name, original_id, notice_id, sol_num,
            )

    # ------------------------------------------------------------------
    # Main scrape
    # ------------------------------------------------------------------

    def scrape(self) -> dict:
        """Fetch CSV, classify tenders, store matches.

        Returns:
            Stats dict with keys: records_found, records_matched, records_new.
        """
        store = self._store
        run_id = store.start_run(self.name)
        stats = {"records_found": 0, "records_matched": 0, "records_new": 0}

        try:
            csv_text = self.fetch_csv()
            if csv_text is None:
                # 304 Not Modified
                store.end_run(run_id, status="success", **stats)
                self._mark_success()
                return stats

            tenders = self.parse_csv(csv_text)
            stats["records_found"] = len(tenders)

            if not tenders:
                store.end_run(run_id, status="success", **stats)
                self._mark_success()
                return stats

            # Validate columns on first row
            if not self._validate_columns(tenders[0]):
                missing = REQUIRED_COLUMNS - set(tenders[0].keys())
                msg = f"Missing required columns: {missing}"
                logger.error("[%s] %s", self.name, msg)
                store.end_run(run_id, status="error", error_message=msg, **stats)
                return stats

            for row in tenders:
                source_id = self._cell(row, COL_REFERENCE)
                title = self._cell(row, COL_TITLE)
                description = self._cell(row, COL_DESCRIPTION)
                buyer = self._cell(row, COL_BUYER)
                closing_date = self._cell(row, COL_CLOSING_DATE) or None
                tender_url = self._cell(row, COL_URL)
                notice_type = self._cell(row, COL_NOTICE_TYPE)
                solicitation_number = self._cell(row, COL_SOLICITATION)

                if not source_id or not title:
                    continue

                unspsc_codes = self._extract_unspsc(row)
                gsin_codes = self._extract_gsin(row)

                classification = classify_opportunity(
                    title, description,
                    unspsc_codes=unspsc_codes,
                    gsin_codes=gsin_codes,
                )

                if classification["tier"] == 0:
                    continue

                stats["records_matched"] += 1

                is_new, notice_id = store.add_notice(
                    source=self.name,
                    source_id=source_id,
                    title=title,
                    description=description,
                    buyer=buyer,
                    closing_date=closing_date,
                    url=tender_url,
                    notice_type=notice_type,
                    product_type=classification.get("product_type", ""),
                    vendor_flags=classification.get("vendor_flags", []),
                    classification=classification,
                    raw_json=row,
                    solicitation_number=solicitation_number,
                )

                if is_new:
                    stats["records_new"] += 1
                    # Check for amendment linkage
                    self._detect_amendment(row, notice_id)

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

    parser = argparse.ArgumentParser(description="CanadaBuys CSV scraper")
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    args = parser.parse_args()

    from config import DATA_DIR
    db_path = DATA_DIR / "rfp.db"
    with OpportunityStore(db_path=db_path) as store:
        scraper = CanadaBuysScraper(store=store, delay_seconds=0)
        try:
            stats = scraper.scrape()
            logger.info("Scrape complete: %s", stats)
        finally:
            scraper.close()

    sys.exit(0)


if __name__ == "__main__":
    main()
