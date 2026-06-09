"""Validation layer for the self-maintaining source ingestion platform.

This module provides record validation against SourceConfig rules with confidence scoring.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from lib.source_config import ValidationRules

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Result of record validation."""
    is_valid: bool
    errors: list[str]


class SourceValidator:
    """
    Validates extracted records against SourceConfig validation rules.

    This is a deterministic layer - no AI, just rule enforcement.
    """

    def __init__(self, rules: ValidationRules):
        self.rules = rules

    def validate_record(self, record: dict) -> ValidationResult:
        """
        Validate a single record against rules.

        Args:
            record: Dictionary with field names as keys

        Returns:
            ValidationResult with is_valid flag and error messages
        """
        errors = []

        # Check required fields
        for field in self.rules.required_fields:
            value = record.get(field)
            if not value or (isinstance(value, str) and not value.strip()):
                errors.append(f"Required field missing or empty: {field}")

        # Validate title length (if title present)
        if "title" in record and record["title"]:
            title = record["title"]
            if len(title) < self.rules.min_title_length:
                errors.append(
                    f"Title too short: {len(title)} chars (min: {self.rules.min_title_length})"
                )
            if len(title) > self.rules.max_title_length:
                errors.append(
                    f"Title too long: {len(title)} chars (max: {self.rules.max_title_length})"
                )

        # Validate date format (if closing_date present)
        if "closing_date" in record and record["closing_date"]:
            if self.rules.date_format:
                try:
                    datetime.strptime(record["closing_date"], self.rules.date_format)
                except ValueError as exc:
                    errors.append(
                        f"Invalid date format: '{record['closing_date']}' "
                        f"(expected: {self.rules.date_format}). Error: {exc}"
                    )

        # Validate notice type (if whitelist provided)
        if self.rules.allowed_notice_types and "notice_type" in record:
            notice_type = record.get("notice_type")
            if notice_type and notice_type not in self.rules.allowed_notice_types:
                errors.append(
                    f"Invalid notice_type: '{notice_type}' "
                    f"(allowed: {self.rules.allowed_notice_types})"
                )

        return ValidationResult(is_valid=len(errors) == 0, errors=errors)

    def validate_batch(
        self,
        records: list[dict]
    ) -> tuple[list[dict], list[tuple[dict, ValidationResult]]]:
        """
        Validate multiple records.

        Args:
            records: List of record dictionaries

        Returns:
            Tuple of (valid_records, errors)
            - valid_records: Records that passed validation
            - errors: List of (record, ValidationResult) for failures
        """
        valid_records = []
        errors = []

        for record in records:
            result = self.validate_record(record)
            if result.is_valid:
                valid_records.append(record)
            else:
                errors.append((record, result))

        return valid_records, errors

    def calculate_quality_metrics(self, records: list[dict]) -> dict:
        """
        Calculate data quality metrics for a batch of records.

        Args:
            records: List of record dictionaries

        Returns:
            Dictionary with quality metrics:
            - completeness: % of fields that are non-empty (avg across records)
            - consistency: % of records with consistent field presence
            - uniqueness: % of unique records (by source_id)
        """
        if not records:
            return {
                "completeness": 0.0,
                "consistency": 0.0,
                "uniqueness": 0.0,
                "sample_size": 0
            }

        # Completeness: % of non-empty fields per record (averaged)
        completeness_scores = []
        for record in records:
            non_empty = sum(1 for v in record.values() if v and str(v).strip())
            score = non_empty / len(record) if record else 0.0
            completeness_scores.append(score)
        completeness = sum(completeness_scores) / len(completeness_scores)

        # Check if meets min threshold
        meets_threshold = completeness >= self.rules.min_completeness_rate

        # Consistency: % of records that have the same set of fields
        field_sets = [set(r.keys()) for r in records]
        if field_sets:
            most_common_fields = max(set(map(frozenset, field_sets)), key=field_sets.count)
            consistent_count = sum(1 for fs in field_sets if set(fs) == set(most_common_fields))
            consistency = consistent_count / len(records)
        else:
            consistency = 0.0

        # Uniqueness: % of unique source_ids
        source_ids = [r.get("source_id") for r in records if r.get("source_id")]
        unique_ids = len(set(source_ids))
        uniqueness = unique_ids / len(source_ids) if source_ids else 0.0

        return {
            "completeness": completeness,
            "consistency": consistency,
            "uniqueness": uniqueness,
            "meets_threshold": meets_threshold,
            "sample_size": len(records)
        }


@dataclass
class ValidationConfidence:
    """
    Confidence in validation quality.

    Simpler than ExtractionConfidence - mainly tracks data quality metrics.
    """
    completeness: float         # % of non-empty fields
    consistency: float          # % of records with consistent schema
    uniqueness: float           # % of unique records
    sample_size: int            # Number of records validated

    def __post_init__(self):
        """Calculate overall confidence."""
        self.overall = self._calculate_overall()

    def _calculate_overall(self) -> float:
        """
        Calculate weighted overall confidence.

        Weights:
        - completeness: 40%
        - consistency: 30%
        - uniqueness: 30%
        """
        return (
            self.completeness * 0.40 +
            self.consistency * 0.30 +
            self.uniqueness * 0.30
        )

    def to_dict(self) -> dict:
        """Export to dictionary for storage."""
        return {
            'completeness': self.completeness,
            'consistency': self.consistency,
            'uniqueness': self.uniqueness,
            'sample_size': self.sample_size,
            'overall': self.overall
        }


def validate_records_with_confidence(
    records: list[dict],
    rules: ValidationRules
) -> tuple[list[dict], list[tuple[dict, ValidationResult]], ValidationConfidence]:
    """
    Convenience function to validate records and calculate confidence in one call.

    Args:
        records: List of record dictionaries
        rules: Validation rules from SourceConfig

    Returns:
        Tuple of (valid_records, errors, confidence)
    """
    validator = SourceValidator(rules)

    # Validate
    valid_records, errors = validator.validate_batch(records)

    # Calculate quality metrics
    quality_metrics = validator.calculate_quality_metrics(records)

    # Create confidence score
    confidence = ValidationConfidence(
        completeness=quality_metrics["completeness"],
        consistency=quality_metrics["consistency"],
        uniqueness=quality_metrics["uniqueness"],
        sample_size=quality_metrics["sample_size"]
    )

    return valid_records, errors, confidence
