"""Enrichment layer: incumbent intelligence, lobbying signals, standing offer detection.

Downloads and indexes Open Canada Contracts + Lobbying Registry CSVs,
then cross-references RFP opportunities to surface competitive intel.
"""

import csv
import io
import logging
import os
import re
import subprocess
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from lib.known_vendors import KNOWN_CYBER_IT_FIRMS, KNOWN_IT_CYBER_FIRMS_EXACT

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Buyer normalization
# ---------------------------------------------------------------------------

# Maps common abbreviations and short names to canonical department names
# used in the Open Canada Contracts dataset.
BUYER_ALIASES: dict[str, str] = {
    # National Defence & Security
    "DND": "Department of National Defence",
    "National Defence": "Department of National Defence",
    "Dept of National Defence": "Department of National Defence",
    "CSE": "Communications Security Establishment",
    "Communications Security Establishment Canada": "Communications Security Establishment",
    "CSIS": "Canadian Security Intelligence Service",
    "RCMP": "Royal Canadian Mounted Police",
    "GRC": "Royal Canadian Mounted Police",
    "CBSA": "Canada Border Services Agency",
    "ASFC": "Canada Border Services Agency",
    "Border Services": "Canada Border Services Agency",

    # Central agencies
    "PSPC": "Public Services and Procurement Canada",
    "PWGSC": "Public Services and Procurement Canada",
    "Public Works": "Public Services and Procurement Canada",
    "SSC": "Shared Services Canada",
    "SPC": "Shared Services Canada",
    "TBS": "Treasury Board of Canada Secretariat",
    "Treasury Board": "Treasury Board of Canada Secretariat",
    "PCO": "Privy Council Office",

    # Revenue & Finance
    "CRA": "Canada Revenue Agency",
    "ARC": "Canada Revenue Agency",
    "Revenue Agency": "Canada Revenue Agency",
    "OSFI": "Office of the Superintendent of Financial Institutions",
    "BDC": "Business Development Bank of Canada",
    "EDC": "Export Development Canada",
    "FINTRAC": "Financial Transactions and Reports Analysis Centre of Canada",
    "Bank of Canada": "Bank of Canada",

    # Social & Employment
    "ESDC": "Employment and Social Development Canada",
    "Service Canada": "Employment and Social Development Canada",
    "EDSC": "Employment and Social Development Canada",
    "IRCC": "Immigration, Refugees and Citizenship Canada",
    "CIC": "Immigration, Refugees and Citizenship Canada",
    "Immigration Canada": "Immigration, Refugees and Citizenship Canada",
    "VAC": "Veterans Affairs Canada",
    "Veterans Affairs": "Veterans Affairs Canada",
    "ISC": "Indigenous Services Canada",
    "CIRNAC": "Crown-Indigenous Relations and Northern Affairs Canada",

    # Innovation & Science
    "ISED": "Innovation, Science and Economic Development Canada",
    "Industry Canada": "Innovation, Science and Economic Development Canada",
    "NRC": "National Research Council Canada",
    "CNRC": "National Research Council Canada",
    "NSERC": "Natural Sciences and Engineering Research Council of Canada",
    "CSA": "Canadian Space Agency",
    "StatCan": "Statistics Canada",
    "Statistics Canada": "Statistics Canada",

    # Foreign Affairs & Trade
    "GAC": "Global Affairs Canada",
    "DFATD": "Global Affairs Canada",
    "Foreign Affairs": "Global Affairs Canada",

    # Health
    "HC": "Health Canada",
    "Health Canada": "Health Canada",
    "PHAC": "Public Health Agency of Canada",
    "CIHR": "Canadian Institutes of Health Research",

    # Transport & Infrastructure
    "TC": "Transport Canada",
    "Transport Canada": "Transport Canada",
    "ECCC": "Environment and Climate Change Canada",
    "Environment Canada": "Environment and Climate Change Canada",
    "NRCan": "Natural Resources Canada",
    "DFO": "Fisheries and Oceans Canada",
    "Fisheries and Oceans": "Fisheries and Oceans Canada",
    "CCG": "Canadian Coast Guard",

    # Justice & Public Safety
    "DOJ": "Department of Justice Canada",
    "Justice Canada": "Department of Justice Canada",
    "PS": "Public Safety Canada",
    "Public Safety": "Public Safety Canada",
    "CSC": "Correctional Service of Canada",
    "Corrections Canada": "Correctional Service of Canada",
    "PBC": "Parole Board of Canada",

    # Other federal
    "AAFC": "Agriculture and Agri-Food Canada",
    "Agriculture Canada": "Agriculture and Agri-Food Canada",
    "PCH": "Canadian Heritage",
    "Canadian Heritage": "Canadian Heritage",
    "INFC": "Infrastructure Canada",
    "CATSA": "Canadian Air Transport Security Authority",
    "NAV Canada": "NAV Canada",
    "CNSC": "Canadian Nuclear Safety Commission",
    "CRTC": "Canadian Radio-television and Telecommunications Commission",
    "OAG": "Office of the Auditor General of Canada",
    "Elections Canada": "Elections Canada",
    "LAC": "Library and Archives Canada",
    "Library and Archives": "Library and Archives Canada",
    "PSPC": "Public Services and Procurement Canada",
    "PPSC": "Public Prosecution Service of Canada",

    # Truncated names from CanadaBuys search results (ellipsis at end)
    "Office of the Superintendent of Financial…": "Office of the Superintendent of Financial Institutions Canada",
    "Department of Public Works and Governmen...": "Public Services and Procurement Canada",
    "Department of Public Works and Government…": "Public Services and Procurement Canada",
    "Department of Employment and Social…": "Employment and Social Development Canada",
    "Department of Fisheries and Oceans (DFO…": "Fisheries and Oceans Canada",
    "Department of Foreign Affairs, Trade and…": "Global Affairs Canada",
    "Foreign Affairs, Trade And Development (…": "Global Affairs Canada",
    "Department of Agriculture and Agri-Food (…": "Agriculture and Agri-Food Canada",
    "Department of National Defence -…": "Department of National Defence",
    "Defence Construction Canada - Ontario…": "Defence Construction Canada",
    "Public Safety and Emergency Preparedness…": "Public Safety Canada",
    "Public Works and Government Services…": "Public Services and Procurement Canada",
    "Shared Services Canada / Public Services…": "Shared Services Canada",
    "Canadian Radio Television and…": "Canadian Radio-television and Telecommunications Commission",
    "Canadian Radio-television and…": "Canadian Radio-television and Telecommunications Commission",
    "Natural Sciences and Engineering Research…": "Natural Sciences and Engineering Research Council of Canada",
    "Economic Development Agency of Canada for…": "Economic Development Agency of Canada for the Regions of Quebec",
    "Federal Economic Development Agency for…": "Federal Economic Development Agency for Southern Ontario",
    "Provincial Health Services Authority (…": "Provincial Health Services Authority",
    "Canada Deposit Insurance Corporation (…": "Canada Deposit Insurance Corporation",
    "Financial Transactions and Reports Analysis…": "Financial Transactions and Reports Analysis Centre of Canada",
    "Registry of the Public Servants…": "Office of the Commissioner of Lobbying of Canada",
    "Information Management & Strategic…": "Shared Services Canada",

    # Provincial (BC health authorities commonly in Bonfire)
    "PHSA": "Provincial Health Services Authority",
    "Fraser Health": "Fraser Health Authority",
    "Interior Health": "Interior Health Authority",
    "Island Health": "Island Health Authority",
    "Northern Health": "Northern Health Authority",
    "BCEHS": "BC Emergency Health Services",
}

# Build reverse lookup: canonical name -> canonical name (identity map)
# so normalize_buyer("Department of National Defence") also works.
_CANONICAL_SET = set(BUYER_ALIASES.values())

# Pre-compute lowercase lookup for case-insensitive matching
_ALIAS_LOWER: dict[str, str] = {k.lower(): v for k, v in BUYER_ALIASES.items()}
_CANONICAL_LOWER: dict[str, str] = {c.lower(): c for c in _CANONICAL_SET}


def normalize_buyer(name: str) -> str:
    """Normalize a buyer name to its canonical form.

    Tries exact alias match, then canonical identity, then case-insensitive
    substring matching against known aliases.

    Returns the canonical name if matched, otherwise the original name stripped.
    """
    name = name.strip()
    if not name:
        return name

    # Exact alias match
    if name in BUYER_ALIASES:
        return BUYER_ALIASES[name]

    # Already canonical
    if name in _CANONICAL_SET:
        return name

    # Case-insensitive alias match
    name_lower = name.lower()
    if name_lower in _ALIAS_LOWER:
        return _ALIAS_LOWER[name_lower]
    if name_lower in _CANONICAL_LOWER:
        return _CANONICAL_LOWER[name_lower]

    return name


# ---------------------------------------------------------------------------
# Standing offers / supply arrangements PLUR is eligible for
# ---------------------------------------------------------------------------

PLUR_STANDING_OFFERS = ["TBIPS", "CSPV", "ProServices", "SLSAs"]

# Keywords that indicate a standing offer or supply arrangement vehicle
SA_KEYWORDS = [
    "TBIPS", "CSPV", "ProServices", "SBIPS", "PASS",
    "standing offer", "supply arrangement",
]

_SA_PATTERNS = [
    re.compile(r"\b" + re.escape(kw) + r"\b", re.IGNORECASE)
    for kw in SA_KEYWORDS
]


def detect_standing_offers(title: str, description: str = "") -> list[str]:
    """Return list of standing offer vehicles mentioned in the text."""
    corpus = f"{title} {description}"
    found = []
    for pattern, kw in zip(_SA_PATTERNS, SA_KEYWORDS):
        if pattern.search(corpus):
            found.append(kw)
    return found


# ---------------------------------------------------------------------------
# Cyber/IT relevance filtering for contracts
# ---------------------------------------------------------------------------

# Keywords to filter contracts CSV down to cyber/IT relevant records.
# We only index records whose description contains at least one of these.
_CYBER_IT_FILTER_KEYWORDS = [
    "cyber", "security", "securite", "IT ", "information technology",
    "software", "logiciel", "network", "reseau", "computer", "informatique",
    "cloud", "data", "donnee", "digital", "numerique", "identity", "identite",
    "access", "acces", "authentication", "threat", "menace", "encryption",
    "chiffrement", "firewall", "antivirus", "SIEM", "SOC", "IAM", "PAM",
    "managed services", "professional services", "consulting",
    "systems integration", "infrastructure",
]

_CYBER_IT_FILTER_RE = re.compile(
    "|".join(re.escape(kw) for kw in _CYBER_IT_FILTER_KEYWORDS),
    re.IGNORECASE,
)

# Pre-compiled regex for extracting 4+ character words (used in scoring loops)
_WORD_RE = re.compile(r"\b\w{4,}\b")

# Commodity codes (GSIN/UNSPSC) that indicate IT/cyber contracts
_IT_COMMODITY_PREFIXES = [
    "D", "N70",  # GSIN: D = IT, N70 = ADP/telecom
    "4323", "8111",  # UNSPSC prefixes for IT/security
]

# Lobbying subject matter codes relevant to cyber/IT.
# Wide intake: all 5 codes that plausibly correlate with cyber/IT/defence vendors.
# The firm-level relevance scoring (vendor name match + keyword match) gates which
# registrations actually appear in results, so broader codes here don't produce noise.
# Excluded: SMT-17 (Government Procurement), SMT-20 (Industry) - too broad.
_LOBBY_RELEVANT_CODES = {
    "SMT-39",  # National Security/Security (highest signal for cyber)
    "SMT-8",   # Defence (DND/defence buyers)
    "SMT-1",   # Telecommunications (network/telecom lobbying)
    "SMT-30",  # Science and Technology (IT/cyber falls here for many firms)
    "SMT-43",  # Privacy and Access to Information (identity/access management)
}

# Score weights for lobbying relevance ranking
_LOBBY_SCORE_EXACT_VENDOR = 5  # Exact match in KNOWN_IT_CYBER_FIRMS_EXACT curated set
_LOBBY_SCORE_FIRM_NAME = 3     # Known IT/cyber/defence vendor name (substring match)
_LOBBY_SCORE_CUSTOM_KW = 2     # Keyword match in CUSTOM_SUBJ_OBJET_PERSO
_SMT_SCORES = {"SMT-39": 2, "SMT-8": 1, "SMT-1": 1, "SMT-30": 1, "SMT-43": 1}

# Keywords for matching against CUSTOM_SUBJ_OBJET_PERSO free text (lowercase)
_LOBBY_CUSTOM_KEYWORDS = {
    "cybersecurity", "cyber", "security", "information technology",
    "it ", "software", "network", "cloud", "identity",
    "access management", "siem", "soc",
}

# Lobbying Registrations ZIP (registrations, NOT communications)
_LOBBYING_REGISTRATIONS_ZIP_URL = (
    "https://lobbycanada.gc.ca/media/zwcjycef/registrations_enregistrements_ocl_cal.zip"
)

# ---------------------------------------------------------------------------
# CSV download + caching
# ---------------------------------------------------------------------------

# Open Canada Contracts dataset ID
_CONTRACTS_DATASET_ID = "d8f85d91-7dec-4fd1-8055-483b77225d8b"
_CONTRACTS_CKAN_URL = (
    f"https://open.canada.ca/data/api/3/action/package_show"
    f"?id={_CONTRACTS_DATASET_ID}"
)
# Direct fallback URL (may change)
_CONTRACTS_DIRECT_URL = (
    "https://open.canada.ca/data/dataset/"
    f"{_CONTRACTS_DATASET_ID}/resource/"
    "fac950c0-00d5-4ec1-a4d3-9cbebf98a305/download/contracts.csv"
)

# Lobbying Registry communications CSV
_LOBBYING_ZIP_URL = (
    "https://lobbycanada.gc.ca/media/mqbbmaqk/communications_ocl_cal.zip"
)

_MAX_CACHE_AGE_SECONDS = 7 * 24 * 3600  # 7 days


def _file_age_seconds(path: Path) -> float:
    """Return age of file in seconds, or inf if missing."""
    if not path.exists():
        return float("inf")
    return time.time() - path.stat().st_mtime


def _download_file(
    url: str,
    dest: Path,
    label: str = "file",
    min_size_bytes: int = 0,
    timeout: int = 600,
) -> bool:
    """Download a file using curl (httpx has issues with large files on this VPS).

    Args:
        url: URL to download.
        dest: Destination path.
        label: Human-readable label for log messages.
        min_size_bytes: If > 0, fail if the downloaded file is smaller than this
            (catches truncated/partial downloads that curl reports as success).
        timeout: subprocess timeout in seconds (default 600 for large files).

    Returns True on success, False on failure.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Download to a temp file first so a failed download never replaces a valid cache
    tmp_dest = dest.with_suffix(dest.suffix + ".tmp")
    logger.info("Downloading %s from %s", label, url)
    t0 = time.time()
    try:
        result = subprocess.run(
            ["curl", "-sS", "--compressed", "-L", "-o", str(tmp_dest), url],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            logger.error("curl failed for %s: %s", label, result.stderr.strip())
            if tmp_dest.exists():
                tmp_dest.unlink()
            return False
        elapsed = time.time() - t0
        size_bytes = tmp_dest.stat().st_size if tmp_dest.exists() else 0
        size_mb = size_bytes / (1024 * 1024)
        if min_size_bytes > 0 and size_bytes < min_size_bytes:
            logger.error(
                "Downloaded %s appears truncated: %.1f MB (expected >= %.1f MB)",
                label,
                size_mb,
                min_size_bytes / (1024 * 1024),
            )
            if tmp_dest.exists():
                tmp_dest.unlink()
            return False
        tmp_dest.rename(dest)
        logger.info(
            "Downloaded %s: %.1f MB in %.1fs", label, size_mb, elapsed
        )
        return True
    except subprocess.TimeoutExpired:
        logger.error("Download timed out for %s (%ds limit)", label, timeout)
        if tmp_dest.exists():
            tmp_dest.unlink()
        return False
    except Exception as exc:
        logger.error("Download error for %s: %s", label, exc)
        if tmp_dest.exists():
            tmp_dest.unlink()
        return False


# ---------------------------------------------------------------------------
# Contract index
# ---------------------------------------------------------------------------

class _ContractRecord:
    """Lightweight container for an indexed contract record."""
    __slots__ = ("vendor", "value", "date", "sole_source", "num_bidders", "description", "reference_number")

    def __init__(
        self,
        vendor: str,
        value: float,
        date: str,
        sole_source: bool,
        num_bidders: int,
        description: str,
        reference_number: str = "",
    ):
        self.vendor = vendor
        self.value = value
        self.date = date
        self.sole_source = sole_source
        self.num_bidders = num_bidders
        self.description = description
        self.reference_number = reference_number


def _parse_float(val: str) -> float:
    """Parse a float from CSV, handling commas and currency symbols."""
    if not val:
        return 0.0
    cleaned = val.replace(",", "").replace("$", "").replace(" ", "").strip()
    try:
        return float(cleaned)
    except (ValueError, TypeError):
        return 0.0


def _parse_int(val: str) -> int:
    """Parse an int from CSV, defaulting to 0."""
    if not val:
        return 0
    try:
        return int(val.strip())
    except (ValueError, TypeError):
        return 0


# ---------------------------------------------------------------------------
# EnrichmentEngine
# ---------------------------------------------------------------------------

class EnrichmentEngine:
    """Cross-references opportunities with contracts and lobbying data."""

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # In-memory indexes (populated by load_data)
        # Key: normalized department name (lowercase)
        # Value: list of _ContractRecord
        self._contracts_by_dept: dict[str, list[_ContractRecord]] = {}

        # Key: normalized institution name (lowercase)
        # Value: list of dicts with firm, subject, date
        self._lobbying_by_dept: dict[str, list[dict]] = {}

        self._loaded = False

    @property
    def contracts_path(self) -> Path:
        return self.data_dir / "contracts.csv"

    @property
    def lobbying_zip_path(self) -> Path:
        return self.data_dir / "lobbying_registrations.zip"

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def load_data(self) -> None:
        """Download (if stale/missing) and index contracts + lobbying CSVs."""
        self._load_contracts()
        self._load_lobbying()
        self._loaded = True

    # Minimum expected size for the full contracts CSV.
    # The full "Contracts over $10,000" dataset is ~600 MB uncompressed.
    # The legacy/truncated file is ~935 KB.  Anything under 50 MB is suspect.
    _CONTRACTS_MIN_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB

    def _load_contracts(self) -> None:
        """Download and index Open Canada Contracts CSV.

        Uses the full proactive disclosure dataset (100K+ records).  The CKAN
        API is queried first to get a signed/current download URL; the known
        direct URL is used as a fallback.

        A minimum-size guard ensures a truncated download never masquerades as
        a valid cache.
        """
        # If the cached file is suspiciously small it is almost certainly the
        # legacy 935 KB file (resource 7f9b18ca) or a truncated download,
        # rather than the full ~600 MB proactive disclosure dataset
        # (resource fac950c0, 100K+ records).  Delete it unconditionally so the
        # download logic below fetches the correct file.
        # _CONTRACTS_MIN_SIZE_BYTES can be patched to 0 in tests so that
        # small fixture CSVs are left untouched.
        if (
            self.contracts_path.exists()
            and self._CONTRACTS_MIN_SIZE_BYTES > 0
            and self.contracts_path.stat().st_size < self._CONTRACTS_MIN_SIZE_BYTES
        ):
            logger.warning(
                "Cached contracts CSV is only %.1f MB - looks like the legacy/"
                "file or a truncated download. Deleting to force full re-download.",
                self.contracts_path.stat().st_size / (1024 * 1024),
            )
            self.contracts_path.unlink()

        age = _file_age_seconds(self.contracts_path)
        if age < _MAX_CACHE_AGE_SECONDS:
            logger.info(
                "Contracts CSV is %.1f days old (%.1f MB), using cache",
                age / 86400,
                self.contracts_path.stat().st_size / (1024 * 1024),
            )
        else:
            # Try CKAN API first to get current resource URL
            url = self._resolve_contracts_url()
            ok = _download_file(
                url,
                self.contracts_path,
                "contracts CSV",
                min_size_bytes=self._CONTRACTS_MIN_SIZE_BYTES,
                timeout=600,
            )
            if not ok:
                if url != _CONTRACTS_DIRECT_URL:
                    logger.warning("CKAN URL failed, trying direct fallback URL")
                    ok = _download_file(
                        _CONTRACTS_DIRECT_URL,
                        self.contracts_path,
                        "contracts CSV (direct fallback)",
                        min_size_bytes=self._CONTRACTS_MIN_SIZE_BYTES,
                        timeout=600,
                    )
                if not ok:
                    logger.error("Failed to download contracts CSV from all URLs")
                    return

        self._index_contracts()

    def _resolve_contracts_url(self) -> str:
        """Use CKAN API to find the current CSV resource URL.

        The CKAN dataset contains multiple CSV resources (legacy data, nil reports,
        aggregated totals, and the full proactive disclosure dataset).  We must
        select the correct one: "Contracts over $10,000" (resource
        fac950c0-00d5-4ec1-a4d3-9cbebf98a305), which is the full 100K+ record
        dataset.  Simply picking the first CSV resource returns the legacy file
        (~935 KB, ~2 K records) instead.
        """
        _PREFERRED_RESOURCE_ID = "fac950c0-00d5-4ec1-a4d3-9cbebf98a305"
        _PREFERRED_RESOURCE_NAME = "Contracts over $10,000"

        try:
            import json as _json
            result = subprocess.run(
                ["curl", "-sS", "-L", "--max-time", "30", _CONTRACTS_CKAN_URL],
                capture_output=True,
                text=True,
                timeout=35,
            )
            if result.returncode == 0 and result.stdout.strip():
                data = _json.loads(result.stdout)
                if data.get("success"):
                    resources = data.get("result", {}).get("resources", [])

                    # Pass 1: prefer by known resource ID
                    for r in resources:
                        if r.get("id", "") == _PREFERRED_RESOURCE_ID:
                            url = r.get("url", "")
                            if url:
                                logger.info(
                                    "Resolved contracts CSV URL via CKAN (by ID): %s", url
                                )
                                return url

                    # Pass 2: prefer by name match (case-insensitive), skip
                    # legacy/nil/aggregated variants
                    for r in resources:
                        name = r.get("name", "")
                        if (
                            r.get("format", "").upper() == "CSV"
                            and _PREFERRED_RESOURCE_NAME.lower() in name.lower()
                            and "legacy" not in name.lower()
                            and "nil" not in name.lower()
                            and "aggregated" not in name.lower()
                        ):
                            url = r.get("url", "")
                            if url:
                                logger.info(
                                    "Resolved contracts CSV URL via CKAN (by name): %s", url
                                )
                                return url
        except Exception as exc:
            logger.warning("CKAN API lookup failed: %s", exc)

        logger.info("Using direct contracts CSV URL (CKAN unavailable)")
        return _CONTRACTS_DIRECT_URL

    def _index_contracts(self) -> None:
        """Parse contracts CSV and build in-memory index by department."""
        if not self.contracts_path.exists():
            logger.warning("Contracts CSV not found at %s", self.contracts_path)
            return

        t0 = time.time()
        count = 0
        skipped = 0
        self._contracts_by_dept.clear()

        try:
            with open(self.contracts_path, encoding="utf-8-sig", errors="replace") as f:
                reader = csv.DictReader(f)
                if reader.fieldnames is None:
                    logger.error("Contracts CSV has no header row")
                    return

                # Log available columns for debugging
                logger.debug("Contracts CSV columns: %s", reader.fieldnames)

                for row in reader:
                    # Filter to cyber/IT relevant contracts
                    desc = row.get("description_en", "") or row.get("description_fr", "") or ""
                    commodity = row.get("commodity_code", "") or ""
                    vendor = row.get("vendor_name", "") or ""

                    # Skip if not IT/cyber relevant
                    is_it = False
                    if _CYBER_IT_FILTER_RE.search(desc):
                        is_it = True
                    elif any(commodity.startswith(p) for p in _IT_COMMODITY_PREFIXES):
                        is_it = True

                    if not is_it:
                        skipped += 1
                        continue

                    dept_raw = row.get("owner_org_title", "") or row.get("owner_org", "") or ""
                    if not dept_raw:
                        continue

                    # The proactive disclosure CSV uses bilingual dept names:
                    # "National Defence | Défense nationale".  Strip the French
                    # portion and normalize to canonical English names so the
                    # lookup keys match what normalize_buyer() produces.
                    dept_en = dept_raw.split("|")[0].strip()
                    dept = normalize_buyer(dept_en) or dept_en

                    value = _parse_float(
                        row.get("contract_value", "") or row.get("original_value", "") or ""
                    )
                    date = row.get("contract_date", "") or row.get("contract_period_start", "") or ""
                    procedure = (row.get("solicitation_procedure", "") or "").lower()
                    sole_source = "non-competitive" in procedure or "sole source" in procedure
                    num_bidders = _parse_int(row.get("number_of_bids", "") or "")

                    dept_key = dept.lower().strip()
                    ref_number = (row.get("reference_number", "") or "").strip()

                    rec = _ContractRecord(
                        vendor=vendor.strip(),
                        value=value,
                        date=date.strip(),
                        sole_source=sole_source,
                        num_bidders=num_bidders,
                        description=desc.strip(),
                        reference_number=ref_number,
                    )
                    self._contracts_by_dept.setdefault(dept_key, []).append(rec)
                    count += 1

        except Exception as exc:
            logger.error("Error indexing contracts CSV: %s", exc)
            return

        elapsed = time.time() - t0
        logger.info(
            "Indexed %d IT/cyber contracts across %d departments (skipped %d non-IT) in %.1fs",
            count,
            len(self._contracts_by_dept),
            skipped,
            elapsed,
        )

    def _load_lobbying(self) -> None:
        """Download lobbying registrations ZIP and index it.

        The ZIP contains multiple CSVs that must be joined by REG_ID_ENR:
        - Registration_SubjectMattersExport.csv (filter by relevant codes)
        - Registration_PrimaryExport.csv (firm/client names)
        - Registration_GovernmentInstExport.csv (target institutions)
        - Codes_SubjectMatterTypesExport.csv (code descriptions)
        """
        age = _file_age_seconds(self.lobbying_zip_path)
        if age < _MAX_CACHE_AGE_SECONDS:
            logger.info(
                "Lobbying ZIP is %.1f days old, using cache", age / 86400
            )
        else:
            success = _download_file(
                _LOBBYING_REGISTRATIONS_ZIP_URL,
                self.lobbying_zip_path,
                label="lobbying registrations ZIP",
                min_size_bytes=10 * 1024 * 1024,
            )
            if not success:
                logger.error("Failed to download lobbying registrations ZIP")
                return

        self._index_lobbying()

    def _index_lobbying(self) -> None:
        """Parse lobbying ZIP and build in-memory index by institution.

        Joins 3 CSVs by REG_ID_ENR:
        1. Filter SubjectMatters to relevant codes -> set of REG_IDs
        2. Look up firm names from PrimaryExport for those REG_IDs
        3. Look up target institutions from GovernmentInstExport for those REG_IDs
        4. Build _lobbying_by_dept: institution -> [{firm, subject, date}]
        """
        if not self.lobbying_zip_path.exists():
            logger.warning("Lobbying ZIP not found at %s", self.lobbying_zip_path)
            return

        t0 = time.time()
        self._lobbying_by_dept.clear()

        try:
            with zipfile.ZipFile(self.lobbying_zip_path, "r") as zf:
                # Step 0: Load subject matter code descriptions
                code_descs = self._read_subject_code_descriptions(zf)

                # Step 1: Find REG_IDs with relevant subject matter codes
                # reg_id -> set of subject codes
                relevant_regs = self._read_relevant_subject_matters(zf)
                logger.info(
                    "Found %d registrations with relevant subject matter codes",
                    len(relevant_regs),
                )

                if not relevant_regs:
                    return

                # Step 2: Look up firm/client names for relevant REG_IDs
                # reg_id -> firm name
                firm_names = self._read_firm_names(zf, set(relevant_regs.keys()))

                # Step 3: Look up institutions for relevant REG_IDs
                # Build the final index
                count = self._read_institutions_and_build_index(
                    zf, relevant_regs, firm_names, code_descs
                )

        except Exception as exc:
            logger.error("Error indexing lobbying ZIP: %s", exc)
            return

        elapsed = time.time() - t0
        logger.info(
            "Indexed %d lobbying registrations across %d departments in %.1fs",
            count,
            len(self._lobbying_by_dept),
            elapsed,
        )

    def _read_subject_code_descriptions(
        self, zf: zipfile.ZipFile
    ) -> dict[str, str]:
        """Read Codes_SubjectMatterTypesExport.csv -> {code: description}."""
        result: dict[str, str] = {}
        try:
            with zf.open("Codes_SubjectMatterTypesExport.csv") as f:
                reader = csv.DictReader(
                    io.TextIOWrapper(f, encoding="latin-1", errors="replace")
                )
                for row in reader:
                    code = (row.get("SUBJECT_CODE_OBJET") or "").strip()
                    desc = (row.get("SMT_EN_DESC") or "").strip()
                    if code and desc:
                        result[code] = desc
        except KeyError:
            logger.warning("Codes_SubjectMatterTypesExport.csv not found in ZIP")
        return result

    def _read_relevant_subject_matters(
        self, zf: zipfile.ZipFile
    ) -> dict[str, dict]:
        """Read SubjectMatters CSV, return {reg_id: {codes: set, custom_text: str}}.

        Only includes registrations with relevant subject matter codes.
        Also captures the CUSTOM_SUBJ_OBJET_PERSO free-text field for keyword scoring.
        """
        result: dict[str, dict] = {}
        with zf.open("Registration_SubjectMattersExport.csv") as f:
            reader = csv.DictReader(
                io.TextIOWrapper(f, encoding="latin-1", errors="replace")
            )
            total = 0
            for row in reader:
                total += 1
                code = (row.get("SUBJECT_CODE_OBJET") or "").strip()
                if code in _LOBBY_RELEVANT_CODES:
                    reg_id = (row.get("REG_ID_ENR") or "").strip()
                    if reg_id:
                        if reg_id not in result:
                            result[reg_id] = {"codes": set(), "custom_text": ""}
                        result[reg_id]["codes"].add(code)
                        custom = (row.get("CUSTOM_SUBJ_OBJET_PERSO") or "").strip()
                        if custom:
                            existing = result[reg_id]["custom_text"]
                            result[reg_id]["custom_text"] = (
                                f"{existing} {custom}" if existing else custom
                            )
        logger.info(
            "Scanned %d subject matter rows, %d relevant",
            total,
            sum(len(v["codes"]) for v in result.values()),
        )
        return result

    def _read_firm_names(
        self, zf: zipfile.ZipFile, relevant_ids: set[str]
    ) -> dict[str, dict]:
        """Read PrimaryExport CSV, return {reg_id: {name, effective_date}} for relevant IDs."""
        result: dict[str, dict] = {}
        with zf.open("Registration_PrimaryExport.csv") as f:
            reader = csv.DictReader(
                io.TextIOWrapper(f, encoding="latin-1", errors="replace")
            )
            total = 0
            for row in reader:
                total += 1
                reg_id = (row.get("REG_ID_ENR") or "").strip()
                if reg_id not in relevant_ids:
                    continue
                # Use client org name first (who is being represented),
                # fall back to firm name (the lobbying firm itself)
                name = (row.get("EN_CLIENT_ORG_CORP_NM_AN") or "").strip()
                if not name or name == "null":
                    name = (row.get("EN_FIRM_NM_FIRME_AN") or "").strip()
                if not name or name == "null":
                    name = (row.get("FR_CLIENT_ORG_CORP_NM") or "").strip()
                if name and name != "null":
                    effective = (row.get("EFFECTIVE_DATE_VIGUEUR") or "").strip()
                    if effective == "null":
                        effective = ""
                    result[reg_id] = {"name": name, "effective_date": effective}
        logger.info(
            "Scanned %d primary registrations, found names for %d relevant",
            total,
            len(result),
        )
        return result

    def _read_institutions_and_build_index(
        self,
        zf: zipfile.ZipFile,
        relevant_regs: dict[str, dict],
        firm_names: dict[str, dict],
        code_descs: dict[str, str],
    ) -> int:
        """Read GovernmentInstExport CSV and build _lobbying_by_dept index.

        Returns count of indexed entries.
        """
        count = 0
        with zf.open("Registration_GovernmentInstExport.csv") as f:
            reader = csv.DictReader(
                io.TextIOWrapper(f, encoding="latin-1", errors="replace")
            )
            for row in reader:
                reg_id = (row.get("REG_ID_ENR") or "").strip()
                if reg_id not in relevant_regs:
                    continue

                institution = (row.get("INSTITUTION") or "").strip()
                if not institution:
                    continue

                firm_info = firm_names.get(reg_id)
                if not firm_info:
                    continue
                firm = firm_info["name"]
                effective_date = firm_info.get("effective_date", "")

                reg_info = relevant_regs[reg_id]
                custom_text = reg_info.get("custom_text", "")

                # Create one entry per subject code for this registration
                for code in reg_info["codes"]:
                    desc = code_descs.get(code, code)
                    dept_key = institution.lower().strip()
                    entry = {
                        "firm": firm,
                        "subject": desc,
                        "subject_code": code,
                        "custom_text": custom_text,
                        "date": effective_date,
                    }
                    self._lobbying_by_dept.setdefault(dept_key, []).append(entry)
                    count += 1

        return count

    # ------------------------------------------------------------------
    # Enrichment query
    # ------------------------------------------------------------------

    def enrich(
        self,
        buyer: str,
        title: str,
        description: str = "",
    ) -> dict:
        """Return enrichment data for an opportunity.

        Args:
            buyer: The buying organization name.
            title: Opportunity title.
            description: Opportunity description.

        Returns:
            {
                "incumbent": {"vendor": str, "value": float, "date": str,
                              "sole_source": bool, "num_bidders": int} or None,
                "similar_awards": [{"vendor": str, "value": float, ...}],
                "competitive_landscape": {
                    "top_competitors": [{"vendor": str, "wins": int, "total_value": float}],
                    "avg_award_value": float,
                    "num_similar_awards": int,
                },
                "lobbying": [{"firm": str, "subject": str, "date": str}],
                "standing_offers": ["TBIPS", ...],
            }
        """
        result: dict = {
            "incumbent": None,
            "similar_awards": [],
            "competitive_landscape": {
                "top_competitors": [],
                "avg_award_value": 0.0,
                "num_similar_awards": 0,
            },
            "lobbying": [],
            "standing_offers": [],
        }

        # Standing offers (always runs, no data dependency)
        result["standing_offers"] = detect_standing_offers(title, description)

        if not buyer:
            return result

        # Normalize buyer
        canonical = normalize_buyer(buyer)
        buyer_key = canonical.lower().strip()

        # Rank contracts once, share results between incumbent + similar awards
        ranked = self._rank_contract_matches(buyer_key, title, description, department_name=canonical)

        # Find incumbent contracts
        incumbent = self._find_incumbent(buyer_key, title, description, ranked=ranked)
        if incumbent:
            result["incumbent"] = incumbent

        similar_awards = self.find_similar_awards(buyer, title, description, ranked=ranked)
        if similar_awards:
            result["similar_awards"] = similar_awards
            result["competitive_landscape"] = self._build_competitive_landscape(similar_awards)

        # Find lobbying signals for all tiers - T3 opportunities also benefit
        # from knowing who is lobbying the buyer department on related subjects.
        lobbying = self._find_lobbying(buyer_key, title, description)
        if lobbying:
            result["lobbying"] = lobbying

        return result

    # Stopwords excluded from incumbent keyword overlap counting.
    # Generic words that match everything and create false positive incumbents.
    _INCUMBENT_STOPWORDS = frozenset({
        # English stopwords
        "the", "and", "of", "for", "to", "in", "a", "an", "is", "are",
        "was", "were", "be", "been", "being", "have", "has", "had",
        "do", "does", "did", "will", "would", "could", "should", "may",
        "might", "shall", "can", "it", "its", "this", "that", "with",
        "from", "by", "on", "at", "or", "as", "if", "but", "not", "no",
        "all", "any", "each", "every", "both", "few", "more", "most",
        "other", "some", "such", "than", "too", "very", "just", "also",
        # Generic procurement terms (match everything, add no signal)
        "services", "service", "canada", "government", "federal",
        "department", "support", "management", "system", "systems",
        "solution", "solutions", "project", "national", "information",
        "technology", "provision", "procurement", "professional",
        "consulting", "consultant", "consultants", "contract", "contracts",
        "agreement", "renewal", "maintenance", "annual", "program",
        "programme", "office", "agency", "corporation", "institute",
        "centre", "center", "infrastructure", "equipment", "supply",
        "delivery", "implementation", "development", "operations",
        "operational", "resources", "resource", "general", "related",
        "various", "miscellaneous", "other", "request", "proposal",
        "notice", "requirement", "requirements", "acquisition",
        "amendment", "phase", "period", "year", "years", "month",
        "fiscal", "quarterly", "ongoing", "temporary", "term",
        "long", "short", "based", "level", "type", "category",
        "products", "product", "platform", "tools", "tool",
        "data", "digital", "integrated", "enterprise", "corporate",
        # French generic terms
        "pour", "dans", "avec", "des", "les", "une", "aux",
        "sont", "être", "avoir", "plus", "entre", "comme",
        "mise", "oeuvre", "travaux", "fourniture", "acquisition",
    })

    def _find_incumbent(
        self,
        buyer_key: str,
        title: str = "",
        description: str = "",
        ranked: list[dict] | None = None,
    ) -> Optional[dict]:
        """Find the most relevant historical contract for this buyer + topic.

        Scores each candidate contract by keyword overlap between the opportunity
        text and the contract description.  Relevance dominates: a satellite
        contract must not appear as incumbent for a file-transfer or
        virtualization RFP at the same department.

        Scoring formula:
            score = meaningful_overlap * 2 + min((contract_value / 1M) * 0.1, 2.0)

        Stopwords (generic IT/gov terms) are excluded from overlap counting.
        Minimum threshold: overlap >= 3 meaningful words.
        Product name bonus: if the opportunity title contains a specific product
        name that also appears in a contract description, that contract gets a
        large bonus (+10) to prioritize exact product matches.
        """
        if ranked is None:
            ranked = self._rank_contract_matches(buyer_key, title, description)
        if not ranked:
            return None

        best = ranked[0]
        best_contract = best["contract"]
        best_overlap = best["overlap"]

        # Require at least 3 meaningful (non-stopword) overlapping words.
        # Prevents high-value but off-topic contracts from winning on value alone.
        if best_contract is None or best_overlap < 3:
            return None

        return self._contract_to_dict(best_contract)

    def find_similar_awards(
        self,
        buyer: str,
        title: str,
        description: str = "",
        ranked: list[dict] | None = None,
    ) -> list[dict]:
        """Find similar past awarded contracts across all departments.

        Searches the buyer's own department first (most relevant), then
        searches across all other departments for contracts with high
        keyword overlap (4+ meaningful words required for cross-dept matches).
        Returns up to 10 results, deduplicated by reference_number.
        Each result includes a 'department' field.
        """
        if not buyer:
            return []

        canonical = normalize_buyer(buyer)
        buyer_key = canonical.lower().strip()

        if ranked is None:
            ranked = self._rank_contract_matches(buyer_key, title, description, department_name=canonical)

        # Collect same-department results (overlap >= 1)
        seen_refs: set[str] = set()
        similar_awards = []
        for match in ranked:
            if match["overlap"] <= 0:
                continue
            ref = match["contract"].reference_number
            if ref and ref in seen_refs:
                continue
            award = self._contract_to_dict(match["contract"])
            award["description"] = match["contract"].description[:200].strip()
            award["overlap_score"] = match["score"]
            award["department"] = match.get("department", canonical)
            similar_awards.append(award)
            if ref:
                seen_refs.add(ref)

        # Search cross-department (require 4+ meaningful word overlap)
        words, product_names = self._extract_contract_match_terms(title, description)
        cross_dept_min_overlap = 4

        for dept_key, contracts in self._contracts_by_dept.items():
            if dept_key == buyer_key:
                continue
            # Quick check: skip departments with no potential matches.
            # Score first few contracts; if none have any overlap, skip dept.
            found_any = False
            for rec in contracts:
                if not rec.vendor:
                    continue
                desc_all = set(_WORD_RE.findall(rec.description.lower()))
                desc_words = desc_all - self._INCUMBENT_STOPWORDS
                overlap_words = words & desc_words
                overlap = len(overlap_words)
                if overlap < cross_dept_min_overlap:
                    continue

                ref = rec.reference_number
                if ref and ref in seen_refs:
                    continue

                found_any = True
                product_bonus = 0.0
                if product_names:
                    matched_products = product_names & desc_all
                    if matched_products:
                        product_bonus = 10.0 * len(matched_products)

                value_bonus = min((rec.value / 1_000_000) * 0.1, 2.0) if rec.value > 0 else 0.0
                score = overlap * 2 + value_bonus + product_bonus

                # Resolve department display name from key
                dept_display = dept_key.title()
                for alias_val in _CANONICAL_SET:
                    if alias_val.lower() == dept_key:
                        dept_display = alias_val
                        break

                award = self._contract_to_dict(rec)
                award["description"] = rec.description[:200].strip()
                award["overlap_score"] = score
                award["department"] = dept_display
                similar_awards.append(award)
                if ref:
                    seen_refs.add(ref)

        # Sort all results by overlap_score descending
        similar_awards.sort(key=lambda a: a["overlap_score"], reverse=True)
        return similar_awards[:10]

    def _rank_contract_matches(
        self,
        buyer_key: str,
        title: str = "",
        description: str = "",
        department_name: str = "",
    ) -> list[dict]:
        """Return contracts ranked by overlap/value relevance for an opportunity."""
        contracts = self._contracts_by_dept.get(buyer_key, [])
        if not contracts:
            return []

        words, product_names = self._extract_contract_match_terms(title, description)
        ranked = []

        for rec in contracts:
            if not rec.vendor:
                continue
            desc_all = set(_WORD_RE.findall( rec.description.lower()))
            desc_words = desc_all - self._INCUMBENT_STOPWORDS
            overlap_words = words & desc_words
            overlap = len(overlap_words)

            product_bonus = 0.0
            if product_names:
                matched_products = product_names & desc_all
                if matched_products:
                    product_bonus = 10.0 * len(matched_products)

            value_bonus = min((rec.value / 1_000_000) * 0.1, 2.0) if rec.value > 0 else 0.0
            score = overlap * 2 + value_bonus + product_bonus
            ranked.append({
                "contract": rec,
                "score": score,
                "overlap": overlap,
                "department": department_name,
            })

        ranked.sort(
            key=lambda item: (
                item["score"],
                item["overlap"],
                item["contract"].value,
                item["contract"].date,
            ),
            reverse=True,
        )
        return ranked

    def _extract_contract_match_terms(
        self,
        title: str = "",
        description: str = "",
    ) -> tuple[set[str], set[str]]:
        """Build opportunity keyword sets used for contract relevance scoring."""
        corpus = f"{title} {description}".lower()
        all_words = set(_WORD_RE.findall( corpus))
        words = all_words - self._INCUMBENT_STOPWORDS

        title_tokens = re.findall(r"\b[A-Z][A-Za-z]{3,}\b", title)
        product_names = {t.lower() for t in title_tokens} - self._INCUMBENT_STOPWORDS
        return words, product_names

    @staticmethod
    def _contract_to_dict(contract: _ContractRecord) -> dict:
        return {
            "vendor": contract.vendor,
            "value": contract.value,
            "date": contract.date,
            "sole_source": contract.sole_source,
            "num_bidders": contract.num_bidders,
            "reference_number": contract.reference_number,
        }

    @staticmethod
    def _build_competitive_landscape(similar_awards: list[dict]) -> dict:
        """Aggregate similar-award results into a competitive landscape summary."""
        if not similar_awards:
            return {
                "top_competitors": [],
                "avg_award_value": 0.0,
                "num_similar_awards": 0,
            }

        vendors: dict[str, dict] = {}
        total_value = 0.0

        for award in similar_awards:
            vendor = award.get("vendor") or "Unknown"
            value = float(award.get("value") or 0.0)
            total_value += value

            if vendor not in vendors:
                vendors[vendor] = {"vendor": vendor, "wins": 0, "total_value": 0.0}
            vendors[vendor]["wins"] += 1
            vendors[vendor]["total_value"] += value

        top_competitors = sorted(
            vendors.values(),
            key=lambda item: (item["wins"], item["total_value"], item["vendor"]),
            reverse=True,
        )[:5]

        return {
            "top_competitors": top_competitors,
            "avg_award_value": total_value / len(similar_awards),
            "num_similar_awards": len(similar_awards),
        }

    @staticmethod
    def _opportunity_is_it_relevant(title: str, description: str) -> bool:
        """Return True if the opportunity text contains IT/cyber keywords.

        Used to gate lobbying enrichment: non-IT opportunities (street sweepers,
        construction, cleaning) should not get lobbying signals from IT/cyber
        firms that happen to lobby the same department.
        """
        corpus = f"{title} {description}"
        return bool(_CYBER_IT_FILTER_RE.search(corpus))

    def _find_lobbying(
        self,
        buyer_key: str,
        title: str = "",
        description: str = "",
    ) -> list[dict]:
        """Find lobbying registrations relevant to this department and opportunity.

        Two-layer relevance filtering:
        1. Gate: skip lobbying entirely if the opportunity has no IT/cyber keywords
           (prevents defence contractors showing on "Street Sweeper" RFPs at DND).
        2. Score: rank firms by both generic IT/cyber signals AND opportunity-specific
           keyword overlap with the firm's lobbying subject text. The overlap score
           differentiates results across different RFPs at the same department.

        Scoring formula per firm:
        - Known IT/cyber/defence vendor name match (+3)
        - Generic cyber keyword in CUSTOM_SUBJ_OBJET_PERSO (+2)
        - Subject matter code bonus (SMT-39: +2, others: +1)
        - Opportunity-specific keyword overlap with custom text (+1 per word, max +3)

        Only returns registrations with score > 0, sorted by (score, overlap) desc,
        max 5 results. Filters to registrations from the last 3 years.
        """
        # Gate: non-IT opportunities get zero lobbying signals.
        # A "Street Sweeper" at DND should not surface Raytheon/CAE/CrowdStrike
        # just because they lobby DND on defence/security topics.
        if not self._opportunity_is_it_relevant(title, description):
            return []

        entries = self._lobbying_by_dept.get(buyer_key, [])
        if not entries:
            # Try partial matching (the lobbying CSV may use slightly different dept names)
            for dept_key, dept_entries in self._lobbying_by_dept.items():
                if buyer_key in dept_key or dept_key in buyer_key:
                    entries = dept_entries
                    break

        if not entries:
            return []

        # Build opportunity keyword set for matching
        opp_corpus = f"{title} {description}".lower()
        opp_words = set(_WORD_RE.findall( opp_corpus))

        # Date cutoff: 3 years ago
        cutoff = datetime.now(timezone.utc).year - 3
        cutoff_str = f"{cutoff}-01-01"

        # scored entries: (base_score, opp_overlap, result_dict)
        scored: list[tuple[int, int, dict]] = []
        seen_firms: set[str] = set()

        for entry in entries:
            firm = entry["firm"]
            firm_lower = firm.lower()

            # Deduplicate by firm (keep highest-scoring entry per firm)
            if firm_lower in seen_firms:
                continue

            # Date filtering: skip registrations older than 3 years
            entry_date = entry.get("date", "")
            if entry_date and entry_date < cutoff_str:
                continue

            score = 0
            has_content_signal = False  # vendor name or keyword match (not just a code)

            # Score: exact match in curated KNOWN_IT_CYBER_FIRMS_EXACT set (+5, highest signal)
            if firm in KNOWN_IT_CYBER_FIRMS_EXACT or firm.strip() in KNOWN_IT_CYBER_FIRMS_EXACT:
                score += _LOBBY_SCORE_EXACT_VENDOR
                has_content_signal = True
            # Score: substring match against known vendor names (+3, fallback for variants)
            elif any(vendor_substr in firm_lower for vendor_substr in KNOWN_CYBER_IT_FIRMS):
                score += _LOBBY_SCORE_FIRM_NAME
                has_content_signal = True

            # Score: custom subject keyword match (+2)
            custom_text = (entry.get("custom_text", "") or "").lower()
            if custom_text and any(kw in custom_text for kw in _LOBBY_CUSTOM_KEYWORDS):
                score += _LOBBY_SCORE_CUSTOM_KW
                has_content_signal = True

            # Score: subject matter codes (only count as bonus on top of content signals)
            code = entry.get("subject_code", "")
            score += _SMT_SCORES.get(code, 0)

            # Opportunity-specific relevance: keyword overlap between the
            # opportunity text and the firm's lobbying subject description.
            # This is the key differentiator that prevents identical results
            # across different RFPs at the same department.
            opp_overlap = 0
            if custom_text and opp_words:
                custom_words = set(_WORD_RE.findall( custom_text))
                opp_overlap = len(opp_words & custom_words)
                if opp_overlap >= 1:
                    has_content_signal = True
                    # +1 per overlapping word, max +3
                    score += min(opp_overlap, 3)

            # Firm name overlap: if the firm's name contains words from the
            # opportunity text, boost score. This differentiates "Nutanix" for
            # a Nutanix renewal vs. "IBM" for the same RFP.
            firm_words = set(_WORD_RE.findall( firm_lower))
            firm_opp_overlap = len(opp_words & firm_words)
            if firm_opp_overlap >= 1:
                score += firm_opp_overlap * 2
                opp_overlap += firm_opp_overlap

            # Require at least one content-level signal (vendor name or keyword match).
            # A bare subject matter code is not enough, that's what caused the
            # DaimlerChrysler/Enbridge garbage results.
            if not has_content_signal or score <= 0:
                continue

            seen_firms.add(firm_lower)
            scored.append((score, opp_overlap, {
                "firm": firm,
                "subject": entry.get("subject", ""),
                "date": entry_date,
                "score": score,
            }))

        # Sort by (score desc, opp_overlap desc) so opportunity-specific
        # relevance breaks ties between firms with equal generic scores.
        scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
        return [item[2] for item in scored[:5]]
