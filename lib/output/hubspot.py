"""HubSpot output integration for RFP records.

This module provides a decoupled sync layer between SQLite storage and HubSpot.
HubSpot sync failures do NOT break ingestion - they're logged and can be retried.

Maps internal RFP records to HubSpot "Signals" custom object schema.
"""

import json
import logging
import re
import time
from datetime import datetime
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


class HubSpotClient:
    """HubSpot API client for syncing RFP records to Signals custom object.

    Handles HTTP communication with HubSpot CRM API v3, including:
    - Payload mapping from SQLite schema to HubSpot Signals object
    - Error handling and logging
    - Rate limiting (100ms delay between requests)

    Example usage:
        client = HubSpotClient(
            api_key="...",
            object_type_id="2-229341360"
        )
        success, hubspot_id, error = client.push_record(record_dict)
        if success:
            print(f"Synced to HubSpot ID: {hubspot_id}")
        else:
            print(f"Sync failed: {error}")
    """

    def __init__(
        self,
        api_key: str,
        object_type_id: str,
        timeout: int = 30,
        rate_limit_delay: float = 0.1,
    ):
        """Initialize HubSpot client.

        Args:
            api_key: HubSpot API key (Bearer token)
            object_type_id: HubSpot custom object type ID (e.g., "2-229341360" for Signals)
            timeout: HTTP request timeout in seconds (default: 30)
            rate_limit_delay: Delay between requests in seconds (default: 0.1)
        """
        self.api_key = api_key
        self.object_type_id = object_type_id
        self.endpoint = f"https://api.hubapi.com/crm/v3/objects/{object_type_id}"
        self.timeout = timeout
        self.rate_limit_delay = rate_limit_delay
        self.client = httpx.Client(timeout=timeout)

    def push_record(self, record: dict) -> tuple[bool, Optional[str], Optional[str]]:
        """Push a single RFP record to HubSpot Signals object.

        Args:
            record: Dictionary with SQLite row data (from notices table)

        Returns:
            Tuple of (success, hubspot_id, error_message):
            - success: True if record was pushed successfully
            - hubspot_id: HubSpot record ID (if success=True)
            - error_message: Error description (if success=False)
        """
        try:
            # Build HubSpot Signals properties from SQLite record
            signal_properties = self._build_signal_properties(record)

            # Wrap in CRM v3 payload format
            payload = {"properties": signal_properties}

            # POST to HubSpot CRM API
            response = self.client.post(
                self.endpoint,
                json=payload,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
            )

            response.raise_for_status()
            result = response.json()

            # Extract HubSpot record ID from CRM v3 response
            # CRM v3 returns: {"id": "...", "properties": {...}, "createdAt": "...", "updatedAt": "..."}
            hubspot_id = result.get("id", "")

            logger.info(f"Pushed record {record['id']} to HubSpot Signals (ID: {hubspot_id})")

            # Rate limiting delay
            time.sleep(self.rate_limit_delay)

            return (True, hubspot_id, None)

        except httpx.HTTPStatusError as e:
            error_msg = f"HTTP {e.response.status_code}: {e.response.text[:200]}"
            logger.error(f"HubSpot API error for record {record['id']}: {error_msg}")
            return (False, None, error_msg)

        except httpx.TimeoutException as e:
            error_msg = f"Request timeout after {self.timeout}s"
            logger.error(f"HubSpot timeout for record {record['id']}: {error_msg}")
            return (False, None, error_msg)

        except Exception as e:
            error_msg = f"{type(e).__name__}: {str(e)[:200]}"
            logger.error(f"HubSpot push failed for record {record['id']}: {error_msg}")
            return (False, None, error_msg)

    def _build_signal_properties(self, record: dict) -> dict:
        """Map SQLite record to HubSpot Signals object properties.

        Signals schema fields:
        - identifier (required, unique): stable unique ID
        - summary: short sales-friendly summary
        - description: longer description
        - organization_or_vertical: buyer/org
        - source: originating source name (WARNING: may be unique constraint)
        - source_id: source system record ID
        - url: original listing URL
        - signal_primary_type: enum (Hard, Medium, Soft)
        - signal_subtype: multi-select (semicolon-separated)
        - relevance_tier: enum (Cyber, IAM, IS/IT, Other)
        - confidence_score: number
        - matched_keywords: string
        - published: date
        - retrieved: date
        - deadlinedue: date

        Args:
            record: SQLite row dictionary

        Returns:
            Dictionary of HubSpot Signals properties
        """
        # Parse classification JSON
        classification = self._parse_classification(record)

        # Build properties with Signals schema mapping
        properties = {
            # Required unique identifier
            "identifier": self._generate_identifier(record),

            # Sales-friendly summary
            "summary": self._generate_summary(record),

            # Description
            "description": record.get("description") or record["title"],

            # Organization/buyer
            "organization_or_vertical": record.get("buyer") or "",

            # Source information
            # NOTE: Schema indicates 'source' may have uniqueness constraint.
            # Using composite value (source-source_id) to ensure uniqueness per record.
            # This makes each record's source unique while preserving source system ID.
            "source": f"{record['source']}-{record['source_id']}",
            "source_id": record["source_id"],

            # URL
            "url": record.get("url") or "",

            # Signal type classification
            "signal_primary_type": self._map_signal_primary_type(record),
            "signal_subtype": self._map_signal_subtype(record),

            # Relevance classification
            "relevance_tier": self._map_relevance_tier(classification),
            "confidence_score": classification.get("confidence", 0.0),
            "matched_keywords": self._format_keywords(classification.get("matched_keywords", [])),

            # Dates
            "published": self._format_date(record.get("closing_date")),  # Use closing date as published
            "retrieved": self._format_date(record["fetch_timestamp"]),
            "deadlinedue": self._format_date(record.get("closing_date")),
        }

        # Remove empty string values to keep HubSpot cleaner
        # Keep 0 and 0.0 values (valid for numeric fields)
        properties = {k: v for k, v in properties.items() if v != ""}

        return properties

    def _generate_identifier(self, record: dict) -> str:
        """Generate stable unique identifier for HubSpot Signals.

        Pattern: YYMMDD-BUYER-<source_id or db_id>

        Must be deterministic (same record = same identifier each run).

        Args:
            record: SQLite row dictionary

        Returns:
            Unique identifier string
        """
        # Extract date from fetch_timestamp (format: YYYY-MM-DDTHH:MM:SS...)
        fetch_ts = record.get("fetch_timestamp", "")
        try:
            dt = datetime.fromisoformat(fetch_ts.replace("Z", "+00:00"))
            date_part = dt.strftime("%y%m%d")
        except (ValueError, AttributeError):
            date_part = "000000"

        # Sanitize buyer name for identifier (remove special chars, limit length)
        buyer = record.get("buyer", "UNKNOWN")
        buyer_safe = re.sub(r"[^A-Za-z0-9]", "", buyer)[:20].upper()
        if not buyer_safe:
            buyer_safe = "UNKNOWN"

        # Use source_id if available, otherwise db id
        record_id = record.get("source_id") or str(record["id"])
        record_id_safe = re.sub(r"[^A-Za-z0-9\-]", "", record_id)[:30]

        # Combine into stable identifier
        identifier = f"{date_part}-{buyer_safe}-{record_id_safe}"

        return identifier

    def _generate_summary(self, record: dict) -> str:
        """Generate short sales-friendly summary.

        Pattern: <BUYER> RFP — <short title>

        Args:
            record: SQLite row dictionary

        Returns:
            Summary string (max ~100 chars)
        """
        buyer = record.get("buyer", "Unknown Org")
        title = record["title"]

        # Truncate title if too long
        max_title_len = 80 - len(buyer)
        if len(title) > max_title_len:
            title_short = title[:max_title_len - 3] + "..."
        else:
            title_short = title

        summary = f"{buyer} RFP — {title_short}"

        return summary

    def _map_signal_primary_type(self, record: dict) -> str:
        """Map notice type to HubSpot signal_primary_type enum.

        Enum values: Hard, Medium, Soft

        For RFPs/RFQs (actual procurement), use "Hard".
        Could add logic for Medium/Soft in future.

        Args:
            record: SQLite row dictionary

        Returns:
            Signal primary type enum value
        """
        # All procurement notices are "Hard" signals (actual opportunities)
        return "Hard"

    def _map_signal_subtype(self, record: dict) -> str:
        """Map notice type to HubSpot signal_subtype enum.

        Enum values (from schema): RFP, RFQ, RFI/Forcast/Plan (note typo)
        Multi-select field: use semicolon to separate multiple values.

        Args:
            record: SQLite row dictionary

        Returns:
            Signal subtype value (semicolon-separated if multiple)
        """
        notice_type = record.get("notice_type", "").upper()

        # Map to schema enum values
        if "RFP" in notice_type:
            return "RFP"
        elif "RFQ" in notice_type:
            return "RFQ"
        elif any(keyword in notice_type for keyword in ["RFI", "FORECAST", "PLAN", "NOTICE"]):
            return "RFI/Forcast/Plan"  # Match schema typo
        else:
            # Default to RFP for procurement records
            return "RFP"

    def _map_relevance_tier(self, classification: dict) -> str:
        """Map internal tier to HubSpot relevance_tier enum.

        Enum values: Cyber, IAM, IS/IT, Other

        Args:
            classification: Parsed classification_json dictionary

        Returns:
            Relevance tier enum value
        """
        tier = classification.get("tier", 0)
        matched_keywords = classification.get("matched_keywords", [])

        # Map tier to HubSpot enum
        if tier == 1 or any("cyber" in kw.lower() for kw in matched_keywords):
            return "Cyber"
        elif tier == 2 or any("iam" in kw.lower() or "identity" in kw.lower() for kw in matched_keywords):
            return "IAM"
        elif tier == 3 or any("it" in kw.lower() for kw in matched_keywords):
            return "IS/IT"
        else:
            return "Other"

    def _format_date(self, date_value: Optional[str]) -> str:
        """Format date for HubSpot.

        HubSpot accepts ISO 8601 date format (YYYY-MM-DD).

        Args:
            date_value: Date string (may be ISO 8601 or other format)

        Returns:
            Formatted date string (YYYY-MM-DD) or empty string if invalid
        """
        if not date_value:
            return ""

        try:
            # Parse ISO 8601 datetime and extract date part
            dt = datetime.fromisoformat(date_value.replace("Z", "+00:00"))
            return dt.strftime("%Y-%m-%d")
        except (ValueError, AttributeError):
            # If parsing fails, try to extract YYYY-MM-DD pattern
            match = re.search(r"\d{4}-\d{2}-\d{2}", date_value)
            if match:
                return match.group(0)
            return ""

    def _parse_classification(self, record: dict) -> dict:
        """Parse classification_json field safely.

        Args:
            record: SQLite row dictionary

        Returns:
            Parsed classification dictionary (empty dict if parsing fails)
        """
        try:
            classification_json = record.get("classification_json", "{}")
            if not classification_json:
                return {}
            return json.loads(classification_json)
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning(f"Failed to parse classification_json for record {record.get('id')}: {e}")
            return {}

    def _format_keywords(self, keywords: list[str]) -> str:
        """Format matched keywords as comma-separated string.

        Args:
            keywords: List of keyword strings

        Returns:
            Comma-separated string (limited to first 10 keywords)
        """
        if not keywords:
            return ""
        # Limit to first 10 keywords to avoid overly long strings
        return ", ".join(keywords[:10])

    def close(self):
        """Close HTTP client and release resources."""
        self.client.close()

    def __enter__(self):
        """Context manager support."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager cleanup."""
        self.close()


class HubSpotSync:
    """Orchestrates syncing of pending RFP records from SQLite to HubSpot.

    This class provides decoupled sync logic that:
    - Reads unsynced records from SQLite (hubspot_synced=0)
    - Pushes them to HubSpot via HubSpotClient
    - Updates sync status in database
    - Logs failures without crashing

    Example usage:
        from pathlib import Path
        client = HubSpotClient(api_key="...", endpoint="...")
        syncer = HubSpotSync(db_path=Path("data/rfp.db"), client=client)
        stats = syncer.sync_pending(batch_size=100)
        print(f"Synced: {stats['synced']}, Failed: {stats['failed']}")
    """

    def __init__(self, db_path, hubspot_client: HubSpotClient):
        """Initialize sync orchestrator.

        Args:
            db_path: Path to SQLite database
            hubspot_client: Configured HubSpotClient instance
        """
        import sqlite3
        from pathlib import Path

        self.db_path = Path(db_path)
        self.hubspot = hubspot_client
        self._sqlite3 = sqlite3  # Store for later use

    def sync_pending(
        self,
        batch_size: int = 100,
        retry_failed: bool = False,
    ) -> dict:
        """Sync pending records to HubSpot.

        Args:
            batch_size: Maximum records to process in this run (default: 100)
            retry_failed: Whether to retry previously failed records (default: False)

        Returns:
            Stats dictionary with keys:
            - synced: Number of records successfully synced
            - failed: Number of records that failed to sync
            - skipped: Number of records skipped (currently always 0)
        """
        conn = self._sqlite3.connect(str(self.db_path))
        conn.row_factory = self._sqlite3.Row

        try:
            # Build query for unsynced records
            if retry_failed:
                # Include records that previously failed (have error message)
                query = """
                    SELECT * FROM notices
                    WHERE hubspot_synced = 0
                    ORDER BY fetch_timestamp DESC
                    LIMIT ?
                """
            else:
                # Only new records (never attempted sync)
                query = """
                    SELECT * FROM notices
                    WHERE hubspot_synced = 0
                      AND hubspot_sync_at IS NULL
                    ORDER BY fetch_timestamp DESC
                    LIMIT ?
                """

            rows = conn.execute(query, (batch_size,)).fetchall()

            if not rows:
                logger.info("No pending records to sync")
                return {"synced": 0, "failed": 0, "skipped": 0}

            logger.info(f"Starting HubSpot sync for {len(rows)} records...")

            synced = 0
            failed = 0

            for row in rows:
                record = dict(row)
                record_id = record["id"]

                # Push to HubSpot
                success, hubspot_id, error_msg = self.hubspot.push_record(record)

                if success:
                    # Mark as successfully synced
                    conn.execute(
                        """UPDATE notices SET
                           hubspot_synced = 1,
                           hubspot_id = ?,
                           hubspot_sync_at = datetime('now'),
                           hubspot_sync_error = NULL
                           WHERE id = ?""",
                        (hubspot_id, record_id),
                    )
                    synced += 1
                else:
                    # Record error but don't mark as synced (can retry later)
                    conn.execute(
                        """UPDATE notices SET
                           hubspot_sync_at = datetime('now'),
                           hubspot_sync_error = ?
                           WHERE id = ?""",
                        (error_msg, record_id),
                    )
                    failed += 1

            # Commit all changes
            conn.commit()

            logger.info(
                f"HubSpot sync complete: {synced} synced, {failed} failed"
            )

            return {"synced": synced, "failed": failed, "skipped": 0}

        finally:
            conn.close()
