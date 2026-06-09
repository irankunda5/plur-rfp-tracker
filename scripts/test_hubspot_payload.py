#!/usr/bin/env python3
"""Test HubSpot Signals payload structure using httpbin.org echo endpoint.

This script:
1. Reads a few records from the database
2. Formats them as HubSpot Signals payloads
3. Sends to httpbin.org/post (which echoes back the payload)
4. Displays the formatted payload for verification

Usage:
    python3 scripts/test_hubspot_payload.py
"""

import json
import sqlite3
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.output.hubspot import HubSpotClient

DB_PATH = Path(__file__).parent.parent / "data" / "rfp.db"


def main():
    print("Testing HubSpot Signals payload structure\n" + "=" * 80)

    # Connect to database
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    # Get a few sample records with classification
    rows = conn.execute(
        """SELECT * FROM notices
           WHERE json_extract(classification_json, '$.tier') IS NOT NULL
           LIMIT 3"""
    ).fetchall()

    if not rows:
        print("No records with classification in database")
        return

    # Create mock HubSpot client
    # NOTE: Using httpbin.org instead of real HubSpot for testing
    # This bypasses the real endpoint construction in __init__
    client = HubSpotClient(
        api_key="test_key_12345",
        object_type_id="test-object-type",
    )
    # Override endpoint for testing
    client.endpoint = "https://httpbin.org/post"

    print(f"\nTesting {len(rows)} sample records...\n")

    for row in rows:
        record = dict(row)
        print(f"Record {record['id']}: {record['title'][:60]}...")
        print(f"  Source: {record['source']}")
        print(f"  Buyer: {record.get('buyer', 'N/A')}")
        print(f"  Classification: {record.get('classification_json', '{}')[:100]}...")

        # Build Signals properties
        signal_properties = client._build_signal_properties(record)

        print("\nSignals Properties:")
        print(json.dumps(signal_properties, indent=2))

        # Build full CRM v3 payload
        full_payload = {"properties": signal_properties}
        print("\nFull CRM v3 Payload:")
        print(json.dumps(full_payload, indent=2))

        # Test actual POST (httpbin.org will echo back the request)
        print("\nSending to httpbin.org...")
        success, hubspot_id, error = client.push_record(record)

        if success:
            print(f"✓ Success (mock HubSpot ID: {hubspot_id})")
        else:
            print(f"✗ Failed: {error}")

        print("\n" + "=" * 80 + "\n")

    client.close()
    conn.close()

    print("Test complete. Signals payload structure looks good!")
    print("\nWhen you get real HubSpot credentials:")
    print("1. Set environment variables:")
    print("   export HUBSPOT_API_KEY='your_api_key'")
    print("   export HUBSPOT_OBJECT_TYPE_ID='2-229341360'")
    print("2. Test sync: python3 scripts/sync_hubspot.py --batch-size 5")
    print("3. Verify records appear in HubSpot Signals")
    print("4. Run full scraper: python3 run.py --once")


if __name__ == "__main__":
    main()
