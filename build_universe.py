#!/usr/bin/env python3
"""
Build data/universe.csv: U.S. and Canadian Technology and Biotech companies
listed on a U.S. exchange (Nasdaq, NYSE, NYSE American, Cboe).

It reads every exchange-listed company from the SEC, checks each one's
industry code (SIC) and location, and keeps the matches. Canadian companies
are included when they are registered with the SEC (most larger ones are,
through Form 40-F or 10-K). Takes about 20-30 minutes because the SEC allows
about 10 requests a second.

Usage: python3 build_universe.py --email you@example.com
"""
import argparse
import csv
import json
import os
import sys
import time

import sources as src
from sectors import sector_for_sic, country_for_code

FIELDS = ["cik", "name", "tickers", "exchange", "sector", "sic", "industry",
          "hq_city", "hq_country", "incorporation_country", "filer_category"]
LISTED = {"Nasdaq", "NYSE", "CBOE"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--email", default=os.environ.get("SEC_CONTACT_EMAIL", ""))
    ap.add_argument("--out", default="data/universe.csv")
    ap.add_argument("--limit", type=int, help="Check only the first N companies (quick test)")
    a = ap.parse_args()

    rows = src.sec_tickers(a.email)
    by_cik = {}
    for r in rows:
        if r["exchange"] in LISTED:
            by_cik.setdefault(r["cik"], []).append(r)
    ciks = list(by_cik)[: a.limit] if a.limit else list(by_cik)
    print(f"Checking {len(ciks):,} exchange-listed companies...")

    out, start = [], time.time()
    for i, cik in enumerate(ciks, 1):
        if i % 500 == 0:
            print(f"  {i:,}/{len(ciks):,}  kept {len(out):,}  ({(time.time() - start) / 60:.1f} min)")
        try:
            sub = src.sec_submissions(cik, a.email)
        except src.DataError as e:
            print(f"  skip {cik}: {e}", file=sys.stderr)
            continue
        sector = sector_for_sic(sub.get("sic"))
        if sector == "Other":
            continue
        biz = (sub.get("addresses") or {}).get("business") or {}
        hq = country_for_code(biz.get("stateOrCountry"), biz.get("stateOrCountryDescription"))
        inc = country_for_code(sub.get("stateOfIncorporation"), sub.get("stateOfIncorporationDescription"))
        if hq not in ("United States", "Canada") and inc != "Canada":
            continue
        tick = by_cik[cik]
        out.append({
            "cik": cik, "name": tick[0]["name"] if tick[0]["name"] and not tick[0]["name"].isupper() else (sub.get("name") or tick[0]["name"]),
            "tickers": " ".join(t["ticker"] for t in tick), "exchange": tick[0]["exchange"],
            "sector": sector, "sic": sub.get("sic", ""), "industry": sub.get("sicDescription", ""),
            "hq_city": (biz.get("city") or "").title(), "hq_country": hq or inc,
            "incorporation_country": inc, "filer_category": sub.get("category") or "",
        })

    out.sort(key=lambda r: r["name"].lower())
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(out)
    by = {}
    for r in out:
        by[(r["sector"], r["hq_country"])] = by.get((r["sector"], r["hq_country"]), 0) + 1
    print(f"Wrote {len(out):,} companies to {a.out}: " + ", ".join(f"{k[0]}/{k[1]} {v}" for k, v in sorted(by.items())))


if __name__ == "__main__":
    main()
