#!/usr/bin/env python3
"""Add HubSpot tracking columns to notices table.

This migration is idempotent and safe to run multiple times.
Adds minimal columns needed for decoupled HubSpot sync:
- hubspot_synced: Boolean flag (0 = pending, 1 = synced)
- hubspot_id: HubSpot record ID (for idempotent upserts)
- hubspot_sync_at: Timestamp of last sync attempt
- hubspot_sync_error: Error message if sync failed

Usage:
    python3 scripts/migrate_hubspot_columns.py
"""

import sqlite3
import sys
from pathlib import Path

# Assume we're in scripts/ directory, DB is in ../data/
DB_PATH = Path(__file__).parent.parent / "data" / "rfp.db"


def check_column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    """Check if a column exists in a table."""
    cursor = conn.execute(f"PRAGMA table_info({table})")
    columns = {row[1] for row in cursor.fetchall()}
    return column in columns


def migrate(db_path: Path) -> None:
    """Run the migration."""
    if not db_path.exists():
        print(f"Error: Database not found at {db_path}")
        sys.exit(1)

    print(f"Connecting to database: {db_path}")
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    try:
        # Check if migration already applied
        if check_column_exists(conn, "notices", "hubspot_synced"):
            print("✓ Migration already applied (hubspot_synced column exists)")
            print("  Skipping migration to avoid duplicate columns")
            return

        print("Adding HubSpot tracking columns to notices table...")

        # Add columns (all nullable/optional to be safe)
        conn.execute("ALTER TABLE notices ADD COLUMN hubspot_synced INTEGER DEFAULT 0")
        conn.execute("ALTER TABLE notices ADD COLUMN hubspot_id TEXT")
        conn.execute("ALTER TABLE notices ADD COLUMN hubspot_sync_at TEXT")
        conn.execute("ALTER TABLE notices ADD COLUMN hubspot_sync_error TEXT")

        # Create index for efficient queries of pending records
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_notices_hubspot_synced
            ON notices(hubspot_synced, fetch_timestamp)
        """)

        conn.commit()

        print("✓ Migration complete!")
        print("\nAdded columns:")
        print("  - hubspot_synced (INTEGER DEFAULT 0)")
        print("  - hubspot_id (TEXT)")
        print("  - hubspot_sync_at (TEXT)")
        print("  - hubspot_sync_error (TEXT)")
        print("\nAdded index:")
        print("  - idx_notices_hubspot_synced ON (hubspot_synced, fetch_timestamp)")

        # Show current record count
        cursor = conn.execute("SELECT COUNT(*) FROM notices")
        count = cursor.fetchone()[0]
        print(f"\n{count} existing records will be marked as pending sync (hubspot_synced=0)")

    except Exception as e:
        print(f"Error during migration: {e}")
        conn.rollback()
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    migrate(DB_PATH)
