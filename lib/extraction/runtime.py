"""V2 runtime helper for config-driven extraction.

This module provides the integration layer between run.py and the v2
ScraperEngine. It handles:
- Loading configs from YAML
- Running ScraperEngine
- Classification
- Storage
- Normalizing results to v1 stats format
"""

import logging
from pathlib import Path

from lib.source_config import load_source_config_from_yaml
from lib.extraction.engine import ScraperEngine
from lib.keywords import classify_opportunity
from lib.storage import OpportunityStore

logger = logging.getLogger(__name__)


def run_v2_source(name: str, store: OpportunityStore) -> dict:
    """
    Execute a v2 config-driven source.

    This is the v2 equivalent of run.py's run_scraper() for legacy scrapers.
    It loads the YAML config, runs ScraperEngine, classifies records, stores them,
    and returns stats in the same format as v1 scrapers.

    Args:
        name: Source name (must have configs/{name}.yaml)
        store: OpportunityStore instance

    Returns:
        dict: {"records_found": int, "records_matched": int, "records_new": int}

    Raises:
        FileNotFoundError: If config file doesn't exist
        Exception: If extraction/storage fails
    """
    # 1. Load config
    config_path = Path(__file__).parent.parent.parent / "configs" / f"{name}.yaml"

    if not config_path.exists():
        raise FileNotFoundError(
            f"No config found for v2 source '{name}' at {config_path}. "
            f"V2_SOURCES requires a YAML config in configs/ directory."
        )

    logger.info(f"[v2] Loading config from: {config_path}")
    config = load_source_config_from_yaml(str(config_path))
    logger.info(f"[v2] Loaded config: {config.name} (version {config.version})")

    # 2. Start run tracking
    run_id = store.start_run(config.source_id)
    logger.info(f"[v2] Started run tracking (run_id={run_id})")

    try:
        # 3. Extract + validate via ScraperEngine
        logger.info(f"[v2] Starting extraction for {config.source_id}")
        engine = ScraperEngine()
        result = engine.run(config)

        # 4. Log extraction stats
        logger.info(
            f"[v2] Extraction complete. Stats: {result.stats}. "
            f"Confidence: {result.extraction_confidence.overall:.2f} "
            f"(selector={result.extraction_confidence.selector_match_rate:.2f}, "
            f"completeness={result.extraction_confidence.record_completeness:.2f}, "
            f"validation={result.extraction_confidence.validation_pass_rate:.2f})"
        )

        # Log warnings if any
        if result.extraction_confidence.warnings:
            for warning in result.extraction_confidence.warnings:
                logger.warning(f"[v2] {warning}")

        # 5. Check extraction health
        # Only apply validation pass rate check when records were actually found
        # Empty results (0 records) are normal and should be marked as success
        if result.stats['found'] > 0 and result.extraction_confidence.validation_pass_rate < 0.8:
            logger.error(
                f"[v2] Low validation pass rate: "
                f"{result.extraction_confidence.validation_pass_rate:.1%}. "
                f"Aborting storage."
            )
            # End run tracking with partial failure
            store.end_run(
                run_id=run_id,
                records_found=result.stats['found'],
                records_new=0,
                records_matched=0,
                status="partial_failure",
                error_message=f"Low validation pass rate: {result.extraction_confidence.validation_pass_rate:.1%}"
            )
            # Return stats showing found but no new records
            return {
                "records_found": result.stats['found'],
                "records_matched": 0,
                "records_new": 0
            }

        # 6. Classify records
        logger.info(f"[v2] Classifying {len(result.records)} valid records")
        classified_records = []

        for record in result.records:
            classification = classify_opportunity(
                title=record.get('title', ''),
                description=record.get('description', ''),
                title_only=False
            )

            # Only keep records that match our criteria (tier >= 1)
            if classification['tier'] >= 1:
                classified_records.append({
                    'record': record,
                    'classification': classification
                })

        logger.info(
            f"[v2] Classification complete. "
            f"Matched {len(classified_records)}/{len(result.records)} records (tier >= 1)"
        )

        # 7. Store records
        logger.info(f"[v2] Storing {len(classified_records)} classified records")

        new_count = 0
        duplicate_count = 0
        failed_count = 0

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
                logger.error(
                    f"[v2] Failed to store record: "
                    f"{record.get('title', 'UNKNOWN')[:50]} - {exc}"
                )

        logger.info(
            f"[v2] Storage complete. "
            f"New: {new_count}, Duplicates: {duplicate_count}, Failed: {failed_count}"
        )

        # 8. End run tracking with success or partial_failure
        if failed_count == 0:
            status = "success"
            error_msg = None
        else:
            status = "partial_failure"
            error_msg = f"{failed_count} records failed to store"

        store.end_run(
            run_id=run_id,
            records_found=result.stats['found'],
            records_new=new_count,
            records_matched=len(classified_records) - failed_count,
            status=status,
            error_message=error_msg
        )

        # 9. Return normalized stats (v1 format)
        return {
            "records_found": result.stats['found'],
            "records_matched": len(classified_records) - failed_count,
            "records_new": new_count
        }

    except Exception as exc:
        # End run tracking with failure
        logger.error(f"[v2] Execution failed: {exc}")
        store.end_run(
            run_id=run_id,
            records_found=0,
            records_new=0,
            records_matched=0,
            status="failure",
            error_message=str(exc)[:500]  # Truncate long error messages
        )
        # Re-raise to preserve error handling behavior
        raise
