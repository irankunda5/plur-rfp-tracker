"""Test script for the new extraction pipeline.

This script tests the CanadaBuys CSV extraction using the new config-driven approach.
"""

import logging
import sys
from pathlib import Path

from lib.source_config import load_source_config_from_yaml
from lib.extraction.engine import ScraperEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s"
)

logger = logging.getLogger(__name__)


def test_canadabuys_csv():
    """Test CanadaBuys CSV extraction."""
    print("=" * 80)
    print("Testing CanadaBuys CSV Extraction (Config-Driven)")
    print("=" * 80)

    # Load config
    config_path = Path(__file__).parent / "configs" / "canadabuys_csv.yaml"
    print(f"\n1. Loading config from: {config_path}")

    config = load_source_config_from_yaml(str(config_path))
    print(f"   ✓ Loaded: {config.name} (type: {config.type}, version: {config.version})")

    # Validate config
    print("\n2. Validating config")
    engine = ScraperEngine()
    validation = engine.validate_config(config)

    if not validation["valid"]:
        print(f"   ✗ Config validation failed:")
        for error in validation["errors"]:
            print(f"     - {error}")
        return False

    print(f"   ✓ Config is valid")

    # Test extraction
    print("\n3. Running extraction test (this may take 10-30 seconds...)")

    try:
        result = engine.run(config)

        print(f"\n4. Extraction Results:")
        print(f"   Records found: {result.stats['found']}")
        print(f"   Records valid: {result.stats['valid']}")
        print(f"   Records invalid: {result.stats['invalid']}")
        print(f"   Execution time: {result.execution_time_ms}ms")

        print(f"\n5. Extraction Confidence:")
        confidence = result.extraction_confidence
        print(f"   Overall: {confidence.overall:.2f}")
        print(f"   Selector match rate: {confidence.selector_match_rate:.2f}")
        print(f"   Record completeness: {confidence.record_completeness:.2f}")
        print(f"   Schema stability: {confidence.schema_stability:.2f}")
        print(f"   Validation pass rate: {confidence.validation_pass_rate:.2f}")

        if confidence.warnings:
            print(f"\n   Warnings:")
            for warning in confidence.warnings:
                print(f"     - {warning}")

        print(f"\n6. Decision:")
        if confidence.should_auto_approve():
            print(f"   ✓ HIGH CONFIDENCE - Auto-approve for production")
        elif confidence.should_escalate():
            print(f"   ✗ LOW CONFIDENCE - Escalate to developer")
        else:
            print(f"   ⚠ MEDIUM CONFIDENCE - Requires human review")

        # Show sample records
        if result.records:
            print(f"\n7. Sample Records (first 3):")
            for i, record in enumerate(result.records[:3], 1):
                print(f"\n   Record {i}:")
                print(f"     Title: {record.get('title', 'N/A')[:80]}")
                print(f"     Buyer: {record.get('buyer', 'N/A')[:60]}")
                print(f"     Closing: {record.get('closing_date', 'N/A')}")
                print(f"     URL: {record.get('url', 'N/A')[:80]}")

        # Show validation errors (if any)
        if result.validation_errors:
            print(f"\n8. Validation Errors (first 5):")
            for i, (record, validation_result) in enumerate(result.validation_errors[:5], 1):
                print(f"\n   Error {i}:")
                print(f"     Record: {record.get('title', 'N/A')[:60]}")
                print(f"     Issues:")
                for error in validation_result.errors:
                    print(f"       - {error}")

        print("\n" + "=" * 80)
        print("✓ TEST PASSED")
        print("=" * 80)

        return True

    except Exception as exc:
        print(f"\n✗ Extraction failed: {exc}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = test_canadabuys_csv()
    sys.exit(0 if success else 1)
