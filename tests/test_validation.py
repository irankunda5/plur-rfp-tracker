"""Unit tests for the validation layer."""

import pytest
from datetime import datetime

from lib.extraction.validator import (
    SourceValidator,
    ValidationResult,
    ValidationConfidence,
    validate_records_with_confidence
)
from lib.source_config import ValidationRules


class TestSourceValidator:
    """Test SourceValidator class."""

    def test_validate_record_with_required_fields(self):
        """Test validation of required fields."""
        rules = ValidationRules(required_fields=["title", "source_id"])
        validator = SourceValidator(rules)

        # Valid record
        record = {"title": "Test Title", "source_id": "123", "description": "Test"}
        result = validator.validate_record(record)
        assert result.is_valid is True
        assert len(result.errors) == 0

        # Missing required field
        record = {"title": "Test Title"}
        result = validator.validate_record(record)
        assert result.is_valid is False
        assert any("source_id" in error for error in result.errors)

        # Empty required field
        record = {"title": "", "source_id": "123"}
        result = validator.validate_record(record)
        assert result.is_valid is False
        assert any("title" in error for error in result.errors)

    def test_validate_record_with_title_length(self):
        """Test validation of title length constraints."""
        rules = ValidationRules(
            required_fields=["title"],
            min_title_length=10,
            max_title_length=50
        )
        validator = SourceValidator(rules)

        # Title too short
        record = {"title": "Short"}
        result = validator.validate_record(record)
        assert result.is_valid is False
        assert any("too short" in error.lower() for error in result.errors)

        # Title too long
        record = {"title": "A" * 100}
        result = validator.validate_record(record)
        assert result.is_valid is False
        assert any("too long" in error.lower() for error in result.errors)

        # Valid title
        record = {"title": "This is a valid title length"}
        result = validator.validate_record(record)
        assert result.is_valid is True

    def test_validate_record_with_date_format(self):
        """Test validation of date format."""
        rules = ValidationRules(
            required_fields=["closing_date"],
            date_format="%Y-%m-%d"
        )
        validator = SourceValidator(rules)

        # Valid date
        record = {"closing_date": "2026-12-31"}
        result = validator.validate_record(record)
        assert result.is_valid is True

        # Invalid date format
        record = {"closing_date": "12/31/2026"}
        result = validator.validate_record(record)
        assert result.is_valid is False
        assert any("date format" in error.lower() for error in result.errors)

        # Invalid date value
        record = {"closing_date": "2026-13-45"}
        result = validator.validate_record(record)
        assert result.is_valid is False

    def test_validate_record_with_notice_types(self):
        """Test validation of notice type whitelist."""
        rules = ValidationRules(
            required_fields=[],
            allowed_notice_types=["Open Call", "Amendment", "Award"]
        )
        validator = SourceValidator(rules)

        # Valid notice type
        record = {"notice_type": "Open Call"}
        result = validator.validate_record(record)
        assert result.is_valid is True

        # Invalid notice type
        record = {"notice_type": "Unknown Type"}
        result = validator.validate_record(record)
        assert result.is_valid is False
        assert any("notice_type" in error.lower() for error in result.errors)

    def test_validate_batch(self):
        """Test batch validation."""
        rules = ValidationRules(required_fields=["title", "source_id"])
        validator = SourceValidator(rules)

        records = [
            {"title": "Valid 1", "source_id": "1"},
            {"title": "Valid 2", "source_id": "2"},
            {"title": "", "source_id": "3"},  # Invalid: empty title
            {"title": "Valid 4"},  # Invalid: missing source_id
            {"title": "Valid 5", "source_id": "5"},
        ]

        valid_records, errors = validator.validate_batch(records)

        assert len(valid_records) == 3
        assert len(errors) == 2
        assert valid_records[0]["source_id"] == "1"
        assert valid_records[1]["source_id"] == "2"
        assert valid_records[2]["source_id"] == "5"

    def test_calculate_quality_metrics(self):
        """Test quality metrics calculation."""
        rules = ValidationRules(min_completeness_rate=0.8)
        validator = SourceValidator(rules)

        records = [
            {"title": "Test 1", "buyer": "Buyer 1", "description": "Desc 1", "source_id": "1"},
            {"title": "Test 2", "buyer": "Buyer 2", "description": "Desc 2", "source_id": "2"},
            {"title": "Test 3", "buyer": "", "description": "Desc 3", "source_id": "3"},
        ]

        metrics = validator.calculate_quality_metrics(records)

        assert "completeness" in metrics
        assert "consistency" in metrics
        assert "uniqueness" in metrics
        assert "sample_size" in metrics
        assert metrics["sample_size"] == 3
        assert 0.0 <= metrics["completeness"] <= 1.0
        assert 0.0 <= metrics["consistency"] <= 1.0
        assert 0.0 <= metrics["uniqueness"] <= 1.0


class TestValidationConfidence:
    """Test ValidationConfidence class."""

    def test_confidence_calculation(self):
        """Test overall confidence calculation."""
        confidence = ValidationConfidence(
            completeness=0.9,
            consistency=0.8,
            uniqueness=1.0,
            sample_size=100
        )

        # Overall = 0.9*0.4 + 0.8*0.3 + 1.0*0.3 = 0.36 + 0.24 + 0.3 = 0.9
        assert 0.89 <= confidence.overall <= 0.91

    def test_confidence_to_dict(self):
        """Test dictionary export."""
        confidence = ValidationConfidence(
            completeness=0.9,
            consistency=0.8,
            uniqueness=1.0,
            sample_size=100
        )

        data = confidence.to_dict()

        assert "completeness" in data
        assert "consistency" in data
        assert "uniqueness" in data
        assert "sample_size" in data
        assert "overall" in data
        assert data["completeness"] == 0.9
        assert data["sample_size"] == 100


class TestValidateRecordsWithConfidence:
    """Test convenience function."""

    def test_validate_records_with_confidence(self):
        """Test full validation with confidence scoring."""
        rules = ValidationRules(
            required_fields=["title", "source_id"],
            min_completeness_rate=0.7
        )

        records = [
            {"title": "Test 1", "source_id": "1", "buyer": "Buyer 1"},
            {"title": "Test 2", "source_id": "2", "buyer": "Buyer 2"},
            {"title": "", "source_id": "3", "buyer": "Buyer 3"},  # Invalid
        ]

        valid_records, errors, confidence = validate_records_with_confidence(
            records, rules
        )

        assert len(valid_records) == 2
        assert len(errors) == 1
        assert isinstance(confidence, ValidationConfidence)
        assert confidence.sample_size == 3
        assert 0.0 <= confidence.overall <= 1.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
