"""Keyword matching for RFP/bid classification against PLUR cybersecurity ICP."""

import re
import unicodedata
from typing import TypedDict

# ---------------------------------------------------------------------------
# Keyword lists
# ---------------------------------------------------------------------------

HIGH_CONFIDENCE_CYBER = [
    "cybersecurity",
    "cyber security",
    "information security",
    "network security",
    "endpoint protection",
    "identity management",
    "access management",
    "IAM",
    "PAM",
    "privileged access",
    "zero trust",
    "SASE",
    "MFA",
    "multi-factor authentication",
    "SOC",
    "SIEM",
    "vulnerability assessment",
    "penetration testing",
    "threat detection",
    "incident response",
    "security operations",
    "data loss prevention",
    "encryption",
    "PKI",
    "ITSG-33",
    "PBMM",
    "cloud security",
    "FedRAMP",
    "CMMC",
    "CPCSC",
    "GRC",
    "governance risk compliance",
    "risk management framework",
    "security audit",
    "security assessment",
    "managed detection and response",
    "MDR",
    "EDR",
    "XDR",
    "SOAR",
    "security information and event management",
    "threat intelligence",
    "cyber threat",
    "red team",
    "blue team",
    "security operations center",
    "vulnerability scanning",
    "threat and risk assessment",
    "privacy impact assessment",
    # French - cyber (accented variants handled by normalize_text)
    "cybersecurite",
    "securite de l'information",
    "securite informatique",
    "authentification multifacteur",
    "habilitation de securite",
    "evaluation de la securite",
    "test de penetration",
    "evaluation des menaces et des risques",
    "evaluation des facteurs relatifs a la vie privee",
]

BROADER_IT = [
    "IT infrastructure",
    "cloud migration",
    "managed services",
    "network infrastructure",
    "IT professional services",
    "systems integration",
    "digital transformation",
    "IT modernization",
    "data centre",
    "data center",
    "software licensing",
    "managed detection",
    "endpoint detection",
    "security clearance",
    "DLP",
    "information technology",
    "cloud services",
    "cloud solution",
    "firewall",
    "server infrastructure",
    "network switch",
    "network modernization",
    "unified communications",
    "IT service management",
    "ITSM",
    "IT asset management",
    "disaster recovery",
    "help desk",
    "backup and recovery",
    "IT governance",
    # French - broader IT
    "technologies de l'information",
    "services infonuagiques",
    "solution infonuagique",
    "centre de donnees",
]

PLUR_SPECIFIC = [
    "identity verification",
    "continuous authentication",
    "biometric authentication",
    "passwordless",
    "workforce identity",
    "insider threat",
    "user behavior analytics",
    "UBA",
    "UEBA",
    "ICAM",
    "IGA",
    "identity governance",
    "identity proofing",
    "credential management",
    "federation",
    "SSO",
    "single sign-on",
    "directory services",
    "privileged access workstation",
    "Active Directory",
    # French - identity
    "gestion des identites",
    "gestion des acces",
    "controle d'acces privilegie",
]

# Negative keywords - exclude physical security, guard services, etc.
NEGATIVE_KEYWORDS = [
    "security guard",
    "guard services",
    "armoured car",
    "armored car",
    "locksmith",
    "janitorial",
    "cleaning services",
    "landscaping",
    "snow removal",
    "catering",
    "furniture",
    "office supplies",
    "street sweeper",
    "heating",
    "waste management",
    # Construction / facility negatives (DND base contracts etc.)
    "construction",
    "renovation",
    "demolition",
    "barracks",
    "armoury",
    "armory",
    "recapitalization",
    "commissioning services",
    "roofing",
    "paving",
    "plumbing",
    "electrical contractor",
    "general contractor",
    "travaux de construction",
    # French negatives
    "agent de securite",
    "gardiennage",
    "services de garde",
]

# Vendor products for reseller opportunity detection
VENDOR_PRODUCTS = {
    "ForgeRock": ["ForgeRock"],
    "CrowdStrike": ["CrowdStrike", "CrowdStrike Falcon", "Falcon EDR", "Falcon XDR"],
    "Palo Alto": ["Palo Alto", "Prisma", "Cortex"],
    "SailPoint": ["SailPoint"],
    "CyberArk": ["CyberArk"],
    "Okta": ["Okta"],
    "Ping Identity": ["Ping Identity", "PingFederate", "PingOne"],
    "SentinelOne": ["SentinelOne"],
    "Splunk": ["Splunk"],
    "Microsoft": ["Azure AD", "Entra ID", "Defender"],
}

# NAICS codes relevant to PLUR's business
NAICS_CODES = {
    "541512": "Computer Systems Design Services",
    "541519": "Other Computer Related Services",
    "541511": "Custom Computer Programming Services",
    "541513": "Computer Facilities Management Services",
    "561621": "Security Systems Services",
    "541690": "Other Scientific and Technical Consulting Services",
}

# UNSPSC codes for Canadian procurement (used by CanadaBuys alongside GSIN)
UNSPSC_CODES = {
    "43232300": "Network Security Equipment",
    "43232400": "Network Security Services",
    "81112200": "Computer or Network Security",
    "43233200": "Intrusion Detection Systems",
    "43232600": "Access Control Systems",
}

# GSIN codes - Canadian procurement commodity codes (CanadaBuys)
# Values are (description, tier_boost) where tier_boost is the minimum tier to assign
GSIN_CODES = {
    # N70xx: ADP/computer equipment
    "N7010": ("ADPE System Configuration", 3),
    "N7021": ("Central Processing Unit", 3),
    "N7022": ("ADP Key Entry Equipment", 3),
    "N7023": ("ADP Output Equipment", 3),
    "N7025": ("ADP Storage Devices", 3),
    "N7030": ("ADP Software", 3),
    "N7035": ("ADP Supplies", 3),
    "N7042": ("Mini/Micro Computer Systems", 3),
    "N7045": ("ADP Peripherals", 3),
    # D3xx: ADP/IT services
    "D301": ("ADPE Facilities Management", 3),
    "D302": ("Systems Analysis and Design", 3),
    "D304": ("Computer Programming Services", 3),
    "D306": ("ADP Data Conversion Services", 3),
    "D307": ("Automated Information Services", 3),
    "D308": ("Database Services", 3),
    "D310": ("Help Desk Services", 3),
    "D311": ("IT Management Services", 3),
    "D314": ("Systems Engineering Services", 3),
    "D316": ("Telecommunications Services", 3),
    "D317": ("Web/Internet Services", 3),
    "D318": ("Managed IT Services", 2),
    "D320": ("Hosting Services", 3),
    "D399": ("Other IT Services", 3),
    # JI7010: ADPE system configuration
    "JI7010": ("ADPE System Configuration", 3),
}

# Product vs Services keywords
_PRODUCT_KEYWORDS = [
    "software license", "software licensing", "license renewal",
    "hardware", "appliance", "equipment",
]
_SERVICES_KEYWORDS = [
    "consulting", "professional services", "managed services",
    "assessment", "audit", "advisory", "implementation",
]

# ---------------------------------------------------------------------------
# Tier definitions
# ---------------------------------------------------------------------------

# Tier 1: strong cybersecurity signal (HIGH_CONFIDENCE_CYBER)
# Tier 2: PLUR-specific IAM/identity signal (PLUR_SPECIFIC)
# Tier 3: broader IT - may be relevant (BROADER_IT)
# Tier 0: no match

_TIER_MAP = [
    (1, HIGH_CONFIDENCE_CYBER),
    (2, PLUR_SPECIFIC),
    (3, BROADER_IT),
]


class ClassifyResult(TypedDict):
    matched_keywords: list[str]
    tier: int          # 0 = no match, 1 = cyber, 2 = IAM/PLUR, 3 = IT
    confidence: float  # 0.0 - 1.0
    product_type: str  # "product", "services", or ""
    vendor_flags: list[str]  # vendor products detected


# ---------------------------------------------------------------------------
# Text normalization
# ---------------------------------------------------------------------------

def normalize_text(text: str) -> str:
    """Strip accents/diacritics from text for matching.

    Uses NFD decomposition to separate base characters from combining marks,
    then strips combining characters. This allows 'cybersécurité' to match
    'cybersecurite'.
    """
    nfd = unicodedata.normalize("NFD", text)
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")


# ---------------------------------------------------------------------------
# Matching helpers
# ---------------------------------------------------------------------------

def _build_pattern(keyword: str) -> re.Pattern:
    """Build a whole-word case-insensitive regex for a keyword.

    Multi-word phrases are matched as-is (word boundary on outer edges only).
    Single-word acronyms like 'SOC' use strict word boundaries to avoid
    matching 'Societe' or 'SIEM' matching 'Siemens'.
    Short all-caps acronyms (2-4 chars) are matched case-sensitively to avoid
    'Pam' matching 'PAM'.
    """
    escaped = re.escape(keyword)
    if " " in keyword:
        # Phrase: anchor on outer words
        return re.compile(r"\b" + escaped + r"\b", re.IGNORECASE)
    elif keyword.isupper() and 2 <= len(keyword) <= 4:
        # Short acronym: case-sensitive to avoid Pam->PAM, Soc->SOC etc.
        return re.compile(r"(?<![A-Za-z0-9])" + escaped + r"(?![A-Za-z0-9])")
    else:
        # Single token: strict word boundary on both sides
        return re.compile(r"(?<![A-Za-z0-9])" + escaped + r"(?![A-Za-z0-9])", re.IGNORECASE)


# Pre-compile patterns keyed by keyword string
_PATTERNS: dict[str, re.Pattern] = {}
for _kw_list in [HIGH_CONFIDENCE_CYBER, PLUR_SPECIFIC, BROADER_IT]:
    for _kw in _kw_list:
        _PATTERNS[_kw] = _build_pattern(_kw)

_NEGATIVE_PATTERNS: list[re.Pattern] = [_build_pattern(kw) for kw in NEGATIVE_KEYWORDS]
_VENDOR_PATTERNS: dict[str, list[re.Pattern]] = {
    vendor: [_build_pattern(p) for p in patterns]
    for vendor, patterns in VENDOR_PRODUCTS.items()
}


def _find_matches(text: str, keyword_list: list[str]) -> list[str]:
    """Return keywords from the list that appear in text."""
    return [kw for kw in keyword_list if _PATTERNS[kw].search(text)]


def _detect_vendors(text: str) -> list[str]:
    """Detect vendor product mentions in text."""
    found = []
    for vendor, patterns in _VENDOR_PATTERNS.items():
        for p in patterns:
            if p.search(text):
                found.append(vendor)
                break
    return found


def _detect_product_type(text: str) -> str:
    """Detect whether opportunity is for products or services."""
    text_lower = text.lower()
    has_product = any(kw in text_lower for kw in _PRODUCT_KEYWORDS)
    has_services = any(kw in text_lower for kw in _SERVICES_KEYWORDS)
    if has_product and not has_services:
        return "product"
    if has_services and not has_product:
        return "services"
    if has_product and has_services:
        return "product"  # mixed: lean product for reseller flag
    return ""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def classify_opportunity(
    title: str,
    description: str = "",
    *,
    title_only: bool = False,
    unspsc_codes: list[str] | None = None,
    gsin_codes: list[str] | None = None,
) -> ClassifyResult:
    """Classify an RFP/bid against PLUR keyword tiers.

    Args:
        title: Opportunity title (always checked).
        description: Full description text (optional, improves recall).
        title_only: If True, use lower threshold (for Bonfire title-only sources).
        unspsc_codes: Optional UNSPSC codes from the opportunity metadata.
        gsin_codes: Optional GSIN codes from CanadaBuys metadata.

    Returns:
        ClassifyResult with matched_keywords, tier (0-3), confidence (0-1),
        product_type, and vendor_flags.
    """
    # Normalize accents before matching
    norm_title = normalize_text(title)
    norm_desc = normalize_text(description)
    corpus = f"{norm_title} {norm_desc}"
    title_lower = norm_title.lower()

    # Check negative keywords against full corpus (title + description)
    neg_hits = sum(1 for p in _NEGATIVE_PATTERNS if p.search(corpus))

    all_matches: list[str] = []
    best_tier = 0
    title_hits = 0

    for tier, kw_list in _TIER_MAP:
        matches = _find_matches(corpus, kw_list)
        if matches:
            if best_tier == 0:
                best_tier = tier
            all_matches.extend(matches)
            for kw in matches:
                if _PATTERNS[kw].search(norm_title):
                    title_hits += 1

    # UNSPSC code boost: if opportunity has matching UNSPSC, treat as at least Tier 3
    unspsc_boost = False
    if unspsc_codes:
        for code in unspsc_codes:
            if code in UNSPSC_CODES:
                unspsc_boost = True
                if best_tier == 0:
                    best_tier = 3
                break

    # GSIN code boost: similar to UNSPSC, boost to at least the tier specified in GSIN_CODES
    gsin_boost = False
    if gsin_codes:
        for code in gsin_codes:
            # Match exact code or prefix (e.g., "N7030" matches "N7030")
            matched_gsin = GSIN_CODES.get(code)
            if matched_gsin:
                gsin_boost = True
                _, gsin_tier = matched_gsin
                if best_tier == 0 or gsin_tier < best_tier:
                    best_tier = gsin_tier
                break

    if not all_matches and not unspsc_boost and not gsin_boost:
        return ClassifyResult(
            matched_keywords=[], tier=0, confidence=0.0,
            product_type="", vendor_flags=[],
        )

    # Detect vendor products and product type
    vendor_flags = _detect_vendors(corpus)
    product_type = _detect_product_type(corpus)

    unique_matches = list(dict.fromkeys(all_matches))  # dedupe, preserve order
    tier_weight = {1: 1.0, 2: 0.9, 3: 0.7}.get(best_tier, 0.5)

    if title_only:
        # Lower threshold for title-only: fewer matches needed for decent confidence
        raw_score = (len(unique_matches) * 2 + title_hits) / 5.0
    else:
        raw_score = (len(unique_matches) + title_hits) / 5.0

    # UNSPSC boost adds 0.2 to raw score
    if unspsc_boost:
        raw_score += 0.2

    # GSIN boost adds 0.2 to raw score
    if gsin_boost:
        raw_score += 0.2

    confidence = min(1.0, raw_score * tier_weight)
    confidence = max(0.05, confidence - (neg_hits * 0.3))  # penalty, floor at 0.05

    return ClassifyResult(
        matched_keywords=unique_matches,
        tier=best_tier,
        confidence=round(confidence, 3),
        product_type=product_type,
        vendor_flags=vendor_flags,
    )
