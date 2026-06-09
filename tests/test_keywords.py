"""Tests for lib/keywords.py - keyword matching and classify_opportunity()."""

import sys
from pathlib import Path

# Allow imports from project root without installing as package
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from lib.keywords import (
    classify_opportunity, HIGH_CONFIDENCE_CYBER, PLUR_SPECIFIC, BROADER_IT,
    NEGATIVE_KEYWORDS, UNSPSC_CODES, GSIN_CODES, normalize_text, VENDOR_PRODUCTS,
)


# ---------------------------------------------------------------------------
# Tier 1: High-confidence cyber matches
# ---------------------------------------------------------------------------

class TestHighConfidenceCyber:
    def test_cybersecurity_in_title(self):
        result = classify_opportunity("Cybersecurity Services for Government of Canada")
        assert result["tier"] == 1
        assert "cybersecurity" in [kw.lower() for kw in result["matched_keywords"]]
        assert result["confidence"] > 0

    def test_siem_acronym_matches(self):
        result = classify_opportunity("SIEM Platform Deployment and Integration")
        assert result["tier"] == 1
        assert "SIEM" in result["matched_keywords"]

    def test_zero_trust_two_word(self):
        result = classify_opportunity("Zero Trust Architecture Assessment")
        assert result["tier"] == 1
        assert "zero trust" in result["matched_keywords"]

    def test_mfa_acronym(self):
        result = classify_opportunity("MFA Implementation for Corporate Network")
        assert result["tier"] == 1
        assert "MFA" in result["matched_keywords"]

    def test_penetration_testing(self):
        result = classify_opportunity("Annual Penetration Testing Services")
        assert result["tier"] == 1
        assert "penetration testing" in result["matched_keywords"]

    def test_multi_keyword_boosts_confidence(self):
        """Multiple cyber keywords in one opportunity should push confidence up."""
        single = classify_opportunity("Cybersecurity audit")
        multi = classify_opportunity(
            "Cybersecurity and SIEM deployment",
            "SOC integration, vulnerability assessment, DLP, encryption, PKI review",
        )
        assert multi["confidence"] > single["confidence"]

    def test_itsg33_canadian_standard(self):
        result = classify_opportunity("Cloud Hosting Compliant with ITSG-33")
        assert result["tier"] == 1
        assert "ITSG-33" in result["matched_keywords"]

    def test_description_extends_matching(self):
        """Cyber keywords in description should still trigger tier 1."""
        result = classify_opportunity(
            "IT Services RFP",
            "The vendor must provide SIEM, endpoint protection, and DLP capabilities.",
        )
        assert result["tier"] == 1


# ---------------------------------------------------------------------------
# Tier 2: PLUR-specific IAM/identity matches
# ---------------------------------------------------------------------------

class TestPlurSpecific:
    def test_passwordless_authentication(self):
        result = classify_opportunity("Passwordless Authentication Platform")
        assert result["tier"] == 2
        assert "passwordless" in result["matched_keywords"]

    def test_ueba_acronym(self):
        result = classify_opportunity("UEBA Tool Procurement")
        assert result["tier"] == 2
        assert "UEBA" in result["matched_keywords"]

    def test_insider_threat_in_description(self):
        result = classify_opportunity(
            "Security Platform RFP",
            "Vendor must address insider threat monitoring and UBA capabilities.",
        )
        assert result["tier"] == 2

    def test_biometric_authentication(self):
        result = classify_opportunity("Biometric Authentication for Employee Access")
        assert result["tier"] == 2

    def test_continuous_authentication(self):
        result = classify_opportunity("Continuous Authentication Solution for Remote Workforce")
        assert result["tier"] == 2
        assert "continuous authentication" in result["matched_keywords"]

    def test_tier2_overrides_tier3(self):
        """If both tier 2 and tier 3 keywords match, result should be tier 2."""
        result = classify_opportunity(
            "IT Managed Services with Identity Verification",
        )
        assert result["tier"] == 2


# ---------------------------------------------------------------------------
# Tier 3: Broader IT matches
# ---------------------------------------------------------------------------

class TestBroaderIT:
    def test_cloud_migration(self):
        result = classify_opportunity("Cloud Migration Services for Finance Department")
        assert result["tier"] == 3
        assert "cloud migration" in result["matched_keywords"]

    def test_it_modernization(self):
        result = classify_opportunity("IT Modernization Project Phase 2")
        assert result["tier"] == 3

    def test_managed_services(self):
        result = classify_opportunity("Managed Services Contract 2026")
        assert result["tier"] == 3
        assert "managed services" in result["matched_keywords"]

    def test_systems_integration(self):
        result = classify_opportunity("Systems Integration for New ERP Platform")
        assert result["tier"] == 3

    def test_dlp_alone_is_tier3(self):
        """'DLP' acronym alone should be Tier 3, not Tier 1 (false positive fix)."""
        result = classify_opportunity(
            "Street Sweeper, Regenerative Air, Cab Over, Self Propelled with DLP"
        )
        assert result["tier"] == 3
        assert "DLP" in result["matched_keywords"]

    def test_data_loss_prevention_is_tier1(self):
        """'data loss prevention' (full phrase) should remain Tier 1."""
        result = classify_opportunity("Data Loss Prevention Solution Procurement")
        assert result["tier"] == 1
        assert "data loss prevention" in result["matched_keywords"]

    def test_dlp_with_cybersecurity_keyword_is_tier1(self):
        """'DLP' + 'cybersecurity' together should match as Tier 1 (cyber keyword wins)."""
        result = classify_opportunity(
            "Cybersecurity Platform with DLP Capabilities"
        )
        assert result["tier"] == 1
        assert "cybersecurity" in result["matched_keywords"]
        # Both keywords may be matched, but tier should be 1 (cyber takes priority)


# ---------------------------------------------------------------------------
# Tier 0: No match
# ---------------------------------------------------------------------------

class TestNoMatch:
    def test_office_furniture(self):
        result = classify_opportunity("Office Furniture Supply and Installation")
        assert result["tier"] == 0
        assert result["matched_keywords"] == []
        assert result["confidence"] == 0.0

    def test_catering_services(self):
        result = classify_opportunity("Catering Services for Government Cafeteria")
        assert result["tier"] == 0

    def test_construction(self):
        result = classify_opportunity("General Contractor for Building Renovation")
        assert result["tier"] == 0

    def test_empty_strings(self):
        result = classify_opportunity("", "")
        assert result["tier"] == 0
        assert result["confidence"] == 0.0


# ---------------------------------------------------------------------------
# Case insensitivity
# ---------------------------------------------------------------------------

class TestCaseInsensitivity:
    def test_all_caps(self):
        result = classify_opportunity("CYBERSECURITY ASSESSMENT SERVICES")
        assert result["tier"] == 1

    def test_all_lowercase(self):
        result = classify_opportunity("cybersecurity assessment services")
        assert result["tier"] == 1

    def test_mixed_case(self):
        result = classify_opportunity("CyBeRsEcUrItY Assessment")
        assert result["tier"] == 1

    def test_soc_uppercase(self):
        """SOC as uppercase acronym should match; lowercase 'soc' should not (avoids 'social')."""
        result = classify_opportunity("SOC services for enterprise")
        assert result["tier"] == 1
        assert "SOC" in result["matched_keywords"]


# ---------------------------------------------------------------------------
# Word boundary / false positive prevention
# ---------------------------------------------------------------------------

class TestWordBoundaries:
    def test_siem_does_not_match_siemens(self):
        """'SIEM' should not match 'Siemens' (a company name)."""
        result = classify_opportunity("Siemens Industrial Control System Procurement")
        assert "SIEM" not in result["matched_keywords"]

    def test_soc_does_not_match_societe(self):
        """'SOC' should not match 'Société Générale' or 'societe'."""
        result = classify_opportunity("Societe Generale Banking Software License")
        assert "SOC" not in result["matched_keywords"]

    def test_dlp_does_not_match_partial(self):
        """'DLP' should not match as part of a longer word."""
        result = classify_opportunity("DLPT Language Proficiency Test Administration")
        assert "DLP" not in result["matched_keywords"]

    def test_iam_does_not_match_iam_prefix(self):
        """'IAM' as standalone should not match 'IAMGOLD' or similar."""
        result = classify_opportunity("IAMGOLD Mining Services Contract")
        assert "IAM" not in result["matched_keywords"]

    def test_uba_does_not_match_partial(self):
        """'UBA' should not match 'CUBA' or 'UBAnd'."""
        result = classify_opportunity("Cuba Trade Relations Office Supplies")
        assert "UBA" not in result["matched_keywords"]

    def test_cyber_security_two_words(self):
        """'cyber security' (two words) should match as a phrase."""
        result = classify_opportunity("Cyber Security Risk Assessment")
        assert result["tier"] == 1
        assert "cyber security" in result["matched_keywords"]

    def test_iam_standalone_matches(self):
        """'IAM' as a standalone word should match."""
        result = classify_opportunity("IAM Solution Procurement for Federal Agency")
        assert result["tier"] == 1
        assert "IAM" in result["matched_keywords"]

    def test_pam_does_not_match_name(self):
        """'PAM' should not match the name 'Pam' in a sentence."""
        result = classify_opportunity("Contact Pam Smith for details")
        assert result["tier"] == 0
        assert "PAM" not in result["matched_keywords"]


# ---------------------------------------------------------------------------
# Confidence scoring sanity checks
# ---------------------------------------------------------------------------

class TestConfidence:
    def test_confidence_in_range(self):
        for title in [
            "Cybersecurity audit",
            "Office furniture",
            "SIEM UEBA MFA DLP SOC IAM PKI penetration testing vulnerability assessment",
        ]:
            result = classify_opportunity(title)
            assert 0.0 <= result["confidence"] <= 1.0

    def test_title_match_higher_confidence_than_description_only(self):
        """Title hit should yield higher confidence than description-only hit."""
        title_hit = classify_opportunity("SIEM Platform Procurement")
        desc_only = classify_opportunity("IT Services RFP", "The vendor must provide SIEM.")
        assert title_hit["confidence"] >= desc_only["confidence"]


# ---------------------------------------------------------------------------
# French-language matching
# ---------------------------------------------------------------------------

class TestFrenchKeywords:
    def test_cybersecurite(self):
        result = classify_opportunity("Services de cybersecurite pour le gouvernement")
        assert result["tier"] == 1
        assert "cybersecurite" in result["matched_keywords"]

    def test_securite_information(self):
        result = classify_opportunity("Securite de l'information - evaluation")
        assert result["tier"] == 1

    def test_authentification_multifacteur(self):
        result = classify_opportunity("Mise en oeuvre d'authentification multifacteur")
        assert result["tier"] == 1

    def test_gestion_identites(self):
        result = classify_opportunity("Gestion des identites et des acces")
        assert result["tier"] == 2
        assert "gestion des identites" in result["matched_keywords"]

    def test_french_siem_soar(self):
        result = classify_opportunity("Acquisition d'une solution SIEM et SOAR")
        assert result["tier"] == 1
        assert "SIEM" in result["matched_keywords"]
        assert "SOAR" in result["matched_keywords"]


# ---------------------------------------------------------------------------
# Accent normalization (Phase 0 additions)
# ---------------------------------------------------------------------------

class TestAccentNormalization:
    def test_normalize_text_strips_accents(self):
        assert normalize_text("cybersécurité") == "cybersecurite"
        assert normalize_text("évaluation") == "evaluation"
        assert normalize_text("sécurité") == "securite"

    def test_normalize_text_preserves_plain_ascii(self):
        assert normalize_text("cybersecurity") == "cybersecurity"
        assert normalize_text("SIEM") == "SIEM"

    def test_accented_cybersecurite_classifies(self):
        """'cybersécurité' with accents should match as Tier 1."""
        result = classify_opportunity("Services de cybersécurité")
        assert result["tier"] == 1

    def test_accented_evaluation_securite(self):
        """'Évaluation de la sécurité' with accents should match."""
        result = classify_opportunity("Évaluation de la sécurité")
        assert result["tier"] == 1

    def test_mixed_accent_input(self):
        """Mixed accented and plain text should classify correctly."""
        result = classify_opportunity("Évaluation de la sécurité informatique")
        assert result["tier"] == 1

    def test_accented_french_identity(self):
        """'gestion des identités' with accent should match Tier 2."""
        result = classify_opportunity("Gestion des identités et des accès")
        assert result["tier"] == 2

    def test_ascii_equivalent_still_works(self):
        """Plain ASCII 'cybersecurite' should still match after normalization."""
        result = classify_opportunity("Services de cybersecurite")
        assert result["tier"] == 1

    def test_accented_habilitation(self):
        result = classify_opportunity("Habilitation de sécurité du personnel")
        assert result["tier"] == 1

    def test_accented_description(self):
        """Accents in description should also be normalized."""
        result = classify_opportunity(
            "Services IT",
            "Le fournisseur doit offrir des services de cybersécurité avancés."
        )
        assert result["tier"] == 1

    def test_accent_in_negative_keywords(self):
        """Accented 'agent de sécurité' should trigger negative keyword."""
        result = classify_opportunity("Agent de sécurité - gardiennage")
        assert result["tier"] == 0 or result["confidence"] < 0.1


# ---------------------------------------------------------------------------
# Negative keywords check full corpus (Phase 0 fix)
# ---------------------------------------------------------------------------

class TestNegativeKeywords:
    def test_security_guard_reduces_confidence(self):
        """Security guard in title should reduce confidence even if cyber keywords match."""
        pure_cyber = classify_opportunity("Security assessment services")
        with_guard = classify_opportunity("Security guard and security assessment services")
        assert with_guard["confidence"] < pure_cyber["confidence"]

    def test_pure_guard_services_no_cyber(self):
        """Pure guard services with no cyber keywords should be tier 0."""
        result = classify_opportunity("Security Guard Services for Federal Building")
        assert result["tier"] == 0

    def test_furniture_still_tier0(self):
        result = classify_opportunity("Office furniture and cleaning services")
        assert result["tier"] == 0

    def test_negative_doesnt_kill_strong_match(self):
        """Negative keywords shouldn't zero out a strong cyber match."""
        result = classify_opportunity(
            "Cybersecurity and security guard services",
            "SIEM deployment, SOC operations, penetration testing"
        )
        assert result["tier"] == 1
        assert result["confidence"] > 0

    def test_description_negatives_reduce_confidence(self):
        """Negative keywords in description should also reduce confidence."""
        clean = classify_opportunity(
            "Security Services RFP",
            "Network security operations and SIEM monitoring"
        )
        with_neg = classify_opportunity(
            "Security Services RFP",
            "Network security operations and SIEM monitoring. Also includes security guard patrol services."
        )
        assert with_neg["confidence"] < clean["confidence"]

    def test_description_only_negative_applied(self):
        """Negative in description (not title) should still apply penalty."""
        result = classify_opportunity(
            "Security Assessment",
            "This includes security guard dispatch and cybersecurity audit"
        )
        # Should still classify (has cyber keywords) but with reduced confidence
        assert result["tier"] == 1
        pure = classify_opportunity(
            "Security Assessment",
            "This includes cybersecurity audit"
        )
        assert result["confidence"] < pure["confidence"]


# ---------------------------------------------------------------------------
# Security clearance demotion + construction false positive suppression
# ---------------------------------------------------------------------------

class TestSecurityClearanceDemotion:
    def test_security_clearance_alone_is_tier3(self):
        """'security clearance' alone should be Tier 3, not Tier 1."""
        result = classify_opportunity("Personnel Security Clearance Required")
        assert result["tier"] == 3
        assert "security clearance" in result["matched_keywords"]

    def test_dcc_construction_contract_demoted(self):
        """DND construction contract with 'security clearance' should be penalised by
        construction negative keywords, keeping confidence low."""
        result = classify_opportunity(
            "Barracks Renovation and Construction Services - CFB Trenton",
            "All contractor personnel must hold a valid security clearance. "
            "Work includes demolition, roofing, paving, and general contractor services.",
        )
        # Construction negatives should keep this out of useful range
        assert result["confidence"] < 0.3

    def test_real_cyber_rfp_with_security_clearance_stays_tier1(self):
        """A genuine cyber RFP that also mentions security clearance should remain Tier 1
        because cybersecurity keywords outweigh the clearance signal."""
        result = classify_opportunity(
            "Cybersecurity Operations Centre Services",
            "Vendor staff must hold SECRET security clearance. "
            "Scope includes SIEM deployment, threat detection, and incident response.",
        )
        assert result["tier"] == 1
        assert result["confidence"] > 0.3


# ---------------------------------------------------------------------------
# Title-only mode (Phase 0 addition for Bonfire)
# ---------------------------------------------------------------------------

class TestTitleOnlyMode:
    def test_title_only_captures_cyber_match(self):
        result = classify_opportunity("Cybersecurity RFP", title_only=True)
        assert result["tier"] == 1

    def test_title_only_boosts_confidence(self):
        """title_only mode should give higher confidence for same keywords."""
        normal = classify_opportunity("SIEM Platform")
        title_only = classify_opportunity("SIEM Platform", title_only=True)
        assert title_only["confidence"] >= normal["confidence"]

    def test_title_only_no_match_still_zero(self):
        result = classify_opportunity("Office Furniture", title_only=True)
        assert result["tier"] == 0

    def test_title_only_broader_it(self):
        result = classify_opportunity("IT Modernization Project", title_only=True)
        assert result["tier"] == 3


# ---------------------------------------------------------------------------
# UNSPSC code matching (Phase 0 addition)
# ---------------------------------------------------------------------------

class TestUNSPSCMatching:
    def test_unspsc_matching_boosts_classification(self):
        """UNSPSC code 81112200 (Computer/Network Security) should boost."""
        result = classify_opportunity(
            "IT Services RFP",
            unspsc_codes=["81112200"],
        )
        assert result["tier"] <= 3  # Should get classified
        assert result["confidence"] > 0

    def test_unspsc_with_keyword_match(self):
        """UNSPSC + keyword should give higher confidence than keyword alone."""
        kw_only = classify_opportunity("Cybersecurity audit")
        kw_plus_unspsc = classify_opportunity(
            "Cybersecurity audit",
            unspsc_codes=["43232300"],
        )
        assert kw_plus_unspsc["confidence"] >= kw_only["confidence"]

    def test_unspsc_irrelevant_code_no_boost(self):
        """Non-matching UNSPSC code should not boost."""
        result = classify_opportunity(
            "Office Supplies",
            unspsc_codes=["99999999"],
        )
        assert result["tier"] == 0


# ---------------------------------------------------------------------------
# Vendor product detection
# ---------------------------------------------------------------------------

class TestVendorDetection:
    def test_forgerock_detected(self):
        result = classify_opportunity("ForgeRock IAM License Renewal")
        assert "ForgeRock" in result["vendor_flags"]

    def test_crowdstrike_detected(self):
        result = classify_opportunity("CrowdStrike Falcon EDR Deployment")
        assert "CrowdStrike" in result["vendor_flags"]

    def test_no_vendor_in_generic(self):
        result = classify_opportunity("Cybersecurity Services RFP")
        assert result["vendor_flags"] == []

    def test_vendor_in_description(self):
        result = classify_opportunity(
            "Endpoint Protection Services",
            "Must support SentinelOne integration"
        )
        assert "SentinelOne" in result["vendor_flags"]


# ---------------------------------------------------------------------------
# Product vs Services tagging
# ---------------------------------------------------------------------------

class TestProductType:
    def test_software_licensing_is_product(self):
        result = classify_opportunity("Software Licensing for Cybersecurity Tools")
        assert result["product_type"] == "product"

    def test_consulting_is_services(self):
        result = classify_opportunity("Cybersecurity Consulting Services")
        assert result["product_type"] == "services"

    def test_no_signal_is_empty(self):
        result = classify_opportunity("Cybersecurity RFP")
        assert result["product_type"] == ""


# ---------------------------------------------------------------------------
# Expanded IAM vocabulary
# ---------------------------------------------------------------------------

class TestExpandedIAM:
    def test_iga_identity_governance(self):
        result = classify_opportunity("Identity Governance and Administration Platform")
        assert result["tier"] == 2
        assert "IGA" in result["matched_keywords"] or "identity governance" in result["matched_keywords"]

    def test_sso_single_sign_on(self):
        result = classify_opportunity("Single Sign-On Implementation Project")
        assert result["tier"] == 2

    def test_active_directory(self):
        result = classify_opportunity("Active Directory Migration and Consolidation")
        assert result["tier"] == 2
        assert "Active Directory" in result["matched_keywords"]

    def test_credential_management(self):
        result = classify_opportunity("Credential Management System for Government Employees")
        assert result["tier"] == 2

    def test_icam(self):
        result = classify_opportunity("ICAM Solution for Federal Agency")
        assert result["tier"] == 2
        assert "ICAM" in result["matched_keywords"]


# ---------------------------------------------------------------------------
# UNSPSC codes exist
# ---------------------------------------------------------------------------

class TestClassificationCodes:
    def test_unspsc_codes_populated(self):
        assert len(UNSPSC_CODES) > 0
        assert "43232300" in UNSPSC_CODES  # Network Security Equipment

    def test_negative_keywords_populated(self):
        assert len(NEGATIVE_KEYWORDS) > 0
        assert "security guard" in NEGATIVE_KEYWORDS
