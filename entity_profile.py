"""
Builds one company's profile from public sources.

build_profile() returns a dict with these sections:
  company, market, description, securities, holders, events, news, regm, warnings, sources
"""
import html
import json
import re
import statistics
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta

import sources as src
from sectors import sector_for_sic, country_for_code
import regm

EVENT_DAYS = 180
HOLDER_YEARS = 3
PERIODIC = ("10-K", "10-Q", "20-F", "40-F")
ANNUAL = ("10-K", "20-F", "40-F")
FPI_FORMS = ("20-F", "40-F", "6-K")

# --------------------------------------------------------------------------
# Corporate events from SEC filing history
# --------------------------------------------------------------------------
WHY = {
    "M&A": "Possible merger or acquisition: advisers typically apply watch-list and information-barrier controls",
    "Capital markets": "Possible offering: Regulation M trading limits and research quiet periods may apply to underwriters",
    "Activism / ownership": "Change in a significant holding: may signal activism or a contest for control",
    "Management / governance": "Board, management or shareholder-rights change",
    "Earnings / reporting": "Reporting event: companies and brokers commonly restrict trading and research around results",
    "Press release": "Company announcement furnished or filed with the SEC",
    "Distress": "Credit or listing risk: possible restructuring, covenant or delisting issues",
}
FORM_EVENTS = {
    "425": ("M&A", "Merger communication (Rule 425)"),
    "S-4": ("M&A", "Merger/exchange offer registration (S-4)"),
    "F-4": ("M&A", "Merger/exchange offer registration (F-4)"),
    "PREM14A": ("M&A", "Preliminary merger proxy"),
    "DEFM14A": ("M&A", "Definitive merger proxy"),
    "SC TO-T": ("M&A", "Third-party tender offer"),
    "SC TO-I": ("M&A", "Issuer tender offer / buyback"),
    "SC 14D9": ("M&A", "Response to tender offer (14D-9)"),
    "SC 13E3": ("M&A", "Going-private transaction (13E-3)"),
    "S-1": ("Capital markets", "Registration statement (S-1)"),
    "F-1": ("Capital markets", "Registration statement (F-1)"),
    "S-3": ("Capital markets", "Shelf registration (S-3)"),
    "S-3ASR": ("Capital markets", "Automatic shelf registration (WKSI)"),
    "F-3": ("Capital markets", "Shelf registration (F-3)"),
    "F-3ASR": ("Capital markets", "Automatic shelf registration (WKSI)"),
    "F-10": ("Capital markets", "MJDS registration (Canadian issuer)"),
    "424B1": ("Capital markets", "Final prospectus"),
    "424B2": ("Capital markets", "Prospectus supplement (shelf takedown)"),
    "424B3": ("Capital markets", "Prospectus supplement"),
    "424B4": ("Capital markets", "Final prospectus (priced offering)"),
    "424B5": ("Capital markets", "Prospectus supplement (shelf takedown)"),
    "424B7": ("Capital markets", "Prospectus supplement (resale)"),
    "FWP": ("Capital markets", "Free writing prospectus (offering marketing)"),
    "S-8": ("Capital markets", "Employee share plan registration (S-8)"),
    "SCHEDULE 13D": ("Activism / ownership", "Schedule 13D: activist or control stake"),
    "SCHEDULE 13D/A": ("Activism / ownership", "Schedule 13D amendment"),
    "SC 13D": ("Activism / ownership", "Schedule 13D: activist or control stake"),
    "SC 13D/A": ("Activism / ownership", "Schedule 13D amendment"),
    "PREC14A": ("Activism / ownership", "Proxy contest: preliminary dissident proxy"),
    "DEFC14A": ("Activism / ownership", "Proxy contest: definitive proxy"),
    "NT 10-K": ("Distress", "Late annual report notice"),
    "NT 10-Q": ("Distress", "Late quarterly report notice"),
    "NT 20-F": ("Distress", "Late annual report notice"),
    "10-K": ("Earnings / reporting", "Annual report (10-K)"),
    "10-Q": ("Earnings / reporting", "Quarterly report (10-Q)"),
    "20-F": ("Earnings / reporting", "Annual report (20-F)"),
    "40-F": ("Earnings / reporting", "Annual report (40-F)"),
}
ITEM_EVENTS = {
    "1.01": ("M&A", "Material definitive agreement (8-K 1.01)"),
    "1.02": ("M&A", "Termination of material agreement (8-K 1.02)"),
    "1.03": ("Distress", "Bankruptcy or receivership (8-K 1.03)"),
    "2.01": ("M&A", "Completed acquisition or disposition (8-K 2.01)"),
    "2.02": ("Earnings / reporting", "Earnings release (8-K 2.02)"),
    "2.03": ("Capital markets", "New debt obligation (8-K 2.03)"),
    "2.04": ("Distress", "Debt acceleration trigger (8-K 2.04)"),
    "2.05": ("Management / governance", "Restructuring / exit costs (8-K 2.05)"),
    "3.01": ("Distress", "Delisting or listing-standard notice (8-K 3.01)"),
    "3.02": ("Capital markets", "Unregistered equity sale (8-K 3.02)"),
    "3.03": ("Capital markets", "Change to security holder rights (8-K 3.03)"),
    "4.01": ("Earnings / reporting", "Auditor change (8-K 4.01)"),
    "4.02": ("Distress", "Non-reliance on financials / restatement (8-K 4.02)"),
    "5.01": ("M&A", "Change in control (8-K 5.01)"),
    "5.02": ("Management / governance", "Director or officer change (8-K 5.02)"),
    "5.03": ("Management / governance", "Charter or bylaw amendment (8-K 5.03)"),
    "5.07": ("Management / governance", "Shareholder vote results (8-K 5.07)"),
    "7.01": ("Press release", "Regulation FD disclosure (8-K 7.01)"),
    "8.01": ("Press release", "Other material event (8-K 8.01)"),
}


def _recent(sub):
    rec = sub.get("filings", {}).get("recent", {})
    n = len(rec.get("form", []))
    keys = ["form", "filingDate", "accessionNumber", "primaryDocument", "items", "reportDate"]
    return [{k: (rec.get(k) or [""] * n)[i] for k in keys} for i in range(n)]   # newest first


def corporate_events(filings, cik, days=EVENT_DAYS, today=None):
    today = today or date.today()
    cutoff = (today - timedelta(days=days)).isoformat()
    out, seen = [], set()

    def add(dt, status, cat, ftype, title, url=""):
        k = (dt, ftype, title)
        if k not in seen:
            seen.add(k)
            out.append({"date": dt, "status": status, "category": cat, "form": ftype,
                        "title": title, "why": WHY[cat], "url": url})

    for f in filings:
        if f["filingDate"] < cutoff:
            continue
        url = src.filing_url(cik, f["accessionNumber"], f["primaryDocument"])
        form = f["form"]
        if form in ("8-K", "8-K/A", "6-K"):
            items = [i.strip() for i in (f["items"] or "").split(",") if i.strip()]
            hits = [ITEM_EVENTS[i] for i in items if i in ITEM_EVENTS]
            if form == "6-K" and not hits:
                hits = [("Press release", "Report of foreign private issuer (6-K)")]
            for cat, title in hits:
                add(f["filingDate"], "Filed", cat, form, title, url)
        else:
            key = form if form in FORM_EVENTS else form.replace("/A", "")
            if key in FORM_EVENTS:
                cat, title = FORM_EVENTS[key]
                add(f["filingDate"], "Filed", cat, form,
                    title + (" (amendment)" if form.endswith("/A") and form not in FORM_EVENTS else ""), url)

    # Estimated milestones
    def first(forms):
        return next((f for f in filings if f["form"] in forms), None)

    t = today.isoformat()
    f = first(("S-3", "S-3ASR", "F-3", "F-3ASR", "F-10"))
    if f:
        exp = (date.fromisoformat(f["filingDate"]) + timedelta(days=3 * 365)).isoformat()
        if exp >= t:
            add(exp, "Estimated", "Capital markets", f["form"] + " expiry",
                f"Shelf window open until about {exp} (filed {f['filingDate']}); offerings possible on short notice")
    ipo = None
    for i in range(len(filings) - 1, -1, -1):                    # oldest first
        if filings[i]["form"] == "424B4" and any(x["form"] in ("S-1", "F-1") for x in filings[i:]):
            ipo = filings[i]
            break
    if ipo:
        lock = (date.fromisoformat(ipo["filingDate"]) + timedelta(days=180)).isoformat()
        if lock >= (today - timedelta(days=30)).isoformat():
            add(lock, "Estimated", "Capital markets", "Lock-up expiry",
                f"Estimated IPO lock-up expiry (180 days after pricing on {ipo['filingDate']})")
    f = first(PERIODIC)
    if f and f["form"] in ("10-Q", "10-K"):
        nxt = date.fromisoformat(f["filingDate"]) + timedelta(days=91)
        while nxt < today:
            nxt += timedelta(days=91)
        add(nxt.isoformat(), "Estimated", "Earnings / reporting", "Next report",
            "Estimated next earnings / periodic report (about 91 days after the last one)")
    f = first(("DEFM14A",))
    if f and f["filingDate"] >= cutoff:
        add((date.fromisoformat(f["filingDate"]) + timedelta(days=35)).isoformat(), "Estimated", "M&A",
            "Shareholder vote", "Expected merger shareholder meeting (about 5 weeks after definitive proxy)")
    return sorted(out, key=lambda e: e["date"], reverse=True)


# --------------------------------------------------------------------------
# Annual report text: business description and cover-page flags
# --------------------------------------------------------------------------
def html_to_text(raw):
    txt = re.sub(r"(?is)<(script|style).*?</\1>", " ", raw or "")
    txt = html.unescape(re.sub(r"<[^>]+>", " ", txt))
    return re.sub(r"\s+", " ", txt)


def extract_description(raw, form, max_chars=900):
    txt = html_to_text(raw)
    pats = {"10-K": r"item\s*1\.?\s*business",
            "20-F": r"(business overview|item\s*4\.?\s*information on the company)",
            "40-F": r"(description of the business|general development of the business|our business)"}
    hits = [m.end() for m in re.finditer(pats.get(form, pats["10-K"]), txt, re.I)]
    for start in reversed(hits):                 # skip table-of-contents hits
        chunk = txt[start:start + 4000].strip(" .:-—")
        chunk = re.sub(r"^(overview|general|our company|introduction)\s*", "", chunk, flags=re.I)
        if len(re.findall(r"\b(we|our|the company|is a|are a|corporation)\b", chunk[:900], re.I)) >= 2:
            chunk = chunk[:max_chars]
            return chunk.rsplit(". ", 1)[0] + "." if ". " in chunk else chunk
    return ""


TRUE_MARKS = {"true", "yes", "☒", "x", "☒"}
FALSE_MARKS = {"false", "no", "☐", "☐"}


def cover_flags(raw):
    """Read Inline XBRL cover-page (dei) tags: EGC, shell, WKSI, filer category, float."""
    flags = {}
    for m in re.finditer(r'<ix:nonNumeric\b([^>]*)>(.*?)</ix:nonNumeric>', raw or "", re.S | re.I):
        nm = re.search(r'name="dei:(\w+)"', m.group(1))
        if not nm:
            continue
        val = html.unescape(re.sub(r"<[^>]+>", "", m.group(2))).strip()
        key = nm.group(1)
        if key in ("EntityEmergingGrowthCompany", "EntityShellCompany", "EntityExTransitionPeriod",
                   "EntityWellKnownSeasonedIssuer", "EntityVoluntaryFilers", "EntitySmallBusiness"):
            v = val.lower()
            flags[key] = True if v in TRUE_MARKS else False if v in FALSE_MARKS else None
        elif key in ("EntityFilerCategory", "EntityIncorporationStateCountryCode", "SecurityExchangeName"):
            flags.setdefault(key, val)
    return flags


def _pick_aif_exhibit(cik, f, email):
    """40-F business text lives in the Annual Information Form exhibit; find it."""
    idx = src.http_get(f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{f['accessionNumber'].replace('-', '')}/index.json",
                       user_agent=src.sec_ua(email), sec=True)
    try:
        items = json.loads(idx or "{}").get("directory", {}).get("item", [])
    except json.JSONDecodeError:
        return None
    names = [i["name"] for i in items if i["name"].lower().endswith((".htm", ".html"))]
    for pat in (r"aif", r"ex(hibit)?[-_]?99[-_.]?1\b", r"99[-_.]?1"):
        for n in names:
            if re.search(pat, n, re.I):
                return n
    return None


# --------------------------------------------------------------------------
# XBRL company facts: shares, float, cash, debt, revenue
# --------------------------------------------------------------------------
def _latest(facts, taxonomy, concepts, unit_pref=("USD", "CAD", "shares")):
    """Latest value across concept names; returns (value, unit, end_date, form) or None."""
    best = None
    tx = (facts.get("facts") or {}).get(taxonomy) or {}
    for c in concepts:
        units = (tx.get(c) or {}).get("units") or {}
        for u, rows in units.items():
            if unit_pref and u not in unit_pref:
                continue
            for r in rows:
                cand = (r.get("end", ""), r.get("filed", ""), r["val"], u, r.get("form", ""))
                if best is None or cand[:2] > best[:2]:
                    best = cand
        if best:
            break
    return None if best is None else {"value": best[2], "unit": best[3], "date": best[0], "form": best[4]}


def _annual_revenue(facts):
    best = None
    for tax, concepts in (("us-gaap", ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
                                       "SalesRevenueNet"]), ("ifrs-full", ["Revenue"])):
        for c in concepts:
            for u, rows in ((facts.get("facts") or {}).get(tax, {}).get(c, {}).get("units") or {}).items():
                for r in rows:
                    if r.get("fp") == "FY" and r.get("form") in ANNUAL and r.get("start"):
                        days = (date.fromisoformat(r["end"]) - date.fromisoformat(r["start"])).days
                        if 330 <= days <= 400 and (best is None or r["end"] > best["date"]):
                            best = {"value": r["val"], "unit": u, "date": r["end"]}
    return best


def balance_sheet(facts):
    shares = _latest(facts, "dei", ["EntityCommonStockSharesOutstanding"], ("shares",))
    pf = _latest(facts, "dei", ["EntityPublicFloat"], ("USD",))
    cash = (_latest(facts, "us-gaap", ["CashAndCashEquivalentsAtCarryingValue",
                                       "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents", "Cash"])
            or _latest(facts, "ifrs-full", ["CashAndCashEquivalents"]))
    debt = _latest(facts, "us-gaap", ["LongTermDebt", "DebtInstrumentCarryingAmount"])
    if not debt:
        nc = _latest(facts, "us-gaap", ["LongTermDebtNoncurrent"])
        cur = _latest(facts, "us-gaap", ["LongTermDebtCurrent", "DebtCurrent"])
        if nc:
            debt = dict(nc, value=nc["value"] + (cur["value"] if cur and cur["unit"] == nc["unit"] and cur["date"] == nc["date"] else 0))
    if not debt:
        debt = _latest(facts, "ifrs-full", ["Borrowings"])
    if not debt:
        nc = _latest(facts, "ifrs-full", ["NoncurrentPortionOfNoncurrentBorrowings", "NoncurrentBorrowings"])
        cur = _latest(facts, "ifrs-full", ["CurrentBorrowings", "CurrentPortionOfNoncurrentBorrowings"])
        if nc:
            debt = dict(nc, value=nc["value"] + (cur["value"] if cur and cur["unit"] == nc["unit"] else 0))
    return {"shares_out": shares, "public_float": pf, "cash": cash, "debt": debt,
            "revenue": _annual_revenue(facts)}


# --------------------------------------------------------------------------
# Schedule 13D / 13G holders
# --------------------------------------------------------------------------
def parse_13dg_xml(text):
    try:
        root = ET.fromstring((text or "").encode("utf-8"))
    except ET.ParseError:
        return []
    loc = lambda t: t.rsplit("}", 1)[-1].lower()
    out, seen = [], set()
    for block in root.iter():
        name = pct = None
        for ch in block:
            t, v = loc(ch.tag), (ch.text or "").strip()
            if not v:
                continue
            if name is None and ("reportingpersonname" in t or t in ("nameofreportingperson", "personname")):
                name = v
            elif pct is None and "percent" in t:
                m = re.search(r"[\d.]+", v)
                pct = float(m.group()) if m else None
        if name and name.lower() not in seen:
            seen.add(name.lower())
            out.append((name, pct))
    return out


def significant_holders(filings, cik, email, years=HOLDER_YEARS, max_filings=25):
    cutoff = (date.today() - timedelta(days=365 * years)).isoformat()
    holders, n = {}, 0
    for f in filings:
        if not f["form"].startswith(("SCHEDULE 13D", "SCHEDULE 13G")) or f["filingDate"] < cutoff:
            continue
        if n >= max_filings:
            break
        n += 1
        doc = f["primaryDocument"].split("/")[-1]
        if not doc.lower().endswith(".xml"):
            continue
        raw, url = src.sec_doc(cik, f["accessionNumber"], doc, email)
        for name, pct in parse_13dg_xml(raw):
            holders.setdefault(name.lower(), {"name": name, "pct": pct, "date": f["filingDate"],
                                              "form": f["form"].replace("SCHEDULE ", "Sch. "), "url": url})
    return sorted(holders.values(), key=lambda h: -(h["pct"] or 0))


# --------------------------------------------------------------------------
# Market data
# --------------------------------------------------------------------------
def venue_stats(symbol, exchange, currency, key):
    daily = src.av_daily(symbol, key)
    if not daily:
        raise src.DataError(f"No price history for {symbol}.")
    weekly = src.av_weekly(symbol, key)
    last_d, last_px, _ = daily[-1]
    cut60 = (date.fromisoformat(last_d) - timedelta(days=60)).isoformat()
    win = [(c, v) for d, c, v in daily if d > cut60]
    m1 = daily[-22][1] if len(daily) >= 22 else None
    cut52 = (date.fromisoformat(last_d) - timedelta(days=364)).isoformat()
    wk = [w for w in weekly if w[0] > cut52] or weekly[-52:]
    hi = max(wk, key=lambda w: w[1]) if wk else None
    lo = min(wk, key=lambda w: w[2]) if wk else None
    return {
        "symbol": symbol, "exchange": exchange, "currency": currency,
        "price": last_px, "price_date": last_d,
        "change_1m_pct": (last_px / m1 - 1) * 100 if m1 else None,
        "high_52w": hi[1] if hi else None, "high_52w_week": hi[0] if hi else None,
        "low_52w": lo[2] if lo else None, "low_52w_week": lo[0] if lo else None,
        "adv_shares": statistics.mean(v for _, v in win) if win else None,
        "adtv_value": statistics.mean(c * v for c, v in win) if win else None,
        "adtv_days": len(win),
        "adtv_window": f"{cut60} to {last_d}",
    }


def market_data(company, securities, facts_bs, key, warnings):
    out = {"venues": [], "fx": {"USD": 1.0}, "notes": []}
    common = [s for s in securities if s["type"] == "Common Stock" or s["type"] == "ADR/ADS"]
    us = next((s for s in common if s["country"] == "US" and s["exchange"] != "OTC"), None) or \
        next((s for s in common if s["country"] == "US"), None)
    ca = next((s for s in securities if s["country"] == "CA"), None)
    for s, ccy in ((us, "USD"), (ca, "CAD")):
        if not s:
            continue
        try:
            sym = s.get("av_symbol") or s["ticker"].replace(".", "-")
            out["venues"].append(venue_stats(sym, s["exchange"], ccy, key))
        except src.QuotaError as e:
            warnings.append(str(e))
            break
        except src.DataError as e:
            warnings.append(f"Market data for {s['ticker']}: {e}")
    if any(v["currency"] == "CAD" for v in out["venues"]):
        try:
            out["fx"]["CAD"] = src.av_fx("CAD", "USD", key)
        except src.DataError as e:
            out["fx"]["CAD"] = None
            warnings.append(f"CAD/USD rate unavailable ({e}); worldwide ADTV shows U.S. trading only.")
    if not out["venues"]:
        return out
    p = out["venues"][0]
    out["primary"] = p
    to_usd = lambda v, c: None if v is None or out["fx"].get(c) is None else v * out["fx"][c]
    # Worldwide ADTV in USD (Reg M uses worldwide trading)
    parts = [to_usd(v["adtv_value"], v["currency"]) for v in out["venues"]]
    out["adtv_usd"] = sum(x for x in parts if x is not None) if any(x is not None for x in parts) else None
    out["adv_shares_total"] = sum(v["adv_shares"] or 0 for v in out["venues"]) or None
    sh = facts_bs.get("shares_out")
    if sh:
        out["shares_out"], out["shares_out_date"] = sh["value"], sh["date"]
        out["market_cap"] = sh["value"] * p["price"]
        out["market_cap_ccy"] = p["currency"]
        out["market_cap_usd"] = to_usd(out["market_cap"], p["currency"])

        def conv(item):          # bring balance-sheet amounts into the price currency
            if not item:
                return None
            if item["unit"] == p["currency"]:
                return item["value"]
            usd = to_usd(item["value"], item["unit"]) if item["unit"] in out["fx"] else None
            if usd is None:
                return None
            return usd if p["currency"] == "USD" else (usd / out["fx"][p["currency"]] if out["fx"].get(p["currency"]) else None)
        cash, debt = conv(facts_bs.get("cash")), conv(facts_bs.get("debt"))
        if cash is not None:
            out["cash"], out["debt"] = cash, debt or 0.0
            out["enterprise_value"] = out["market_cap"] + (debt or 0.0) - cash
            out["bs_date"] = (facts_bs.get("cash") or {}).get("date")
    pf = facts_bs.get("public_float")
    if pf:
        out["public_float_usd"], out["public_float_date"] = pf["value"], pf["date"]
    return out


# --------------------------------------------------------------------------
# Main entry point
# --------------------------------------------------------------------------
def build_profile(cik, settings, sec_tickers, symdir, progress=lambda msg: None):
    cik = str(cik).zfill(10)
    email = settings.get("SEC_CONTACT_EMAIL", "")
    av_key = settings.get("ALPHAVANTAGE_KEY", "")
    fh_key = settings.get("FINNHUB_KEY", "")
    warnings, used = [], ["SEC EDGAR"]

    progress("Company record (SEC)")
    sub = src.sec_submissions(cik, email)
    filings = _recent(sub)
    biz = (sub.get("addresses") or {}).get("business") or {}
    forms = {f["form"] for f in filings}
    nice = next((t["name"] for t in sec_tickers if t["cik"] == cik and t["name"]), "")
    company = {
        "name": nice if nice and not nice.isupper() else (sub.get("name") or nice), "cik": cik, "sic": sub.get("sic", ""),
        "industry": sub.get("sicDescription", ""), "sector": sector_for_sic(sub.get("sic")),
        "incorporation": sub.get("stateOfIncorporationDescription") or sub.get("stateOfIncorporation", ""),
        "incorporation_country": country_for_code(sub.get("stateOfIncorporation"), sub.get("stateOfIncorporationDescription")),
        "hq_city": (biz.get("city") or "").title(),
        "hq_region": biz.get("stateOrCountryDescription") or biz.get("stateOrCountry", ""),
        "hq_country": country_for_code(biz.get("stateOrCountry"), biz.get("stateOrCountryDescription")),
        "website": sub.get("website") or "", "fiscal_year_end": sub.get("fiscalYearEnd") or "",
        "filer_category": sub.get("category") or "", "entity_type": sub.get("entityType") or "",
        "ein": sub.get("ein") or "", "lei": sub.get("lei") or "",
        "foreign_private_issuer": bool(forms & set(FPI_FORMS)) and not (forms & {"10-K", "10-Q"}),
        "former_names": [n.get("name") for n in (sub.get("formerNames") or [])][:3],
    }

    # Equity securities: every ticker the SEC links to this CIK
    progress("Equity securities")
    securities = []
    for t in [x for x in sec_tickers if x["cik"] == cik]:
        dot = t["ticker"].replace("-", ".")
        d = symdir.get(dot) or symdir.get(t["ticker"]) or {}
        name = d.get("name") or company["name"]
        securities.append({"ticker": dot, "exchange": d.get("exchange") or t["exchange"] or "OTC",
                           "country": "US", "name": name,
                           "type": classify(name, d.get("is_etf"), t["exchange"])})
    if company["hq_country"] == "Canada" or company["incorporation_country"] == "Canada":
        try:
            tsx = src.av_search_tsx(company["name"], av_key)
            if tsx:
                securities.append({"ticker": tsx["symbol"].rsplit(".", 1)[0], "av_symbol": tsx["symbol"],
                                   "exchange": tsx["exchange"], "country": "CA",
                                   "name": tsx["name"] or company["name"], "type": "Common Stock"})
        except src.DataError as e:
            warnings.append(f"TSX listing lookup: {e}")
    securities.sort(key=lambda s: (s["type"] != "Common Stock", s["country"] != "US", s["ticker"]))

    # Balance sheet and cover-page facts
    progress("Financial facts (SEC XBRL)")
    try:
        facts = src.sec_facts(cik, email)
    except src.DataError as e:
        facts = {}
        warnings.append(f"XBRL facts: {e}")
    bs = balance_sheet(facts)

    # Annual report: business description and cover flags
    progress("Business description (latest annual report)")
    description, desc_src, flags = "", "", {}
    annual = next((f for f in filings if f["form"] in ANNUAL), None)
    latest_periodic = next((f for f in filings if f["form"] in PERIODIC), None)
    if annual:
        raw, url = src.sec_doc(cik, annual["accessionNumber"], annual["primaryDocument"], email)
        flags = cover_flags(raw)
        description = extract_description(raw, annual["form"])
        if not description and annual["form"] == "40-F":
            ex = _pick_aif_exhibit(cik, annual, email)
            if ex:
                raw2, url = src.sec_doc(cik, annual["accessionNumber"], ex, email)
                description = extract_description(raw2, "40-F")
        desc_src = f"{annual['form']} filed {annual['filingDate']}"
        # EGC status only changes at fiscal year end, so the annual report cover is enough.
    elif latest_periodic:
        raw, _ = src.sec_doc(cik, latest_periodic["accessionNumber"], latest_periodic["primaryDocument"], email)
        flags = cover_flags(raw)
    if not description:
        warnings.append("Business description could not be extracted automatically; see the latest annual report.")

    progress("Significant holders (Schedule 13D/13G)")
    holders = significant_holders(filings, cik, email)

    progress("Corporate events (last 180 days)")
    events = corporate_events(filings, cik)

    progress("Market data")
    if av_key:
        used.append("Alpha Vantage")
    market = market_data(company, securities, bs, av_key, warnings) if av_key else {"venues": [], "fx": {"USD": 1.0}}
    if not av_key:
        warnings.append("Market data is off: add a free Alpha Vantage key (ALPHAVANTAGE_KEY) in the app settings.")
        if bs.get("public_float"):
            market["public_float_usd"], market["public_float_date"] = bs["public_float"]["value"], bs["public_float"]["date"]
        if bs.get("shares_out"):
            market["shares_out"], market["shares_out_date"] = bs["shares_out"]["value"], bs["shares_out"]["date"]

    progress("News")
    news = []
    us_common = next((s for s in securities if s["country"] == "US" and s["type"] == "Common Stock"), None)
    if fh_key and us_common:
        try:
            news = src.finnhub_news(us_common["ticker"], fh_key)[:25]
            used.append("Finnhub")
        except src.DataError as e:
            warnings.append(f"News: {e}")
    elif not fh_key:
        warnings.append("News headlines are off: add a free Finnhub key (FINNHUB_KEY). Filed press releases still appear under events.")

    profile = {
        "as_of": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "company": company, "cover": flags, "financials": bs, "market": market,
        "description": description, "description_source": desc_src,
        "securities": securities, "holders": holders, "events": events, "news": news,
        "filings": filings, "warnings": warnings, "sources": used,
    }
    profile["regm"] = regm.analyse(profile)
    return profile


def classify(name, is_etf, sec_exchange):
    t = src.classify_security(name, is_etf)
    return t if t != "Other" else "Common Stock"
