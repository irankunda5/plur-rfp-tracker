"""CSV extraction engine for the self-maintaining source ingestion platform.

This module provides generic CSV extraction using pandas and column mappings.
No custom Python code needed - works entirely from SourceConfig.
"""

import io
import logging
import ssl
import subprocess
import tempfile
from typing import Optional

import httpx
import pandas as pd

from lib.source_config import SourceConfig, CSVExtractionConfig
from lib.confidence import ExtractionConfidence

logger = logging.getLogger(__name__)

SYSTEM_CA_BUNDLE = "/etc/ssl/certs/ca-certificates.crt"


class CSVExtractor:
    """
    Generic CSV extractor using pandas.

    Works entirely from SourceConfig - no custom code needed.
    """

    def __init__(self, timeout: float = 30.0):
        self.timeout = timeout

        # Build SSL context (same as legacy scrapers)
        # Fall back to default if CA bundle doesn't exist
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

    def _fetch_csv_via_curl(self, url: str) -> str:
        """
        Fetch CSV using subprocess curl, bypassing httpx SSL/encoding issues.

        This is a fallback for environments where httpx has SSL certificate issues.
        Returns the CSV text. Raises RuntimeError on curl failure.
        """
        logger.warning(f"Falling back to curl for CSV fetch (httpx SSL issue)")

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

        logger.info(f"Successfully fetched {len(text)} bytes via curl")
        return text

    def extract(
        self,
        config: SourceConfig
    ) -> tuple[list[dict], ExtractionConfidence]:
        """
        Extract records from CSV source.

        Args:
            config: SourceConfig with type="csv" and CSVExtractionConfig

        Returns:
            Tuple of (records, confidence)
            - records: List of dicts with mapped field names
            - confidence: ExtractionConfidence metrics

        Raises:
            httpx.HTTPError: If fetch fails
            ValueError: If config is invalid or parsing fails
        """
        if config.type.value != "csv":
            raise ValueError(f"CSVExtractor requires type='csv', got '{config.type}'")

        # Get typed extraction config
        csv_config: CSVExtractionConfig = config.get_extraction_config()

        logger.info(f"[{config.source_id}] Fetching CSV from {config.url}")

        # Fetch CSV (with curl fallback for SSL issues)
        try:
            response = self._client.get(config.url)
            response.raise_for_status()
            csv_text = response.text
            response_size = len(csv_text)
            logger.info(f"[{config.source_id}] Fetched {response_size} bytes")

        except httpx.HTTPError as exc:
            # If SSL error, try curl fallback
            if "SSL" in str(exc) or "certificate" in str(exc).lower():
                logger.warning(f"[{config.source_id}] httpx SSL error: {exc}")
                logger.info(f"[{config.source_id}] Attempting curl fallback...")
                try:
                    csv_text = self._fetch_csv_via_curl(config.url)
                    logger.info(f"[{config.source_id}] Curl fallback succeeded")
                except Exception as curl_exc:
                    logger.error(f"[{config.source_id}] Curl fallback also failed: {curl_exc}")
                    raise
            else:
                logger.error(f"[{config.source_id}] HTTP error: {exc}")
                raise

        # Parse CSV with pandas
        try:
            df = pd.read_csv(
                io.StringIO(csv_text),
                delimiter=csv_config.delimiter,
                encoding=csv_config.encoding,
                skiprows=csv_config.skip_rows,
                header=0 if csv_config.has_header else None
            )

            logger.info(f"[{config.source_id}] Parsed {len(df)} rows, {len(df.columns)} columns")

        except Exception as exc:
            logger.error(f"[{config.source_id}] CSV parsing error: {exc}")
            raise ValueError(f"Failed to parse CSV: {exc}")

        # Map columns to standard schema
        records = []
        warnings = []
        missing_columns = []

        # Check if all source columns exist
        for target_field, source_column in csv_config.columns.items():
            if source_column not in df.columns:
                missing_columns.append(source_column)
                warnings.append(f"Source column '{source_column}' not found in CSV")

        if missing_columns:
            logger.warning(
                f"[{config.source_id}] Missing columns: {missing_columns}. "
                f"Available: {list(df.columns)}"
            )

        # Extract records
        for idx, row in df.iterrows():
            record = {}

            for target_field, source_column in csv_config.columns.items():
                if source_column in df.columns:
                    value = row.get(source_column)

                    # Handle NaN/None values
                    if pd.isna(value):
                        record[target_field] = ""
                    else:
                        record[target_field] = str(value).strip()
                else:
                    # Column missing, set empty string
                    record[target_field] = ""

            records.append(record)

        # Calculate confidence
        confidence = self._calculate_confidence(
            records=records,
            csv_config=csv_config,
            df=df,
            warnings=warnings
        )

        logger.info(
            f"[{config.source_id}] Extracted {len(records)} records. "
            f"Confidence: {confidence.overall:.2f}"
        )

        return records, confidence

    def _calculate_confidence(
        self,
        records: list[dict],
        csv_config: CSVExtractionConfig,
        df: pd.DataFrame,
        warnings: list[str]
    ) -> ExtractionConfidence:
        """
        Calculate extraction confidence for CSV extraction.

        Args:
            records: Extracted records
            csv_config: CSV extraction configuration
            df: Parsed DataFrame
            warnings: List of warnings encountered

        Returns:
            ExtractionConfidence with scores
        """
        # Selector match rate = % of configured columns found in CSV
        expected_columns = set(csv_config.columns.values())
        actual_columns = set(df.columns)
        found_columns = expected_columns & actual_columns
        selector_match_rate = len(found_columns) / len(expected_columns) if expected_columns else 0.0

        # Record completeness = avg % of non-empty fields per record
        if records:
            completeness_scores = []
            for record in records:
                non_empty = sum(1 for v in record.values() if v and str(v).strip())
                completeness_scores.append(non_empty / len(record) if record else 0.0)
            record_completeness = sum(completeness_scores) / len(completeness_scores)
        else:
            record_completeness = 0.0

        # Schema stability = 1.0 (no historical comparison yet, will be added with snapshots)
        schema_stability = 1.0

        # Validation pass rate = not calculated here (done in validation layer)
        # For now, assume all records will pass validation
        validation_pass_rate = 1.0

        return ExtractionConfidence(
            selector_match_rate=selector_match_rate,
            record_completeness=record_completeness,
            schema_stability=schema_stability,
            validation_pass_rate=validation_pass_rate,
            warnings=warnings
        )
