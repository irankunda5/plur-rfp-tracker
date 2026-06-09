#!/usr/bin/env python3
"""
CanadaBuys CSV Extraction - Vertical Slice Integration Script

This script demonstrates the complete end-to-end pipeline:
    1. Load CanadaBuys CSV config (declarative)
    2. Extract records using ScraperEngine
    3. Validate records (deterministic rules)
    4. Classify records using existing keyword system
    5. Store classified records in database
    6. (TODO) Sync to HubSpot
    7. Report run statistics

This is the minimal vertical slice that proves the config-driven architecture works.
"""

import argparse
import json
import logging
import sys
from pathlib import Path

# Add parent directory to path for lib imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.source_config import load_source_config_from_yaml
from lib.extraction.engine import ScraperEngine
from lib.keywords import classify_opportunity
from lib.storage import OpportunityStore

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)


def main():
    """Main entry point for CanadaBuys CSV extraction."""
    parser = argparse.ArgumentParser(
        description="Run CanadaBuys CSV extraction end-to-end"
    )
    parser.add_argument(
        "--config",
        type=str,
        default="configs/canadabuys_csv.yaml",
        help="Path to CanadaBuys CSV config file (default: configs/canadabuys_csv.yaml)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Extract and classify but don't store to database"
    )
    parser.add_argument(
        "--min-tier",
        type=int,
        default=1,
        help="Minimum classification tier to store (default: 1, set to 0 to store all)"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show detailed extraction results"
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    print("=" * 80)
    print("CanadaBuys CSV Extraction - Vertical Slice")
    print("=" * 80)
    print()

    # Step 1: Load config
    logger.info(f"Loading config from: {args.config}")
    config_path = Path(args.config)
    if not config_path.exists():
        logger.error(f"Config file not found: {config_path}")
        return 1

    try:
        config = load_source_config_from_yaml(str(config_path))
        logger.info(f"✓ Loaded config: {config.name} (version {config.version})")
    except Exception as exc:
        logger.error(f"Failed to load config: {exc}")
        return 1

    # Step 2: Extract + validate
    logger.info("Starting extraction...")
    engine = ScraperEngine()

    try:
        result = engine.run(config)
    except Exception as exc:
        logger.error(f"Extraction failed: {exc}")
        import traceback
        traceback.print_exc()
        return 1

    # Step 3: Check extraction health
    logger.info(f"Extraction complete. Stats: {result.stats}")
    logger.info(
        f"Extraction confidence: {result.extraction_confidence.overall:.2f} "
        f"(selector_match={result.extraction_confidence.selector_match_rate:.2f}, "
        f"completeness={result.extraction_confidence.record_completeness:.2f}, "
        f"validation_pass={result.extraction_confidence.validation_pass_rate:.2f})"
    )

    if result.extraction_confidence.warnings:
        logger.warning("Extraction warnings:")
        for warning in result.extraction_confidence.warnings:
            logger.warning(f"  - {warning}")

    # Check health using simplified confidence assessment
    if result.extraction_confidence.validation_pass_rate < 0.8:
        logger.error(
            f"⚠ Unhealthy extraction: validation pass rate too low "
            f"({result.extraction_confidence.validation_pass_rate:.1%})"
        )
        logger.error("Aborting - extraction quality below threshold")
        return 1

    if result.extraction_confidence.selector_match_rate < 0.9:
        logger.warning(
            f"⚠ Low selector match rate: {result.extraction_confidence.selector_match_rate:.1%}"
        )

    if result.stats['found'] == 0:
        logger.error("⚠ No records extracted. Check URL or config.")
        return 1

    logger.info(f"✓ Extraction healthy (quality checks passed)")

    # Step 4: Classify records
    logger.info(f"Classifying {len(result.records)} valid records...")
    classified_records = []

    for record in result.records:
        # Classify using existing keyword system
        classification = classify_opportunity(
            title=record.get('title', ''),
            description=record.get('description', ''),
            title_only=False
        )

        # Only keep records that match our criteria (tier >= min_tier)
        if classification['tier'] >= args.min_tier:
            classified_records.append({
                'record': record,
                'classification': classification
            })

    logger.info(
        f"✓ Classification complete. "
        f"Matched {len(classified_records)}/{len(result.records)} records "
        f"(tier >= {args.min_tier})"
    )

    # Print tier breakdown
    tier_counts = {}
    for item in classified_records:
        tier = item['classification']['tier']
        tier_counts[tier] = tier_counts.get(tier, 0) + 1

    if tier_counts:
        logger.info("Tier breakdown:")
        for tier in sorted(tier_counts.keys()):
            tier_label = {1: "Cyber", 2: "IAM/Identity", 3: "Broader IT"}.get(tier, f"Tier {tier}")
            logger.info(f"  Tier {tier} ({tier_label}): {tier_counts[tier]} records")

    # Step 5: Store records (unless dry-run)
    if args.dry_run:
        logger.info("--dry-run mode: skipping database storage")
        print()
        print("=" * 80)
        print("DRY RUN COMPLETE")
        print("=" * 80)
        print_sample_records(classified_records[:5])
        return 0

    logger.info(f"Storing {len(classified_records)} classified records to database...")

    new_count = 0
    duplicate_count = 0
    failed_count = 0

    with OpportunityStore() as store:
        # Start run tracking
        run_id = store.start_run(config.source_id)
        logger.info(f"Started run tracking (run_id={run_id})")

        try:
            # Store all classified records
            for item in classified_records:
                record = item['record']
                classification = item['classification']

                try:
                    is_new, notice_id = store.add_notice(
                        source=config.source_id,
                        source_id=record.get('source_id', ''),
                        title=record.get('title', ''),
                        description=record.get('description', ''),
                        buyer=record.get('buyer', ''),
                        closing_date=record.get('closing_date'),
                        url=record.get('url', ''),
                        notice_type=record.get('notice_type', ''),
                        product_type=classification.get('product_type', ''),
                        vendor_flags=classification.get('vendor_flags', []),
                        classification=classification,
                        raw_json=record
                    )

                    if is_new:
                        new_count += 1
                    else:
                        duplicate_count += 1

                except Exception as exc:
                    failed_count += 1
                    logger.error(f"Failed to store record: {record.get('title', 'UNKNOWN')[:50]}")
                    logger.error(f"  Error: {exc}")

        finally:
            # Always end run tracking, even on exception
            # Determine status based on failures
            if failed_count == 0:
                status = "success"
            elif failed_count < len(classified_records):
                status = "partial_failure"
                logger.warning(
                    f"Partial failure: {failed_count}/{len(classified_records)} records failed to store"
                )
            else:
                status = "failure"
                logger.error("All records failed to store")

            store.end_run(
                run_id=run_id,
                records_found=result.stats['found'],
                records_new=new_count,
                records_matched=len(classified_records) - failed_count,
                status=status,
                error_message=f"{failed_count} records failed to store" if failed_count > 0 else None
            )

            logger.info(
                f"✓ Storage complete. "
                f"New: {new_count}, Duplicates: {duplicate_count}, Failed: {failed_count}"
            )

    # Step 6: HubSpot sync (TODO)
    # TODO: Implement HubSpot sync when lib/hubspot.py is available
    # For now, just log that this step is skipped
    logger.info("⚠ HubSpot sync not yet implemented (lib/hubspot.py missing)")

    # Step 7: Print summary
    print()
    print("=" * 80)
    if failed_count == 0:
        print("✓ EXTRACTION COMPLETE")
    elif failed_count < len(classified_records):
        print("⚠ EXTRACTION COMPLETE (WITH PARTIAL FAILURES)")
    else:
        print("✗ EXTRACTION FAILED")
    print("=" * 80)
    print()
    print(f"Source:              {config.name}")
    print(f"Records extracted:   {result.stats['found']}")
    print(f"Records valid:       {result.stats['valid']}")
    print(f"Records classified:  {len(classified_records)} (tier >= {args.min_tier})")
    print(f"New opportunities:   {new_count}")
    print(f"Duplicates:          {duplicate_count}")
    if failed_count > 0:
        print(f"Failed to store:     {failed_count}")
    print(f"Execution time:      {result.execution_time_ms}ms")
    print()
    print(f"Confidence:          {result.extraction_confidence.overall:.2f}")
    print(f"  Selector match:    {result.extraction_confidence.selector_match_rate:.2f}")
    print(f"  Completeness:      {result.extraction_confidence.record_completeness:.2f}")
    print(f"  Validation pass:   {result.extraction_confidence.validation_pass_rate:.2f}")
    print()

    # Show sample records if verbose
    if args.verbose and classified_records:
        print_sample_records(classified_records[:5])

    # Return error code if all records failed
    return 1 if failed_count == len(classified_records) else 0


def print_sample_records(classified_records: list[dict]) -> None:
    """Print sample classified records."""
    if not classified_records:
        return

    print("Sample Records:")
    print("-" * 80)
    for i, item in enumerate(classified_records, 1):
        record = item['record']
        classification = item['classification']

        tier_label = {1: "Cyber", 2: "IAM/Identity", 3: "Broader IT"}.get(
            classification['tier'], f"Tier {classification['tier']}"
        )

        print(f"\n{i}. {record.get('title', 'NO TITLE')[:70]}")
        print(f"   Buyer:        {record.get('buyer', 'N/A')[:60]}")
        print(f"   Closing:      {record.get('closing_date', 'N/A')}")
        print(f"   URL:          {record.get('url', 'N/A')[:70]}")
        print(f"   Tier:         {classification['tier']} ({tier_label})")
        print(f"   Confidence:   {classification['confidence']:.2f}")
        print(f"   Keywords:     {', '.join(classification['matched_keywords'][:5])}")
        if classification.get('vendor_flags'):
            print(f"   Vendor flags: {', '.join(classification['vendor_flags'])}")

    print()


if __name__ == "__main__":
    sys.exit(main())
