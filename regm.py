"""
Research safe harbor summary (public data only; not legal advice).

Thresholds used
- Reg M "actively traded": ADTV >= US$1 million and public float >= US$150 million.
- Rule 139(a)(1): issuer meets Form S-3/F-3 registrant requirements (12+ months of
  timely reporting) and the US$75 million public float test, and is not a shell,
  blank-check or ineligible issuer. Foreign private issuers may instead use the
  US$700 million worldwide float path.
- EGC: flagged on the annual report cover (revenue cap US$1.235 billion).
- FINRA Rule 2241 quiet periods: 10 days after an IPO, 3 days after a follow-on for
  managers/co-managers; not applicable to EGC offerings.
"""
from datetime import date, timedelta

NT_FORMS = ("NT 10-K", "NT 10-Q", "NT 20-F", "NT 40-F")
PERIODIC = ("10-K", "10-Q", "20-F", "40-F")


def _usd(v):
    if v is None:
        return "n/a"
    for div, suf in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(v) >= div:
            return f"US${v / div:,.1f}{suf}"
    return f"US${v:,.0f}"


def analyse(p):
    m, c, cov = p["market"], p["company"], p.get("cover", {})
    filings = p.get("filings", [])
    yr_ago = (date.today() - timedelta(days=365)).isoformat()
    three_yr = (date.today() - timedelta(days=3 * 365)).isoformat()

    adtv = m.get("adtv_usd")
    pf = m.get("public_float_usd") or m.get("market_cap_usd")
    pf_label = "reported" if m.get("public_float_usd") else ("market-cap proxy" if pf else "")
    periodic = [f for f in filings if f["form"] in PERIODIC]
    reporting_12m = bool(periodic and periodic[-1]["filingDate"] <= yr_ago)
    late = any(f["form"] in NT_FORMS and f["filingDate"] >= yr_ago for f in filings)
    bankrupt = any(f["form"].startswith("8-K") and "1.03" in (f.get("items") or "") and f["filingDate"] >= three_yr
                   for f in filings)
    shell = cov.get("EntityShellCompany") or str(c.get("sic")) == "6770"
    egc = cov.get("EntityEmergingGrowthCompany")
    active = None if adtv is None or pf is None else (adtv >= 1_000_000 and pf >= 150_000_000)

    conds = [reporting_12m, not late, (pf >= 75_000_000) if pf is not None else None, not shell, not bankrupt]
    if conds[0] is False or conds[2] is False:      # too new to S-3/F-3 eligibility, or float too small
        r139 = "Not available"
    elif False in conds or None in conds:
        r139 = "Needs review"
    else:
        r139 = "Likely available"

    harbors = [
        ("Rule 139(a)(1) issuer-specific research", r139,
         "S-3/F-3 eligible (12+ months timely reporting), float of US$75M or more, not a shell or ineligible issuer"),
        ("Rule 139(a)(2) industry research", "Available, subject to conditions" if periodic else "Needs review",
         "Issuer is an SEC reporting company; report must cover many issuers in the industry"),
        ("JOBS Act EGC research", "Available" if egc else ("Not applicable" if egc is False else "Needs review"),
         "Emerging growth company" if egc else ("Not an emerging growth company" if egc is False else "EGC flag not found")),
        ("FINRA 2241 quiet period",
         "None (EGC)" if egc else ("Exception likely (actively traded + Rule 139)" if active and r139 == "Likely available"
                                   else "Applies to managers/co-managers"),
         "10 days after an IPO, 3 days after a follow-on; none for EGC offerings"),
    ]
    facts = [("Emerging growth company", {True: "Yes", False: "No", None: "Not tagged"}[egc]),
             ("Reg M actively traded", {True: "Yes", False: "No", None: "Needs market data"}[active]),
             ("Worldwide ADTV (60 days)", _usd(adtv)),
             (f"Public float ({pf_label or 'n/a'})", _usd(pf)),
             ("Foreign private issuer", "Yes" if c.get("foreign_private_issuer") else "No")]
    summary = (f"Rule 139 issuer-specific research {r139.lower()}"
               + ("; EGC, so the JOBS Act research provision applies and there is no FINRA quiet period" if egc else "")
               + ("; actively traded under Reg M" if active else ("; not actively traded under Reg M" if active is False else ""))
               + ". Preliminary screen from public data, not legal advice; firm-side conditions (regular course, "
                 "not an initiation, offering role) need confirming.")
    return {"summary": summary, "harbors": harbors, "facts": facts, "actively_traded": active}
