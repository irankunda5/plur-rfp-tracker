"""RFP tracker configuration."""

import os
from pathlib import Path

from lib.keywords import NAICS_CODES

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
LOG_DIR = BASE_DIR / "logs"


def setup_dirs() -> None:
    """Create data and log directories. Call explicitly, not at import time."""
    DATA_DIR.mkdir(exist_ok=True)
    LOG_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# Notifications (standardized RFP_ prefix)
# ---------------------------------------------------------------------------

def get_slack_webhook_url() -> str | None:
    """Lazy accessor: avoids secrets as module-level globals."""
    return os.environ.get("RFP_SLACK_WEBHOOK_URL")

# Only send Slack digest for tier 1 and 2 matches by default
SLACK_MIN_TIER = int(os.environ.get("RFP_SLACK_MIN_TIER", "2"))

# SAM.gov API key
SAM_GOV_API_KEY: str | None = os.environ.get("SAM_GOV_API_KEY")

# Email digest settings
SMTP_HOST: str = os.environ.get("RFP_SMTP_HOST", "")
SMTP_PORT: int = int(os.environ.get("RFP_SMTP_PORT", "587"))
SMTP_USER: str = os.environ.get("RFP_SMTP_USER", "")
def get_smtp_password() -> str:
    """Lazy accessor: avoids secrets as module-level globals."""
    return os.environ.get("RFP_SMTP_PASSWORD", "")
DIGEST_RECIPIENTS: str = os.environ.get("RFP_DIGEST_RECIPIENTS", "")

# ---------------------------------------------------------------------------
# V2 config-driven sources
# ---------------------------------------------------------------------------

# Sources using v2 config-driven extraction (comma-separated)
# Example: V2_SOURCES=canadabuys_csv,sam_gov_json
V2_SOURCES = set(
    filter(None, os.environ.get('V2_SOURCES', '').split(','))
)

# ---------------------------------------------------------------------------
# Scraper configs
# ---------------------------------------------------------------------------

SCRAPER_CONFIGS: dict[str, dict] = {
    "canadabuys": {
        "url": "https://canadabuys.canada.ca/opendata/pub/newTenderNotice-nouvelAvisAppelOffres.csv",
        "enabled": True,
        "interval_hours": 6,
        "extra": {
            "lookback_days": 7,
            "naics_codes": list(NAICS_CODES.keys()),
        },
    },
    "canadabuys_search": {
        "url": "https://canadabuys.canada.ca/en/tender-opportunities",
        "enabled": True,
        "interval_hours": 12,
        "extra": {},
    },
    "sam_gov": {
        "url": "https://api.sam.gov/opportunities/v2/search",
        "enabled": False,   # needs SAM_GOV_API_KEY env var
        "interval_hours": 12,
        "extra": {
            "naics_codes": list(NAICS_CODES.keys()),
            "posted_from_days": 7,
        },
    },
    "bonfire": {
        "url": "https://bonfirehub.ca",
        "enabled": True,
        "interval_hours": 24,
        "extra": {
            "portals": [
                # BC post-secondary
                "ubc", "uvic", "sfu", "unbc", "bcit", "langara",
                # BC health authorities
                "fraserhealth", "islandhealth",
                # BC municipalities
                "victoria", "kelowna", "saanich", "penticton",
                "vernon", "kamloops", "northcowichan", "burnaby",
                # Alberta
                "ualberta", "sait", "nait",
                # Saskatchewan
                "usask", "sgi",
                # Manitoba
                "umanitoba",
                # Ontario post-secondary
                "uoguelph", "mcmaster", "carleton", "humber",
                "yorku", "senecacollege", "tmu", "georgebrown",
                "sheridancollege", "niagaracollege", "uwo",
                "durhamcollege", "cambriancollege",
                # Ontario agencies
                "waterfrontoronto",
            ],
        },
    },
    "sasktenders": {
        "url": "https://sasktenders.ca/content/public/Search.aspx",
        "enabled": True,
        "interval_hours": 12,
        "extra": {},
    },
}

# ---------------------------------------------------------------------------
# Re-export for convenience
# ---------------------------------------------------------------------------

__all__ = [
    "BASE_DIR",
    "DATA_DIR",
    "LOG_DIR",
    "setup_dirs",
    "get_slack_webhook_url",
    "SLACK_MIN_TIER",
    "SAM_GOV_API_KEY",
    "get_smtp_password",
    "V2_SOURCES",
    "SCRAPER_CONFIGS",
    "NAICS_CODES",
]

# V2 mode: run all production-ready v2 configs instead of v1 scrapers
V2_MODE = os.environ.get('V2_MODE', '').lower() in ('true', '1', 'yes')


def discover_v2_configs(status_filter: str | None = None) -> list[str]:
    """
    Discover v2 config files in configs/ directory.

    Args:
        status_filter: If provided, only return configs with matching status
                      (e.g., "production", "testing", "active")

    Returns:
        List of source_id strings
    """
    import yaml

    configs_dir = BASE_DIR / "configs"
    if not configs_dir.exists():
        return []

    discovered = []
    for yaml_file in configs_dir.glob("*.yaml"):
        try:
            with open(yaml_file, 'r') as f:
                config_data = yaml.safe_load(f)
                if not config_data or 'source_id' not in config_data:
                    continue

                # Check status filter if provided
                if status_filter:
                    config_status = config_data.get('status', 'draft')
                    if config_status != status_filter:
                        continue

                # Check if enabled (default True)
                if not config_data.get('enabled', True):
                    continue

                discovered.append(config_data['source_id'])
        except Exception:
            # Skip malformed configs
            continue

    return sorted(discovered)


def get_production_v2_sources() -> list[str]:
    """Get list of production-ready v2 config sources."""
    return discover_v2_configs(status_filter="production")
