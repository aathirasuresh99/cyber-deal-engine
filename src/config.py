"""Market configuration — the ONLY place the target geography/segment is defined.

This is what makes the architecture geo-agnostic: the product logic (schema, brief
generation, retrieval, ingestion) never hardcodes a country. To serve a new market you
add a MarketProfile and switch ACTIVE_MARKET — no code changes anywhere else.
"""
from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class MarketProfile:
    key: str
    label: str
    # Compliance regimes to flag as a *secondary* sales angle (hero stays breach/vuln).
    compliance_frameworks: List[str]
    # Search terms ingesters use to find relevant security signals (Phase 2+).
    breach_keywords: List[str]


INDIA_MIDMARKET = MarketProfile(
    key="in-midmarket",
    label="Indian mid-market SaaS & fintech",
    compliance_frameworks=[
        "DPDP Act (India)", "RBI data-localization norms", "SEBI regulations",
        "CERT-In incident-reporting directions", "PCI-DSS",
    ],
    breach_keywords=[
        "data breach", "data leak", "ransomware", "hacked", "exposed database",
        "vulnerability", "CVE", "phishing", "credential leak", "misconfiguration",
    ],
)

# Present only to prove the design is geo-agnostic — flip ACTIVE_MARKET to use it.
US_TECH = MarketProfile(
    key="us-tech",
    label="US technology companies",
    compliance_frameworks=["SOC 2", "HIPAA", "CCPA", "GDPR", "PCI-DSS", "FedRAMP"],
    breach_keywords=[
        "data breach", "data leak", "ransomware", "hacked", "exposed database",
        "vulnerability", "CVE", "zero-day", "phishing", "supply-chain attack",
    ],
)

# Region-neutral default: no single country's regime is assumed. The frameworks below are a
# cross-region MENU of examples the model can draw from — the brief prompt tells it to match the
# regime to each company's OWN jurisdiction/sector, so this profile works for companies anywhere.
GLOBAL = MarketProfile(
    key="global",
    label="companies worldwide (any sector, any region)",
    compliance_frameworks=[
        "GDPR", "SOC 2", "ISO 27001", "PCI-DSS", "HIPAA", "CCPA", "DPDP Act",
    ],
    breach_keywords=[
        "data breach", "data leak", "ransomware", "hacked", "exposed database",
        "vulnerability", "CVE", "zero-day", "phishing", "credential leak",
        "supply-chain attack", "misconfiguration",
    ],
)

MARKETS = {p.key: p for p in (GLOBAL, INDIA_MIDMARKET, US_TECH)}

# --- The single switch that chooses the target market for this build ---
# GLOBAL = no geographic lean; briefs any company and matches compliance to the company's own region.
ACTIVE_MARKET: MarketProfile = GLOBAL
