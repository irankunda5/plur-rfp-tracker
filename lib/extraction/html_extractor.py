"""HTML extraction engine for the self-maintaining source ingestion platform.

This module provides generic static HTML table extraction using BeautifulSoup.
No custom Python code needed - works entirely from SourceConfig.

Currently supports:
- Table-based extraction (container + row selectors)
- Positional cell extraction (cell[0], cell[1], etc.)
- Text extraction (cell[N].text)
- Link extraction (cell[N].a.href)
- Optional URL base prefix for relative links

Does NOT support:
- JavaScript rendering (use Playwright/Selenium if needed)
- Complex CSS selector patterns (intentionally narrow for Source #3)
- Multi-page discovery (add when Source #N needs it)
"""

import logging
import re
import ssl
import subprocess
from typing import Optional

import httpx
from bs4 import BeautifulSoup

from lib.source_config import SourceConfig, HTMLExtractionConfig
from lib.confidence import ExtractionConfidence

logger = logging.getLogger(__name__)

SYSTEM_CA_BUNDLE = "/etc/ssl/certs/ca-certificates.crt"


class HTMLExtractor:
    """
    Generic static HTML table extractor using BeautifulSoup.

    Works entirely from SourceConfig - no custom code needed.
    """

    def __init__(self, timeout: float = 30.0):
        self.timeout = timeout

        # Build SSL context (same as CSVExtractor)
        import os
        if os.path.exists(SYSTEM_CA_BUNDLE):
            ssl_ctx = ssl.create_default_context(cafile=SYSTEM_CA_BUNDLE)
        else:
            ssl_ctx = ssl.create_default_context()

        # Build httpx client with proper headers
        self._client = httpx.Client(
            timeout=httpx.Timeout(self.timeout),
            headers={"User-Agent": "rfp-tracker/2.0"},
            verify=ssl_ctx,
            follow_redirects=True
        )

    def __enter__(self):
        return self

    def __exit__(self, *_):
        if self._client and not self._client.is_closed:
            self._client.close()

    def close(self):
        """Close HTTP client."""
        if self._client and not self._client.is_closed:
            self._client.close()

    def _fetch_html_via_curl(self, url: str) -> str:
        """
        Fetch HTML using subprocess curl, bypassing httpx SSL issues.

        This is a fallback for environments where httpx has SSL certificate issues.
        Returns the HTML text. Raises RuntimeError on curl failure.
        """
        logger.warning(f"Falling back to curl for HTML fetch (httpx SSL issue)")

        result = subprocess.run(
            ["curl", "-s", "--compressed", url],
            capture_output=True,
            text=True,
            timeout=120,
        )

        if result.returncode != 0:
            stderr = result.stderr
            raise RuntimeError(f"curl failed (exit {result.returncode}): {stderr}")

        logger.info(f"Successfully fetched {len(result.stdout)} bytes via curl")
        return result.stdout

    def extract(
        self,
        config: SourceConfig
    ) -> tuple[list[dict], ExtractionConfidence]:
        """
        Extract records from static HTML table source.

        Args:
            config: SourceConfig with type="html" and HTMLExtractionConfig

        Returns:
            Tuple of (records, confidence)
            - records: List of dicts with mapped field names
            - confidence: ExtractionConfidence metrics

        Raises:
            httpx.HTTPError: If fetch fails
            ValueError: If config is invalid or parsing fails
        """
        if config.type.value != "html":
            raise ValueError(f"HTMLExtractor requires type='html', got '{config.type}'")

        # Get typed extraction config
        html_config: HTMLExtractionConfig = config.get_extraction_config()

        logger.info(f"[{config.source_id}] Fetching HTML from {config.url}")

        # Fetch HTML (with curl fallback for SSL issues)
        try:
            response = self._client.get(config.url)
            response.raise_for_status()
            html_text = response.text
            logger.info(f"[{config.source_id}] Fetched {len(html_text)} bytes")

        except httpx.HTTPError as exc:
            # If SSL error, try curl fallback
            if "SSL" in str(exc) or "certificate" in str(exc).lower():
                logger.warning(f"[{config.source_id}] httpx SSL error: {exc}")
                logger.info(f"[{config.source_id}] Attempting curl fallback...")
                try:
                    html_text = self._fetch_html_via_curl(config.url)
                    logger.info(f"[{config.source_id}] Curl fallback succeeded")
                except Exception as curl_exc:
                    logger.error(f"[{config.source_id}] Curl fallback also failed: {curl_exc}")
                    raise
            else:
                logger.error(f"[{config.source_id}] HTTP error: {exc}")
                raise

        # Parse HTML with BeautifulSoup
        try:
            soup = BeautifulSoup(html_text, "html.parser")
            logger.debug(f"[{config.source_id}] Parsed HTML successfully")

        except Exception as exc:
            logger.error(f"[{config.source_id}] HTML parsing error: {exc}")
            raise ValueError(f"Failed to parse HTML: {exc}")

        # Find table container
        container = soup.select_one(html_config.container_selector)
        if not container:
            logger.warning(
                f"[{config.source_id}] Container selector '{html_config.container_selector}' not found"
            )
            return [], ExtractionConfidence(
                selector_match_rate=0.0,
                record_completeness=0.0,
                schema_stability=1.0,
                validation_pass_rate=1.0,
                warnings=[f"Container selector '{html_config.container_selector}' not found"]
            )

        # Find rows within container
        rows = container.select(html_config.row_selector)
        logger.info(
            f"[{config.source_id}] Found {len(rows)} rows "
            f"(skipping first {html_config.skip_header_rows})"
        )

        # Skip header rows
        data_rows = rows[html_config.skip_header_rows:]

        # Extract records
        records = []
        warnings = []
        selector_successes = 0
        selector_attempts = 0

        for row_idx, row in enumerate(data_rows):
            record = {}
            cells = row.find_all("td")

            # Track selector success for this row
            for target_field, cell_selector in html_config.columns.items():
                selector_attempts += 1
                value = self._extract_cell_value(
                    cells=cells,
                    selector=cell_selector,
                    url_base=html_config.url_base
                )

                if value is not None:
                    selector_successes += 1
                    record[target_field] = value
                else:
                    record[target_field] = ""
                    if row_idx == 0:  # Only log warning for first row
                        warnings.append(
                            f"Selector '{cell_selector}' for field '{target_field}' failed"
                        )

            records.append(record)

        # Calculate confidence
        confidence = self._calculate_confidence(
            records=records,
            selector_successes=selector_successes,
            selector_attempts=selector_attempts,
            warnings=warnings
        )

        logger.info(
            f"[{config.source_id}] Extracted {len(records)} records. "
            f"Confidence: {confidence.overall:.2f}"
        )

        return records, confidence

    def _extract_cell_value(
        self,
        cells: list,
        selector: str,
        url_base: Optional[str] = None
    ) -> Optional[str]:
        """
        Extract value from table cells using selector notation.

        Supported patterns:
        - "cell[0]" or "cell[0].text" → text content of cell 0
        - "cell[0].a.href" → href attribute of <a> tag in cell 0

        Args:
            cells: List of BeautifulSoup td elements
            selector: Selector string (e.g., "cell[0].text", "cell[1].a.href")
            url_base: Base URL for converting relative links to absolute

        Returns:
            Extracted string value, or None if extraction failed
        """
        # Parse selector: "cell[N].text" or "cell[N].a.href"
        match = re.match(r"cell\[(\d+)\](?:\.(.+))?", selector)
        if not match:
            logger.warning(f"Invalid selector format: '{selector}' (expected 'cell[N]' or 'cell[N].text')")
            return None

        cell_index = int(match.group(1))
        sub_selector = match.group(2) or "text"  # Default to text

        # Check if cell index exists
        if cell_index >= len(cells):
            return None

        cell = cells[cell_index]

        # Handle different sub-selectors
        if sub_selector == "text":
            # Extract text content
            return cell.get_text(strip=True)

        elif sub_selector == "a.href":
            # Extract link href
            link = cell.find("a")
            if not link or not link.get("href"):
                return None

            href = link["href"]

            # Convert relative URLs to absolute if url_base provided
            if url_base and href and not href.startswith("http"):
                # Handle both /path and path formats
                if href.startswith("/"):
                    return f"{url_base}{href}"
                else:
                    return f"{url_base}/{href}"

            return href

        else:
            logger.warning(f"Unsupported sub-selector: '{sub_selector}' in '{selector}'")
            return None

    def _calculate_confidence(
        self,
        records: list[dict],
        selector_successes: int,
        selector_attempts: int,
        warnings: list[str]
    ) -> ExtractionConfidence:
        """
        Calculate extraction confidence for HTML extraction.

        Args:
            records: Extracted records
            selector_successes: Number of successful selector extractions
            selector_attempts: Total selector extraction attempts
            warnings: List of warnings encountered

        Returns:
            ExtractionConfidence with scores
        """
        # Selector match rate = % of selectors that successfully extracted values
        selector_match_rate = (
            selector_successes / selector_attempts if selector_attempts > 0 else 0.0
        )

        # Record completeness = avg % of non-empty fields per record
        if records:
            completeness_scores = []
            for record in records:
                non_empty = sum(1 for v in record.values() if v and str(v).strip())
                completeness_scores.append(non_empty / len(record) if record else 0.0)
            record_completeness = sum(completeness_scores) / len(completeness_scores)
        else:
            record_completeness = 0.0

        # Schema stability = 1.0 (no historical comparison yet)
        schema_stability = 1.0

        # Validation pass rate = not calculated here (done in validation layer)
        validation_pass_rate = 1.0

        return ExtractionConfidence(
            selector_match_rate=selector_match_rate,
            record_completeness=record_completeness,
            schema_stability=schema_stability,
            validation_pass_rate=validation_pass_rate,
            warnings=warnings
        )
