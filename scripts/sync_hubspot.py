#!/usr/bin/env python3
"""Manually trigger HubSpot sync for pending records.

This script allows manual syncing of RFP records to HubSpot Signals object, useful for:
- Testing HubSpot integration
- Retrying failed syncs
- Backfilling historical data

Usage:
    # Sync up to 100 pending records
    python3 scripts/sync_hubspot.py

    # Sync up to 500 records
    python3 scripts/sync_hubspot.py --batch-size 500

    # Retry previously failed records
    python3 scripts/sync_hubspot.py --retry-failed

    # Dry run (show what would be synced without actually syncing)
    python3 scripts/sync_hubspot.py --dry-run

Environment variables required:
    HUBSPOT_API_KEY - HubSpot API key (Bearer token)
    HUBSPOT_OBJECT_TYPE_ID - HubSpot Signals object type ID (e.g., "2-229341360")
"""

import argparse
import logging
import os
import sqlite3
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.output.hubspot import HubSpotClient, HubSpotSync

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent.parent / "data" / "rfp.db"


def check_env_vars() -> tuple[str, str] | None:
    """Check if required environment variables are set.

    Returns:
        Tuple of (api_key, object_type_id) if both are set, None otherwise
    """
    api_key = os.environ.get("HUBSPOT_API_KEY")
    object_type_id = os.environ.get("HUBSPOT_OBJECT_TYPE_ID")

    if not api_key:
        logger.error("HUBSPOT_API_KEY environment variable not set")
        return None

    if not object_type_id:
        logger.error("HUBSPOT_OBJECT_TYPE_ID environment variable not set")
        return None

    return (api_key, object_type_id)


def show_pending_stats(db_path: Path):
    """Show statistics about pending records."""
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    # Total records
    total = cursor.execute("SELECT COUNT(*) FROM notices").fetchone()[0]

    # Pending sync
    pending = cursor.execute(
        "SELECT COUNT(*) FROM notices WHERE hubspot_synced = 0"
    ).fetchone()[0]

    # Previously synced
    synced = cursor.execute(
        "SELECT COUNT(*) FROM notices WHERE hubspot_synced = 1"
    ).fetchone()[0]

    # Failed syncs
    failed = cursor.execute(
        "SELECT COUNT(*) FROM notices WHERE hubspot_sync_error IS NOT NULL"
    ).fetchone()[0]

    conn.close()

    logger.info(f"Database statistics:")
    logger.info(f"  Total records: {total}")
    logger.info(f"  Synced to HubSpot: {synced}")
    logger.info(f"  Pending sync: {pending}")
    logger.info(f"  Failed syncs: {failed}")

    return {"total": total, "pending": pending, "synced": synced, "failed": failed}


def show_sample_records(db_path: Path, limit: int = 5):
    """Show sample pending records that would be synced."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    rows = conn.execute(
        """SELECT id, source, title, buyer, closing_date
           FROM notices
           WHERE hubspot_synced = 0
           ORDER BY fetch_timestamp DESC
           LIMIT ?""",
        (limit,),
    ).fetchall()

    if not rows:
        logger.info("No pending records to sync")
        return

    logger.info(f"\nSample pending records (showing {len(rows)}):")
    for row in rows:
        logger.info(
            f"  [{row['id']}] {row['source']}: {row['title'][:60]}... | {row['buyer']}"
        )

    conn.close()


def main():
    parser = argparse.ArgumentParser(
        description="Manually trigger HubSpot sync for pending RFP records"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Maximum number of records to sync (default: 100)",
    )
    parser.add_argument(
        "--retry-failed",
        action="store_true",
        help="Retry previously failed records",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be synced without actually syncing",
    )
    parser.add_argument(
        "--show-stats",
        action="store_true",
        help="Show sync statistics and exit",
    )
    args = parser.parse_args()

    # Check database exists
    if not DB_PATH.exists():
        logger.error(f"Database not found: {DB_PATH}")
        return 1

    # Show stats if requested
    if args.show_stats:
        show_pending_stats(DB_PATH)
        return 0

    # Show pending stats
    stats = show_pending_stats(DB_PATH)

    if stats["pending"] == 0:
        logger.info("No pending records to sync")
        return 0

    # Show sample records
    show_sample_records(DB_PATH, limit=5)

    # Dry run: exit before syncing
    if args.dry_run:
        logger.info(f"\nDry run: would sync up to {args.batch_size} records")
        return 0

    # Check environment variables
    env_vars = check_env_vars()
    if not env_vars:
        logger.error("Required environment variables not set")
        return 1

    api_key, object_type_id = env_vars

    # Confirm with user
    logger.info(f"\nReady to sync up to {args.batch_size} records to HubSpot Signals")
    logger.info(f"Object Type ID: {object_type_id}")
    logger.info(f"Retry failed: {args.retry_failed}")

    response = input("\nProceed with sync? [y/N]: ")
    if response.lower() != "y":
        logger.info("Sync cancelled")
        return 0

    # Run sync
    logger.info("\nStarting HubSpot sync...")

    try:
        with HubSpotClient(api_key=api_key, object_type_id=object_type_id) as client:
            syncer = HubSpotSync(db_path=DB_PATH, hubspot_client=client)
            sync_stats = syncer.sync_pending(
                batch_size=args.batch_size,
                retry_failed=args.retry_failed,
            )

        logger.info("\n" + "=" * 60)
        logger.info("Sync complete!")
        logger.info(f"  Successfully synced: {sync_stats['synced']}")
        logger.info(f"  Failed: {sync_stats['failed']}")
        logger.info("=" * 60)

        if sync_stats["failed"] > 0:
            logger.warning(
                f"\n{sync_stats['failed']} records failed to sync. "
                "Check logs for details or run with --retry-failed to retry."
            )

        return 0

    except Exception as e:
        logger.error(f"Sync failed: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
