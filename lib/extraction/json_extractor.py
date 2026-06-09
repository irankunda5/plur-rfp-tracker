"""JSON API extraction engine for the self-maintaining source ingestion platform.

This module provides generic JSON API extraction using httpx and field mappings.
No custom Python code needed - works entirely from SourceConfig.
"""

import json
import logging
import os
import ssl
import subprocess
from typing import Any, Optional

import httpx

from lib.source_config import SourceConfig, JSONExtractionConfig
from lib.confidence import ExtractionConfidence

logger = logging.getLogger(__name__)

SYSTEM_CA_BUNDLE = "/etc/ssl/certs/ca-certificates.crt"


class JSONExtractor:
    """
    Generic JSON API extractor using httpx.

    Works entirely from SourceConfig - no custom code needed.
    Supports:
    - API key authentication (query param or header)
    - Nested JSON response navigation
    - Field mapping with dot notation
    """

    def __init__(self, timeout: float = 30.0):
        self.timeout = timeout

        # Build SSL context (same as CSVExtractor)
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

    def _get_nested_value(self, obj: dict, path: str) -> Any:
        """
        Get value from nested dict using dot notation.

        Examples:
            _get_nested_value({"a": {"b": "value"}}, "a.b") -> "value"
            _get_nested_value({"title": "test"}, "title") -> "test"

        Args:
            obj: Dictionary to traverse
            path: Dot-separated path to value

        Returns:
            Value at path, or None if not found
        """
        keys = path.split(".")
        current = obj

        for key in keys:
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                return None

        return current

    def extract(
        self,
        config: SourceConfig
    ) -> tuple[list[dict], ExtractionConfidence]:
        """
        Extract records from JSON API source.

        Args:
            config: SourceConfig with type="json_api" and JSONExtractionConfig

        Returns:
            Tuple of (records, confidence)
            - records: List of dicts with mapped field names
            - confidence: ExtractionConfidence metrics

        Raises:
            httpx.HTTPError: If fetch fails
            ValueError: If config is invalid or parsing fails
        """
        if config.type.value != "json_api":
            raise ValueError(f"JSONExtractor requires type='json_api', got '{config.type}'")

        # Get typed extraction config
        json_config: JSONExtractionConfig = config.get_extraction_config()

        logger.info(f"[{config.source_id}] Fetching JSON from {config.url}")

        # Build query parameters
        params = dict(json_config.query_params)

        # Add authentication if configured
        if config.auth.type == "api_key":
            if not config.auth.key_name:
                raise ValueError("API key auth requires key_name (env var name)")

            api_key = os.environ.get(config.auth.key_name)
            if not api_key:
                raise ValueError(
                    f"API key not found in environment variable '{config.auth.key_name}'. "
                    f"Please set this environment variable before running."
                )

            # Add API key to query params or headers
            if config.auth.header_name:
                self._client.headers[config.auth.header_name] = api_key
            else:
                # Default: add as query parameter
                params["api_key"] = api_key

        # Fetch JSON
        data = None
        try:
            response = self._client.get(config.url, params=params)
            response.raise_for_status()
            data = response.json()

            logger.info(
                f"[{config.source_id}] Fetched JSON response "
                f"({len(response.content)} bytes)"
            )

        except httpx.HTTPError as exc:
            # SSL errors common on some systems; try curl fallback
            if "SSL" in str(exc) or "CERTIFICATE" in str(exc):
                logger.warning(
                    f"[{config.source_id}] httpx SSL error, trying curl fallback: {exc}"
                )
                try:
                    # Build curl command with params
                    if params:
                        param_str = "&".join(f"{k}={v}" for k, v in params.items())
                        full_url = f"{config.url}?{param_str}"
                    else:
                        full_url = config.url

                    result = subprocess.run(
                        ["curl", "-s", "--compressed", full_url],
                        capture_output=True,
                        text=True,
                        check=True,
                        timeout=self.timeout
                    )
                    data = json.loads(result.stdout)
                    logger.info(
                        f"[{config.source_id}] Fetched JSON via curl "
                        f"({len(result.stdout)} bytes)"
                    )
                except Exception as curl_exc:
                    logger.error(f"[{config.source_id}] curl fallback failed: {curl_exc}")
                    raise
            else:
                logger.error(f"[{config.source_id}] HTTP error: {exc}")
                raise
        except json.JSONDecodeError as exc:
            logger.error(f"[{config.source_id}] JSON parsing error: {exc}")
            raise ValueError(f"Failed to parse JSON response: {exc}")

        if data is None:
            raise ValueError(f"Failed to fetch JSON data from {config.url}")

        # Navigate to records array if response_path specified
        if json_config.response_path:
            records_array = self._get_nested_value(data, json_config.response_path)
            if records_array is None:
                logger.warning(
                    f"[{config.source_id}] response_path '{json_config.response_path}' "
                    f"not found in response. Available keys: {list(data.keys())}"
                )
                records_array = []
            elif not isinstance(records_array, list):
                # Handle dict responses (e.g., Bonfire: {id1: {...}, id2: {...}})
                if isinstance(records_array, dict):
                    logger.info(
                        f"[{config.source_id}] response_path '{json_config.response_path}' "
                        f"is a dict, converting values to list ({len(records_array)} records)"
                    )
                    records_array = list(records_array.values())
                else:
                    logger.warning(
                        f"[{config.source_id}] response_path '{json_config.response_path}' "
                        f"is not a list or dict (got {type(records_array)})"
                    )
                    records_array = []
        else:
            # No response_path: assume root is array or dict with records
            if isinstance(data, list):
                records_array = data
            else:
                # Try common patterns
                for key in ["data", "results", "records", "items"]:
                    if key in data and isinstance(data[key], list):
                        records_array = data[key]
                        logger.info(
                            f"[{config.source_id}] Auto-detected records at '{key}'"
                        )
                        break
                else:
                    logger.warning(
                        f"[{config.source_id}] Could not find records array. "
                        f"Root keys: {list(data.keys())}"
                    )
                    records_array = []

        logger.info(f"[{config.source_id}] Found {len(records_array)} records")

        # Map fields
        records = []
        warnings = []
        missing_fields = set()

        for raw_record in records_array:
            if not isinstance(raw_record, dict):
                warnings.append(f"Record is not a dict: {type(raw_record)}")
                continue

            record = {}

            for target_field, source_path in json_config.columns.items():
                value = self._get_nested_value(raw_record, source_path)

                if value is None:
                    record[target_field] = ""
                    missing_fields.add(source_path)
                else:
                    # Convert to string, handle various types
                    if isinstance(value, str):
                        record[target_field] = value.strip()
                    elif isinstance(value, (int, float, bool)):
                        record[target_field] = str(value)
                    elif isinstance(value, dict):
                        # For nested objects, store as string representation
                        record[target_field] = str(value)
                    else:
                        record[target_field] = str(value) if value else ""

            records.append(record)

        if missing_fields:
            warnings.append(
                f"Missing fields in some records: {sorted(missing_fields)}"
            )
            logger.warning(
                f"[{config.source_id}] Missing fields in some records: "
                f"{sorted(missing_fields)}"
            )

        # Calculate confidence
        confidence = self._calculate_confidence(
            records=records,
            json_config=json_config,
            total_records=len(records_array),
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
        json_config: JSONExtractionConfig,
        total_records: int,
        warnings: list[str]
    ) -> ExtractionConfidence:
        """
        Calculate extraction confidence for JSON API extraction.

        Args:
            records: Extracted records
            json_config: JSON extraction configuration
            total_records: Total records found in response
            warnings: List of warnings encountered

        Returns:
            ExtractionConfidence with scores
        """
        # Selector match rate = % of records successfully extracted
        if total_records > 0:
            selector_match_rate = len(records) / total_records
        else:
            selector_match_rate = 0.0

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
