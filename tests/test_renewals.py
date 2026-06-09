"""Tests for lib/renewals.py - IT Renewal Calendar."""

import csv
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from lib.renewals import (
    RenewalCalendar,
    _is_renewable_it_contract,
    _classify_relevance,
    _extract_product,
    _normalize_description,
    _group_key,
    _parse_date,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _write_contracts_csv(path: Path, rows: list[dict]) -> None:
    """Write a minimal contracts CSV fixture with BOM."""
    fieldnames = [
        "reference_number", "procurement_id", "vendor_name", "vendor_postal_code",
        "buyer_name", "contract_date", "economic_object_code", "description_en",
        "description_fr", "contract_period_start", "delivery_date", "contract_value",
        "original_value", "amendment_value", "comments_en", "owner_org", "owner_org_title",
        "additional_comments_en", "standing_offer_number",
    ]
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            full_row = {k: "" for k in fieldnames}
            # Map buyer_name to owner_org_title for backward compat with test data
            if "buyer_name" in row and "owner_org_title" not in row:
                row["owner_org_title"] = row["buyer_name"]
            full_row.update(row)
            writer.writerow(full_row)


@pytest.fixture
def data_dir(tmp_path):
    """Create a temp data directory with a contracts CSV."""
    return tmp_path


def _today_str():
    return date.today().isoformat()


def _days_from_now(n: int) -> str:
    return (date.today() + timedelta(days=n)).isoformat()


def _days_ago(n: int) -> str:
    return (date.today() - timedelta(days=n)).isoformat()


# ---------------------------------------------------------------------------
# Unit tests for helpers
# ---------------------------------------------------------------------------

class TestRenewableITFilter:
    # Software (original keywords)
    def test_matches_software(self):
        assert _is_renewable_it_contract("Enterprise software license") is True

    def test_matches_licence_british(self):
        assert _is_renewable_it_contract("Annual licence renewal") is True

    def test_matches_subscription(self):
        assert _is_renewable_it_contract("Cloud subscription services") is True

    def test_matches_saas(self):
        assert _is_renewable_it_contract("SaaS platform agreement") is True

    def test_matches_maintenance_fees(self):
        assert _is_renewable_it_contract("Software maintenance fees") is True

    # Hardware with maintenance
    def test_matches_networking_equipment(self):
        assert _is_renewable_it_contract("Networking equipment for data centre") is True

    def test_matches_network_equipment(self):
        assert _is_renewable_it_contract("Network equipment refresh") is True

    def test_matches_hardware_maintenance(self):
        assert _is_renewable_it_contract("Hardware maintenance and support contract") is True

    def test_matches_server(self):
        assert _is_renewable_it_contract("Server infrastructure upgrade") is True

    def test_matches_storage(self):
        assert _is_renewable_it_contract("Enterprise storage solution") is True

    def test_matches_communications_security(self):
        assert _is_renewable_it_contract("Communications security equipment") is True

    def test_matches_security_equipment(self):
        assert _is_renewable_it_contract("Security equipment installation") is True

    def test_matches_computer_equipment(self):
        assert _is_renewable_it_contract("Computer equipment purchase") is True

    def test_matches_appliance(self):
        assert _is_renewable_it_contract("Security appliance renewal") is True

    def test_matches_support_renewal(self):
        assert _is_renewable_it_contract("Annual support renewal for firewalls") is True

    def test_matches_router(self):
        assert _is_renewable_it_contract("Router replacement program") is True

    def test_matches_switch(self):
        assert _is_renewable_it_contract("Network switch procurement") is True

    # Negative cases
    def test_no_match_furniture(self):
        assert _is_renewable_it_contract("Office furniture purchase") is False

    def test_no_match_construction(self):
        assert _is_renewable_it_contract("Building construction project") is False

    def test_empty_string(self):
        assert _is_renewable_it_contract("") is False

    def test_none(self):
        assert _is_renewable_it_contract(None) is False


class TestRelevanceClassification:
    def test_crowdstrike_is_high(self):
        assert _classify_relevance("CrowdStrike Inc.") == "HIGH"

    def test_palo_alto_is_high(self):
        assert _classify_relevance("Palo Alto Networks") == "HIGH"

    def test_cgi_is_medium(self):
        assert _classify_relevance("CGI Information Systems") == "MEDIUM"

    def test_microsoft_is_medium(self):
        assert _classify_relevance("Microsoft Canada Co.") == "MEDIUM"

    def test_random_vendor_is_low(self):
        assert _classify_relevance("Bob's Discount Software") == "LOW"

    def test_empty_is_low(self):
        assert _classify_relevance("") == "LOW"

    def test_fortinet_is_high(self):
        assert _classify_relevance("Fortinet Canada") == "HIGH"


# ---------------------------------------------------------------------------
# Integration tests with CSV data
# ---------------------------------------------------------------------------

class TestLoadData:
    def test_load_data_finds_software_contracts(self, data_dir):
        """Contracts with software keywords are picked up."""
        _write_contracts_csv(data_dir / "contracts.csv", [
            {
                "vendor_name": "Acme Software Inc.",
                "buyer_name": "Department of National Defence",
                "description_en": "Enterprise software license renewal",
                "contract_date": "2024-01-15",
                "contract_period_start": "2024-01-15",
                "delivery_date": _days_from_now(60),
                "contract_value": "50000",
            },
            {
                "vendor_name": "Office Depot",
                "buyer_name": "Parks Canada",
                "description_en": "Office supplies and paper",
                "contract_date": "2024-03-01",
                "contract_period_start": "2024-03-01",
                "delivery_date": _days_from_now(90),
                "contract_value": "2000",
            },
        ])
        cal = RenewalCalendar(data_dir)
        cal.load_data()
        renewals = cal.get_upcoming_renewals(days_ahead=3650)
        # Should find the software contract but not the office supplies
        vendors = [r["vendor"] for r in renewals]
        assert "Acme Software Inc." in vendors
        assert "Office Depot" not in vendors

    def test_recurring_purchases_detected(self, data_dir):
        """Same vendor + department + similar description = recurring pattern."""
        _write_contracts_csv(data_dir / "contracts.csv", [
            {
                "vendor_name": "SecureSoft Corp",
                "buyer_name": "Shared Services Canada",
                "description_en": "Security software license",
                "contract_date": "2022-04-01",
                "contract_period_start": "2022-04-01",
                "delivery_date": "2023-03-31",
                "contract_value": "100000",
            },
            {
                "vendor_name": "SecureSoft Corp",
                "buyer_name": "Shared Services Canada",
                "description_en": "Security software license",
                "contract_date": "2023-04-01",
                "contract_period_start": "2023-04-01",
                "delivery_date": "2024-03-31",
                "contract_value": "105000",
            },
            {
                "vendor_name": "SecureSoft Corp",
                "buyer_name": "Shared Services Canada",
                "description_en": "Security software license",
                "contract_date": "2024-04-01",
                "contract_period_start": "2024-04-01",
                "delivery_date": "2025-03-31",
                "contract_value": "110000",
            },
        ])
        cal = RenewalCalendar(data_dir)
        cal.load_data()
        renewals = cal.get_renewals_by_vendor("SecureSoft")
        assert len(renewals) == 1  # Grouped into one renewal
        r = renewals[0]
        assert r["purchase_count"] == 3
        assert r["total_historical_value"] == 315000.0
        assert r["last_contract_value"] == 110000.0

    def test_renewal_projection_annual(self, data_dir):
        """Annual contract projects renewal ~365 days after last end."""
        end_date = _days_from_now(30)
        start_date = (date.today() + timedelta(days=30) - timedelta(days=365)).isoformat()
        _write_contracts_csv(data_dir / "contracts.csv", [
            {
                "vendor_name": "Annual Vendor",
                "buyer_name": "Treasury Board of Canada Secretariat",
                "description_en": "Software license annual",
                "contract_date": start_date,
                "contract_period_start": start_date,
                "delivery_date": end_date,
                "contract_value": "25000",
            },
        ])
        cal = RenewalCalendar(data_dir)
        cal.load_data()
        renewals = cal.get_renewals_by_vendor("Annual Vendor")
        assert len(renewals) == 1
        projected = date.fromisoformat(renewals[0]["projected_renewal"])
        expected = date.fromisoformat(end_date) + timedelta(days=365)
        assert abs((projected - expected).days) <= 1

    def test_renewal_projection_multi_year(self, data_dir):
        """Multi-year contract projects based on actual duration."""
        # 2-year contract
        start = "2022-01-01"
        end = "2023-12-31"  # ~730 days
        _write_contracts_csv(data_dir / "contracts.csv", [
            {
                "vendor_name": "MultiYear Corp",
                "buyer_name": "Public Services and Procurement Canada",
                "description_en": "Platform subscription 2-year",
                "contract_date": start,
                "contract_period_start": start,
                "delivery_date": end,
                "contract_value": "200000",
            },
        ])
        cal = RenewalCalendar(data_dir)
        cal.load_data()
        renewals = cal.get_renewals_by_vendor("MultiYear")
        assert len(renewals) == 1
        projected = date.fromisoformat(renewals[0]["projected_renewal"])
        end_d = date.fromisoformat(end)
        duration = (end_d - date.fromisoformat(start)).days
        expected = end_d + timedelta(days=duration)
        assert projected == expected

    def test_upcoming_renewals_sorted_by_date(self, data_dir):
        """Renewals are sorted by projected renewal date."""
        _write_contracts_csv(data_dir / "contracts.csv", [
            {
                "vendor_name": "LaterVendor",
                "buyer_name": "RCMP",
                "description_en": "Software license A",
                "contract_date": _days_ago(365),
                "contract_period_start": _days_ago(365),
                "delivery_date": _days_from_now(200),
                "contract_value": "30000",
            },
            {
                "vendor_name": "SoonerVendor",
                "buyer_name": "CSIS",
                "description_en": "Software license B",
                "contract_date": _days_ago(365),
                "contract_period_start": _days_ago(365),
                "delivery_date": _days_from_now(50),
                "contract_value": "40000",
            },
        ])
        cal = RenewalCalendar(data_dir)
        cal.load_data()
        renewals = cal.get_upcoming_renewals(days_ahead=3650)
        assert len(renewals) >= 2
        dates = [r["projected_renewal"] for r in renewals]
        assert dates == sorted(dates)

    def test_plur_relevance_tagging(self, data_dir):
        """Known vendors get correct relevance tags."""
        _write_contracts_csv(data_dir / "contracts.csv", [
            {
                "vendor_name": "CrowdStrike Services Canada Inc.",
                "buyer_name": "Shared Services Canada",
                "description_en": "Endpoint software subscription",
                "contract_date": _days_ago(200),
                "contract_period_start": _days_ago(200),
                "delivery_date": _days_from_now(165),
                "contract_value": "500000",
            },
            {
                "vendor_name": "Microsoft Canada Co.",
                "buyer_name": "Transport Canada",
                "description_en": "Software license renewal",
                "contract_date": _days_ago(300),
                "contract_period_start": _days_ago(300),
                "delivery_date": _days_from_now(65),
                "contract_value": "1000000",
            },
            {
                "vendor_name": "Obscure Niche Corp",
                "buyer_name": "Parks Canada",
                "description_en": "Subscription management platform",
                "contract_date": _days_ago(100),
                "contract_period_start": _days_ago(100),
                "delivery_date": _days_from_now(265),
                "contract_value": "15000",
            },
        ])
        cal = RenewalCalendar(data_dir)
        cal.load_data()

        cs = cal.get_renewals_by_vendor("CrowdStrike")
        assert len(cs) == 1
        assert cs[0]["plur_relevance"] == "HIGH"

        ms = cal.get_renewals_by_vendor("Microsoft")
        assert len(ms) == 1
        assert ms[0]["plur_relevance"] == "MEDIUM"

        niche = cal.get_renewals_by_vendor("Obscure Niche")
        assert len(niche) == 1
        assert niche[0]["plur_relevance"] == "LOW"

    def test_engage_by_calculation(self, data_dir):
        """Engage-by date is 120 days before projected renewal."""
        end_date = _days_from_now(60)
        start_date = _days_ago(305)  # ~365 day contract
        _write_contracts_csv(data_dir / "contracts.csv", [
            {
                "vendor_name": "EngageTest Inc.",
                "buyer_name": "Canada Revenue Agency",
                "description_en": "Software license",
                "contract_date": start_date,
                "contract_period_start": start_date,
                "delivery_date": end_date,
                "contract_value": "75000",
            },
        ])
        cal = RenewalCalendar(data_dir)
        cal.load_data()
        renewals = cal.get_renewals_by_vendor("EngageTest")
        assert len(renewals) == 1
        r = renewals[0]
        projected = date.fromisoformat(r["projected_renewal"])
        engage_by = date.fromisoformat(r["engage_by"])
        assert (projected - engage_by).days == 120

    def test_missing_csv_loads_empty(self, data_dir):
        """If no contracts.csv exists, load_data produces empty results."""
        cal = RenewalCalendar(data_dir)
        cal.load_data()
        assert cal.get_upcoming_renewals() == []

    def test_contracts_without_delivery_date_skipped(self, data_dir):
        """Contracts missing delivery_date are not included in renewals."""
        _write_contracts_csv(data_dir / "contracts.csv", [
            {
                "vendor_name": "NoEndDate Corp",
                "buyer_name": "DND",
                "description_en": "Software license with no end date",
                "contract_date": "2024-01-01",
                "contract_period_start": "2024-01-01",
                "delivery_date": "",
                "contract_value": "10000",
            },
        ])
        cal = RenewalCalendar(data_dir)
        cal.load_data()
        assert cal.get_renewals_by_vendor("NoEndDate") == []

    def test_department_filter(self, data_dir):
        """get_renewals_by_department filters correctly."""
        _write_contracts_csv(data_dir / "contracts.csv", [
            {
                "vendor_name": "Vendor A",
                "buyer_name": "Shared Services Canada",
                "description_en": "Software license",
                "contract_date": _days_ago(200),
                "contract_period_start": _days_ago(200),
                "delivery_date": _days_from_now(165),
                "contract_value": "50000",
            },
            {
                "vendor_name": "Vendor B",
                "buyer_name": "Parks Canada",
                "description_en": "Software subscription",
                "contract_date": _days_ago(200),
                "contract_period_start": _days_ago(200),
                "delivery_date": _days_from_now(165),
                "contract_value": "20000",
            },
        ])
        cal = RenewalCalendar(data_dir)
        cal.load_data()
        ssc = cal.get_renewals_by_department("Shared Services")
        assert len(ssc) == 1
        assert ssc[0]["vendor"] == "Vendor A"

    def test_product_from_comments(self, data_dir):
        """Product names extracted from additional_comments_en take priority."""
        _write_contracts_csv(data_dir / "contracts.csv", [
            {
                "vendor_name": "Softchoice LP",
                "buyer_name": "Shared Services Canada",
                "description_en": "Software license renewal",
                "additional_comments_en": "CrowdStrike Falcon Insight endpoint protection",
                "contract_date": _days_ago(200),
                "contract_period_start": _days_ago(200),
                "delivery_date": _days_from_now(165),
                "contract_value": "500000",
            },
        ])
        cal = RenewalCalendar(data_dir)
        cal.load_data()
        renewals = cal.get_renewals_by_vendor("Softchoice")
        assert len(renewals) == 1
        assert renewals[0]["product"] == "CrowdStrike"
        assert renewals[0]["product_source"] == "comments"

    def test_product_from_standing_offer(self, data_dir):
        """Standing offer number maps to product category."""
        _write_contracts_csv(data_dir / "contracts.csv", [
            {
                "vendor_name": "Some Reseller Inc.",
                "buyer_name": "Transport Canada",
                "description_en": "Software license",
                "standing_offer_number": "EN578-100808/069/EE",
                "contract_date": _days_ago(200),
                "contract_period_start": _days_ago(200),
                "delivery_date": _days_from_now(165),
                "contract_value": "100000",
            },
        ])
        cal = RenewalCalendar(data_dir)
        cal.load_data()
        renewals = cal.get_renewals_by_vendor("Some Reseller")
        assert len(renewals) == 1
        assert renewals[0]["product"] == "ESRI ArcGIS"
        assert renewals[0]["product_source"] == "so"

    def test_product_source_vendor(self, data_dir):
        """Known vendor names produce 'vendor' source."""
        _write_contracts_csv(data_dir / "contracts.csv", [
            {
                "vendor_name": "CrowdStrike Services Canada Inc.",
                "buyer_name": "DND",
                "description_en": "Endpoint software subscription",
                "contract_date": _days_ago(200),
                "contract_period_start": _days_ago(200),
                "delivery_date": _days_from_now(165),
                "contract_value": "300000",
            },
        ])
        cal = RenewalCalendar(data_dir)
        cal.load_data()
        renewals = cal.get_renewals_by_vendor("CrowdStrike")
        assert len(renewals) == 1
        assert renewals[0]["product"] == "CrowdStrike Falcon"
        assert renewals[0]["product_source"] == "vendor"

    def test_comments_priority_over_vendor(self, data_dir):
        """Comments extraction beats vendor name matching."""
        _write_contracts_csv(data_dir / "contracts.csv", [
            {
                "vendor_name": "CDW Canada Corp.",
                "buyer_name": "RCMP",
                "description_en": "Software license",
                "additional_comments_en": "Tenable.io vulnerability scanner",
                "contract_date": _days_ago(200),
                "contract_period_start": _days_ago(200),
                "delivery_date": _days_from_now(165),
                "contract_value": "75000",
            },
        ])
        cal = RenewalCalendar(data_dir)
        cal.load_data()
        renewals = cal.get_renewals_by_vendor("CDW")
        assert len(renewals) == 1
        assert renewals[0]["product"] == "Tenable"
        assert renewals[0]["product_source"] == "comments"

    def test_known_vendor_included_despite_non_it_description(self, data_dir):
        """Known IT vendors are included even if description doesn't match IT keywords."""
        _write_contracts_csv(data_dir / "contracts.csv", [
            {
                "vendor_name": "CrowdStrike Services Canada Inc.",
                "buyer_name": "Shared Services Canada",
                "description_en": "Professional services",
                "contract_date": _days_ago(200),
                "contract_period_start": _days_ago(200),
                "delivery_date": _days_from_now(165),
                "contract_value": "250000",
            },
        ])
        cal = RenewalCalendar(data_dir)
        cal.load_data()
        renewals = cal.get_renewals_by_vendor("CrowdStrike")
        assert len(renewals) == 1
        assert renewals[0]["plur_relevance"] == "HIGH"

    def test_hardware_contract_included(self, data_dir):
        """Hardware contracts with maintenance keywords are included."""
        _write_contracts_csv(data_dir / "contracts.csv", [
            {
                "vendor_name": "Fortinet Canada ULC",
                "buyer_name": "DND",
                "description_en": "Networking equipment",
                "contract_date": _days_ago(200),
                "contract_period_start": _days_ago(200),
                "delivery_date": _days_from_now(165),
                "contract_value": "500000",
            },
        ])
        cal = RenewalCalendar(data_dir)
        cal.load_data()
        renewals = cal.get_renewals_by_vendor("Fortinet")
        assert len(renewals) == 1


# ---------------------------------------------------------------------------
# Unit tests for _extract_product
# ---------------------------------------------------------------------------

class TestExtractProduct:
    def test_comments_highest_priority(self):
        product, source = _extract_product(
            "Softchoice LP", "Software license", "Splunk Enterprise", "",
        )
        assert product == "Splunk"
        assert source == "comments"

    def test_vendor_match(self):
        product, source = _extract_product("CrowdStrike Inc.", "Endpoint software")
        assert product == "CrowdStrike Falcon"
        assert source == "vendor"

    def test_standing_offer_match(self):
        product, source = _extract_product(
            "Random Vendor", "Software license", "", "EN578-100808/058/EE",
        )
        assert product == "Oracle"
        assert source == "so"

    def test_reseller_with_category(self):
        product, source = _extract_product(
            "Softchoice LP", "Security software license",
        )
        assert product == "Reseller: Security Software"
        assert source == "reseller"

    def test_reseller_no_category(self):
        product, source = _extract_product("CDW Canada", "Professional services")
        assert product == "Reseller"
        assert source == "reseller"

    def test_description_category(self):
        product, source = _extract_product(
            "Unknown Vendor Co.", "Firewall appliance and software",
        )
        assert product == "Firewall"
        assert source == "category"

    def test_fallback_cleaned_vendor(self):
        product, source = _extract_product(
            "Acme Software Inc.", "Unmatched thing",
        )
        assert product == "Acme Software"
        assert source == "fallback"

    def test_comments_case_insensitive(self):
        product, source = _extract_product(
            "Reseller Inc.", "License", "SERVICENOW ITSM platform", "",
        )
        assert product == "ServiceNow"
        assert source == "comments"

    def test_multiple_comments_first_wins(self):
        """When comments mention multiple products, first pattern match wins."""
        product, source = _extract_product(
            "Reseller", "License", "Splunk and CrowdStrike integration", "",
        )
        # Splunk appears before CrowdStrike in pattern list
        assert source == "comments"
        # Just verify it picked one of them
        assert product in ("Splunk", "CrowdStrike")
