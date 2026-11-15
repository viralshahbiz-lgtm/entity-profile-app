"""
Regulation M and research safe harbor screen.

A preliminary, automated screen built only from public data. It is not legal
advice: thresholds are applied to approximations (for example a 60-day ADTV
from free market data), and several conditions depend on facts only the firm
knows (whether it is a distribution participant, whether a report is an
initiation, and so on). Every result says what it rests on.

Thresholds used
- Reg M Rule 100/101: "actively traded" = ADTV >= US$1 million and public
  float >= US$150 million (no Rule 101 restricted period). Otherwise one
  business day if ADTV >= US$100,000 and float >= US$25 million, else five.
- Rule 102 (issuers, selling holders, affiliated purchasers): no
  actively-traded exception for the subject security.
- Rule 139(a)(1): issuer meets Form S-3/F-3 registrant requirements and the
  US$75 million public float test (or investment grade), is not a shell or
  ineligible issuer; foreign private issuers may instead rely on the
  US$700 million worldwide float path.
- EGC: annual revenue cap US$1.235 billion (SEC 2022 inflation adjustment).
- FINRA Rule 2241 quiet periods: 10 days after an IPO, 3 days after a
  follow-on for managers/co-managers; not applicable to EGC offerings.
- UMIR "highly-liquid security": 100+ trades and C$1 million+ value per day
  over 60 days, or a Reg M actively-traded security.
"""
from datetime import date, timedelta

EGC_REVENUE_CAP = 1_235_000_000
NT_FORMS = ("NT 10-K", "NT 10-Q", "NT 20-F", "NT 40-F")
PERIODIC = ("10-K", "10-Q", "20-F", "40-F")


def _money(v):
    if v is None:
        return "n/a"
    for div, suf in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(v) >= div:
            return f"US${v / div:,.2f}{suf}"
    return f"US${v:,.0f}"


def analyse(p):
    m, c, cov, fin = p["market"], p["company"], p.get("cover", {}), p.get("financials", {})
    filings = p.get("filings", [])
    today = date.today()
    yr_ago = (today - timedelta(days=365)).isoformat()
    three_yr = (today - timedelta(days=3 * 365)).isoformat()

    adtv = m.get("adtv_usd")
    pf = m.get("public_float_usd")
    pf_src = f"cover of annual report, as of {m.get('public_float_date')}" if pf else ""
    if pf is None and m.get("market_cap_usd"):
        pf = m["market_cap_usd"]
        pf_src = "market cap used as an upper-bound proxy (no reported float); affiliates not excluded"

    periodic = [f for f in filings if f["form"] in PERIODIC]
    first_periodic = periodic[-1]["filingDate"] if periodic else None
    reporting_12m = bool(first_periodic and first_periodic <= yr_ago)
    late = [f for f in filings if f["form"] in NT_FORMS and f["filingDate"] >= yr_ago]
    bankrupt = [f for f in filings if f["form"].startswith("8-K") and "1.03" in (f.get("items") or "")
                and f["filingDate"] >= three_yr]
    shell = cov.get("EntityShellCompany")
    blank_check = str(c.get("sic")) == "6770"
    egc = cov.get("EntityEmergingGrowthCompany")
    wksi = cov.get("EntityWellKnownSeasonedIssuer")
    fpi = c.get("foreign_private_issuer")
    rev = fin.get("revenue")
    tsx = next((v for v in m.get("venues", []) if v["currency"] == "CAD"), None)

    inputs = [
        ("Worldwide ADTV (60 calendar days)", _money(adtv) if adtv is not None else "n/a",
         ", ".join(f"{v['exchange']} {v['adtv_days']} days" for v in m.get("venues", [])) or "needs market data"),
        ("Public float", _money(pf) if pf is not None else "n/a", pf_src or "not reported"),
        ("Average daily volume (shares)", f"{m['adv_shares_total']:,.0f}" if m.get("adv_shares_total") else "n/a", "all venues with data"),
        ("Emerging growth company", {True: "Yes", False: "No", None: "Not tagged"}[egc], "annual report cover (Inline XBRL)"),
        ("Well-known seasoned issuer", {True: "Yes", False: "No", None: "Not tagged"}[wksi], "10-K cover (Inline XBRL)"),
        ("Foreign private issuer", "Yes" if fpi else "No", "files 20-F/40-F/6-K" if fpi else "files 10-K/10-Q"),
        ("SEC reporting since", first_periodic or "n/a", "earliest periodic report in recent filing history"),
        ("Late filings (12 months)", str(len(late)), ", ".join(f["form"] for f in late) or "none"),
        ("Shell / blank check", "Yes" if (shell or blank_check) else ("No" if shell is False else "Not tagged"), "cover flag and SIC 6770"),
        ("Last fiscal-year revenue", f"{rev['unit']} {rev['value'] / 1e6:,.1f}M" if rev else "n/a",
         f"period ended {rev['date']}" if rev else "XBRL facts"),
    ]

    # ---- Trading restriction tiers
    have = adtv is not None and pf is not None
    active = have and adtv >= 1_000_000 and pf >= 150_000_000
    one_day = have and adtv >= 100_000 and pf >= 25_000_000
    tests = []
    if not have:
        tests.append({"rule": "Reg M Rule 101", "who": "Distribution participants and affiliated purchasers",
                      "test": "Actively traded: ADTV >= US$1M and float >= US$150M",
                      "result": "Needs data", "status": "na",
                      "detail": "Add market data (ADTV) and confirm public float to run this test."})
    else:
        tests.append({"rule": "Reg M Rule 101", "who": "Distribution participants and affiliated purchasers",
                      "test": "Actively traded: ADTV >= US$1M and float >= US$150M",
                      "result": "Actively traded: no restricted period" if active else
                      ("1 business day before pricing" if one_day else "5 business days before pricing"),
                      "status": "ok" if active else "warn",
                      "detail": "Anti-manipulation rules still apply." if active else
                      "Restricted period runs to completion of the distribution."})
        tests.append({"rule": "Reg M Rule 102", "who": "Issuer, selling holders, affiliated purchasers",
                      "test": "No actively-traded exception for the subject security",
                      "result": "1 business day before pricing" if one_day else "5 business days before pricing",
                      "status": "warn", "detail": "Issuer buybacks and plan purchases need review during the period."})
    tests.append({"rule": "Reg M Rule 104", "who": "Stabilization and syndicate covering",
                  "test": "Stabilizing bid rules, notice and records", "result": "Applies to any stabilization",
                  "status": "info", "detail": ""})
    tests.append({"rule": "Reg M Rule 105", "who": "Buyers in a registered firm-commitment offering for cash",
                  "test": "Short sale in the 5 business days before pricing bars purchase in the offering",
                  "result": "Applies to registered offerings", "status": "info", "detail": ""})
    if tsx:
        val_ok = (tsx.get("adtv_value") or 0) >= 1_000_000
        tests.append({"rule": "UMIR 7.7 (Canada)", "who": "Dealer-restricted persons",
                      "test": "Highly liquid: 100+ trades and C$1M+ value per day over 60 days, or Reg M actively traded",
                      "result": "Highly liquid (via Reg M actively traded)" if active else
                      ("Value test met; trade-count test needs exchange data" if val_ok else "Not highly liquid"),
                      "status": "ok" if active else ("info" if val_ok else "warn"),
                      "detail": f"TSX average daily value C${(tsx.get('adtv_value') or 0) / 1e6:,.2f}M"})

    # ---- Research safe harbors
    harbors = []
    s3_conditions = {
        "SEC reporting for 12+ months": reporting_12m,
        "No late filings in 12 months": not late,
        "Public float >= US$75M": (pf >= 75_000_000) if pf is not None else None,
        "Not a shell or blank-check company": (not shell and not blank_check) if shell is not None else (False if blank_check else None),
        "No bankruptcy filing in 3 years (ineligible issuer check)": not bankrupt,
    }
    missing = [k for k, v in s3_conditions.items() if v is None]
    failed = [k for k, v in s3_conditions.items() if v is False]
    if failed:
        status = "Not available" if "Public float >= US$75M" in failed or "SEC reporting for 12+ months" in failed else "Needs review"
    elif missing:
        status = "Needs review"
    else:
        status = "Likely available"
    basis = "; ".join(f"{'met' if v else ('not met' if v is False else 'unknown')}: {k}" for k, v in s3_conditions.items())
    if fpi:
        basis += ("; foreign private issuer path also needs F-3 eligibility, 12 months on a designated offshore "
                  "market and US$700M+ worldwide float" + (" (float test met)" if pf and pf >= 700_000_000 else ""))
    harbors.append({"name": "Rule 139(a)(1) issuer-specific research", "status": status, "basis": basis,
                    "firm_checks": "Published in the regular course; not an initiation or re-initiation of coverage."})
    harbors.append({"name": "Rule 139(a)(2) industry research",
                    "status": "Available, subject to conditions" if periodic else "Needs review",
                    "basis": "Issuer is an SEC reporting company" if periodic else "No periodic reports found",
                    "firm_checks": "Covers a substantial number of issuers in the industry; issuer not given materially greater prominence."})
    harbors.append({"name": "JOBS Act section 2(a)(3) EGC research",
                    "status": "Available" if egc else ("Not applicable" if egc is False else "Needs review"),
                    "basis": "Issuer is an emerging growth company" if egc else
                    ("Issuer is not an EGC" if egc is False else "EGC flag not found on the annual report cover"),
                    "firm_checks": "Applies to research on an EGC's proposed or pending common equity offering."})
    if egc:
        q_status, q_basis = "Not applicable", "No FINRA 2241 quiet period for EGC offerings"
    elif active and status == "Likely available":
        q_status, q_basis = "Exception likely available", ("Actively traded and Rule 139 conditions met; otherwise 10 days "
                                                           "after an IPO and 3 days after a follow-on for managers/co-managers")
    else:
        q_status, q_basis = "Applies", "10 days after an IPO; 3 days after a follow-on for managers/co-managers"
    harbors.append({"name": "FINRA Rule 2241 quiet period", "status": q_status, "basis": q_basis,
                    "firm_checks": "Applies only if the firm is a manager or co-manager."})
    harbors.append({"name": "Rule 137 (non-participating broker-dealers)", "status": "Available, subject to conditions",
                    "basis": "Research by a firm not participating in the offering, in the regular course",
                    "firm_checks": "Firm is not a participant and receives no issuer compensation for the report."})
    if tsx:
        harbors.append({"name": "UMIR research exemption (Canada)",
                        "status": "Likely available" if active else "Needs review",
                        "basis": "Highly-liquid security" if active else "Depends on highly-liquid status or normal-course dissemination",
                        "firm_checks": "Research disseminated in the normal course of business."})

    egc_note = ""
    if egc and rev and rev["unit"] == "USD" and rev["value"] >= EGC_REVENUE_CAP:
        egc_note = " Revenue exceeds the EGC cap, so EGC status may end at this fiscal year end."
    summary = (
        ("Actively traded under Reg M: no Rule 101 restricted period for the firm. " if active else
         ("Not actively traded: Rule 101 restricted period of " + ("1" if one_day else "5") + " business day(s). " if have
          else "Reg M tier needs market data. ")) +
        f"Rule 139 issuer-specific research: {status.lower()}." +
        (" EGC: research safe harbor and no FINRA quiet period." if egc else "") + egc_note
    )
    return {"inputs": inputs, "tests": tests, "harbors": harbors, "summary": summary,
            "actively_traded": active,
            "caveats": ["Automated screen from public data; not legal advice. Legal and Compliance confirm every determination.",
                        "ADTV here is a 60-calendar-day average from free daily data. Reg M allows two full calendar months "
                        "before filing or 60 consecutive days ending within 10 days of pricing; recompute at the relevant date.",
                        "Reported public float is as of the last day of the issuer's second fiscal quarter."]}
