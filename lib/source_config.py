"""Source configuration schema for declarative source definitions.

This module defines:
- RawOpportunity: The platform contract that all sources must produce
- SourceConfig: Declarative configuration for procurement sources
- CSVExtractionConfig: CSV-specific extraction configuration
- JSONExtractionConfig: JSON API extraction configuration
- HTMLExtractionConfig: HTML table extraction configuration

Additional extraction config types (RSS, XML) will be added when needed.
Philosophy: Generalize on the 3rd example, not the 1st.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Literal, Optional, Any
from pydantic import BaseModel, Field


# =============================================================================
# Platform Contract: RawOpportunity
# =============================================================================

@dataclass
class RawOpportunity:
    """
    The platform contract between source adapters and the ingestion system.

    Sources vary wildly (HTML, JSON, CSV, RSS), but ALL must produce this schema.
    Everything downstream (classification, enrichment, storage) depends on this.

    This is the canonical procurement notice schema - your product is a
    procurement notice generator, NOT a scraper.
    """
    source: str              # "canadabuys", "bonfire-ubc", etc.
    source_id: str           # Portal-specific ID (unique within source)
    title: str               # Opportunity title
    description: str = ""    # Full description (optional but preferred)
    buyer: str = ""          # Procuring organization
    closing_date: Optional[str] = None  # ISO 8601 format
    url: str = ""            # Link to full tender
    notice_type: str = ""    # "Open call", "Amendment", etc.
    extra_data: Optional[dict] = None  # Source-specific fields (raw)


# =============================================================================
# Source Type Enum
# =============================================================================

class SourceType(str, Enum):
    """
    Supported source types for generic extraction.

    Currently implemented:
    - CSV: CSV file extraction (proven in CanadaBuys vertical slice)
    - JSON_API: JSON API extraction (proven in Bonfire)
    - HTML: Static HTML table extraction (proven in SaskTenders)
    - LEGACY_SCRAPER: For gradual migration from custom Python scrapers

    Additional types (RSS, XML) will be added when needed.
    """
    CSV = "csv"
    JSON_API = "json_api"
    HTML = "html"
    LEGACY_SCRAPER = "legacy_scraper"


# =============================================================================
# Authentication Configuration
# =============================================================================

class AuthConfig(BaseModel):
    """Authentication configuration for sources."""
    type: Literal["none", "api_key", "basic", "bearer", "oauth2"] = "none"
    key_name: Optional[str] = None  # env var name for API key
    header_name: Optional[str] = None  # e.g., "X-API-Key", "Authorization"
    username: Optional[str] = None  # for basic auth
    password_env_var: Optional[str] = None  # env var for password


# =============================================================================
# Type-Specific Extraction Configurations
# =============================================================================

class CSVExtractionConfig(BaseModel):
    """Configuration for CSV extraction."""
    delimiter: str = ","
    encoding: str = "utf-8"
    skip_rows: int = 0
    has_header: bool = True
    columns: dict[str, str] = Field(
        ...,
        description="Field mappings: {target_field: source_column_name}"
    )
    # Example: {"title": "Title-eng", "buyer": "Buyer-eng"}

    class Config:
        json_schema_extra = {
            "example": {
                "delimiter": ",",
                "encoding": "utf-8",
                "columns": {
                    "source_id": "ReferenceNumber",
                    "title": "Title-eng",
                    "description": "Description-eng",
                    "buyer": "Buyer-eng",
                    "closing_date": "ClosingDate-eng"
                }
            }
        }


class JSONExtractionConfig(BaseModel):
    """Configuration for JSON API extraction."""
    columns: dict[str, str] = Field(
        ...,
        description="Field mappings: {target_field: json_path}. Use dot notation for nested fields."
    )
    response_path: Optional[str] = Field(
        None,
        description="Path to records array in response (e.g., 'opportunitiesData' for SAM.gov)"
    )
    query_params: dict[str, str] = Field(
        default_factory=dict,
        description="Static query parameters to add to API request"
    )
    # Example: {"title": "title", "description": "description", "buyer": "organizationId"}

    class Config:
        json_schema_extra = {
            "example": {
                "columns": {
                    "source_id": "noticeId",
                    "title": "title",
                    "description": "description",
                    "buyer": "organizationId",
                    "closing_date": "responseDeadLine",
                    "url": "uiLink",
                    "notice_type": "type"
                },
                "response_path": "opportunitiesData",
                "query_params": {
                    "limit": "1000",
                    "ptype": "o,p,k"
                }
            }
        }


class HTMLExtractionConfig(BaseModel):
    """Configuration for static HTML table extraction."""
    container_selector: str = Field(
        ...,
        description="CSS selector for table container (e.g., 'table', '.results-table')"
    )
    row_selector: str = Field(
        "tr",
        description="CSS selector for table rows within container"
    )
    skip_header_rows: int = Field(
        1,
        description="Number of header rows to skip"
    )
    columns: dict[str, str] = Field(
        ...,
        description="Field mappings: {target_field: cell_selector}. Use 'cell[N]' for positional, 'cell[N].text' for text, 'cell[N].a.href' for links"
    )
    url_base: Optional[str] = Field(
        None,
        description="Base URL for converting relative links to absolute (e.g., 'https://sasktenders.ca')"
    )
    # Example: {"source_id": "cell[0].text", "title": "cell[1].text", "url": "cell[0].a.href"}

    class Config:
        json_schema_extra = {
            "example": {
                "container_selector": "table",
                "row_selector": "tr",
                "skip_header_rows": 1,
                "columns": {
                    "source_id": "cell[0].text",
                    "title": "cell[1].text",
                    "buyer": "cell[2].text",
                    "closing_date": "cell[3].text",
                    "url": "cell[0].a.href"
                },
                "url_base": "https://sasktenders.ca"
            }
        }


# =============================================================================
# Validation Rules
# =============================================================================

class ValidationRules(BaseModel):
    """Validation rules for extracted records."""
    required_fields: list[str] = Field(
        default=["title", "source_id"],
        description="Fields that must be present and non-empty"
    )
    date_format: Optional[str] = "%Y-%m-%d"  # Python strftime format
    min_title_length: int = 5
    max_title_length: int = 500
    allowed_notice_types: Optional[list[str]] = None  # Whitelist if applicable

    # Quality thresholds
    min_completeness_rate: float = 0.8  # At least 80% of fields should be non-empty


# =============================================================================
# Health Monitoring Configuration
# =============================================================================

class HealthConfig(BaseModel):
    """Health monitoring configuration for breakage detection."""
    min_records_expected: int = 1
    max_days_silent: int = 3  # Alert if no records for N days
    error_rate_threshold: float = 0.2  # Alert if >20% extraction errors
    validation_fail_threshold: float = 0.5  # Alert if >50% validation failures


# =============================================================================
# Main SourceConfig Model
# =============================================================================

class SourceConfig(BaseModel):
    """
    Complete configuration for a procurement source.

    This is the core of the self-maintaining platform. Adding a new source
    should require only creating/editing this config, not writing Python code.
    """
    # Identity
    source_id: str = Field(..., description="Unique identifier (e.g., 'canadabuys_csv')")
    name: str = Field(..., description="Human-readable name")
    type: SourceType = Field(..., description="Source type (csv, html, json_api, etc.)")

    # Connection
    url: str = Field(..., description="Source URL or API endpoint")
    enabled: bool = True
    interval_hours: int = Field(12, description="Refresh frequency in hours")

    # Authentication
    auth: AuthConfig = AuthConfig()

    # Extraction configuration (type-specific)
    extraction: dict[str, Any] = Field(
        ...,
        description="Type-specific extraction config (currently: CSVExtractionConfig)"
    )

    # Validation
    validation: ValidationRules = ValidationRules()

    # Health monitoring
    health: HealthConfig = HealthConfig()

    # Metadata
    version: int = 1
    status: Literal["draft", "testing", "production", "active", "deprecated"] = "draft"
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    # Legacy scraper migration support
    legacy_scraper_module: Optional[str] = None  # e.g., "scrapers.canadabuys"
    legacy_scraper_class: Optional[str] = None   # e.g., "CanadaBuysScraper"

    def get_extraction_config(self) -> Any:
        """
        Returns typed extraction config based on source type.

        Currently supports:
        - CSV: Returns CSVExtractionConfig
        - JSON_API: Returns JSONExtractionConfig
        - HTML: Returns HTMLExtractionConfig
        - LEGACY_SCRAPER: Returns raw dict
        """
        if self.type == SourceType.CSV:
            return CSVExtractionConfig(**self.extraction)
        elif self.type == SourceType.JSON_API:
            return JSONExtractionConfig(**self.extraction)
        elif self.type == SourceType.HTML:
            return HTMLExtractionConfig(**self.extraction)
        else:
            # For legacy scrapers or unknown types, return raw dict
            return self.extraction

    class Config:
        json_schema_extra = {
            "example": {
                "source_id": "canadabuys_csv",
                "name": "CanadaBuys CSV Feed",
                "type": "csv",
                "url": "https://canadabuys.canada.ca/opendata/pub/newTenderNotice.csv",
                "enabled": True,
                "interval_hours": 6,
                "auth": {"type": "none"},
                "extraction": {
                    "delimiter": ",",
                    "encoding": "utf-8",
                    "columns": {
                        "source_id": "ReferenceNumber",
                        "title": "Title-eng",
                        "description": "Description-eng",
                        "buyer": "Buyer-eng",
                        "closing_date": "ClosingDate-eng",
                        "url": "URL-eng",
                        "notice_type": "NoticeType-eng"
                    }
                },
                "validation": {
                    "required_fields": ["title", "source_id"],
                    "date_format": "%Y-%m-%d"
                },
                "health": {
                    "min_records_expected": 10,
                    "max_days_silent": 2
                },
                "version": 1,
                "status": "active"
            }
        }


# =============================================================================
# Helper Functions
# =============================================================================

def load_source_config_from_dict(data: dict) -> SourceConfig:
    """Load and validate a SourceConfig from a dictionary."""
    return SourceConfig(**data)


def load_source_config_from_yaml(file_path: str) -> SourceConfig:
    """Load and validate a SourceConfig from a YAML file."""
    import yaml
    with open(file_path, 'r') as f:
        data = yaml.safe_load(f)
    return SourceConfig(**data)


def load_source_config_from_json(file_path: str) -> SourceConfig:
    """Load and validate a SourceConfig from a JSON file."""
    import json
    with open(file_path, 'r') as f:
        data = json.load(f)
    return SourceConfig(**data)
