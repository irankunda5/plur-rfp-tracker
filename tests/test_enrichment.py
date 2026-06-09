"""Tests for lib/enrichment.py - enrichment layer."""

import csv
import io
import os
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from lib.enrichment import (
    BUYER_ALIASES,
    EnrichmentEngine,
    SA_KEYWORDS,
    detect_standing_offers,
    normalize_buyer,
    _parse_float,
    _parse_int,
    _file_age_seconds,
    _CYBER_IT_FILTER_RE,
    _LOBBY_RELEVANT_CODES,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _write_contracts_csv(path: Path, rows: list[dict]) -> None:
    """Write a minimal contracts CSV fixture."""
    fieldnames = [
        "vendor_name", "contract_value", "description_en", "commodity_code",
        "owner_org_title", "contract_date", "solicitation_procedure",
        "number_of_bids", "reference_number",
    ]
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            full_row = {k: "" for k in fieldnames}
            full_row.update(row)
            writer.writerow(full_row)


def _make_csv_bytes(fieldnames: list[str], rows: list[dict], encoding: str = "latin-1") -> bytes:
    """Build CSV bytes from fieldnames and row dicts."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
    writer.writeheader()
    for row in rows:
        full = {k: "" for k in fieldnames}
        full.update(row)
        writer.writerow(full)
    return buf.getvalue().encode(encoding, errors="replace")


def _write_lobbying_zip(
    zip_path: Path,
    primary_rows: list[dict],
    subject_rows: list[dict],
    govt_inst_rows: list[dict],
    code_rows: list[dict] | None = None,
) -> None:
    """Write a lobbying registrations ZIP fixture with joined CSVs.

    Each list contains dicts with the relevant columns for that CSV.
    """
    if code_rows is None:
        # Default code lookup
        code_rows = [
            {"SUBJECT_CODE_OBJET": "SMT-1", "SMT_EN_DESC": "Telecommunications", "SMT_FR_DESC": ""},
            {"SUBJECT_CODE_OBJET": "SMT-8", "SMT_EN_DESC": "Defence", "SMT_FR_DESC": ""},
            {"SUBJECT_CODE_OBJET": "SMT-17", "SMT_EN_DESC": "Government Procurement", "SMT_FR_DESC": ""},
            {"SUBJECT_CODE_OBJET": "SMT-30", "SMT_EN_DESC": "Science and Technology", "SMT_FR_DESC": ""},
            {"SUBJECT_CODE_OBJET": "SMT-39", "SMT_EN_DESC": "National Security/Security", "SMT_FR_DESC": ""},
            {"SUBJECT_CODE_OBJET": "SMT-43", "SMT_EN_DESC": "Privacy and Access to Information", "SMT_FR_DESC": ""},
            {"SUBJECT_CODE_OBJET": "SMT-3", "SMT_EN_DESC": "Agriculture", "SMT_FR_DESC": ""},
        ]

    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr(
            "Codes_SubjectMatterTypesExport.csv",
            _make_csv_bytes(
                ["SUBJECT_CODE_OBJET", "SMT_EN_DESC", "SMT_FR_DESC"],
                code_rows,
            ),
        )
        zf.writestr(
            "Registration_SubjectMattersExport.csv",
            _make_csv_bytes(
                ["REG_ID_ENR", "SUBJECT_CODE_OBJET", "CUSTOM_SUBJ_OBJET_PERSO"],
                subject_rows,
            ),
        )
        zf.writestr(
            "Registration_PrimaryExport.csv",
            _make_csv_bytes(
                [
                    "REG_ID_ENR", "REG_TYPE_ENR", "REG_NUM_ENR", "VERSION_CODE",
                    "EN_FIRM_NM_FIRME_AN", "FR_FIRM_NM_FIRME",
                    "EN_CLIENT_ORG_CORP_NM_AN", "FR_CLIENT_ORG_CORP_NM",
                    "EFFECTIVE_DATE_VIGUEUR", "END_DATE_FIN", "POSTED_DATE_PUBLICATION",
                ],
                primary_rows,
            ),
        )
        zf.writestr(
            "Registration_GovernmentInstExport.csv",
            _make_csv_bytes(
                ["REG_ID_ENR", "INSTITUTION"],
                govt_inst_rows,
            ),
        )


@pytest.fixture
def engine(tmp_path):
    """EnrichmentEngine with tmp data dir."""
    return EnrichmentEngine(data_dir=tmp_path)


@pytest.fixture
def loaded_engine(tmp_path):
    """EnrichmentEngine with fixture data pre-loaded (no download)."""
    eng = EnrichmentEngine(data_dir=tmp_path)

    # Write contracts fixture
    _write_contracts_csv(tmp_path / "contracts.csv", [
        {
            "vendor_name": "Accenture Inc.",
            "contract_value": "840000",
            "description_en": "Managed detection and response cybersecurity services SOC",
            "commodity_code": "D123",
            "owner_org_title": "Department of National Defence",
            "contract_date": "2023-06-15",
            "solicitation_procedure": "Competitive",
            "number_of_bids": "4",
            "reference_number": "C-2023-001",
        },
        {
            "vendor_name": "Deloitte LLP",
            "contract_value": "1250000",
            "description_en": "Identity and access management IAM implementation consulting",
            "commodity_code": "D456",
            "owner_org_title": "Department of National Defence",
            "contract_date": "2024-01-10",
            "solicitation_procedure": "Non-competitive",
            "number_of_bids": "1",
            "reference_number": "C-2024-001",
        },
        {
            "vendor_name": "IBM Canada",
            "contract_value": "500000",
            "description_en": "Cloud infrastructure migration and security assessment",
            "commodity_code": "D789",
            "owner_org_title": "Shared Services Canada",
            "contract_date": "2023-09-01",
            "solicitation_procedure": "Competitive",
            "number_of_bids": "6",
            "reference_number": "C-2023-002",
        },
        {
            "vendor_name": "CGI Inc.",
            "contract_value": "320000",
            "description_en": "Network infrastructure upgrade and maintenance support",
            "commodity_code": "D222",
            "owner_org_title": "Canada Revenue Agency",
            "contract_date": "2024-03-20",
            "solicitation_procedure": "Competitive",
            "number_of_bids": "3",
            "reference_number": "C-2024-002",
        },
        {
            "vendor_name": "General Contractor Co.",
            "contract_value": "2000000",
            "description_en": "Building renovation and plumbing repair at DND base",
            "commodity_code": "F999",
            "owner_org_title": "Department of National Defence",
            "contract_date": "2024-02-01",
            "solicitation_procedure": "Competitive",
            "number_of_bids": "5",
            "reference_number": "C-2024-099",
        },
    ])

    # Write lobbying ZIP fixture
    _write_lobbying_zip(
        tmp_path / "lobbying_registrations.zip",
        primary_rows=[
            {
                "REG_ID_ENR": "100001",
                "EN_CLIENT_ORG_CORP_NM_AN": "Deloitte Canada",
                "EN_FIRM_NM_FIRME_AN": "null",
                "EFFECTIVE_DATE_VIGUEUR": "2025-03-01",
            },
            {
                "REG_ID_ENR": "100002",
                "EN_CLIENT_ORG_CORP_NM_AN": "Palo Alto Networks",
                "EN_FIRM_NM_FIRME_AN": "null",
                "EFFECTIVE_DATE_VIGUEUR": "2025-06-15",
            },
            {
                "REG_ID_ENR": "100003",
                "EN_CLIENT_ORG_CORP_NM_AN": "DaimlerChrysler Canada",
                "EN_FIRM_NM_FIRME_AN": "null",
                "EFFECTIVE_DATE_VIGUEUR": "2024-01-10",
            },
            {
                "REG_ID_ENR": "100004",
                "EN_CLIENT_ORG_CORP_NM_AN": "Farming Corp",
                "EN_FIRM_NM_FIRME_AN": "null",
                "EFFECTIVE_DATE_VIGUEUR": "2025-01-01",
            },
            {
                "REG_ID_ENR": "100005",
                "EN_CLIENT_ORG_CORP_NM_AN": "Enbridge Inc.",
                "EN_FIRM_NM_FIRME_AN": "null",
                "EFFECTIVE_DATE_VIGUEUR": "2024-05-01",
            },
            {
                "REG_ID_ENR": "100006",
                "EN_CLIENT_ORG_CORP_NM_AN": "CrowdStrike Canada",
                "EN_FIRM_NM_FIRME_AN": "null",
                "EFFECTIVE_DATE_VIGUEUR": "2025-09-01",
            },
            {
                "REG_ID_ENR": "100007",
                "EN_CLIENT_ORG_CORP_NM_AN": "CGI Inc.",
                "EN_FIRM_NM_FIRME_AN": "null",
                "EFFECTIVE_DATE_VIGUEUR": "2025-02-01",
            },
            {
                "REG_ID_ENR": "100008",
                "EN_CLIENT_ORG_CORP_NM_AN": "Microsoft Canada",
                "EN_FIRM_NM_FIRME_AN": "null",
                "EFFECTIVE_DATE_VIGUEUR": "2025-04-01",
            },
        ],
        subject_rows=[
            # Deloitte: SMT-39 + cyber custom text
            {"REG_ID_ENR": "100001", "SUBJECT_CODE_OBJET": "SMT-39",
             "CUSTOM_SUBJ_OBJET_PERSO": "cybersecurity consulting and managed security services"},
            # Palo Alto: SMT-8 + cyber custom text
            {"REG_ID_ENR": "100002", "SUBJECT_CODE_OBJET": "SMT-8",
             "CUSTOM_SUBJ_OBJET_PERSO": "network security and SIEM solutions"},
            # DaimlerChrysler: SMT-8 but automotive (no cyber keywords, not a known vendor)
            {"REG_ID_ENR": "100003", "SUBJECT_CODE_OBJET": "SMT-8",
             "CUSTOM_SUBJ_OBJET_PERSO": "automotive parts and vehicle fleet procurement"},
            # Farming Corp: irrelevant subject (Agriculture)
            {"REG_ID_ENR": "100004", "SUBJECT_CODE_OBJET": "SMT-3"},
            # Enbridge: SMT-39 but energy (no cyber keywords, not a known vendor)
            {"REG_ID_ENR": "100005", "SUBJECT_CODE_OBJET": "SMT-39",
             "CUSTOM_SUBJ_OBJET_PERSO": "pipeline safety and energy infrastructure"},
            # CrowdStrike: SMT-39 + known vendor + cyber keywords
            {"REG_ID_ENR": "100006", "SUBJECT_CODE_OBJET": "SMT-39",
             "CUSTOM_SUBJ_OBJET_PERSO": "cybersecurity endpoint detection and SOC services"},
            # CGI: SMT-39 + known vendor + IT keywords
            {"REG_ID_ENR": "100007", "SUBJECT_CODE_OBJET": "SMT-39",
             "CUSTOM_SUBJ_OBJET_PERSO": "information technology identity access management"},
            # Microsoft: SMT-39 + custom text with cloud/identity
            {"REG_ID_ENR": "100008", "SUBJECT_CODE_OBJET": "SMT-39",
             "CUSTOM_SUBJ_OBJET_PERSO": "cloud identity and access management platform"},
        ],
        govt_inst_rows=[
            {"REG_ID_ENR": "100001", "INSTITUTION": "Department of National Defence"},
            {"REG_ID_ENR": "100002", "INSTITUTION": "Department of National Defence"},
            {"REG_ID_ENR": "100003", "INSTITUTION": "Department of National Defence"},
            {"REG_ID_ENR": "100004", "INSTITUTION": "Agriculture and Agri-Food Canada (AAFC)"},
            {"REG_ID_ENR": "100005", "INSTITUTION": "Department of National Defence"},
            {"REG_ID_ENR": "100006", "INSTITUTION": "Department of National Defence"},
            {"REG_ID_ENR": "100007", "INSTITUTION": "Business Development Bank of Canada"},
            {"REG_ID_ENR": "100008", "INSTITUTION": "Business Development Bank of Canada"},
        ],
    )

    eng._index_contracts()
    eng._index_lobbying()
    eng._loaded = True
    return eng


# ---------------------------------------------------------------------------
# Buyer normalization
# ---------------------------------------------------------------------------

class TestNormalizeBuyer:
    def test_exact_alias(self):
        assert normalize_buyer("DND") == "Department of National Defence"

    def test_canonical_identity(self):
        assert normalize_buyer("Department of National Defence") == "Department of National Defence"

    def test_case_insensitive(self):
        assert normalize_buyer("dnd") == "Department of National Defence"
        assert normalize_buyer("Dnd") == "Department of National Defence"

    def test_pspc_alias(self):
        assert normalize_buyer("PSPC") == "Public Services and Procurement Canada"
        assert normalize_buyer("PWGSC") == "Public Services and Procurement Canada"

    def test_ssc_alias(self):
        assert normalize_buyer("SSC") == "Shared Services Canada"

    def test_rcmp_alias(self):
        assert normalize_buyer("RCMP") == "Royal Canadian Mounted Police"

    def test_cbsa_alias(self):
        assert normalize_buyer("CBSA") == "Canada Border Services Agency"

    def test_cra_alias(self):
        assert normalize_buyer("CRA") == "Canada Revenue Agency"

    def test_esdc_alias(self):
        assert normalize_buyer("ESDC") == "Employment and Social Development Canada"

    def test_phsa(self):
        assert normalize_buyer("PHSA") == "Provincial Health Services Authority"

    def test_cse(self):
        assert normalize_buyer("CSE") == "Communications Security Establishment"

    def test_treasury_board(self):
        assert normalize_buyer("Treasury Board") == "Treasury Board of Canada Secretariat"

    def test_gac(self):
        assert normalize_buyer("GAC") == "Global Affairs Canada"

    def test_ised(self):
        assert normalize_buyer("ISED") == "Innovation, Science and Economic Development Canada"

    def test_nrc(self):
        assert normalize_buyer("NRC") == "National Research Council Canada"

    def test_osfi(self):
        assert normalize_buyer("OSFI") == "Office of the Superintendent of Financial Institutions"

    def test_bdc_edc(self):
        assert normalize_buyer("BDC") == "Business Development Bank of Canada"
        assert normalize_buyer("EDC") == "Export Development Canada"

    def test_unknown_buyer_returned_as_is(self):
        assert normalize_buyer("Random Municipality") == "Random Municipality"

    def test_empty_string(self):
        assert normalize_buyer("") == ""

    def test_whitespace_stripped(self):
        assert normalize_buyer("  DND  ") == "Department of National Defence"

    def test_alias_count_at_least_30(self):
        """Ensure we have ~30+ aliases as specified."""
        assert len(BUYER_ALIASES) >= 30


# ---------------------------------------------------------------------------
# Standing offer detection
# ---------------------------------------------------------------------------

class TestStandingOffers:
    def test_tbips_in_title(self):
        offers = detect_standing_offers("TBIPS Task Based Services")
        assert "TBIPS" in offers

    def test_cspv_in_description(self):
        offers = detect_standing_offers("IT Services", "under CSPV supply arrangement")
        assert "CSPV" in offers

    def test_proservices_detected(self):
        offers = detect_standing_offers("ProServices Stream 4 - Security")
        assert "ProServices" in offers

    def test_standing_offer_phrase(self):
        offers = detect_standing_offers("", "This is a standing offer for IT consulting")
        assert "standing offer" in offers

    def test_supply_arrangement_phrase(self):
        offers = detect_standing_offers("supply arrangement for cloud hosting")
        assert "supply arrangement" in offers

    def test_no_match(self):
        offers = detect_standing_offers("General IT Consulting RFP")
        assert offers == []

    def test_multiple_matches(self):
        offers = detect_standing_offers("TBIPS and CSPV eligible services")
        assert "TBIPS" in offers
        assert "CSPV" in offers


# ---------------------------------------------------------------------------
# Parse helpers
# ---------------------------------------------------------------------------

class TestParseHelpers:
    def test_parse_float_normal(self):
        assert _parse_float("840000") == 840000.0

    def test_parse_float_commas(self):
        assert _parse_float("1,250,000") == 1250000.0

    def test_parse_float_dollar_sign(self):
        assert _parse_float("$500,000.00") == 500000.0

    def test_parse_float_empty(self):
        assert _parse_float("") == 0.0

    def test_parse_float_garbage(self):
        assert _parse_float("N/A") == 0.0

    def test_parse_int_normal(self):
        assert _parse_int("4") == 4

    def test_parse_int_empty(self):
        assert _parse_int("") == 0

    def test_parse_int_garbage(self):
        assert _parse_int("N/A") == 0


# ---------------------------------------------------------------------------
# Contract indexing
# ---------------------------------------------------------------------------

class TestContractIndex:
    def test_index_filters_non_it(self, loaded_engine):
        """Building renovation contract should be filtered out."""
        dnd_contracts = loaded_engine._contracts_by_dept.get(
            "department of national defence", []
        )
        vendors = [c.vendor for c in dnd_contracts]
        assert "General Contractor Co." not in vendors

    def test_index_includes_cyber_contracts(self, loaded_engine):
        dnd_contracts = loaded_engine._contracts_by_dept.get(
            "department of national defence", []
        )
        vendors = [c.vendor for c in dnd_contracts]
        assert "Accenture Inc." in vendors
        assert "Deloitte LLP" in vendors

    def test_index_multiple_departments(self, loaded_engine):
        assert "department of national defence" in loaded_engine._contracts_by_dept
        assert "shared services canada" in loaded_engine._contracts_by_dept
        assert "canada revenue agency" in loaded_engine._contracts_by_dept

    def test_sole_source_detection(self, loaded_engine):
        dnd_contracts = loaded_engine._contracts_by_dept["department of national defence"]
        deloitte = [c for c in dnd_contracts if c.vendor == "Deloitte LLP"][0]
        assert deloitte.sole_source is True

    def test_competitive_detection(self, loaded_engine):
        dnd_contracts = loaded_engine._contracts_by_dept["department of national defence"]
        accenture = [c for c in dnd_contracts if c.vendor == "Accenture Inc."][0]
        assert accenture.sole_source is False
        assert accenture.num_bidders == 4


# ---------------------------------------------------------------------------
# Lobbying indexing
# ---------------------------------------------------------------------------

class TestLobbyingIndex:
    def test_lobbying_indexed(self, loaded_engine):
        assert "department of national defence" in loaded_engine._lobbying_by_dept

    def test_lobbying_firms(self, loaded_engine):
        dnd_lobby = loaded_engine._lobbying_by_dept["department of national defence"]
        firms = [e["firm"] for e in dnd_lobby]
        assert "Deloitte Canada" in firms
        assert "Palo Alto Networks" in firms
        assert "CrowdStrike Canada" in firms

    def test_irrelevant_subject_filtered(self, loaded_engine):
        """Agriculture (SMT-3) registrations should be filtered out."""
        all_firms = []
        for entries in loaded_engine._lobbying_by_dept.values():
            all_firms.extend(e["firm"] for e in entries)
        assert "Farming Corp" not in all_firms

    def test_subject_descriptions_resolved(self, loaded_engine):
        """Subject codes should be resolved to human-readable descriptions."""
        dnd_lobby = loaded_engine._lobbying_by_dept["department of national defence"]
        subjects = [e["subject"] for e in dnd_lobby]
        # Should have resolved code to description
        assert any("Security" in s or "Defence" in s for s in subjects)

    def test_custom_text_preserved(self, loaded_engine):
        """CUSTOM_SUBJ_OBJET_PERSO should be stored in index entries."""
        dnd_lobby = loaded_engine._lobbying_by_dept["department of national defence"]
        deloitte = [e for e in dnd_lobby if e["firm"] == "Deloitte Canada"]
        assert len(deloitte) > 0
        assert "cybersecurity" in deloitte[0].get("custom_text", "").lower()

    def test_effective_date_preserved(self, loaded_engine):
        """Effective dates from PrimaryExport should be stored."""
        dnd_lobby = loaded_engine._lobbying_by_dept["department of national defence"]
        deloitte = [e for e in dnd_lobby if e["firm"] == "Deloitte Canada"]
        assert len(deloitte) > 0
        assert deloitte[0]["date"] == "2025-03-01"

    def test_lobbying_latin1_encoding(self, tmp_path):
        """Lobbying ZIP with latin-1 characters should parse without error."""
        _write_lobbying_zip(
            tmp_path / "lobbying_registrations.zip",
            primary_rows=[
                {
                    "REG_ID_ENR": "200001",
                    "EN_CLIENT_ORG_CORP_NM_AN": "Soci\xe9t\xe9 Conseil",
                    "EN_FIRM_NM_FIRME_AN": "null",
                },
            ],
            subject_rows=[
                {"REG_ID_ENR": "200001", "SUBJECT_CODE_OBJET": "SMT-8"},
            ],
            govt_inst_rows=[
                {"REG_ID_ENR": "200001", "INSTITUTION": "D\xe9fense nationale"},
            ],
        )
        eng = EnrichmentEngine(data_dir=tmp_path)
        eng._index_lobbying()
        assert len(eng._lobbying_by_dept) >= 1

    def test_lobbying_empty_zip(self, tmp_path):
        """ZIP with empty CSVs should not crash."""
        _write_lobbying_zip(
            tmp_path / "lobbying_registrations.zip",
            primary_rows=[],
            subject_rows=[],
            govt_inst_rows=[],
        )
        eng = EnrichmentEngine(data_dir=tmp_path)
        eng._index_lobbying()
        assert len(eng._lobbying_by_dept) == 0

    def test_lobbying_missing_zip(self, tmp_path):
        """Missing ZIP file should not crash."""
        eng = EnrichmentEngine(data_dir=tmp_path)
        eng._index_lobbying()
        assert len(eng._lobbying_by_dept) == 0

    def test_firm_name_fallback(self, tmp_path):
        """When EN_CLIENT_ORG_CORP_NM_AN is 'null', falls back to EN_FIRM_NM_FIRME_AN."""
        _write_lobbying_zip(
            tmp_path / "lobbying_registrations.zip",
            primary_rows=[
                {
                    "REG_ID_ENR": "300001",
                    "EN_CLIENT_ORG_CORP_NM_AN": "null",
                    "EN_FIRM_NM_FIRME_AN": "Devon Group",
                },
            ],
            subject_rows=[
                {"REG_ID_ENR": "300001", "SUBJECT_CODE_OBJET": "SMT-39"},
            ],
            govt_inst_rows=[
                {"REG_ID_ENR": "300001", "INSTITUTION": "Public Safety Canada"},
            ],
        )
        eng = EnrichmentEngine(data_dir=tmp_path)
        eng._index_lobbying()
        entries = eng._lobbying_by_dept.get("public safety canada", [])
        assert len(entries) == 1
        assert entries[0]["firm"] == "Devon Group"

    def test_multiple_subjects_per_registration(self, tmp_path):
        """One registration with multiple relevant codes creates multiple entries."""
        _write_lobbying_zip(
            tmp_path / "lobbying_registrations.zip",
            primary_rows=[
                {
                    "REG_ID_ENR": "400001",
                    "EN_CLIENT_ORG_CORP_NM_AN": "Multi-Subject Corp",
                    "EN_FIRM_NM_FIRME_AN": "null",
                },
            ],
            subject_rows=[
                {"REG_ID_ENR": "400001", "SUBJECT_CODE_OBJET": "SMT-8"},
                {"REG_ID_ENR": "400001", "SUBJECT_CODE_OBJET": "SMT-39"},
            ],
            govt_inst_rows=[
                {"REG_ID_ENR": "400001", "INSTITUTION": "Department of National Defence"},
            ],
        )
        eng = EnrichmentEngine(data_dir=tmp_path)
        eng._index_lobbying()
        entries = eng._lobbying_by_dept.get("department of national defence", [])
        assert len(entries) == 2
        subjects = {e["subject"] for e in entries}
        assert "Defence" in subjects
        assert "National Security/Security" in subjects


# ---------------------------------------------------------------------------
# Enrichment queries
# ---------------------------------------------------------------------------

class TestEnrich:
    def test_enrich_known_department(self, loaded_engine):
        """DND cybersecurity query should find incumbent."""
        result = loaded_engine.enrich(
            buyer="DND",
            title="Managed Detection and Response Services",
            description="SOC cybersecurity managed services",
        )
        assert result["incumbent"] is not None
        assert result["incumbent"]["vendor"] in ("Accenture Inc.", "Deloitte LLP")
        assert result["incumbent"]["value"] > 0

    def test_enrich_returns_lobbying(self, loaded_engine):
        result = loaded_engine.enrich(
            buyer="Department of National Defence",
            title="Cybersecurity Assessment",
            description="SIEM SOC penetration testing",
        )
        assert len(result["lobbying"]) > 0
        firms = [e["firm"] for e in result["lobbying"]]
        # Known vendors with cyber keywords should appear
        assert "CrowdStrike Canada" in firms or "Deloitte Canada" in firms

    def test_enrich_standing_offers(self, loaded_engine):
        result = loaded_engine.enrich(
            buyer="SSC",
            title="TBIPS Task Based IT Services",
            description="Under CSPV supply arrangement",
        )
        assert "TBIPS" in result["standing_offers"]
        assert "CSPV" in result["standing_offers"]

    def test_enrich_unknown_department(self, loaded_engine):
        """Unknown department returns empty enrichment, no crash."""
        result = loaded_engine.enrich(
            buyer="City of Timbuktu",
            title="IT Services RFP",
        )
        assert result["incumbent"] is None
        assert result["lobbying"] == []

    def test_enrich_empty_buyer(self, loaded_engine):
        result = loaded_engine.enrich(buyer="", title="Something")
        assert result["incumbent"] is None
        assert result["lobbying"] == []

    def test_enrich_buyer_normalization(self, loaded_engine):
        """Alias 'DND' should resolve to same data as full name."""
        r1 = loaded_engine.enrich(
            buyer="DND",
            title="Cybersecurity Services SOC",
        )
        r2 = loaded_engine.enrich(
            buyer="Department of National Defence",
            title="Cybersecurity Services SOC",
        )
        # Both should find same incumbent (or both None if no match)
        if r1["incumbent"]:
            assert r2["incumbent"] is not None
            assert r1["incumbent"]["vendor"] == r2["incumbent"]["vendor"]

    def test_enrich_sole_source_flag(self, loaded_engine):
        """Query matching sole-source contract should flag it."""
        result = loaded_engine.enrich(
            buyer="DND",
            title="Identity and Access Management IAM consulting",
        )
        if result["incumbent"] and result["incumbent"]["vendor"] == "Deloitte LLP":
            assert result["incumbent"]["sole_source"] is True
            assert result["incumbent"]["num_bidders"] == 1

    def test_enrich_includes_competitive_landscape(self, loaded_engine):
        """Competitive intelligence should be included in enrichment results."""
        result = loaded_engine.enrich(
            buyer="DND",
            title="Cybersecurity Assessment Services",
            description="cybersecurity assessment SOC IAM services",
        )
        assert "similar_awards" in result
        assert "competitive_landscape" in result
        assert result["competitive_landscape"]["num_similar_awards"] == len(result["similar_awards"])


class TestSimilarAwards:
    def test_find_similar_awards_returns_results(self, loaded_engine):
        """Finds relevant contracts for the same department."""
        awards = loaded_engine.find_similar_awards(
            buyer="DND",
            title="Identity and Access Management Services",
            description="IAM identity access consulting",
        )
        assert len(awards) > 0
        assert awards[0]["vendor"] == "Deloitte LLP"
        assert awards[0]["reference_number"] == "C-2024-001"

    def test_find_similar_awards_includes_department_field(self, loaded_engine):
        """Each similar award should include a department field."""
        awards = loaded_engine.find_similar_awards(
            buyer="DND",
            title="Identity and Access Management Services",
            description="IAM identity access consulting",
        )
        assert len(awards) > 0
        for award in awards:
            assert "department" in award
            assert award["department"]  # non-empty

    def test_same_dept_awards_labeled_correctly(self, loaded_engine):
        """Same-department results should have the buyer's canonical name."""
        awards = loaded_engine.find_similar_awards(
            buyer="DND",
            title="Identity and Access Management Services",
            description="IAM identity access consulting",
        )
        assert len(awards) > 0
        # The first result (Deloitte at DND) should have DND's canonical name
        assert awards[0]["department"] == "Department of National Defence"

    def test_find_similar_awards_empty_for_unknown_dept(self, loaded_engine):
        """Unknown buyer with low keyword overlap returns no similar awards."""
        awards = loaded_engine.find_similar_awards(
            buyer="City of Timbuktu",
            title="Cybersecurity Services",
            description="SOC SIEM incident response",
        )
        # Cross-dept requires 4+ word overlap; this query has <4 overlap
        # with any fixture contract, so should still be empty
        assert awards == []

    def test_competitive_landscape_aggregation(self, loaded_engine):
        """Landscape summary groups multiple wins by vendor."""
        awards = [
            {"vendor": "Deloitte LLP", "value": 1_250_000},
            {"vendor": "Deloitte LLP", "value": 950_000},
            {"vendor": "Accenture Inc.", "value": 840_000},
        ]
        landscape = loaded_engine._build_competitive_landscape(awards)
        assert landscape["num_similar_awards"] == 3
        assert landscape["avg_award_value"] == pytest.approx(1_013_333.3333333334)
        assert landscape["top_competitors"][0]["vendor"] == "Deloitte LLP"
        assert landscape["top_competitors"][0]["wins"] == 2
        assert landscape["top_competitors"][0]["total_value"] == 2_200_000

    def test_similar_awards_keyword_overlap(self, loaded_engine):
        """Keyword overlap should shift the top-ranked vendor by opportunity text."""
        mdr_awards = loaded_engine.find_similar_awards(
            buyer="DND",
            title="Managed Detection and Response Services",
            description="managed detection response SOC cybersecurity services",
        )
        iam_awards = loaded_engine.find_similar_awards(
            buyer="DND",
            title="Identity and Access Management Services",
            description="identity access management IAM consulting",
        )
        assert mdr_awards
        assert iam_awards
        assert mdr_awards[0]["vendor"] == "Accenture Inc."
        assert iam_awards[0]["vendor"] == "Deloitte LLP"

    def test_cross_dept_finds_similar_contracts(self, tmp_path):
        """A small dept should find similar cybersecurity contracts at larger depts."""
        eng = EnrichmentEngine(data_dir=tmp_path)
        _write_contracts_csv(tmp_path / "contracts.csv", [
            # Large dept has a very relevant cybersecurity contract
            {
                "vendor_name": "Accenture Inc.",
                "contract_value": "900000",
                "description_en": "cybersecurity penetration testing vulnerability assessment managed detection response",
                "commodity_code": "D123",
                "owner_org_title": "Department of National Defence",
                "contract_date": "2024-01-15",
                "solicitation_procedure": "Competitive",
                "number_of_bids": "5",
                "reference_number": "CROSS-001",
            },
            # Another dept has a similar contract
            {
                "vendor_name": "Deloitte LLP",
                "contract_value": "750000",
                "description_en": "cybersecurity penetration testing security assessment professional consulting",
                "commodity_code": "D456",
                "owner_org_title": "Shared Services Canada",
                "contract_date": "2023-11-01",
                "solicitation_procedure": "Competitive",
                "number_of_bids": "4",
                "reference_number": "CROSS-002",
            },
            # Small dept has only one unrelated IT contract
            {
                "vendor_name": "LocalIT Corp",
                "contract_value": "50000",
                "description_en": "desktop support help desk software",
                "commodity_code": "D789",
                "owner_org_title": "Canadian Heritage",
                "contract_date": "2024-03-01",
                "solicitation_procedure": "Competitive",
                "number_of_bids": "2",
                "reference_number": "CROSS-003",
            },
        ])
        _write_lobbying_zip(
            tmp_path / "lobbying_registrations.zip",
            primary_rows=[], subject_rows=[], govt_inst_rows=[],
        )
        eng._index_contracts()
        eng._index_lobbying()
        eng._loaded = True

        # Search from Canadian Heritage for cybersecurity penetration testing
        awards = eng.find_similar_awards(
            buyer="Canadian Heritage",
            title="Cybersecurity Penetration Testing Assessment",
            description="cybersecurity penetration testing vulnerability assessment",
        )

        assert len(awards) >= 2, f"Expected cross-dept results, got {len(awards)}"
        vendors = [a["vendor"] for a in awards]
        assert "Accenture Inc." in vendors
        assert "Deloitte LLP" in vendors

        # Results should include department names from other departments
        depts = [a["department"] for a in awards]
        assert "Department of National Defence" in depts
        assert "Shared Services Canada" in depts

    def test_cross_dept_deduplicates_by_reference(self, tmp_path):
        """Same reference_number should not appear twice in results."""
        eng = EnrichmentEngine(data_dir=tmp_path)
        _write_contracts_csv(tmp_path / "contracts.csv", [
            {
                "vendor_name": "TestVendor",
                "contract_value": "100000",
                "description_en": "cybersecurity penetration testing vulnerability assessment managed",
                "commodity_code": "D123",
                "owner_org_title": "Department of National Defence",
                "contract_date": "2024-01-15",
                "solicitation_procedure": "Competitive",
                "number_of_bids": "3",
                "reference_number": "DEDUP-001",
            },
        ])
        _write_lobbying_zip(
            tmp_path / "lobbying_registrations.zip",
            primary_rows=[], subject_rows=[], govt_inst_rows=[],
        )
        eng._index_contracts()
        eng._index_lobbying()
        eng._loaded = True

        awards = eng.find_similar_awards(
            buyer="DND",
            title="Cybersecurity Penetration Testing Assessment",
            description="cybersecurity penetration testing vulnerability assessment managed",
        )
        refs = [a["reference_number"] for a in awards if a["reference_number"]]
        assert len(refs) == len(set(refs)), "Duplicate reference_numbers found"

    def test_cross_dept_returns_max_10(self, tmp_path):
        """Results should be capped at 10."""
        eng = EnrichmentEngine(data_dir=tmp_path)
        rows = []
        for i in range(15):
            rows.append({
                "vendor_name": f"Vendor{i}",
                "contract_value": str(100000 + i * 10000),
                "description_en": "cybersecurity penetration testing vulnerability assessment managed detection response endpoint",
                "commodity_code": "D123",
                "owner_org_title": f"Department {i}",
                "contract_date": "2024-01-15",
                "solicitation_procedure": "Competitive",
                "number_of_bids": "3",
                "reference_number": f"MAX-{i:03d}",
            })
        _write_contracts_csv(tmp_path / "contracts.csv", rows)
        _write_lobbying_zip(
            tmp_path / "lobbying_registrations.zip",
            primary_rows=[], subject_rows=[], govt_inst_rows=[],
        )
        eng._index_contracts()
        eng._index_lobbying()
        eng._loaded = True

        awards = eng.find_similar_awards(
            buyer="Some Other Dept",
            title="Cybersecurity Penetration Testing Assessment",
            description="cybersecurity penetration testing vulnerability assessment managed detection response endpoint",
        )
        assert len(awards) <= 10


# ---------------------------------------------------------------------------
# Caching behavior
# ---------------------------------------------------------------------------

class TestCaching:
    def test_fresh_file_not_redownloaded(self, tmp_path):
        """If contracts CSV exists and is < 7 days old, don't download."""
        contracts_path = tmp_path / "contracts.csv"
        _write_contracts_csv(contracts_path, [
            {
                "vendor_name": "TestCorp",
                "contract_value": "100000",
                "description_en": "cybersecurity testing",
                "commodity_code": "D100",
                "owner_org_title": "Test Department",
                "contract_date": "2024-01-01",
                "solicitation_procedure": "Competitive",
                "number_of_bids": "2",
            }
        ])

        eng = EnrichmentEngine(data_dir=tmp_path)
        # Patch the min-size threshold to 0 so the small test fixture CSV is
        # not mistaken for the legacy/truncated production file.
        with patch.object(type(eng), "_CONTRACTS_MIN_SIZE_BYTES", new=0):
            # Mock _download_file to verify it's NOT called
            with patch("lib.enrichment._download_file") as mock_dl:
                eng._load_contracts()
                mock_dl.assert_not_called()
        # But data should still be indexed
        assert len(eng._contracts_by_dept) == 1

    def test_stale_file_triggers_download(self, tmp_path):
        """If contracts CSV is > 7 days old, attempt download."""
        contracts_path = tmp_path / "contracts.csv"
        _write_contracts_csv(contracts_path, [])
        # Make the file appear old
        old_time = os.path.getmtime(str(contracts_path)) - (8 * 86400)
        os.utime(str(contracts_path), (old_time, old_time))

        eng = EnrichmentEngine(data_dir=tmp_path)
        with patch("lib.enrichment._download_file", return_value=False) as mock_dl:
            with patch.object(eng, "_resolve_contracts_url", return_value="https://example.com/contracts.csv"):
                eng._load_contracts()
                assert mock_dl.called

    def test_missing_file_triggers_download(self, tmp_path):
        """If contracts CSV is missing, attempt download."""
        eng = EnrichmentEngine(data_dir=tmp_path)
        with patch("lib.enrichment._download_file", return_value=False) as mock_dl:
            with patch.object(eng, "_resolve_contracts_url", return_value="https://example.com/contracts.csv"):
                eng._load_contracts()
                assert mock_dl.called


# ---------------------------------------------------------------------------
# Lobbying ZIP extraction
# ---------------------------------------------------------------------------

class TestLobbyingZip:
    def test_load_downloads_and_indexes(self, tmp_path):
        """_load_lobbying downloads ZIP via _download_file and indexes it."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        dest_zip = data_dir / "lobbying_registrations.zip"

        def fake_download(url, dest, **kwargs):
            """Simulate download by writing a fixture ZIP to dest."""
            _write_lobbying_zip(
                dest,
                primary_rows=[
                    {
                        "REG_ID_ENR": "500001",
                        "EN_CLIENT_ORG_CORP_NM_AN": "TestFirm",
                        "EN_FIRM_NM_FIRME_AN": "null",
                    },
                ],
                subject_rows=[
                    {"REG_ID_ENR": "500001", "SUBJECT_CODE_OBJET": "SMT-39"},
                ],
                govt_inst_rows=[
                    {"REG_ID_ENR": "500001", "INSTITUTION": "Test Dept"},
                ],
            )
            return True

        eng = EnrichmentEngine(data_dir=data_dir)

        with patch("lib.enrichment._download_file", side_effect=fake_download):
            eng._load_lobbying()

        assert len(eng._lobbying_by_dept) >= 1
        entries = eng._lobbying_by_dept.get("test dept", [])
        assert len(entries) == 1
        assert entries[0]["firm"] == "TestFirm"

    def test_cached_zip_not_recopied(self, tmp_path):
        """If ZIP exists and is fresh, don't re-copy from source."""
        _write_lobbying_zip(
            tmp_path / "lobbying_registrations.zip",
            primary_rows=[
                {
                    "REG_ID_ENR": "600001",
                    "EN_CLIENT_ORG_CORP_NM_AN": "CachedFirm",
                    "EN_FIRM_NM_FIRME_AN": "null",
                },
            ],
            subject_rows=[
                {"REG_ID_ENR": "600001", "SUBJECT_CODE_OBJET": "SMT-8"},
            ],
            govt_inst_rows=[
                {"REG_ID_ENR": "600001", "INSTITUTION": "Cached Dept"},
            ],
        )
        eng = EnrichmentEngine(data_dir=tmp_path)
        # Should use cached ZIP directly, no copy needed
        eng._load_lobbying()
        assert "cached dept" in eng._lobbying_by_dept


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_download_failure_returns_empty(self, tmp_path):
        """If all downloads fail, enrich returns empty data without crashing."""
        eng = EnrichmentEngine(data_dir=tmp_path)
        with patch("lib.enrichment._download_file", return_value=False):
            with patch.object(eng, "_resolve_contracts_url", return_value="https://example.com/fail"):
                eng.load_data()
        result = eng.enrich("DND", "Cybersecurity RFP")
        assert result["incumbent"] is None
        assert result["lobbying"] == []

    def test_cyber_it_filter_regex(self):
        """Filter regex catches IT/cyber keywords."""
        assert _CYBER_IT_FILTER_RE.search("cybersecurity assessment")
        assert _CYBER_IT_FILTER_RE.search("software licensing agreement")
        assert _CYBER_IT_FILTER_RE.search("network infrastructure")
        assert _CYBER_IT_FILTER_RE.search("cloud migration services")
        assert not _CYBER_IT_FILTER_RE.search("catering services for event")

    def test_file_age_missing_file(self, tmp_path):
        """Missing file returns infinite age."""
        age = _file_age_seconds(tmp_path / "nonexistent.csv")
        assert age == float("inf")

    def test_file_age_existing_file(self, tmp_path):
        """Existing file returns age in seconds."""
        f = tmp_path / "test.csv"
        f.write_text("test")
        age = _file_age_seconds(f)
        assert 0 <= age < 5  # should be very recent

    def test_enrich_with_standing_offer_only(self, engine):
        """Even without loaded data, standing offers should be detected."""
        result = engine.enrich(
            buyer="SSC",
            title="TBIPS Task Authorization",
        )
        assert "TBIPS" in result["standing_offers"]
        assert result["incumbent"] is None

    def test_lobbying_partial_match(self, loaded_engine):
        """Partial department name matching for lobbying."""
        # BDC has CGI (known vendor + IT keywords) in lobbying data
        result = loaded_engine.enrich(
            buyer="BDC",
            title="Identity Platform License Renewal",
            description="identity access management SSO",
        )
        assert len(result["lobbying"]) > 0
        firms = [e["firm"] for e in result["lobbying"]]
        assert "CGI Inc." in firms


# ---------------------------------------------------------------------------
# Lobbying relevance scoring
# ---------------------------------------------------------------------------

class TestLobbyingRelevance:
    """Tests for keyword-based relevance scoring in _find_lobbying."""

    def test_irrelevant_firms_filtered_out(self, loaded_engine):
        """DaimlerChrysler and Enbridge should be filtered out of cyber RFP results."""
        result = loaded_engine.enrich(
            buyer="DND",
            title="Cybersecurity Professional Services",
            description="SIEM SOC penetration testing managed security",
        )
        firms = [e["firm"] for e in result["lobbying"]]
        assert "DaimlerChrysler Canada" not in firms
        assert "Enbridge Inc." not in firms

    def test_relevant_firms_included(self, loaded_engine):
        """Known vendors with cyber keywords should appear in results."""
        result = loaded_engine.enrich(
            buyer="DND",
            title="Cybersecurity Professional Services",
            description="SIEM SOC penetration testing managed security",
        )
        firms = [e["firm"] for e in result["lobbying"]]
        # CrowdStrike: known vendor (+3) + cyber custom text (+2) + SMT-39 (+2) = 7
        assert "CrowdStrike Canada" in firms
        # Deloitte: known vendor (+3) + cyber custom text (+2) + SMT-39 (+2) = 7
        assert "Deloitte Canada" in firms

    def test_max_five_results(self, loaded_engine):
        """_find_lobbying should return at most 5 results."""
        result = loaded_engine.enrich(
            buyer="DND",
            title="Cybersecurity Assessment",
            description="security SOC SIEM network cloud identity",
        )
        assert len(result["lobbying"]) <= 5

    def test_results_sorted_by_score(self, loaded_engine):
        """Results should be sorted by relevance score descending."""
        result = loaded_engine.enrich(
            buyer="DND",
            title="Cybersecurity Assessment",
            description="SIEM SOC managed security endpoint detection",
        )
        lobbying = result["lobbying"]
        if len(lobbying) >= 2:
            scores = [e["score"] for e in lobbying]
            assert scores == sorted(scores, reverse=True)

    def test_street_sweeper_zero_signals(self, loaded_engine):
        """Non-IT RFP should return zero lobbying signals (IT relevance gate)."""
        result = loaded_engine.enrich(
            buyer="DND",
            title="Street Sweeper, Regenerative Air",
            description="self propelled cab over vehicle",
        )
        # The IT relevance gate should kill all lobbying results for non-IT RFPs.
        # No IT/cyber keywords in "Street Sweeper" -> empty lobbying.
        assert result["lobbying"] == [], (
            f"Expected zero lobbying for non-IT RFP, got: "
            f"{[e['firm'] for e in result['lobbying']]}"
        )

    def test_bdc_forgerock_shows_it_firms(self, loaded_engine):
        """BDC ForgeRock query should show IT firms, not random companies."""
        result = loaded_engine.enrich(
            buyer="Business Development Bank of Canada",
            title="ForgeRock Identity Platform License Renewal",
            description="identity access management SSO",
        )
        firms = [e["firm"] for e in result["lobbying"]]
        # CGI is a known vendor with IT custom text
        assert "CGI Inc." in firms

    def test_date_filtering_excludes_old_registrations(self, tmp_path):
        """Registrations older than 3 years should be filtered out."""
        _write_lobbying_zip(
            tmp_path / "lobbying_registrations.zip",
            primary_rows=[
                {
                    "REG_ID_ENR": "700001",
                    "EN_CLIENT_ORG_CORP_NM_AN": "Old CrowdStrike",
                    "EN_FIRM_NM_FIRME_AN": "null",
                    "EFFECTIVE_DATE_VIGUEUR": "2020-01-01",
                },
                {
                    "REG_ID_ENR": "700002",
                    "EN_CLIENT_ORG_CORP_NM_AN": "Recent CrowdStrike",
                    "EN_FIRM_NM_FIRME_AN": "null",
                    "EFFECTIVE_DATE_VIGUEUR": "2025-06-01",
                },
            ],
            subject_rows=[
                {"REG_ID_ENR": "700001", "SUBJECT_CODE_OBJET": "SMT-39",
                 "CUSTOM_SUBJ_OBJET_PERSO": "cybersecurity endpoint"},
                {"REG_ID_ENR": "700002", "SUBJECT_CODE_OBJET": "SMT-39",
                 "CUSTOM_SUBJ_OBJET_PERSO": "cybersecurity endpoint"},
            ],
            govt_inst_rows=[
                {"REG_ID_ENR": "700001", "INSTITUTION": "Test Dept"},
                {"REG_ID_ENR": "700002", "INSTITUTION": "Test Dept"},
            ],
        )
        eng = EnrichmentEngine(data_dir=tmp_path)
        eng._index_lobbying()
        eng._loaded = True

        result = eng._find_lobbying("test dept", "Cybersecurity", "SOC SIEM")
        firms = [e["firm"] for e in result]
        assert "Recent CrowdStrike" in firms
        assert "Old CrowdStrike" not in firms

    def test_lobbying_result_includes_date(self, loaded_engine):
        """Returned lobbying entries should include the registration date."""
        result = loaded_engine.enrich(
            buyer="DND",
            title="Cybersecurity Services",
            description="SIEM SOC endpoint",
        )
        for entry in result["lobbying"]:
            assert "date" in entry

    def test_known_vendor_scores_higher(self, loaded_engine):
        """Known vendors should score higher than unknown firms with same codes."""
        result = loaded_engine.enrich(
            buyer="DND",
            title="Cybersecurity Assessment",
            description="SIEM SOC managed security",
        )
        lobbying = result["lobbying"]
        firms = [e["firm"] for e in lobbying]
        # CrowdStrike (known vendor) should appear before Palo Alto (known vendor)
        # or at least both should appear. DaimlerChrysler should not.
        if "CrowdStrike Canada" in firms and "DaimlerChrysler Canada" in firms:
            assert firms.index("CrowdStrike Canada") < firms.index("DaimlerChrysler Canada")
        # But more importantly, DaimlerChrysler shouldn't be there at all
        assert "DaimlerChrysler Canada" not in firms

    def test_non_it_rfps_get_no_lobbying(self, loaded_engine):
        """Various non-IT RFP types should return zero lobbying signals."""
        non_it_cases = [
            ("Construction of building addition", "concrete steel framing"),
            ("Janitorial cleaning services", "floor waxing window cleaning"),
            ("Catering for annual conference", "food beverage reception"),
            ("Office furniture procurement", "desks chairs tables"),
        ]
        for title, desc in non_it_cases:
            result = loaded_engine.enrich(buyer="DND", title=title, description=desc)
            assert result["lobbying"] == [], (
                f"Expected no lobbying for '{title}', got: "
                f"{[e['firm'] for e in result['lobbying']]}"
            )

    def test_it_relevant_rfp_gets_lobbying(self, loaded_engine):
        """IT-relevant RFP should still get lobbying signals."""
        result = loaded_engine.enrich(
            buyer="DND",
            title="Network Security Assessment",
            description="firewall SIEM cybersecurity endpoint detection",
        )
        assert len(result["lobbying"]) > 0

    def test_opportunity_specific_scoring_differentiates_results(self, tmp_path):
        """Different RFPs at the same department should get differently-scored results.

        This is the core fix for the 'same 5 firms for every SSC RFP' problem.
        Firms whose lobbying subject overlaps with the specific opportunity text
        should score higher than firms with generic IT lobbying.
        """
        _write_lobbying_zip(
            tmp_path / "lobbying_registrations.zip",
            primary_rows=[
                {
                    "REG_ID_ENR": "800001",
                    "EN_CLIENT_ORG_CORP_NM_AN": "FileTransfer Corp",
                    "EN_FIRM_NM_FIRME_AN": "null",
                    "EFFECTIVE_DATE_VIGUEUR": "2025-01-01",
                },
                {
                    "REG_ID_ENR": "800002",
                    "EN_CLIENT_ORG_CORP_NM_AN": "CloudInfra Corp",
                    "EN_FIRM_NM_FIRME_AN": "null",
                    "EFFECTIVE_DATE_VIGUEUR": "2025-01-01",
                },
            ],
            subject_rows=[
                {"REG_ID_ENR": "800001", "SUBJECT_CODE_OBJET": "SMT-39",
                 "CUSTOM_SUBJ_OBJET_PERSO": "managed file transfer data security software"},
                {"REG_ID_ENR": "800002", "SUBJECT_CODE_OBJET": "SMT-39",
                 "CUSTOM_SUBJ_OBJET_PERSO": "cloud infrastructure virtualization security platform"},
            ],
            govt_inst_rows=[
                {"REG_ID_ENR": "800001", "INSTITUTION": "Shared Services Canada"},
                {"REG_ID_ENR": "800002", "INSTITUTION": "Shared Services Canada"},
            ],
        )
        eng = EnrichmentEngine(data_dir=tmp_path)
        eng._index_lobbying()
        eng._loaded = True

        # File transfer RFP should rank FileTransfer Corp higher
        ft_result = eng._find_lobbying(
            "shared services canada",
            "GoAnywhere Managed File Transfer",
            "file transfer data management software",
        )
        # Cloud infra RFP should rank CloudInfra Corp higher
        cloud_result = eng._find_lobbying(
            "shared services canada",
            "Cloud Infrastructure Renewal",
            "cloud infrastructure virtualization platform",
        )

        ft_firms = [e["firm"] for e in ft_result]
        cloud_firms = [e["firm"] for e in cloud_result]

        # Both should return results
        assert len(ft_result) > 0
        assert len(cloud_result) > 0

        # The firm with more overlap to the specific opportunity should score higher
        if "FileTransfer Corp" in ft_firms and "CloudInfra Corp" in ft_firms:
            ft_scores = {e["firm"]: e["score"] for e in ft_result}
            assert ft_scores["FileTransfer Corp"] > ft_scores["CloudInfra Corp"], (
                f"FileTransfer should score higher for file transfer RFP: {ft_scores}"
            )

        if "CloudInfra Corp" in cloud_firms and "FileTransfer Corp" in cloud_firms:
            cloud_scores = {e["firm"]: e["score"] for e in cloud_result}
            assert cloud_scores["CloudInfra Corp"] > cloud_scores["FileTransfer Corp"], (
                f"CloudInfra should score higher for cloud RFP: {cloud_scores}"
            )


# ---------------------------------------------------------------------------
# Incumbent relevance (keyword overlap gating)
# ---------------------------------------------------------------------------

class TestIncumbentRelevance:
    """Tests that incumbent matching requires keyword overlap, not just value."""

    def _make_engine_with_telesat(self, tmp_path):
        """Engine with an SSC satellite contract (TELESAT-style) + relevant contracts."""
        eng = EnrichmentEngine(data_dir=tmp_path)
        _write_contracts_csv(tmp_path / "contracts.csv", [
            # High-value satellite contract - should NOT match file transfer / virtualization RFPs
            {
                "vendor_name": "TELESAT CANADA",
                "contract_value": "26000000",
                "description_en": "satellite communications services bandwidth capacity government",
                "commodity_code": "D999",
                "owner_org_title": "Shared Services Canada",
                "contract_date": "2023-01-15",
                "solicitation_procedure": "Non-competitive",
                "number_of_bids": "1",
            },
            # Nutanix-relevant contract
            {
                "vendor_name": "Nutanix Inc.",
                "contract_value": "500000",
                "description_en": "Nutanix hyperconverged infrastructure software renewal virtualization",
                "commodity_code": "D111",
                "owner_org_title": "Shared Services Canada",
                "contract_date": "2024-03-01",
                "solicitation_procedure": "Non-competitive",
                "number_of_bids": "1",
            },
            # GoAnywhere-relevant contract
            {
                "vendor_name": "HelpSystems LLC",
                "contract_value": "150000",
                "description_en": "GoAnywhere managed file transfer software license",
                "commodity_code": "D222",
                "owner_org_title": "Shared Services Canada",
                "contract_date": "2023-09-01",
                "solicitation_procedure": "Non-competitive",
                "number_of_bids": "1",
            },
        ])
        _write_lobbying_zip(
            tmp_path / "lobbying_registrations.zip",
            primary_rows=[],
            subject_rows=[],
            govt_inst_rows=[],
        )
        eng._index_contracts()
        eng._index_lobbying()
        eng._loaded = True
        return eng

    def test_satellite_contract_not_incumbent_for_nutanix(self, tmp_path):
        """TELESAT $26M satellite deal must not appear for a Nutanix renewal RFP."""
        eng = self._make_engine_with_telesat(tmp_path)
        result = eng.enrich(
            "Shared Services Canada",
            "Nutanix Annual Renewal",
            "infrastructure virtualization hyperconverged",
        )
        inc = result.get("incumbent")
        assert inc is None or inc["vendor"] != "TELESAT CANADA", (
            f"Expected non-TELESAT incumbent, got: {inc}"
        )

    def test_satellite_contract_not_incumbent_for_goanywhere(self, tmp_path):
        """TELESAT $26M satellite deal must not appear for a file transfer RFP."""
        eng = self._make_engine_with_telesat(tmp_path)
        result = eng.enrich(
            "Shared Services Canada",
            "GoAnywhere for DND",
            "file transfer managed",
        )
        inc = result.get("incumbent")
        assert inc is None or inc["vendor"] != "TELESAT CANADA", (
            f"Expected non-TELESAT incumbent, got: {inc}"
        )

    def test_relevant_contract_wins_over_high_value_irrelevant(self, tmp_path):
        """Nutanix-matching contract wins over high-value satellite contract."""
        eng = self._make_engine_with_telesat(tmp_path)
        result = eng.enrich(
            "Shared Services Canada",
            "Nutanix Hyperconverged Infrastructure Renewal",
            "Nutanix virtualization infrastructure software annual",
        )
        inc = result.get("incumbent")
        assert inc is not None, "Expected Nutanix contract to win"
        assert inc["vendor"] == "Nutanix Inc.", (
            f"Expected Nutanix Inc., got: {inc['vendor']}"
        )

    def test_goanywhere_contract_wins_for_file_transfer_rfp(self, tmp_path):
        """GoAnywhere contract wins over satellite contract for file transfer RFP."""
        eng = self._make_engine_with_telesat(tmp_path)
        result = eng.enrich(
            "Shared Services Canada",
            "GoAnywhere Managed File Transfer License",
            "GoAnywhere file transfer software",
        )
        inc = result.get("incumbent")
        assert inc is not None, "Expected GoAnywhere contract to match"
        assert inc["vendor"] == "HelpSystems LLC", (
            f"Expected HelpSystems LLC, got: {inc['vendor']}"
        )

    def test_no_incumbent_when_no_overlap(self, tmp_path):
        """Returns None when opportunity has zero keyword overlap with all contracts."""
        eng = self._make_engine_with_telesat(tmp_path)
        result = eng.enrich(
            "Shared Services Canada",
            "Catering Services Conference",
            "food beverage reception",
        )
        inc = result.get("incumbent")
        assert inc is None, f"Expected None, got: {inc}"

    def test_high_value_irrelevant_alone_returns_none(self, tmp_path):
        """If only contract is high-value but off-topic, returns None not that contract."""
        eng = EnrichmentEngine(data_dir=tmp_path)
        _write_contracts_csv(tmp_path / "contracts.csv", [
            {
                "vendor_name": "TELESAT CANADA",
                "contract_value": "26000000",
                "description_en": "satellite communications services bandwidth capacity",
                "commodity_code": "D999",
                "owner_org_title": "Shared Services Canada",
                "contract_date": "2023-01-15",
                "solicitation_procedure": "Non-competitive",
                "number_of_bids": "1",
            },
        ])
        _write_lobbying_zip(
            tmp_path / "lobbying_registrations.zip",
            primary_rows=[],
            subject_rows=[],
            govt_inst_rows=[],
        )
        eng._index_contracts()
        eng._index_lobbying()
        eng._loaded = True

        result = eng.enrich(
            "Shared Services Canada",
            "Nutanix Annual Renewal",
            "infrastructure virtualization hyperconverged",
        )
        assert result.get("incumbent") is None
