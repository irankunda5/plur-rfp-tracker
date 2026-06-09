"""Confidence scoring framework for extraction quality assessment.

This module provides confidence metrics for extraction results, used to assess
data quality and determine if extraction is reliable enough to trust.

Currently implements:
- ExtractionConfidence: Quality assessment for extraction results

Future phases will add:
- ConfigGenerationConfidence: For AI-generated configs (Phase 3)
- RepairConfidence: For AI-proposed repairs (Phase 4)
- ConfidenceCalibrator: For calibration tracking
"""

from dataclasses import dataclass, field
from typing import Optional


# =============================================================================
# Extraction Confidence
# =============================================================================

@dataclass
class ExtractionConfidence:
    """
    Confidence metrics for extraction results.

    Used to determine if extraction is reliable enough to trust without review.
    """
    # Component scores (0.0-1.0)
    selector_match_rate: float = 0.0      # % of selectors that found elements
    record_completeness: float = 0.0       # % of records with all required fields
    schema_stability: float = 1.0          # How similar to historical schema
    validation_pass_rate: float = 0.0      # % passing validation rules

    # Factors that lower confidence
    warnings: list[str] = field(default_factory=list)

    # Overall confidence (calculated)
    overall: Optional[float] = None

    def __post_init__(self):
        """Calculate overall confidence if not provided."""
        if self.overall is None:
            self.overall = self._calculate_overall()

    def _calculate_overall(self) -> float:
        """
        Calculate weighted overall confidence.

        Weights:
        - selector_match_rate: 25%
        - record_completeness: 30%
        - schema_stability: 20%
        - validation_pass_rate: 25%
        """
        weights = {
            'selector_match_rate': 0.25,
            'record_completeness': 0.30,
            'schema_stability': 0.20,
            'validation_pass_rate': 0.25
        }

        score = (
            self.selector_match_rate * weights['selector_match_rate'] +
            self.record_completeness * weights['record_completeness'] +
            self.schema_stability * weights['schema_stability'] +
            self.validation_pass_rate * weights['validation_pass_rate']
        )

        # Penalty for warnings (each warning reduces score by 5%)
        penalty = min(len(self.warnings) * 0.05, 0.3)  # Max 30% penalty

        return max(0.0, score - penalty)

    def should_auto_approve(self) -> bool:
        """
        High confidence → auto-approve for production.

        Criteria:
        - Overall >= 0.9
        - Selector match rate >= 0.95
        - Validation pass rate >= 0.95
        """
        return (
            self.overall >= 0.9 and
            self.selector_match_rate >= 0.95 and
            self.validation_pass_rate >= 0.95
        )

    def should_escalate(self) -> bool:
        """
        Low confidence → escalate to developer.

        Criteria:
        - Overall < 0.6
        - Validation pass rate < 0.8
        """
        return self.overall < 0.6 or self.validation_pass_rate < 0.8

    def requires_review(self) -> bool:
        """Medium confidence → requires human review."""
        return not self.should_auto_approve() and not self.should_escalate()

    def to_dict(self) -> dict:
        """Export to dictionary for storage."""
        return {
            'selector_match_rate': self.selector_match_rate,
            'record_completeness': self.record_completeness,
            'schema_stability': self.schema_stability,
            'validation_pass_rate': self.validation_pass_rate,
            'overall': self.overall,
            'warnings': self.warnings,
            'should_auto_approve': self.should_auto_approve(),
            'should_escalate': self.should_escalate(),
            'requires_review': self.requires_review()
        }
