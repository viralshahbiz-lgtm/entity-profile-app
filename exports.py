"""
Securities CSV: every equity and fixed income security for the company with all identifiers.
Equity rows come first, then fixed income. Opens directly in Excel.
"""
import csv
import io

HEADERS = [
    "Group", "Security Name", "Description", "Security Type", "Ticker", "Exchange", "Listing Country",
    "ISIN", "CUSIP", "SEDOL", "FIGI", "Composite FIGI", "Share Class FIGI",
    "Coupon (%)", "Maturity", "Amount Issued (USD)", "Exchange Listing (Debt)",
    "Issuer Name", "Issuer CIK", "Issuer LEI", "Source", "Source Document", "As Of",
]
SEDOL_NOTE = "Not available (licensed by LSEG)"


def _bond_type(desc):
    d = (desc or "").lower()
    if "convertible" in d or "exchangeable" in d:
        return "Convertible note"
    if "floating" in d:
        return "Floating rate note"
    if "debenture" in d:
        return "Debenture"
    return "Note / bond"


def securities_rows(p):
    c, ids, debt = p["company"], p.get("identifiers") or {}, p.get("debt") or {}
    lei = (ids.get("entity") or {}).get("LEI") or c.get("lei") or ""
    base = {"Issuer Name": c["name"], "Issuer CIK": c["cik"], "Issuer LEI": lei, "As Of": p["as_of"]}
    names = {s["ticker"]: s for s in p.get("securities", [])}
    rows = []

    # Equity: identifier table if loaded, otherwise the listed securities themselves
    eq = ids.get("securities") or [{"ticker": s["ticker"], "exchange": s["exchange"], "type": s["type"], "isin": "", "cusip": "",
                                     "figi": "", "composite_figi": "", "share_class_figi": ""} for s in p.get("securities", [])]
    for x in eq:
        s = names.get(x["ticker"], {})
        country = s.get("country") or ("CA" if x.get("exchange") in ("TSX", "TSXV") else "US")
        rows.append(dict(base, **{
            "Group": "Equity",
            "Security Name": s.get("name") or f"{c['name']} {x.get('type') or 'equity'}",
            "Description": f"{x.get('type') or s.get('type') or 'Equity'} listed on {x.get('exchange') or 'n/a'}",
            "Security Type": x.get("type") or s.get("type") or "Equity",
            "Ticker": x.get("ticker", ""), "Exchange": x.get("exchange", ""), "Listing Country": country,
            "ISIN": x.get("isin", ""), "CUSIP": x.get("cusip", ""), "SEDOL": SEDOL_NOTE,
            "FIGI": x.get("figi", ""), "Composite FIGI": x.get("composite_figi", ""),
            "Share Class FIGI": x.get("share_class_figi", ""),
            "Source": "SEC / exchange listings; GLEIF; OpenFIGI",
        }))

    # Fixed income
    for b in debt.get("bonds", []):
        coupon = b.get("coupon", "")
        rows.append(dict(base, **{
            "Group": "Fixed Income",
            "Security Name": f"{c['name']} {b['description']}".strip(),
            "Description": b["description"],
            "Security Type": _bond_type(b["description"]),
            "Ticker": (b.get("listed") or "").split()[-1] if b.get("listed") else "",
            "Exchange": " ".join((b.get("listed") or "").split()[:-1]),
            "Listing Country": "US",
            "ISIN": b.get("isin", ""), "CUSIP": b.get("cusip", ""), "SEDOL": SEDOL_NOTE,
            "FIGI": b.get("figi", ""), "Composite FIGI": "", "Share Class FIGI": "",
            "Coupon (%)": coupon if coupon and coupon != "Floating" else ("Floating" if coupon else ""),
            "Maturity": b.get("maturity", ""),
            "Amount Issued (USD)": f"{b['principal']:.0f}" if b.get("principal") else "",
            "Exchange Listing (Debt)": b.get("listed", ""),
            "Source": ", ".join(b.get("sources", [])), "Source Document": b.get("link", ""),
        }))
    return rows


def securities_csv(p):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=HEADERS, extrasaction="ignore")
    w.writeheader()
    for r in securities_rows(p):
        w.writerow({h: r.get(h, "") for h in HEADERS})
    return buf.getvalue().encode("utf-8-sig")        # BOM so Excel opens accents and symbols correctly
