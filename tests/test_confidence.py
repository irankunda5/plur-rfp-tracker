"""Unit tests for extraction confidence scoring."""

import pytest

from lib.confidence import ExtractionConfidence


class TestExtractionConfidence:
    """Test ExtractionConfidence class."""

    def test_confidence_calculation(self):
        """Test overall confidence calculation."""
        confidence = ExtractionConfidence(
            selector_match_rate=0.9,
            record_completeness=0.85,
            schema_stability=1.0,
            validation_pass_rate=0.95
        )

        # Overall = 0.9*0.25 + 0.85*0.30 + 1.0*0.20 + 0.95*0.25
        #         = 0.225 + 0.255 + 0.20 + 0.2375 = 0.9175
        assert 0.91 <= confidence.overall <= 0.92

    def test_confidence_with_warnings(self):
        """Test confidence calculation with warning penalties."""
        confidence = ExtractionConfidence(
            selector_match_rate=1.0,
            record_completeness=1.0,
            schema_stability=1.0,
            validation_pass_rate=1.0,
            warnings=["Warning 1", "Warning 2"]  # 2 warnings = 10% penalty
        )

        # Base score would be 1.0, but 2 warnings reduce by 10%
        assert 0.89 <= confidence.overall <= 0.91

    def test_should_auto_approve(self):
        """Test auto-approval logic."""
        # High confidence - should auto-approve
        confidence = ExtractionConfidence(
            selector_match_rate=0.96,
            record_completeness=0.9,
            schema_stability=1.0,
            validation_pass_rate=0.96
        )
        assert confidence.should_auto_approve() is True

        # Low selector match - should not auto-approve
        confidence = ExtractionConfidence(
            selector_match_rate=0.90,  # Below 0.95 threshold
            record_completeness=0.9,
            schema_stability=1.0,
            validation_pass_rate=0.96
        )
        assert confidence.should_auto_approve() is False

        # Low validation pass rate - should not auto-approve
        confidence = ExtractionConfidence(
            selector_match_rate=0.96,
            record_completeness=0.9,
            schema_stability=1.0,
            validation_pass_rate=0.90  # Below 0.95 threshold
        )
        assert confidence.should_auto_approve() is False

    def test_should_escalate(self):
        """Test escalation logic."""
        # Very low confidence - should escalate
        confidence = ExtractionConfidence(
            selector_match_rate=0.5,
            record_completeness=0.4,
            schema_stability=0.6,
            validation_pass_rate=0.5
        )
        assert confidence.should_escalate() is True

        # Low validation pass rate - should escalate
        confidence = ExtractionConfidence(
            selector_match_rate=0.9,
            record_completeness=0.9,
            schema_stability=1.0,
            validation_pass_rate=0.75  # Below 0.8 threshold
        )
        assert confidence.should_escalate() is True

        # Medium confidence - should not escalate
        confidence = ExtractionConfidence(
            selector_match_rate=0.85,
            record_completeness=0.8,
            schema_stability=0.9,
            validation_pass_rate=0.85
        )
        assert confidence.should_escalate() is False

    def test_requires_review(self):
        """Test review requirement logic."""
        # Medium confidence - requires review
        confidence = ExtractionConfidence(
            selector_match_rate=0.85,
            record_completeness=0.8,
            schema_stability=0.9,
            validation_pass_rate=0.85
        )
        assert confidence.requires_review() is True
        assert confidence.should_auto_approve() is False
        assert confidence.should_escalate() is False

    def test_to_dict(self):
        """Test dictionary export."""
        confidence = ExtractionConfidence(
            selector_match_rate=0.9,
            record_completeness=0.85,
            schema_stability=1.0,
            validation_pass_rate=0.95,
            warnings=["Test warning"]
        )

        data = confidence.to_dict()

        assert "selector_match_rate" in data
        assert "record_completeness" in data
        assert "overall" in data
        assert "should_auto_approve" in data
        assert "should_escalate" in data
        assert "requires_review" in data
        assert data["warnings"] == ["Test warning"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
