"""IT Renewal Calendar - projects renewal dates from historical contract data.

Reads the Open Canada contracts CSV, identifies recurring IT contracts (software,
security products, and hardware with maintenance), and projects forward to predict
upcoming renewal windows for PLUR sales engagement.
"""

import csv
import re
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from lib.enrichment import normalize_buyer, _parse_float
from lib.known_vendors import KNOWN_CYBER_IT_FIRMS

# ---------------------------------------------------------------------------
# Renewable IT contract filter
# ---------------------------------------------------------------------------

_RENEWABLE_IT_KEYWORDS = re.compile(
    r"(?:"
    # Software (original)
    r"software|licen[cs]e|subscription|saas|platform|renewal|maintenance\s+fees"
    # Security products
    r"|firewall|endpoint|antivirus|anti-virus|malware|data\s+loss|dlp"
    r"|intrusion|threat|vulnerability|encryption|backup|cloud\s+service"
    r"|identity\s+management|access\s+management|authentication"
    r"|monitoring|siem|log\s+management|security\s+information"
    # Hardware with maintenance
    r"|hardware\s+maintenance|support\s+renewal|maintenance\s+renewal"
    r"|maintenance\s+and\s+support|support\s+and\s+maintenance"
    r"|server\s+maintenance|network\s+equipment|networking\s+equipment"
    r"|communications\s+security|security\s+equipment|security\s+system"
    r"|alarm.*security|detection\s+system"
    # IT hardware categories
    r"|computer\s+equipment|server|storage|router|switch|appliance"
    r"|workstation|laptop|desktop|monitor"
    r")",
    re.IGNORECASE,
)


def _is_renewable_it_contract(description: str) -> bool:
    """Return True if description indicates a renewable IT contract (software, security, or hardware with maintenance)."""
    if not description:
        return False
    return bool(_RENEWABLE_IT_KEYWORDS.search(description))


# ---------------------------------------------------------------------------
# Date parsing
# ---------------------------------------------------------------------------

def _parse_date(val: str) -> Optional[date]:
    """Parse a date string from the contracts CSV. Returns None on failure."""
    if not val or not val.strip():
        return None
    val = val.strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(val, fmt).date()
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# PLUR relevance classification
# ---------------------------------------------------------------------------

# Direct competitors or displacement targets (HIGH)
_HIGH_RELEVANCE_VENDORS = {
    "crowdstrike", "palo alto", "sentinelone", "fortinet", "fireeye",
    "mandiant", "tenable", "cyberark", "sailpoint", "tanium", "splunk",
    "zscaler", "optiv", "securekey", "entrust", "check point",
    "esentire", "netsecure", "blackberry", "veeam",
}

# Services competitors or platform incumbents (MEDIUM)
_MEDIUM_RELEVANCE_VENDORS = {
    "cgi", "deloitte", "accenture", "kpmg", "pwc", "booz allen",
    "leidos", "saic", "unisys", "dxc", "compugen", "tata",
    "wipro", "serco", "general dynamics", "lockheed martin",
    "raytheon", "thales", "bae systems", "microsoft", "cisco",
    "ibm", "oracle", "amazon web services", "google", "dell",
    "hewlett", "hp canada", "vmware", "citrix", "juniper",
    "servicenow", "salesforce",
}


def _classify_relevance(vendor_name: str) -> str:
    """Classify vendor relevance to PLUR. Returns HIGH, MEDIUM, or LOW."""
    if not vendor_name:
        return "LOW"
    lower = vendor_name.lower()
    for pattern in _HIGH_RELEVANCE_VENDORS:
        if pattern in lower:
            return "HIGH"
    for pattern in _MEDIUM_RELEVANCE_VENDORS:
        if pattern in lower:
            return "MEDIUM"
    # Also check the known_vendors dict for substring matches
    for pattern, category in KNOWN_CYBER_IT_FIRMS.items():
        if pattern in lower:
            if category == "CYBER":
                return "HIGH"
            elif category in ("IT_SERVICES", "DEFENSE_IT", "IT_VENDOR", "TELCO"):
                return "MEDIUM"
    return "LOW"


# ---------------------------------------------------------------------------
# Product extraction
# ---------------------------------------------------------------------------

# Known product names to extract from vendor or description
_PRODUCT_NAMES = {
    "crowdstrike": "CrowdStrike Falcon",
    "palo alto": "Palo Alto Networks",
    "fortinet": "FortiGate/FortiNet",
    "fortigate": "FortiGate",
    "sentinelone": "SentinelOne",
    "cyberark": "CyberArk",
    "sailpoint": "SailPoint",
    "forgerock": "ForgeRock",
    "okta": "Okta",
    "splunk": "Splunk",
    "servicenow": "ServiceNow",
    "zscaler": "Zscaler",
    "tenable": "Tenable",
    "tanium": "Tanium",
    "vmware": "VMware",
    "microsoft": "Microsoft",
    "cisco": "Cisco",
    "oracle": "Oracle",
    "sap ": "SAP",
    "salesforce": "Salesforce",
    "adobe": "Adobe",
    "figma": "Figma",
    "jfrog": "JFrog",
    "atlassian": "Atlassian",
    "confluence": "Atlassian Confluence",
    "jira": "Atlassian Jira",
    "zoom": "Zoom",
    "slack": "Slack",
    "github": "GitHub",
    "gitlab": "GitLab",
    "docker": "Docker",
    "red hat": "Red Hat",
    "esri": "Esri ArcGIS",
    "arcgis": "Esri ArcGIS",
    "veritas": "Veritas",
    "commvault": "Commvault",
    "veeam": "Veeam",
    "nutanix": "Nutanix",
    "dell emc": "Dell EMC",
    "hewlett": "HPE",
    "checkpoint": "Check Point",
    "check point": "Check Point",
    "sophos": "Sophos",
    "trellix": "Trellix",
    "fireeye": "Trellix (FireEye)",
    "mandiant": "Mandiant",
    "blackberry": "BlackBerry",
    "cylance": "BlackBerry Cylance",
    "trend micro": "Trend Micro",
    "mcafee": "McAfee/Trellix",
    "symantec": "Broadcom/Symantec",
    "broadcom": "Broadcom",
    "rapid7": "Rapid7",
    "qualys": "Qualys",
    "proofpoint": "Proofpoint",
    "mimecast": "Mimecast",
    "carbon black": "VMware Carbon Black",
    "elastic": "Elastic",
    "datadog": "Datadog",
    "dynatrace": "Dynatrace",
    "automation anywhere": "Automation Anywhere",
    "uipath": "UiPath",
    "power bi": "Microsoft Power BI",
    "tableau": "Tableau",
    "snowflake": "Snowflake",
    "goanywhere": "Fortra GoAnywhere",
    "opentext": "OpenText",
    "open text": "OpenText",
    "appian": "Appian",
    "ibm": "IBM",
    # Networking / wireless
    "aruba": "Aruba Networks",
    "juniper": "Juniper Networks",
    "infoblox": "Infoblox",
    "arista": "Arista Networks",
    "extrahop": "ExtraHop",
    # IT management / endpoint
    "ivanti": "Ivanti",
    "beyondtrust": "BeyondTrust",
    "hcl bigfix": "HCL BigFix",
    "bigfix": "HCL BigFix",
    "manageengine": "ManageEngine",
    "solarwinds": "SolarWinds",
    "forescout": "Forescout",
    "micro focus": "Micro Focus",
    "netiq": "Micro Focus NetIQ",
    # Encryption / PKI / certificates
    "thales": "Thales",
    "safenet": "Thales SafeNet",
    "entrust": "Entrust",
    "venafi": "Venafi",
    # OT security
    "nozomi": "Nozomi Networks",
    "claroty": "Claroty",
    "dragos": "Dragos",
    # AI-powered threat detection
    "vectra": "Vectra AI",
}


# ---------------------------------------------------------------------------
# Standing offer to product category mapping
# ---------------------------------------------------------------------------

_STANDING_OFFER_PRODUCTS = {
    # Microsoft
    "700433063": "Microsoft",
    "K000013914": "Microsoft",
    # ESRI/GIS
    "EN578-100808/069/EE": "ESRI ArcGIS",
    # Oracle
    "EN578-100808/058/EE": "Oracle",
    # SAS
    "EN578-100808/045/EE": "SAS Analytics",
    # Enterprise dev tools (Carahsoft: Jira, Confluence, Tableau)
    "EN578-100808/155/EE": "Enterprise Dev Tools",
    # GIS/CAD
    "EN578-100808/181/EE": "GIS/CAD Software",
    # SAP
    "EN578-100808/050/EE": "SAP",
    # IBM
    "EN578-100808/051/EE": "IBM",
    # Red Hat
    "EN578-100808/102/EE": "Red Hat",
    # Cisco
    "EN578-100808/037/EE": "Cisco",
    # VMware
    "EN578-100808/139/EE": "VMware",
}


# ---------------------------------------------------------------------------
# Product name extraction from additional_comments
# ---------------------------------------------------------------------------

_COMMENT_PRODUCT_PATTERNS: list[tuple[re.Pattern, str]] = [
    # Cybersecurity / EDR / SIEM
    (re.compile(r'\b(?:ServiceNow)\b', re.IGNORECASE), 'ServiceNow'),
    (re.compile(r'\b(?:Splunk)\b', re.IGNORECASE), 'Splunk'),
    (re.compile(r'\b(?:Fortinet|FortiGate|FortiNet|FortiManager|FortiAnalyzer)\b', re.IGNORECASE), 'Fortinet'),
    (re.compile(r'\b(?:CrowdStrike|CrowdStrike\s+Falcon|Falcon\s+(?:Insight|Prevent|Complete|Discover|Overwatch|X|XDR))\b', re.IGNORECASE), 'CrowdStrike'),
    (re.compile(r'\b(?:SentinelOne)\b', re.IGNORECASE), 'SentinelOne'),
    (re.compile(r'\bPalo\s+Alto\b', re.IGNORECASE), 'Palo Alto Networks'),
    (re.compile(r'\b(?:Tenable|Nessus|Tenable\.io|Tenable\.sc)\b', re.IGNORECASE), 'Tenable'),
    (re.compile(r'\b(?:Qualys)\b', re.IGNORECASE), 'Qualys'),
    (re.compile(r'\b(?:Rapid7|InsightVM|InsightConnect)\b', re.IGNORECASE), 'Rapid7'),
    (re.compile(r'\b(?:CyberArk)\b', re.IGNORECASE), 'CyberArk'),
    (re.compile(r'\b(?:SailPoint)\b', re.IGNORECASE), 'SailPoint'),
    (re.compile(r'\b(?:Tanium)\b', re.IGNORECASE), 'Tanium'),
    (re.compile(r'\b(?:Zscaler)\b', re.IGNORECASE), 'Zscaler'),
    (re.compile(r'\b(?:Check\s*Point)\b', re.IGNORECASE), 'Check Point'),
    (re.compile(r'\b(?:Sophos)\b', re.IGNORECASE), 'Sophos'),
    (re.compile(r'\b(?:Trellix)\b', re.IGNORECASE), 'Trellix'),
    (re.compile(r'\b(?:McAfee)\b', re.IGNORECASE), 'McAfee/Trellix'),
    (re.compile(r'\b(?:Symantec)\b', re.IGNORECASE), 'Broadcom/Symantec'),
    (re.compile(r'\b(?:Carbon\s+Black)\b', re.IGNORECASE), 'VMware Carbon Black'),
    (re.compile(r'\b(?:Trend\s+Micro)\b', re.IGNORECASE), 'Trend Micro'),
    (re.compile(r'\b(?:Proofpoint)\b', re.IGNORECASE), 'Proofpoint'),
    (re.compile(r'\b(?:Mimecast)\b', re.IGNORECASE), 'Mimecast'),
    (re.compile(r'\b(?:BlackBerry|Cylance)\b', re.IGNORECASE), 'BlackBerry Cylance'),
    (re.compile(r'\b(?:Varonis)\b', re.IGNORECASE), 'Varonis'),
    (re.compile(r'\b(?:Darktrace)\b', re.IGNORECASE), 'Darktrace'),
    (re.compile(r'\b(?:Imperva)\b', re.IGNORECASE), 'Imperva'),
    (re.compile(r'\b(?:Recorded\s+Future)\b', re.IGNORECASE), 'Recorded Future'),
    (re.compile(r'\b(?:Anomali)\b', re.IGNORECASE), 'Anomali'),
    (re.compile(r'\b(?:LogRhythm)\b', re.IGNORECASE), 'LogRhythm'),
    (re.compile(r'\b(?:Secureworks)\b', re.IGNORECASE), 'Secureworks'),
    # Collaboration / Productivity
    (re.compile(r'\b(?:Adobe)\b', re.IGNORECASE), 'Adobe'),
    (re.compile(r'\b(?:Tableau)\b', re.IGNORECASE), 'Tableau'),
    (re.compile(r'\b(?:Jira)\b', re.IGNORECASE), 'Atlassian Jira'),
    (re.compile(r'\b(?:Confluence)\b', re.IGNORECASE), 'Atlassian Confluence'),
    (re.compile(r'\b(?:Slack)\b', re.IGNORECASE), 'Slack'),
    (re.compile(r'\b(?:Zoom)\b', re.IGNORECASE), 'Zoom'),
    (re.compile(r'\b(?:Power\s*BI)\b', re.IGNORECASE), 'Microsoft Power BI'),
    (re.compile(r'\b(?:SharePoint)\b', re.IGNORECASE), 'Microsoft SharePoint'),
    (re.compile(r'\b(?:Teams)\b', re.IGNORECASE), 'Microsoft Teams'),
    (re.compile(r'\b(?:Dynamics\s+365)\b', re.IGNORECASE), 'Microsoft Dynamics 365'),
    (re.compile(r'\b(?:Azure)\b', re.IGNORECASE), 'Microsoft Azure'),
    (re.compile(r'\b(?:AWS|Amazon\s+Web\s+Services)\b', re.IGNORECASE), 'AWS'),
    (re.compile(r'\b(?:Google\s+Cloud|GCP)\b', re.IGNORECASE), 'Google Cloud'),
    # Infrastructure / Dev
    (re.compile(r'\b(?:Quest\s+Software|Quest)\b', re.IGNORECASE), 'Quest Software'),
    (re.compile(r'\b(?:VMware)\b', re.IGNORECASE), 'VMware'),
    (re.compile(r'\b(?:Citrix)\b', re.IGNORECASE), 'Citrix'),
    (re.compile(r'\b(?:Nutanix)\b', re.IGNORECASE), 'Nutanix'),
    (re.compile(r'\b(?:Red\s+Hat)\b', re.IGNORECASE), 'Red Hat'),
    (re.compile(r'\b(?:GitHub)\b', re.IGNORECASE), 'GitHub'),
    (re.compile(r'\b(?:GitLab)\b', re.IGNORECASE), 'GitLab'),
    (re.compile(r'\b(?:Docker)\b', re.IGNORECASE), 'Docker'),
    (re.compile(r'\b(?:Kubernetes|K8s)\b', re.IGNORECASE), 'Kubernetes'),
    (re.compile(r'\b(?:Veeam)\b', re.IGNORECASE), 'Veeam'),
    (re.compile(r'\b(?:Commvault)\b', re.IGNORECASE), 'Commvault'),
    (re.compile(r'\b(?:Veritas)\b', re.IGNORECASE), 'Veritas'),
    # Enterprise platforms
    (re.compile(r'\b(?:SAP)\b'), 'SAP'),
    (re.compile(r'\b(?:Salesforce)\b', re.IGNORECASE), 'Salesforce'),
    (re.compile(r'\b(?:Oracle)\b', re.IGNORECASE), 'Oracle'),
    (re.compile(r'\b(?:ESRI|ArcGIS)\b', re.IGNORECASE), 'ESRI ArcGIS'),
    (re.compile(r'\b(?:OpenText|Open\s+Text)\b', re.IGNORECASE), 'OpenText'),
    (re.compile(r'\b(?:Appian)\b', re.IGNORECASE), 'Appian'),
    (re.compile(r'\b(?:MicroStrategy)\b', re.IGNORECASE), 'MicroStrategy'),
    (re.compile(r'\b(?:Snowflake)\b', re.IGNORECASE), 'Snowflake'),
    (re.compile(r'\b(?:Datadog)\b', re.IGNORECASE), 'Datadog'),
    (re.compile(r'\b(?:Dynatrace)\b', re.IGNORECASE), 'Dynatrace'),
    (re.compile(r'\b(?:Elastic)\b', re.IGNORECASE), 'Elastic'),
    # Networking
    (re.compile(r'\b(?:Cisco)\b', re.IGNORECASE), 'Cisco'),
    (re.compile(r'\b(?:F5\s+Networks|F5\s+BIG-IP)\b', re.IGNORECASE), 'F5 Networks'),
    (re.compile(r'\b(?:Aruba(?:\s+Networks)?|Aruba\s+ClearPass)\b', re.IGNORECASE), 'Aruba Networks'),
    (re.compile(r'\b(?:Juniper(?:\s+Networks)?|Juniper\s+SRX)\b', re.IGNORECASE), 'Juniper Networks'),
    (re.compile(r'\b(?:Infoblox)\b', re.IGNORECASE), 'Infoblox'),
    (re.compile(r'\b(?:Arista(?:\s+Networks)?)\b', re.IGNORECASE), 'Arista Networks'),
    (re.compile(r'\b(?:ExtraHop)\b', re.IGNORECASE), 'ExtraHop'),
    # IT management / endpoint
    (re.compile(r'\b(?:Ivanti)\b', re.IGNORECASE), 'Ivanti'),
    (re.compile(r'\b(?:BeyondTrust)\b', re.IGNORECASE), 'BeyondTrust'),
    (re.compile(r'\b(?:HCL\s+BigFix|BigFix)\b', re.IGNORECASE), 'HCL BigFix'),
    (re.compile(r'\b(?:ManageEngine)\b', re.IGNORECASE), 'ManageEngine'),
    (re.compile(r'\b(?:SolarWinds)\b', re.IGNORECASE), 'SolarWinds'),
    (re.compile(r'\b(?:Forescout)\b', re.IGNORECASE), 'Forescout'),
    (re.compile(r'\b(?:Micro\s+Focus|NetIQ)\b', re.IGNORECASE), 'Micro Focus'),
    # Encryption / PKI / certificates
    (re.compile(r'\b(?:Thales)\b', re.IGNORECASE), 'Thales'),
    (re.compile(r'\b(?:SafeNet)\b', re.IGNORECASE), 'Thales SafeNet'),
    (re.compile(r'\b(?:Entrust)\b', re.IGNORECASE), 'Entrust'),
    (re.compile(r'\b(?:Venafi)\b', re.IGNORECASE), 'Venafi'),
    # OT security
    (re.compile(r'\b(?:Nozomi(?:\s+Networks)?)\b', re.IGNORECASE), 'Nozomi Networks'),
    (re.compile(r'\b(?:Claroty)\b', re.IGNORECASE), 'Claroty'),
    (re.compile(r'\b(?:Dragos)\b', re.IGNORECASE), 'Dragos'),
    # AI-powered threat detection
    (re.compile(r'\b(?:Vectra(?:\s+AI)?)\b', re.IGNORECASE), 'Vectra AI'),
]


# Description category extraction - map generic procurement descriptions to short labels
_DESC_CATEGORIES = {
    "networking software": "Networking Software",
    "application software": "Application Software",
    "client software": "Client Software",
    "operating system": "OS/System Software",
    "security software": "Security Software",
    "database": "Database Software",
    "web services subscriptions": "Web Services",
    "electronic subscriptions": "Electronic Subscriptions",
    "saas": "SaaS",
    "cloud": "Cloud Services",
    "endpoint": "Endpoint Security",
    "firewall": "Firewall",
    "antivirus": "Antivirus/EDR",
    "identity": "Identity/IAM",
    "backup": "Backup/Recovery",
    "monitoring": "Monitoring",
    "encryption": "Encryption",
}


# Known IT resellers - these sell other vendors' products
_KNOWN_RESELLERS = {
    "ipss", "softchoice", "cdw", "insight", "shi ", "compugen", "compucom",
    "quadbridge", "cistel", "conexsys", "access 2 networks", "advanced chippewa",
    "teel technologies", "long view", "microserv", "itex", "pcm canada",
    "softlanding", "scalar", "converge", "optiv", "carahsoft", "immix",
    "presidio", "world wide technology", "wwt", "zones", "gurulink",
    "adirondack", "cgi information systems", "n harris computer",
}


def _extract_product(
    vendor: str,
    description: str,
    additional_comments: str = "",
    standing_offer: str = "",
) -> tuple[str, str]:
    """Extract a product/platform name from vendor, description, comments, and standing offer.

    Returns (product_name, source) where source is one of:
      "comments"  - explicit product name found in additional_comments (highest confidence)
      "vendor"    - matched against known product names dict
      "so"        - standing offer number mapped to product category
      "reseller"  - vendor is a known reseller, category from description
      "category"  - generic category from description keywords
      "fallback"  - cleaned vendor name (lowest confidence)

    Priority: comments > known product name > standing offer > reseller tag > description category > cleaned vendor.
    """
    # 1. Check additional_comments for explicit product mentions (highest signal)
    if additional_comments:
        for pattern, product in _COMMENT_PRODUCT_PATTERNS:
            if pattern.search(additional_comments):
                return product, "comments"

    combined = (vendor + " " + description).lower()
    vendor_lower = vendor.lower()

    # 2. Check for known product names in vendor + description
    for pattern, product in _PRODUCT_NAMES.items():
        if pattern in combined:
            return product, "vendor"

    # 3. Check standing offer number against category mapping
    if standing_offer and standing_offer in _STANDING_OFFER_PRODUCTS:
        return _STANDING_OFFER_PRODUCTS[standing_offer], "so"

    # 4. Check if vendor is a known reseller
    for reseller in _KNOWN_RESELLERS:
        if reseller in vendor_lower:
            # Try to extract product from comments even with lower-signal patterns
            # Then try category from description
            desc_lower = description.lower()
            for pattern, category in _DESC_CATEGORIES.items():
                if pattern in desc_lower:
                    return f"Reseller: {category}", "reseller"
            return "Reseller", "reseller"

    # 5. Extract category from description
    desc_lower = description.lower()
    for pattern, category in _DESC_CATEGORIES.items():
        if pattern in desc_lower:
            return category, "category"

    # 6. Fallback: clean vendor name
    vendor_clean = vendor.strip()
    for suffix in (" INC.", " INC", " LTD.", " LTD", " CORP.", " CORP",
                    " CO.", " LLC", " LP", " S.A.", " CANADA", " CORPORATION",
                    " CONSULTING", " SERVICES", " TECHNOLOGIES", " SOLUTIONS",
                    " GROUP", " INTERNATIONAL", " SYSTEMS"):
        if vendor_clean.upper().endswith(suffix):
            vendor_clean = vendor_clean[:len(vendor_clean) - len(suffix)].strip()
    return (vendor_clean if len(vendor_clean) <= 30 else ""), "fallback"


# ---------------------------------------------------------------------------
# Renewal grouping key
# ---------------------------------------------------------------------------

def _normalize_description(desc: str) -> str:
    """Normalize description for grouping similar contracts."""
    if not desc:
        return ""
    # Lowercase, strip extra whitespace, remove fiscal year references
    d = desc.lower().strip()
    d = re.sub(r"\b\d{4}[-/]\d{2,4}\b", "", d)  # remove year ranges like 2023-2024
    d = re.sub(r"\bfy\s*\d+", "", d)  # remove FY references
    d = re.sub(r"\bq[1-4]\b", "", d)  # remove quarter references
    d = re.sub(r"\s+", " ", d).strip()
    return d


def _safe_project_date(base: date, days: int) -> date | None:
    """Add days to a date, returning None on OverflowError."""
    try:
        return base + timedelta(days=days)
    except OverflowError:
        return None


def _group_key(vendor: str, department: str, description: str) -> str:
    """Generate a grouping key for identifying recurring purchases."""
    v = vendor.lower().strip() if vendor else ""
    d = department.lower().strip() if department else ""
    desc_norm = _normalize_description(description)
    # Truncate description to first 60 chars for grouping (avoids minor wording changes)
    desc_short = desc_norm[:60]
    return f"{v}|||{d}|||{desc_short}"


# ---------------------------------------------------------------------------
# RenewalCalendar
# ---------------------------------------------------------------------------

class RenewalCalendar:
    """Builds renewal projections from the Open Canada contracts CSV."""

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self._renewals: list[dict] = []

    def load_data(self) -> None:
        """Parse contracts CSV and build renewal projections."""
        csv_path = self.data_dir / "contracts.csv"
        if not csv_path.exists():
            return

        # Phase 1: Read all renewable IT contracts and group by vendor+dept+description
        groups: dict[str, list[dict]] = defaultdict(list)

        with open(csv_path, "r", encoding="utf-8-sig", errors="replace") as f:
            reader = csv.DictReader(f)
            for row in reader:
                desc = row.get("description_en", "") or ""
                vendor = (row.get("vendor_name", "") or "").strip()
                if not _is_renewable_it_contract(desc):
                    # Still include if vendor is a known IT/security company
                    vendor_lower = vendor.lower()
                    if not any(pattern in vendor_lower for pattern in KNOWN_CYBER_IT_FIRMS):
                        continue

                delivery = _parse_date(row.get("delivery_date", ""))
                if not delivery:
                    continue  # Can't project renewal without an end date

                contract_start = _parse_date(row.get("contract_period_start", ""))
                contract_date = _parse_date(row.get("contract_date", ""))
                value = _parse_float(row.get("contract_value", ""))
                dept_raw = (row.get("owner_org_title", "") or "").strip()
                # Bilingual: "English Name | French Name" - take English
                department = dept_raw.split("|")[0].strip() if dept_raw else ""
                ref_num = (row.get("\ufeffreference_number", "") or row.get("reference_number", "") or "").strip()
                addl_comments = (row.get("additional_comments_en", "") or "").strip()
                standing_offer = (row.get("standing_offer_number", "") or "").strip()

                if not vendor or not department:
                    continue

                # Use additional_comments if it has product info, append to description
                full_desc = desc
                if addl_comments and len(addl_comments) > 3:
                    full_desc = f"{desc} ({addl_comments})"

                key = _group_key(vendor, department, desc)
                groups[key].append({
                    "vendor": vendor,
                    "department": department,
                    "description": full_desc,
                    "contract_value": value,
                    "contract_period_start": contract_start,
                    "delivery_date": delivery,
                    "contract_date": contract_date,
                    "reference_number": ref_num,
                    "additional_comments": addl_comments,
                    "standing_offer": standing_offer,
                })

        # Phase 2: For each group, compute renewal projection
        today = date.today()
        self._renewals = []

        for key, contracts in groups.items():
            if len(contracts) < 1:
                continue

            # Sort by delivery_date ascending
            contracts.sort(key=lambda c: c["delivery_date"])

            vendor = contracts[-1]["vendor"]  # use most recent name
            department = contracts[-1]["department"]
            description = contracts[-1]["description"]
            last_end = contracts[-1]["delivery_date"]
            total_value = sum(c["contract_value"] for c in contracts)
            last_value = contracts[-1]["contract_value"]
            purchase_count = len(contracts)
            reference_number = contracts[-1].get("reference_number", "")
            additional_comments = contracts[-1].get("additional_comments", "")
            standing_offer = contracts[-1].get("standing_offer", "")

            # Determine typical contract length
            if purchase_count >= 2:
                # Use average gap between delivery dates as the renewal cycle
                gaps = []
                for i in range(1, len(contracts)):
                    prev_end = contracts[i - 1]["delivery_date"]
                    curr_start = contracts[i].get("contract_period_start") or contracts[i]["contract_date"]
                    if curr_start and prev_end:
                        gap = (curr_start - prev_end).days
                        # Only count reasonable gaps (not overlapping or huge gaps)
                        if -30 <= gap <= 180:
                            gaps.append(gap)

                # Calculate typical contract duration from first/last
                durations = []
                for c in contracts:
                    start = c.get("contract_period_start") or c.get("contract_date")
                    if start and c["delivery_date"]:
                        dur = (c["delivery_date"] - start).days
                        if 30 <= dur <= 2000:
                            durations.append(dur)

                if durations:
                    avg_duration = sum(durations) // len(durations)
                else:
                    avg_duration = 365  # default annual

                projected = _safe_project_date(last_end, avg_duration)
                if projected is None:
                    continue
            else:
                # Single purchase: check if contract has start and end to compute duration
                c = contracts[0]
                start = c.get("contract_period_start") or c.get("contract_date")
                if start and c["delivery_date"]:
                    dur = (c["delivery_date"] - start).days
                    if 30 <= dur <= 2000:
                        projected = _safe_project_date(last_end, dur)
                    else:
                        projected = _safe_project_date(last_end, 365)
                else:
                    projected = _safe_project_date(last_end, 365)
                if projected is None:
                    continue

            # Skip renewals projected far in the past (before 120 days ago)
            if projected < today - timedelta(days=120):
                continue

            days_until = (projected - today).days
            engage_by = projected - timedelta(days=120)
            engage_days = (engage_by - today).days
            is_actionable = engage_days <= 30

            norm_dept = normalize_buyer(department)
            relevance = _classify_relevance(vendor)
            product, product_source = _extract_product(
                vendor, description, additional_comments, standing_offer,
            )

            self._renewals.append({
                "vendor": vendor,
                "department": norm_dept,
                "description": description,
                "product": product,
                "product_source": product_source,
                "reference_number": reference_number,
                "last_contract_value": last_value,
                "total_historical_value": total_value,
                "purchase_count": purchase_count,
                "last_end_date": last_end.isoformat(),
                "projected_renewal": projected.isoformat(),
                "days_until_renewal": days_until,
                "engage_by": engage_by.isoformat(),
                "is_actionable": is_actionable,
                "plur_relevance": relevance,
            })

        # Sort by projected renewal date
        self._renewals.sort(key=lambda r: r["projected_renewal"])

    def get_upcoming_renewals(self, days_ahead: int = 365) -> list[dict]:
        """Return renewals coming up in the next N days, sorted by date.

        Each renewal dict contains:
        - vendor: who holds the current contract
        - department: which dept
        - description: what the software/service is
        - last_contract_value: most recent purchase value
        - total_historical_value: sum of all purchases
        - purchase_count: how many times purchased
        - last_end_date: when the current contract ends
        - projected_renewal: estimated renewal date
        - days_until_renewal: days from today
        - engage_by: 120 days before renewal (when PLUR should start outreach)
        - is_actionable: True if engage_by is in the past or within 30 days
        - plur_relevance: HIGH/MEDIUM/LOW
        """
        today = date.today()
        cutoff = today + timedelta(days=days_ahead)
        results = []
        for r in self._renewals:
            proj = date.fromisoformat(r["projected_renewal"])
            if proj <= cutoff:
                # Recalculate days_until and is_actionable (may have changed since load)
                days_until = (proj - today).days
                engage_by = proj - timedelta(days=120)
                engage_days = (engage_by - today).days
                updated = dict(r)
                updated["days_until_renewal"] = days_until
                updated["is_actionable"] = engage_days <= 30
                results.append(updated)
        return results

    def get_renewals_by_vendor(self, vendor_substr: str) -> list[dict]:
        """Find all renewals for a specific vendor (substring match)."""
        lower = vendor_substr.lower()
        return [r for r in self._renewals if lower in r["vendor"].lower()]

    def get_renewals_by_department(self, dept: str) -> list[dict]:
        """Find all renewals at a specific department (substring match)."""
        lower = dept.lower()
        return [r for r in self._renewals if lower in r["department"].lower()]
