"""Scraper Engine orchestrator for the self-maintaining source ingestion platform.

This is the main entry point for executing SourceConfigs. It selects the appropriate
extractor, runs extraction + validation, and returns results with confidence scores.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from lib.source_config import SourceConfig, SourceType
from lib.extraction.csv_extractor import CSVExtractor
from lib.extraction.json_extractor import JSONExtractor
from lib.extraction.html_extractor import HTMLExtractor
from lib.extraction.validator import SourceValidator, ValidationResult, validate_records_with_confidence
from lib.confidence import ExtractionConfidence

logger = logging.getLogger(__name__)


@dataclass
class RunResult:
    """Result of scraper execution."""
    # Records
    records: list[dict]                # Valid records (passed validation)
    raw_records: list[dict]            # All extracted records (before validation)

    # Stats
    stats: dict                        # {"found": int, "valid": int, "invalid": int}

    # Errors
    validation_errors: list[tuple[dict, ValidationResult]]  # Records that failed validation

    # Confidence scores
    extraction_confidence: ExtractionConfidence
    validation_confidence: Optional[dict] = None

    # Metadata
    source_id: str = ""
    execution_time_ms: int = 0
    timestamp: Optional[str] = None


class ScraperEngine:
    """
    Generic scraper engine that executes SourceConfigs without custom code.

    This is the core of the self-maintaining platform:
    - Selects appropriate extractor based on source type
    - Runs extraction
    - Validates records
    - Returns results with confidence scores

    Adding a new source = creating a SourceConfig, not writing Python code.
    """

    def __init__(self):
        """Initialize scraper engine with available extractors."""
        self.extractors = {}
        self._register_extractors()

    def _register_extractors(self):
        """Register available extraction engines."""
        self.extractors[SourceType.CSV] = CSVExtractor
        self.extractors[SourceType.JSON_API] = JSONExtractor
        self.extractors[SourceType.HTML] = HTMLExtractor
        # Future extractors will be registered here:
        # self.extractors[SourceType.RSS] = RSSExtractor
        # self.extractors[SourceType.XML] = XMLExtractor

    def run(self, config: SourceConfig) -> RunResult:
        """
        Execute extraction for a source config.

        This is the main entry point. It:
        1. Selects appropriate extractor based on config.type
        2. Extracts records
        3. Validates records
        4. Returns results + stats + errors + confidence scores

        Args:
            config: SourceConfig defining the source

        Returns:
            RunResult with records, stats, errors, and confidence

        Raises:
            ValueError: If source type not supported or config invalid
            httpx.HTTPError: If source fetch fails
        """
        start_time = datetime.now()
        logger.info(f"[{config.source_id}] Starting extraction (type: {config.type})")

        # 1. Select extractor
        if config.type not in self.extractors:
            available = list(self.extractors.keys())
            raise ValueError(
                f"No extractor for source type '{config.type}'. "
                f"Available: {available}"
            )

        extractor_class = self.extractors[config.type]

        # 2. Extract records
        try:
            with extractor_class() as extractor:
                raw_records, extraction_confidence = extractor.extract(config)

            logger.info(
                f"[{config.source_id}] Extracted {len(raw_records)} records. "
                f"Extraction confidence: {extraction_confidence.overall:.2f}"
            )

        except Exception as exc:
            logger.error(f"[{config.source_id}] Extraction failed: {exc}")
            # Return empty result with error
            return RunResult(
                records=[],
                raw_records=[],
                stats={"found": 0, "valid": 0, "invalid": 0},
                validation_errors=[],
                extraction_confidence=ExtractionConfidence(
                    selector_match_rate=0.0,
                    record_completeness=0.0,
                    schema_stability=0.0,
                    validation_pass_rate=0.0,
                    warnings=[f"Extraction failed: {str(exc)}"]
                ),
                source_id=config.source_id,
                execution_time_ms=0,
                timestamp=datetime.now().isoformat()
            )

        # 3. Validate records
        valid_records, validation_errors, validation_confidence = validate_records_with_confidence(
            records=raw_records,
            rules=config.validation
        )

        logger.info(
            f"[{config.source_id}] Validation complete. "
            f"Valid: {len(valid_records)}, Invalid: {len(validation_errors)}"
        )

        # Update extraction confidence with validation pass rate
        extraction_confidence.validation_pass_rate = (
            len(valid_records) / len(raw_records) if raw_records else 0.0
        )
        # Recalculate overall confidence with new validation pass rate
        extraction_confidence.overall = extraction_confidence._calculate_overall()

        # 4. Build stats
        stats = {
            "found": len(raw_records),
            "valid": len(valid_records),
            "invalid": len(validation_errors)
        }

        # Calculate execution time
        execution_time_ms = int((datetime.now() - start_time).total_seconds() * 1000)

        logger.info(
            f"[{config.source_id}] Execution complete in {execution_time_ms}ms. "
            f"Stats: {stats}"
        )

        # 5. Return result
        return RunResult(
            records=valid_records,
            raw_records=raw_records,
            stats=stats,
            validation_errors=validation_errors,
            extraction_confidence=extraction_confidence,
            validation_confidence=validation_confidence.to_dict(),
            source_id=config.source_id,
            execution_time_ms=execution_time_ms,
            timestamp=datetime.now().isoformat()
        )

    def test_config(self, config: SourceConfig) -> dict:
        """
        Test a SourceConfig without storing results.

        This is used for config validation and testing new sources.

        Args:
            config: SourceConfig to test

        Returns:
            Dictionary with test results:
            - success: bool
            - stats: dict
            - sample_records: list (first 5 valid records)
            - errors: list (validation errors)
            - confidence: dict (extraction + validation confidence)
        """
        try:
            result = self.run(config)

            return {
                "success": True,
                "stats": result.stats,
                "sample_records": result.records[:5],
                "validation_errors": [
                    {
                        "record": record,
                        "errors": validation_result.errors
                    }
                    for record, validation_result in result.validation_errors[:10]
                ],
                "extraction_confidence": result.extraction_confidence.to_dict(),
                "validation_confidence": result.validation_confidence,
                "execution_time_ms": result.execution_time_ms
            }

        except Exception as exc:
            logger.error(f"[{config.source_id}] Test failed: {exc}")
            return {
                "success": False,
                "error": str(exc),
                "stats": {"found": 0, "valid": 0, "invalid": 0}
            }

    def validate_config(self, config: SourceConfig) -> dict:
        """
        Validate a SourceConfig without running extraction.

        This checks:
        - Config schema is valid
        - Required fields present
        - Source type is supported
        - Extraction config is valid for the source type

        Args:
            config: SourceConfig to validate

        Returns:
            Dictionary with validation results:
            - valid: bool
            - errors: list[str]
        """
        errors = []

        # Check source type supported
        if config.type not in self.extractors:
            errors.append(
                f"Source type '{config.type}' not supported. "
                f"Available: {list(self.extractors.keys())}"
            )

        # Check required fields
        if not config.url:
            errors.append("URL is required")

        if not config.source_id:
            errors.append("source_id is required")

        # Check extraction config is present
        if not config.extraction:
            errors.append("extraction config is required")

        # Try to parse type-specific extraction config
        try:
            config.get_extraction_config()
        except Exception as exc:
            errors.append(f"Invalid extraction config: {exc}")

        return {
            "valid": len(errors) == 0,
            "errors": errors
        }
