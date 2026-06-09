"""Tender-Based Renewal Intelligence.

Cross-references historical CanadaBuys security product tender data to predict
renewal windows for DLP, OT Security, Insider Threat, CTI, and other categories
that are invisible in the Open Canada contracts CSV (sold via resellers).

Logic: if a department issued a DLP tender 3 years ago, they almost certainly
have a renewal window approaching. Project at 1yr, 3yr, and 5yr cycles and let
the user decide which is plausible.
"""

import json
import re
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

from lib.enrichment import normalize_buyer

# ---------------------------------------------------------------------------
# False positive filters
# ---------------------------------------------------------------------------

_FP_TITLE_PATTERNS = re.compile(
    r'\b(officer|guard|physical|cargo|van|truck|vehicle|liquor|retail|store|theft'
    r'|shoplifting|loss prevention officer|security guard|loss prevention officer'
    r'|rfi\b|request for information)\b',
    re.IGNORECASE,
)

_FP_BUYERS = {
    'liquor', 'lcbo', 'liquor distribution', 'bclc', 'casino',
}

# RFI-only tenders (information gathering, not procurement)
_RFI_TITLE_PATTERN = re.compile(
    r'^(?:request for information|rfi)\b',
    re.IGNORECASE,
)


def _is_false_positive(tender: dict) -> bool:
    """Return True if this tender is NOT an IT security procurement."""
    title = tender.get('title', '').lower()
    buyer = tender.get('buyer', '').lower()

    if _FP_TITLE_PATTERNS.search(title):
        return True
    if any(fp in buyer for fp in _FP_BUYERS):
        return True
    # Pure RFIs are not procurements - still keep them if they mention vendor names
    if _RFI_TITLE_PATTERN.match(tender.get('title', '')):
        search_term = tender.get('search_term', '').lower()
        # Only keep RFIs that matched on a specific vendor name (high signal)
        has_vendor = any(v in search_term for v in _HIGH_CONFIDENCE_VENDORS)
        if not has_vendor:
            return True
    return False


# ---------------------------------------------------------------------------
# Product category metadata
# ---------------------------------------------------------------------------

_CATEGORY_LABELS = {
    'dlp': 'DLP / Data Loss Prevention',
    'insider_threat': 'Insider Threat / UEBA',
    'ot': 'OT / ICS Security',
    'cti': 'Cyber Threat Intelligence',
    'edr': 'EDR / Endpoint',
    'siem': 'SIEM',
    'iam': 'IAM / PAM',
    'firewall': 'Firewall / Network Security',
    'vuln': 'Vulnerability Management',
    'email': 'Email Security',
    'network': 'Network Security',
}

# Vendor names that indicate HIGH confidence when found in search_term
_HIGH_CONFIDENCE_VENDORS = {
    'forcepoint', 'varonis', 'dtex', 'securonix', 'nozomi', 'claroty', 'dragos',
    'recorded future', 'anomali', 'mandiant', 'darktrace', 'vectra', 'exabeam',
    'logrhythm', 'splunk', 'crowdstrike', 'sentinelone', 'cyberark', 'sailpoint',
    'beyondtrust', 'entrust', 'tenable', 'qualys', 'rapid7', 'proofpoint',
    'mimecast', 'digital guardian', 'trellix', 'illumio', 'axonius',
    'palo alto', 'fortinet', 'checkpoint', 'sophos', 'tanium', 'carbon black',
}


def _is_high_confidence(tender_count: int, search_term: str) -> bool:
    """Return True if this group warrants HIGH confidence."""
    if tender_count >= 2:
        return True
    st_lower = search_term.lower()
    if any(vendor in st_lower for vendor in _HIGH_CONFIDENCE_VENDORS):
        return True
    return False


# ---------------------------------------------------------------------------
# Projection helpers
# ---------------------------------------------------------------------------

def _project_date(base: date, years: int) -> date:
    """Add N years to a date (handling Feb 29 edge case)."""
    target_year = base.year + years
    try:
        return base.replace(year=target_year)
    except ValueError:
        # Feb 29 in non-leap year -> Feb 28
        return base.replace(year=target_year, day=28)


def _days_until(target: date, today: date) -> int:
    return (target - today).days


# ---------------------------------------------------------------------------
# TenderRenewalCalendar
# ---------------------------------------------------------------------------

class TenderRenewalCalendar:
    """Builds renewal projections from historical CanadaBuys tender data."""

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self._by_group: dict[tuple, list[dict]] = {}
        self._projections: list[dict] = []

    def load_data(self) -> None:
        """Load security_product_tenders.json and compute projections."""
        json_path = self.data_dir / "security_product_tenders.json"
        if not json_path.exists():
            return

        with open(json_path, "r", encoding="utf-8") as f:
            raw = json.load(f)

        tenders = raw.get("tenders", [])

        # Group by (normalized_buyer, product_category) after false-positive filtering
        groups: dict[tuple, list[dict]] = defaultdict(list)
        for t in tenders:
            if _is_false_positive(t):
                continue
            closing_raw = t.get("closing_date", "")
            if not closing_raw:
                continue
            try:
                closing = date.fromisoformat(closing_raw)
            except ValueError:
                continue

            norm_buyer = normalize_buyer(t.get("buyer", "").strip())
            if not norm_buyer:
                continue

            category = t.get("product_category", "")
            if not category:
                continue

            key = (norm_buyer, category)
            groups[key].append({
                **t,
                "_closing_date": closing,
                "_norm_buyer": norm_buyer,
            })

        self._by_group = dict(groups)

        today = date.today()
        cutoff_past = today - timedelta(days=120)
        projections = []

        for (norm_buyer, category), entries in groups.items():
            # Sort descending by closing date
            entries.sort(key=lambda e: e["_closing_date"], reverse=True)

            most_recent = entries[0]
            award_date = most_recent["_closing_date"] + timedelta(days=60)

            proj_1yr = _project_date(award_date, 1)
            proj_3yr = _project_date(award_date, 3)
            proj_5yr = _project_date(award_date, 5)

            # Include if at least one projection is not too far in the past
            if proj_5yr < cutoff_past:
                continue

            tender_count = len(entries)
            search_term = most_recent.get("search_term", "")
            confidence = "HIGH" if _is_high_confidence(tender_count, search_term) else "MEDIUM"

            projections.append({
                "vendor": "Unknown (via tender)",
                "department": norm_buyer,
                "product_category": category,
                "product_label": _CATEGORY_LABELS.get(category, category.upper()),
                "search_term": search_term,
                "tender_title": most_recent.get("title", ""),
                "tender_url": most_recent.get("url", ""),
                "last_tender_date": most_recent.get("closing_date", ""),
                "tender_count": tender_count,
                "projected_renewal_1yr": proj_1yr.isoformat(),
                "projected_renewal_3yr": proj_3yr.isoformat(),
                "projected_renewal_5yr": proj_5yr.isoformat(),
                "days_until_1yr": _days_until(proj_1yr, today),
                "days_until_3yr": _days_until(proj_3yr, today),
                "days_until_5yr": _days_until(proj_5yr, today),
                "confidence": confidence,
                "source": "tender_history",
            })

        # Sort by 3yr projection (most likely cycle) ascending
        projections.sort(key=lambda r: r["projected_renewal_3yr"])
        self._projections = projections

    def get_upcoming(self, days_ahead: int = 365, category: str = None) -> list[dict]:
        """Return tender-based renewal predictions within days_ahead.

        A row is included if ANY of its three projections (1yr/3yr/5yr) falls
        within the window. This lets users see that a dept's 1yr cycle may have
        passed but the 3yr cycle is approaching.
        """
        today = date.today()
        cutoff = today + timedelta(days=days_ahead)
        cutoff_past = today - timedelta(days=120)

        results = []
        for r in self._projections:
            if category and r["product_category"] != category:
                continue

            proj_1 = date.fromisoformat(r["projected_renewal_1yr"])
            proj_3 = date.fromisoformat(r["projected_renewal_3yr"])
            proj_5 = date.fromisoformat(r["projected_renewal_5yr"])

            # Include if any projection is in the window [cutoff_past, cutoff]
            in_window = any(
                cutoff_past <= p <= cutoff
                for p in (proj_1, proj_3, proj_5)
            )
            if not in_window:
                continue

            # Recalculate days_until in case load happened a while ago
            updated = dict(r)
            updated["days_until_1yr"] = _days_until(proj_1, today)
            updated["days_until_3yr"] = _days_until(proj_3, today)
            updated["days_until_5yr"] = _days_until(proj_5, today)
            results.append(updated)

        return results

    def get_categories(self) -> list[str]:
        """Return list of product categories that have projection data."""
        return sorted(set(r["product_category"] for r in self._projections))
