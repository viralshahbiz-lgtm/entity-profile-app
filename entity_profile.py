"""
Builds one company's profile from public sources.

build_profile() returns a dict with these sections:
  company, market, description, listing (how and when it went public), identifiers,
  securities, holders, events (90 days), news (90 days), regm (safe harbor summary),
  warnings, sources
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

EVENT_DAYS = 90
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
    "Regulatory / clinical": "Regulatory or clinical milestone: can move the stock and trigger research and trading restrictions",
    "Legal / regulatory action": "Litigation or regulatory action: reputational and conflicts review",
    "Business update": "Partnership, product or contract news",
}

# Keyword rules for classifying web news into event categories (first match wins)
NEWS_RULES = [
    ("M&A", r"\b(acquir\w*|acquisition|merg\w*|takeover|buyout|tender offer|to buy|bid for|bidder|divest\w*|spin-?off|"
            r"go(ing)?[- ]private|take[- ]private|strategic (alternatives|review|options|investment|transaction)|"
            r"explor\w* (a |the )?sale|weigh\w* (a |the )?sale|consider\w* (a |the )?sale|sale process|for sale|"
            r"takeover (interest|approach|bid)|approach(ed)? by|unsolicited|hostile|joint venture|carve-?out|"
            r"asset sale|sells? (its )?\w+ (unit|business|division)|deal talks|in talks to (buy|sell|merge|combine))\b"),
    ("Capital markets", r"\b(ipo|initial public offering|public offering|priced|prices \$|raises? \$|private placement|"
                        r"convertible|senior notes|notes due|share sale|secondary offering|at-the-market|financing round|shelf)\b"),
    ("Activism / ownership", r"\b(activist|stake in|proxy fight|board seats?|13d)\b"),
    ("Regulatory / clinical", r"\b(fda|ema|health canada|approv\w*|clearance|phase [123i]+|clinical trial|topline|data readout|pdufa|breakthrough designation)\b"),
    ("Legal / regulatory action", r"\b(lawsuit|sues|sued|class action|investigation|probe|subpoena|settle\w*|charged|antitrust|doj|sec charges)\b"),
    ("Distress", r"\b(bankruptcy|chapter 11|default|delist\w*|going concern|restructur\w*|layoffs?|job cuts)\b"),
    ("Management / governance", r"\b(ceo|cfo|chief executive|chief financial|appoint\w*|steps? down|resign\w*|names .* (chief|president)|board of directors)\b"),
    ("Earnings / reporting", r"\b(earnings|quarterly results|q[1-4] results|(first|second|third|fourth)[- ]quarter|revenue|guidance|outlook|fiscal (year|quarter))\b"),
    ("Business update", r"\b(partnership|collaborat\w*|launch\w*|contract|agreement with|deal with|unveil\w*)\b"),
]


RUMOR_RE = re.compile(r"\b(rumou?r\w*|reportedly|people familiar|sources? (said|say|familiar)|said to be|is said to|"
                      r"in talks|talks to|weighs?|weighing|explor\w*|considering|could|may (sell|buy|merge)|"
                      r"takeover interest|approached|unsolicited|speculat\w*|according to (a )?report)\b", re.I)


def classify_news(title, content=""):
    text = f"{title} {content}".lower()
    for cat, pat in NEWS_RULES:
        if re.search(pat, text):
            return cat
    return None
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
def _to_pct(v):
    """'5.2', '5.2%', '  7 ' -> float; '.', 'N/A', 'Less than 5' -> None."""
    m = re.search(r"\d+(?:\.\d+)?", v or "")
    try:
        val = float(m.group()) if m else None
    except ValueError:
        return None
    return val if val is not None and 0 <= val <= 100 else None


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
                pct = _to_pct(v)
        if name and name.lower() not in seen:
            seen.add(name.lower())
            out.append((name, pct))
    return out


def significant_holders(filings, cik, email, years=HOLDER_YEARS, max_filings=25):
    cutoff = (date.today() - timedelta(days=365 * years)).isoformat()
    holders, n, cusips = {}, 0, set()
    for f in filings:
        if not f["form"].startswith(("SCHEDULE 13D", "SCHEDULE 13G")) or f["filingDate"] < cutoff:
            continue
        if n >= max_filings:
            break
        n += 1
        doc = f["primaryDocument"].split("/")[-1]
        if not doc.lower().endswith(".xml"):
            continue
        try:
            raw, url = src.sec_doc(cik, f["accessionNumber"], doc, email)
        except src.DataError:
            continue
        cusips.update(re.findall(r"<(?:\w+:)?\w*[Cc][Uu][Ss][Ii][Pp]\w*>\s*([0-9A-Z]{9})\s*<", raw or ""))
        for name, pct in parse_13dg_xml(raw):
            holders.setdefault(name.lower(), {"name": name, "pct": pct, "date": f["filingDate"],
                                              "form": f["form"].replace("SCHEDULE ", "Sch. "), "url": url})
    return sorted(holders.values(), key=lambda h: -(h["pct"] or 0)), cusips


# --------------------------------------------------------------------------
# Market data
# --------------------------------------------------------------------------
def _drop_live_bar(bars):
    """Keep only completed sessions so the price is the prior close, not an intraday print."""
    try:
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("America/New_York"))
    except Exception:                      # tzdata missing: assume UTC-5
        now = datetime.utcnow() - timedelta(hours=5)
    today = now.date().isoformat()
    if bars and bars[-1][0] == today and (now.hour, now.minute) < (16, 30):
        return bars[:-1]
    return bars


def _stats_from_daily(bars, symbol, exchange, currency, provider):
    """bars: (date, high, low, close, volume), oldest first, completed sessions only."""
    if not bars:
        raise src.DataError(f"No price history for {symbol}.")
    last_d, _, _, last_px, _ = bars[-1]
    cut60 = (date.fromisoformat(last_d) - timedelta(days=60)).isoformat()
    win = [(c, v) for d, h, l, c, v in bars if d > cut60]
    m1 = bars[-22][3] if len(bars) >= 22 else None
    cut52 = (date.fromisoformat(last_d) - timedelta(days=364)).isoformat()
    yr = [b for b in bars if b[0] > cut52]
    hi = max(yr, key=lambda b: b[1]) if yr else None
    lo = min(yr, key=lambda b: b[2]) if yr else None
    prev = bars[-2][3] if len(bars) >= 2 else None
    return {
        "symbol": symbol, "exchange": exchange, "currency": currency, "provider": provider,
        "price": last_px, "price_date": last_d,
        "change_1d_pct": (last_px / prev - 1) * 100 if prev else None,
        "change_1m_pct": (last_px / m1 - 1) * 100 if m1 else None,
        "high_52w": hi[1] if hi else None, "high_52w_week": hi[0] if hi else None,
        "low_52w": lo[2] if lo else None, "low_52w_week": lo[0] if lo else None,
        "adv_shares": statistics.mean(v for _, v in win) if win else None,
        "adtv_value": statistics.mean(c * v for c, v in win) if win else None,
        "adtv_days": len(win),
        "adtv_window": f"{cut60} to {last_d}",
        "full_year": bool(yr) and yr[0][0] <= (date.fromisoformat(last_d) - timedelta(days=350)).isoformat(),
    }


def venue_stats(sec, currency, keys, warnings):
    """Prior-close statistics for one listing. U.S.: Twelve Data first, Alpha Vantage as backup. TSX: Alpha Vantage."""
    td_key, av_key = keys.get("TWELVEDATA_KEY", ""), keys.get("ALPHAVANTAGE_KEY", "")
    if currency == "USD" and td_key:
        try:
            bars = _drop_live_bar(src.td_daily(sec["ticker"], td_key))
            return _stats_from_daily(bars, sec["ticker"], sec["exchange"], currency, "Twelve Data")
        except src.DataError as e:
            if not av_key:
                raise
            warnings.append(f"Twelve Data for {sec['ticker']}: {e} Trying Alpha Vantage.")
    if not av_key:
        raise src.DataError("needs an Alpha Vantage key" if currency == "CAD" else "no price provider key set")
    sym = sec.get("av_symbol") or sec["ticker"].replace(".", "-")
    daily = _drop_live_bar([(d, c, c, c, v) for d, c, v in src.av_daily(sym, av_key)])
    weekly = src.av_weekly(sym, av_key)
    st = _stats_from_daily(daily, sym, sec["exchange"], currency, "Alpha Vantage")
    last_d = st["price_date"]
    cut52 = (date.fromisoformat(last_d) - timedelta(days=364)).isoformat()
    wk = [w for w in weekly if w[0] > cut52] or weekly[-52:]
    if wk:                                        # compact daily has ~100 bars; use weekly for the 52-week range
        hi, lo = max(wk, key=lambda w: w[1]), min(wk, key=lambda w: w[2])
        st.update(high_52w=hi[1], high_52w_week=hi[0], low_52w=lo[2], low_52w_week=lo[0], full_year=True)
    return st


def market_data(company, securities, facts_bs, keys, warnings):
    out = {"venues": [], "fx": {"USD": 1.0}, "notes": []}
    common = [s for s in securities if s["type"] == "Common Stock" or s["type"] == "ADR/ADS"]
    us = next((s for s in common if s["country"] == "US" and s["exchange"] != "OTC"), None) or \
        next((s for s in common if s["country"] == "US"), None)
    ca = next((s for s in securities if s["country"] == "CA"), None)
    for s, ccy in ((us, "USD"), (ca, "CAD")):
        if not s:
            continue
        try:
            out["venues"].append(venue_stats(s, ccy, keys, warnings))
        except src.QuotaError as e:
            warnings.append(str(e))
        except src.DataError as e:
            warnings.append(f"Market data for {s['ticker']}: {e}")
    if any(v["currency"] == "CAD" for v in out["venues"]):
        out["fx"]["CAD"] = None
        for fn, k in ((src.td_fx, keys.get("TWELVEDATA_KEY")), (src.av_fx, keys.get("ALPHAVANTAGE_KEY"))):
            if k and out["fx"]["CAD"] is None:
                try:
                    out["fx"]["CAD"] = fn("CAD", "USD", k)
                except src.DataError:
                    pass
        if out["fx"]["CAD"] is None:
            warnings.append("CAD/USD rate unavailable; worldwide ADTV shows U.S. trading only.")
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
# Fixed income: publicly issued debt securities
# --------------------------------------------------------------------------
DEBT_DESC = re.compile(r"(\d{1,2}(?:\.\d{1,4})?)\s?%\s+((?:(?:Senior|Subordinated|Junior|Secured|Unsecured|Convertible|"
                       r"Exchangeable|Fixed[- ]Rate|Floating[- ]Rate|Green|Sustainability(?:-Linked)?)\s+)*)"
                       r"(Notes|Debentures|Bonds)\s+due\s+((?:[A-Z][a-z]+\s+\d{1,2},\s+)?(?:19|20)\d{2})", re.I)
FLOAT_DESC = re.compile(r"(Floating[- ]Rate\s+(?:Senior\s+)?Notes)\s+due\s+((?:[A-Z][a-z]+\s+\d{1,2},\s+)?(?:19|20)\d{2})", re.I)
CUSIP_RE = re.compile(r"CUSIP(?:\s*(?:No\.?|Number|Numbers))?\s*(?:/\s*ISIN)?\s*[:#]?\s*([0-9]{3}[0-9A-Z]{5}[0-9])\b", re.I)
ISIN_RE = re.compile(r"\b((?:US|CA)[0-9A-Z]{9}[0-9])\b")
PRINC_RE = re.compile(r"(?:U\.?S\.?)?\$\s?([\d,]+(?:\.\d+)?)\s*(million|billion)?\s+(?:in\s+)?aggregate\s+principal\s+amount", re.I)
MAT_RE = re.compile(r"Maturity(?:\s+Date)?\s*[:\-]?\s*([A-Z][a-z]+\s+\d{1,2},\s+\d{4})")
OFFER_FORMS = ("424B2", "424B5", "424B3", "FWP", "424B4", "424B7")


def cover_12b(raw):
    """Classes registered on an exchange, from the Inline XBRL cover of the annual report."""
    rows = {}
    for m in re.finditer(r'<ix:nonNumeric\b([^>]*)>(.*?)</ix:nonNumeric>', raw or "", re.S | re.I):
        nm = re.search(r'name="dei:(Security12bTitle|TradingSymbol|SecurityExchangeName|NoTradingSymbolFlag)"', m.group(1))
        ctx = re.search(r'contextRef="([^"]+)"', m.group(1))
        if nm and ctx:
            val = html.unescape(re.sub(r"<[^>]+>", "", m.group(2))).strip()
            rows.setdefault(ctx.group(1), {})[nm.group(1)] = val
    out = []
    for r in rows.values():
        if r.get("Security12bTitle"):
            out.append({"title": r["Security12bTitle"], "symbol": r.get("TradingSymbol", ""),
                        "exchange": r.get("SecurityExchangeName", "")})
    return out


def _amount(num, unit):
    try:
        v = float(num.replace(",", ""))
    except ValueError:
        return None
    return v * (1e9 if (unit or "").lower() == "billion" else 1e6 if (unit or "").lower() == "million" else 1)


def _maturity_year(text):
    m = re.search(r"(19|20)\d{2}", text or "")
    return m.group(0) if m else ""


def parse_debt_terms(text):
    """Split an offering document into tranches and pull coupon, maturity, CUSIP/ISIN and size for each."""
    hits = [(m.start(), m) for m in DEBT_DESC.finditer(text)] + [(m.start(), m) for m in FLOAT_DESC.finditer(text)]
    hits.sort(key=lambda h: h[0])
    out, seen = [], set()
    for k, (pos, m) in enumerate(hits):
        window = text[pos: hits[k + 1][0] if k + 1 < len(hits) else pos + 2500][:2500]
        if m.re is DEBT_DESC:
            coupon, kind, due = m.group(1), " ".join((m.group(2) + m.group(3)).split()), m.group(4)
            desc = f"{coupon}% {kind} due {due}"
        else:
            coupon, due = "Floating", m.group(2)
            desc = f"{' '.join(m.group(1).split())} due {due}"
        c = CUSIP_RE.search(window)
        i = ISIN_RE.search(window)
        prev_end = hits[k - 1][0] + 80 if k else max(0, pos - 400)
        p = PRINC_RE.search(window) or PRINC_RE.search(text[max(prev_end, pos - 400): pos])
        mat = MAT_RE.search(window)
        cusip = c.group(1) if c else (src.cusip_from_isin(i.group(1)) if i else "")
        key = cusip or desc.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append({"description": desc, "coupon": coupon, "maturity": mat.group(1) if mat else due,
                    "cusip": cusip, "isin": i.group(1) if i else (src.isin_from_cusip(cusip, "US") if cusip else ""),
                    "principal": _amount(*p.groups()) if p else None})
    return out


def _parse_figi_bond(row):
    """OpenFIGI bond tickers look like 'AAPL 4.65 02/23/46' or 'XYZ F 12/15/27'."""
    t = row.get("ticker") or row.get("securityDescription") or ""
    m = re.search(r"\s(\d+(?:\.\d+)?|F|V|0)\s+(\d{2}/\d{2}/\d{2,4})", t)
    if not m:
        return None, None
    cpn = "Floating" if m.group(1) in ("F", "V") else m.group(1)
    mm, dd, yy = m.group(2).split("/")
    yy = ("20" + yy) if len(yy) == 2 and int(yy) < 70 else ("19" + yy if len(yy) == 2 else yy)
    return cpn, f"{yy}-{mm}-{dd}"


def debt_securities(filings, cik, email, ids, annual_raw, figi_key, warnings, used, years=3, max_docs=8):
    today = date.today().isoformat()
    bonds = {}

    def merge(rec, source, link=""):
        key = rec.get("cusip") or rec.get("isin") or rec["description"].lower()
        cur = bonds.setdefault(key, {"description": "", "coupon": "", "maturity": "", "isin": "", "cusip": "",
                                     "figi": "", "principal": None, "listed": "", "sources": [], "link": ""})
        for k in ("description", "coupon", "maturity", "isin", "cusip", "figi", "principal", "listed"):
            if rec.get(k) and not cur[k]:
                cur[k] = rec[k]
        if source not in cur["sources"]:
            cur["sources"].append(source)
        cur["link"] = cur["link"] or link

    # 1. Recent offering documents (pricing term sheets and prospectus supplements)
    cutoff = (date.today() - timedelta(days=365 * years)).isoformat()
    docs = [f for f in filings if f["form"] in OFFER_FORMS and f["filingDate"] >= cutoff][:max_docs]
    for f in docs:
        try:
            raw, url = src.sec_doc(cik, f["accessionNumber"], f["primaryDocument"], email)
        except src.DataError:
            continue
        for t in parse_debt_terms(html_to_text(raw)[:400_000]):
            merge(t, f"{f['form']} {f['filingDate']}", url)

    # 2. ISINs mapped to the issuer's LEI (GLEIF) that look like debt, described through OpenFIGI
    isins = [d["isin"] for d in ids.get("debt", [])][:40]
    if isins:
        try:
            res = src.openfigi_map([{"idType": "ID_ISIN", "idValue": i} for i in isins], figi_key)
            for isin, data in zip(isins, res):
                row = next((d for d in data if d.get("marketSector") in ("Corp", "Pfd", None)), data[0] if data else {})
                cpn, mat = _parse_figi_bond(row) if row else (None, None)
                desc = (row.get("securityDescription") or row.get("ticker") or "") if row else ""
                merge({"description": desc or "Debt security (GLEIF mapping)", "coupon": cpn or "", "maturity": mat or "",
                       "isin": isin, "cusip": src.cusip_from_isin(isin), "figi": row.get("figi", "") if row else ""},
                      "GLEIF/OpenFIGI")
        except src.DataError as e:
            warnings.append(f"OpenFIGI (debt): {e}")
            for isin in isins:
                merge({"description": "Debt security (GLEIF mapping)", "isin": isin, "cusip": src.cusip_from_isin(isin)},
                      "GLEIF")

    # 3. Debt listed on an exchange (Section 12(b) classes on the annual report cover)
    for r in cover_12b(annual_raw):
        if re.search(r"\b(notes?|debentures?|bonds?)\b", r["title"], re.I):
            listed = f"{r['exchange']} {r['symbol']}".strip()
            yr, cpn = _maturity_year(r["title"]), re.search(r"(\d{1,2}(?:\.\d+)?)\s?%", r["title"])
            match = next((b for b in bonds.values() if yr and yr in (b["maturity"] + b["description"])
                          and cpn and cpn.group(1).rstrip("0").rstrip(".") in b["coupon"] + b["description"]), None)
            if match:
                match["listed"] = match["listed"] or listed
                match["sources"].append("10-K cover")
            else:
                merge({"description": r["title"], "coupon": cpn.group(1) if cpn else "", "maturity": yr, "listed": listed},
                      "10-K cover")

    def norm_mat(m):
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", m or ""):
            return m
        try:
            return datetime.strptime(m, "%B %d, %Y").date().isoformat()
        except (TypeError, ValueError):
            y = _maturity_year(m)
            return f"{y}-12-31" if y else ""

    rows, matured = [], 0
    for b in bonds.values():
        nm = norm_mat(b["maturity"])
        if nm and nm < today:
            matured += 1
            continue
        b["maturity_sort"] = nm or "9999"
        rows.append(b)
    rows.sort(key=lambda b: b["maturity_sort"])
    if rows:
        used.add("SEC EDGAR offering documents")
    return {"bonds": rows, "matured_excluded": matured, "documents_read": len(docs)}


# --------------------------------------------------------------------------
# Board of directors (SEC Forms 3/4/5 and the proxy statement)
# --------------------------------------------------------------------------
OWNERSHIP_FORMS = ("3", "4", "5", "3/A", "4/A", "5/A")
SUFFIXES = {"JR", "JR.", "SR", "SR.", "II", "III", "IV"}


def _xml_text(block, tag):
    m = re.search(rf"<{tag}>\s*(?:<value>)?\s*([^<]*?)\s*(?:</value>)?\s*</{tag}>", block, re.S | re.I)
    return html.unescape(m.group(1)).strip() if m else ""


def _truthy(v):
    return (v or "").strip().lower() in ("1", "true")


def parse_ownership_xml(raw):
    """Form 3/4/5 XML -> issuer and reporting owners with their relationship to the issuer."""
    if not raw or "<ownershipDocument" not in raw:
        return None
    owners = []
    for blk in re.findall(r"<reportingOwner>(.*?)</reportingOwner>", raw, re.S | re.I):
        owners.append({"cik": _xml_text(blk, "rptOwnerCik").zfill(10), "name": _xml_text(blk, "rptOwnerName"),
                       "director": _truthy(_xml_text(blk, "isDirector")), "officer": _truthy(_xml_text(blk, "isOfficer")),
                       "title": _xml_text(blk, "officerTitle")})
    return {"issuer_cik": _xml_text(raw, "issuerCik").zfill(10), "issuer": _xml_text(raw, "issuerName"),
            "symbol": _xml_text(raw, "issuerTradingSymbol"), "owners": owners}


def display_name(edgar_name):
    """'SMITH JOHN A' -> 'John A. Smith' (EDGAR lists reporting owners last name first)."""
    toks = [t for t in re.split(r"[\s,]+", edgar_name or "") if t]
    if len(toks) < 2:
        return (edgar_name or "").title()
    suffix = [t for t in toks[1:] if t.upper() in SUFFIXES]
    rest = [t for t in toks[1:] if t.upper() not in SUFFIXES]
    fix = lambda t: (t.upper().rstrip(".") + ".") if len(t.rstrip(".")) == 1 else \
        "-".join("'".join(x.capitalize() for x in part.split("'")) for part in t.split("-"))
    return " ".join([fix(t) for t in rest] + [fix(toks[0])] + [s.title() for s in suffix])


def _ownership_doc(cik, f, email):
    doc = f["primaryDocument"].split("/")[-1]
    if not doc.lower().endswith(".xml"):
        return None
    raw, _ = src.sec_doc(cik, f["accessionNumber"], doc, email)
    return parse_ownership_xml(raw)


def _proxy_bio(text, name):
    """Find a director's biography in proxy statement text and return two sentences plus any listed other boards."""
    parts = name.replace(".", "").split()
    if len(parts) < 2:
        return "", ""
    first, last = re.escape(parts[0]), re.escape(parts[-1] if parts[-1].upper().rstrip(".") not in SUFFIXES else parts[-2])
    best, best_score = None, 0
    for m in re.finditer(rf"\b{first}\b(?:\s+[A-Z][a-z]*\.?){{0,2}}\s+{last}\b", text, re.I):
        after = text[m.end(): m.end() + 40]
        # A biography normally opens with the name followed by age or a verb: "Jane Doe, 58, has served ..."
        opener = re.match(r"\s*(,\s*(age\s*)?\d{2}\b|,?\s+(has|is|was|serves|served|joined|brings)\b)", after, re.I)
        kw = r"\b(has served|director since|served as|experience|previously|chief executive|board of directors|joined)\b"
        score = (10 if opener else 0) + len(re.findall(kw, text[m.end(): m.end() + 400], re.I))
        if score > best_score:
            best, best_score = m, score
    if not best or best_score < 10:
        return "", ""
    chunk = text[best.start(): best.start() + 1200]
    sentences = split_sentences(chunk)
    bio = ". ".join(x.rstrip(".") for x in sentences[:2]).strip()
    bio = (bio[:380].rsplit(" ", 1)[0] + "…") if len(bio) > 380 else bio.rstrip(".") + "."
    other = re.search(r"(?:other|current)\s+public\s+(?:company\s+)?(?:boards?|directorships?)[^:]{0,40}:\s*([^.]{3,220})",
                      text[best.start(): best.start() + 3500], re.I)
    return bio, (other.group(1).strip() if other else "")


def board_of_directors(filings, cik, email, company_name, warnings, used, months=18, max_docs=60, max_directors=15):
    cutoff = (date.today() - timedelta(days=30 * months)).isoformat()
    owners = {}
    for f in [f for f in filings if f["form"] in OWNERSHIP_FORMS and f["filingDate"] >= cutoff][:max_docs]:
        try:
            d = _ownership_doc(cik, f, email)
        except src.DataError:
            continue
        if not d:
            continue
        for o in d["owners"]:
            if o["cik"].strip("0") and (o["director"] or o["officer"]):
                cur = owners.setdefault(o["cik"], dict(o, last=f["filingDate"]))
                cur["director"] |= o["director"]
                cur["officer"] |= o["officer"]
                cur["title"] = cur["title"] or o["title"]
    directors = sorted([o for o in owners.values() if o["director"]], key=lambda o: o["last"], reverse=True)[:max_directors]
    if not directors:
        return {"directors": [], "proxy": "", "note": "No director filings (Forms 3/4/5) in the last 18 months. "
                "Foreign private issuers (40-F/20-F filers) do not file these forms."}

    # Proxy statement for biographies
    proxy = next((f for f in filings if f["form"] in ("DEF 14A", "DEFA14A") and
                  f["filingDate"] >= (date.today() - timedelta(days=500)).isoformat()), None)
    ptext, purl = "", ""
    if proxy:
        try:
            raw, purl = src.sec_doc(cik, proxy["accessionNumber"], proxy["primaryDocument"], email)
            ptext = html_to_text(raw)
        except src.DataError:
            pass

    out = []
    for o in directors:
        name = display_name(o["name"])
        # Other public company roles: issuers in the director's own Form 3/4/5 filings (last 3 years)
        others = {}
        try:
            psub = src.sec_submissions(o["cik"], email)
            pf = [f for f in _recent(psub) if f["form"] in OWNERSHIP_FORMS and
                  f["filingDate"] >= (date.today() - timedelta(days=3 * 365)).isoformat()]
            seen_acc = 0
            for f in pf[:10]:
                d = _ownership_doc(o["cik"], f, email)
                seen_acc += 1
                if not d or d["issuer_cik"] == cik:
                    continue
                me = next((x for x in d["owners"] if x["cik"] == o["cik"]), None)
                if me and (me["director"] or me["officer"]):
                    role = ("Director" if me["director"] else "") + (" & " if me["director"] and me["officer"] else "") + \
                           ((me["title"] or "Officer") if me["officer"] else "")
                    others.setdefault(d["issuer"].title(), {"role": role, "symbol": d["symbol"]})
        except src.DataError:
            pass
        bio, listed_other = _proxy_bio(ptext, name) if ptext else ("", "")
        q = requests_quote(f'"{name}" {company_name} board')
        out.append({
            "name": name, "cik": o["cik"],
            "role": "Director" + (f" & {o['title']}" if o["officer"] and o["title"] else (" & Officer" if o["officer"] else "")),
            "other_public_boards": [f"{k} ({v['symbol']}): {v['role']}" if v["symbol"] else f"{k}: {v['role']}"
                                    for k, v in others.items()],
            "proxy_other_boards": listed_other, "bio": bio,
            "edgar_url": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={o['cik']}&type=4&dateb=&owner=include&count=40",
            "web_url": f"https://www.google.com/search?q={q}",
            "last_filing": o["last"],
        })
    used.add("SEC ownership filings")
    return {"directors": out, "proxy": f"DEF 14A filed {proxy['filingDate']}" if proxy else "", "proxy_url": purl,
            "note": "Directors who filed a Form 3, 4 or 5 for this company in the last 18 months."}


def requests_quote(text):
    from urllib.parse import quote_plus
    return quote_plus(text)


# --------------------------------------------------------------------------
# Main entry point
# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
# How and when the company went public
# --------------------------------------------------------------------------
def full_filing_history(sub, email, warnings):
    """Recent filings plus the older pages EDGAR keeps in separate files (oldest at the end)."""
    rows = _recent(sub)
    for f in (sub.get("filings") or {}).get("files") or []:
        try:
            txt = src.http_get(f"https://data.sec.gov/submissions/{f['name']}", user_agent=src.sec_ua(email), sec=True)
            page = json.loads(txt or "{}")
            n = len(page.get("form", []))
            rows += [{k: (page.get(k) or [""] * n)[i] for k in
                      ["form", "filingDate", "accessionNumber", "primaryDocument", "items", "reportDate"]} for i in range(n)]
        except (src.DataError, json.JSONDecodeError) as e:
            warnings.append(f"Older filing history: {e}")
    return sorted(rows, key=lambda f: f["filingDate"], reverse=True)


SPAC_NAME = re.compile(r"\b(acquisition|blank check|spac|merger)\s+(corp|corporation|company|co|inc|ltd|limited|holdings)\b|"
                       r"\bacquisition\s+corp", re.I)


def listing_history(history, cik, company, sub=None):
    """One-line answer: IPO date, or SPAC / blank-check merger (with date), or another route."""
    oldest_first = list(reversed(history))
    first = oldest_first[0]["filingDate"] if oldest_first else None

    def find(pred):
        return next((f for f in oldest_first if pred(f)), None)
    link = lambda f: src.filing_url(cik, f["accessionNumber"], f["primaryDocument"]) if f else ""
    reg = find(lambda f: f["form"] in ("S-1", "F-1", "S-1/A", "F-1/A", "DRS"))
    priced = find(lambda f: f["form"] == "424B4" and (reg is None or f["filingDate"] >= reg["filingDate"]))
    shell_exit = find(lambda f: f["form"].startswith("8-K") and "5.06" in (f.get("items") or ""))
    merger_reg = find(lambda f: f["form"] in ("S-4", "F-4", "S-4/A", "F-4/A", "DEFM14A"))
    former = [n for n in ((sub or {}).get("formerNames") or []) if SPAC_NAME.search(n.get("name") or "")]
    spac_name = former[-1]["name"].title() if former else ""
    form10 = find(lambda f: f["form"] in ("10-12B", "10-12B/A"))
    mjds = find(lambda f: f["form"] in ("40FR12B", "40-F"))
    exch = find(lambda f: f["form"] in ("8-A12B", "8-A12B/A"))

    def out(kind, when, text, f):
        return {"kind": kind, "date": when, "summary": text, "link": link(f), "first_edgar_filing": first}

    if shell_exit and (former or merger_reg) or (former and shell_exit is None and merger_reg):
        f = shell_exit or merger_reg
        when = (shell_exit or merger_reg)["filingDate"]
        who = f" ({spac_name})" if spac_name else ""
        return out("SPAC", when, f"Went public by merging with a SPAC / blank-check company{who}; completed {when}.", f)
    if priced and reg and not former:
        return out("IPO", priced["filingDate"], f"IPO on {priced['filingDate']}.", priced)
    if form10:
        return out("Spin-off", form10["filingDate"], f"Spin-off; registered {form10['filingDate']}.", form10)
    if mjds and (not exch or mjds["filingDate"] <= exch["filingDate"]):
        return out("Cross-listing", mjds["filingDate"],
                   f"Canadian company cross-listed in the U.S. (MJDS) on {mjds['filingDate']}.", mjds)
    if reg and exch and not priced:
        return out("Direct listing", exch["filingDate"], f"Direct listing (no IPO prospectus) on {exch['filingDate']}.", exch)
    return out("Unknown", None, "", None)


ABBREV = re.compile(r"\b(Dr|Mr|Mrs|Ms|Prof|Inc|Corp|Co|Ltd|Jr|Sr|St|No|Nos|vs|U\.S|Ph\.D|M\.D|e\.g|i\.e)\.", re.I)


def split_sentences(text):
    """Sentence split that does not break on 'Dr.', 'Inc.', 'U.S.' and similar."""
    t = ABBREV.sub(lambda m: m.group(0).replace(".", "§"), " ".join((text or "").split()))
    parts = re.split(r"(?<=[a-z0-9\)%§])\.\s+(?=[A-Z])", t)
    return [p.replace("§", ".") for p in parts if p.strip()]


def concise(text, sentences=2, max_chars=300):
    """First one or two sentences, capped in length."""
    parts = split_sentences(text)
    out = ". ".join(p.rstrip(".") for p in parts[:sentences]).strip()
    out = out if out.endswith(".") else out + "."
    return out if len(out) <= max_chars else out[:max_chars].rsplit(" ", 1)[0].rstrip(",;") + "…"


def web_description(company, tav_key, warnings, used):
    if tav_key:
        try:
            r = src.tavily(f"In one or two sentences: what does {company['name']} ({company['industry']}) do, "
                           f"and what are its main products?", tav_key, max_results=5)
            if r["answer"]:
                used.add("Tavily web search")
                return {"text": concise(r["answer"]), "source": "Web search summary",
                        "links": [(x["title"], x["url"]) for x in r["results"][:4]]}
        except src.DataError as e:
            warnings.append(f"Web description: {e}")
    try:
        w = src.wikipedia_summary(company["name"])
        if w:
            used.add("Wikipedia")
            return {"text": concise(w["text"]), "source": f"Wikipedia: {w['title']}", "links": [(w["title"], w["url"])]}
    except (src.DataError, ValueError) as e:
        warnings.append(f"Wikipedia: {e}")
    return None


def web_listing_fallback(company, tav_key, warnings):
    """Only used when EDGAR can't tell (e.g. listed before electronic filing): ask web search for the IPO date."""
    if not tav_key:
        return None
    try:
        r = src.tavily(f"{company['name']} IPO date: when did it go public, and was it through a SPAC merger?",
                       tav_key, max_results=5)
    except src.DataError as e:
        warnings.append(f"Web IPO lookup: {e}")
        return None
    ans = r.get("answer") or ""
    if not ans:
        return None
    m = re.search(r"((?:January|February|March|April|May|June|July|August|September|October|November|December)"
                  r"\s+(?:\d{1,2},\s+)?\d{4})|\b((?:19|20)\d{2})\b", ans)
    when = (m.group(1) or m.group(2)) if m else None
    spac = re.search(r"\b(SPAC|special purpose acquisition|blank[- ]check)\b", ans, re.I)
    if not when:
        return None
    link = r["results"][0]["url"] if r.get("results") else ""
    text = (f"Went public by merging with a SPAC / blank-check company in {when} (web search)." if spac
            else f"IPO in {when} (web search).")
    return {"kind": "SPAC" if spac else "IPO", "date": when, "summary": text, "link": link}


NOT_ARTICLE_URL = re.compile(
    r"/(quote|quotes|symbol|stock-price|stocks?/[a-z.\-]+/?$|markets/stocks|company-profile|profile|chart|options|"
    r"financials|historical|key-statistics|holders|analysis|earnings-calendar|investor-relations|investors/?$|"
    r"market-activity|news-headlines|press-release-list|"
    r"press-releases/?$|news/?$|tag/|topic/|search)", re.I)
NOT_ARTICLE_HOST = re.compile(r"(wikipedia\.org|sec\.gov|youtube\.com|linkedin\.com|facebook\.com|x\.com|twitter\.com|"
                              r"stocktwits\.com|google\.com)$", re.I)
NOT_ARTICLE_TITLE = re.compile(r"(stock price|stock quote|share price|\bquote\b|price & news|price and news|"
                               r"stock forecast|price target|chart|historical data|company profile)", re.I)


def is_article(url, title):
    """Keep links to individual news stories; drop quote pages, profiles, section fronts and home pages."""
    m = re.match(r"https?://([^/]+)(/.*)?$", url or "")
    if not m:
        return False
    host, path = m.group(1).lower().removeprefix("www."), (m.group(2) or "/").split("?")[0]
    if NOT_ARTICLE_HOST.search(host) or NOT_ARTICLE_URL.search(path) or NOT_ARTICLE_TITLE.search(title or ""):
        return False
    segs = [x for x in path.split("/") if x]
    return bool(segs) and (len(segs) >= 2 or len(segs[-1]) >= 20 or "-" in segs[-1])


MNA_QUERY_TERMS = ("acquisition OR merger OR takeover OR buyout OR \"strategic alternatives\" OR \"exploring sale\" "
                   "OR \"in talks\" OR bid OR divestiture OR \"joint venture\"")


def web_news(company, ticker, tav_key, warnings, used, days=EVENT_DAYS):
    """News from the last 90 days; M&A and strategic-transaction stories (including rumors) are fetched separately and listed first."""
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    items = []
    name = company["name"] + (f" ({ticker})" if ticker else "")
    if tav_key:
        for q in (f"{name} acquisition, merger, takeover, sale process, strategic alternatives or deal talks",
                  f"{name} news"):
            try:
                items += src.tavily(q, tav_key, topic="news", days=days, max_results=15, answer=False)["results"]
                used.add("Tavily web search")
            except src.DataError as e:
                warnings.append(f"Web news: {e}")
                break
    if not items:
        for extra in (f"({MNA_QUERY_TERMS.replace(chr(92), '')})", ""):
            try:
                items += src.gdelt_news(src.clean_name(company["name"]), max_records=50 if extra else 75, extra=extra)
                used.add("GDELT news")
            except src.DataError as e:
                warnings.append(f"GDELT news: {e}")
    out, seen = [], set()
    for it in items:
        d = _norm_date(it["date"])
        if d and d < cutoff:
            continue
        key = re.sub(r"\W+", " ", it["title"].lower())[:80]
        if not it["title"] or key in seen or not is_article(it["url"], it["title"]):
            continue
        seen.add(key)
        cat = classify_news(it["title"], it.get("content", ""))
        rumored = cat == "M&A" and bool(RUMOR_RE.search(f"{it['title']} {it.get('content', '')}"))
        out.append(dict(it, date=d or "", category=cat or "", mna=cat == "M&A", rumored=rumored))
    # M&A / strategic first (newest first), then everything else (newest first)
    out.sort(key=lambda x: x["date"], reverse=True)
    return sorted(out, key=lambda x: not x["mna"])


def _norm_date(s):
    """Accepts '2026-11-03', '2026-11-03T10:00:00Z' or 'Mon, 03 Nov 2026 10:00:00 GMT'."""
    s = (s or "").strip()
    m = re.search(r"(\d{4}-\d{2}-\d{2})", s)
    if m:
        return m.group(1)
    m = re.search(r"(\d{1,2}) ([A-Za-z]{3}) (\d{4})", s)
    if m:
        try:
            return datetime.strptime(" ".join(m.groups()), "%d %b %Y").date().isoformat()
        except ValueError:
            return ""
    return ""


def web_events(news):
    out = []
    for n in news:
        cat = classify_news(n["title"], n.get("content", ""))
        if cat and n["date"]:                    # undated items stay in the news list only
            out.append({"date": n["date"], "status": "Rumored" if n.get("rumored") else "Reported", "category": cat,
                        "form": n["source"] or "Web",
                        "title": n["title"], "why": WHY[cat], "url": n["url"]})
    return out


# --------------------------------------------------------------------------
# Security identifiers: tickers, ISIN, CUSIP, FIGI (SEDOL is licensed)
# --------------------------------------------------------------------------
def identifiers(company, securities, cusips_13dg, figi_key, warnings, used):
    ent = {"CIK": company["cik"], "LEI": company.get("lei") or "", "LEI status": "", "EIN": company.get("ein") or ""}
    rows, debt = [], []
    isins = []
    try:
        code = {"United States": "US", "Canada": "CA"}
        countries = tuple({code[x] for x in (company["incorporation_country"], company["hq_country"]) if x in code}) or ("US", "CA")
        lei = src.gleif_find_lei(company["name"], countries)
        if lei:
            ent["LEI"], ent["LEI status"] = lei["lei"], lei["status"]
            isins = src.gleif_isins(lei["lei"])
            used.add("GLEIF")
    except (src.DataError, KeyError, ValueError) as e:
        warnings.append(f"GLEIF (LEI and ISINs): {e}")
    # CUSIPs reported on Schedule 13D/13G cover pages fill gaps
    for c in sorted(cusips_13dg):
        isin = src.isin_from_cusip(c, "US")
        if isin not in isins and src.cusip_from_isin(isin) not in {src.cusip_from_isin(i) for i in isins}:
            isins.append(isin)
    eq = [i for i in isins if src.isin_valid(i) and src.cusip_kind(src.cusip_from_isin(i)) != "Debt / other"]
    debt = [{"isin": i, "cusip": src.cusip_from_isin(i)} for i in isins
            if src.isin_valid(i) and src.cusip_kind(src.cusip_from_isin(i)) == "Debt / other"]
    eq += [i for i in isins if src.isin_valid(i) and i[:2] not in ("US", "CA") and i not in eq]

    # Map equity ISINs and listed tickers to FIGIs
    jobs = [{"idType": "ID_ISIN", "idValue": i} for i in eq[:15]]
    tick_jobs = [{"idType": "TICKER", "idValue": s["ticker"].replace(".", "/") if s["country"] == "US" else s["ticker"],
                  "exchCode": "US" if s["country"] == "US" else "CN"} for s in securities]
    figi_by_isin, figi_by_ticker = {}, {}
    try:
        res = src.openfigi_map(jobs + tick_jobs, figi_key)
        used.add("OpenFIGI")
        for job, data in zip(jobs + tick_jobs, res):
            comp = [d for d in data if d.get("exchCode") in ("US", "CN")] or data
            if comp:
                if job["idType"] == "ID_ISIN":
                    figi_by_isin[job["idValue"]] = comp
                else:
                    figi_by_ticker[(job["idValue"], job["exchCode"])] = [d for d in comp if d.get("exchCode") == job["exchCode"]] or comp
    except src.DataError as e:
        warnings.append(f"OpenFIGI: {e}")

    used_isins = set()
    for s in securities:
        key = (s["ticker"].replace(".", "/") if s["country"] == "US" else s["ticker"], "US" if s["country"] == "US" else "CN")
        f = (figi_by_ticker.get(key) or [{}])[0]
        isin = next((i for i, d in figi_by_isin.items()
                     if any(x.get("compositeFIGI") and x.get("compositeFIGI") == f.get("compositeFIGI") for x in d)), "")
        if not isin and s["type"] == "Common Stock":           # fall back to the issuer's only equity ISIN
            pref = [i for i in eq if i[:2] == ("CA" if company["incorporation_country"] == "Canada" else "US")]
            isin = pref[0] if len(pref) == 1 else ""
        used_isins.add(isin)
        rows.append({"ticker": s["ticker"], "exchange": s["exchange"], "type": f.get("securityType") or s["type"],
                     "isin": isin, "cusip": src.cusip_from_isin(isin), "figi": f.get("figi", ""),
                     "composite_figi": f.get("compositeFIGI", ""), "share_class_figi": f.get("shareClassFIGI", ""),
                     "sedol": "Licensed (not in free sources)"})
    for i in eq:                                           # equity lines without a listed ticker match
        if i not in used_isins:
            f = (figi_by_isin.get(i) or [{}])[0]
            rows.append({"ticker": f.get("ticker", ""), "exchange": "", "type": f.get("securityType") or "Equity",
                         "isin": i, "cusip": src.cusip_from_isin(i), "figi": f.get("figi", ""),
                         "composite_figi": f.get("compositeFIGI", ""), "share_class_figi": f.get("shareClassFIGI", ""),
                         "sedol": "Licensed (not in free sources)"})
    return {"entity": ent, "securities": rows, "debt": debt,
            "notes": ["ISINs come from the GLEIF/ANNA ISIN-to-LEI mapping (CC0) and Schedule 13D/13G cover pages; "
                      "U.S. and Canadian CUSIPs are characters 3-11 of the ISIN.",
                      "CUSIP data is owned by CUSIP Global Services; check licensing before publishing CUSIPs publicly.",
                      "SEDOLs are licensed by LSEG and are not available from free sources."]}


# --------------------------------------------------------------------------
# Main entry point
# --------------------------------------------------------------------------
def _safe(label, fn, default, warnings):
    """Run one profile section; if it fails, record a note and carry on with the rest."""
    try:
        return fn()
    except Exception as e:                     # noqa: BLE001 - keep the page up whatever a source returns
        warnings.append(f"{label} could not be loaded ({type(e).__name__}: {str(e)[:120]}).")
        return default


# --------------------------------------------------------------------------
# Staged loading: a fast base profile, then optional sections on demand
# --------------------------------------------------------------------------
SECTIONS = {            # name -> (label, dependencies)
    "identifiers": ("Equity securities and identifiers", ["holders"]),
    "debt": ("Fixed income securities", ["identifiers", "annual"]),
    "listing": ("How and when it went public", []),
    "holders": ("Significant holders (5%+)", []),
    "news": ("News and corporate events (last 90 days)", []),
    "regm": ("Research safe harbor summary", ["annual"]),
    "board": ("Board of directors", []),
    "annual": ("Annual report cover", []),          # internal helper section
}
USER_SECTIONS = ["identifiers", "debt", "listing", "holders", "news", "regm", "board"]
SECTION_KEYS = {"identifiers": ["identifiers"], "debt": ["debt"], "listing": ["listing"], "holders": ["holders", "cusips"],
                "news": ["news", "events"], "regm": ["regm"], "board": ["board"],
                "annual": ["cover", "annual_raw", "filing_excerpt", "filing_excerpt_source"]}


def build_base(cik, settings, sec_tickers, symdir):
    """Company record, description and market data only: the fast first view."""
    from concurrent.futures import ThreadPoolExecutor
    cik = str(cik).zfill(10)
    email = settings.get("SEC_CONTACT_EMAIL", "")
    av_key, td_key, tav_key = (settings.get(k, "") for k in ("ALPHAVANTAGE_KEY", "TWELVEDATA_KEY", "TAVILY_KEY"))
    warnings, used = [], {"SEC EDGAR"}

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
        "former_names": [n.get("name") for n in (sub.get("formerNames") or [])][:5],
    }

    securities = []
    for t in [x for x in sec_tickers if x["cik"] == cik]:
        dot = t["ticker"].replace("-", ".")
        d = symdir.get(dot) or symdir.get(t["ticker"]) or {}
        name = d.get("name") or company["name"]
        securities.append({"ticker": dot, "exchange": d.get("exchange") or t["exchange"] or "OTC",
                           "country": "US", "name": name, "type": classify(name, d.get("is_etf"), t["exchange"])})
    canadian = company["hq_country"] == "Canada" or company["incorporation_country"] == "Canada"

    def tsx_lookup():
        if canadian and not av_key:
            warnings.append("TSX listing and TSX prior close need an Alpha Vantage key (ALPHAVANTAGE_KEY); U.S. listing shown only.")
        elif canadian:
            try:
                tsx = src.av_search_tsx(company["name"], av_key)
                if tsx:
                    securities.append({"ticker": tsx["symbol"].rsplit(".", 1)[0], "av_symbol": tsx["symbol"],
                                       "exchange": tsx["exchange"], "country": "CA",
                                       "name": tsx["name"] or company["name"], "type": "Common Stock"})
            except src.DataError as e:
                warnings.append(f"TSX listing lookup: {e}")
        securities.sort(key=lambda s: (s["type"] != "Common Stock", s["country"] != "US", s["ticker"]))

    def facts_and_market():
        tsx_lookup()
        facts = _safe("Financial facts (SEC XBRL)", lambda: src.sec_facts(cik, email), {}, warnings)
        bs = _safe("Balance sheet figures", lambda: balance_sheet(facts),
                   {"shares_out": None, "public_float": None, "cash": None, "debt": None, "revenue": None}, warnings)
        if av_key or td_key:
            market = _safe("Market data", lambda: market_data(company, securities, bs, settings, warnings),
                           {"venues": [], "fx": {"USD": 1.0}}, warnings)
            used.update(v["provider"] for v in market.get("venues", []))
        else:
            market = {"venues": [], "fx": {"USD": 1.0}}
            warnings.append("Market data is off: add a free Twelve Data key (TWELVEDATA_KEY) and/or Alpha Vantage key "
                            "(ALPHAVANTAGE_KEY) in the app settings.")
            if bs.get("public_float"):
                market["public_float_usd"], market["public_float_date"] = bs["public_float"]["value"], bs["public_float"]["date"]
            if bs.get("shares_out"):
                market["shares_out"], market["shares_out_date"] = bs["shares_out"]["value"], bs["shares_out"]["date"]
        return bs, market

    # Market data and the web description run at the same time
    with ThreadPoolExecutor(max_workers=2) as pool:
        fm = pool.submit(facts_and_market)
        wd = pool.submit(lambda: _safe("Web description", lambda: web_description(company, tav_key, warnings, used), None, warnings))
        bs, market = fm.result()
        web_desc = wd.result()

    ctx = {"cik": cik, "settings": dict(settings), "as_of": datetime.now().strftime("%Y-%m-%d %H:%M"),
           "sub": sub, "filings": filings, "company": company, "securities": securities, "financials": bs,
           "market": market, "warnings": warnings, "used": used, "loaded": set()}
    if web_desc:
        ctx["description"] = {"text": web_desc["text"], "source": web_desc["source"], "links": web_desc["links"]}
    else:                                   # fall back to the annual report text
        ensure(ctx, "annual")
        if ctx.get("filing_excerpt"):
            ctx["description"] = {"text": concise(ctx["filing_excerpt"]), "source": ctx["filing_excerpt_source"], "links": []}
        else:
            ctx["description"] = {"text": "", "source": "", "links": []}
            warnings.append("No business description found from web search, Wikipedia or the annual report.")
    if not tav_key:
        warnings.append("Web search is off: add a free Tavily key (TAVILY_KEY) for the description summary and fuller news.")
    return ctx


def _sec_annual(ctx):
    cik, email, filings = ctx["cik"], ctx["settings"].get("SEC_CONTACT_EMAIL", ""), ctx["filings"]
    out = {"cover": {}, "annual_raw": "", "filing_excerpt": "", "filing_excerpt_source": ""}
    annual = next((f for f in filings if f["form"] in ANNUAL), None)
    latest_periodic = next((f for f in filings if f["form"] in PERIODIC), None)
    if annual:
        raw, _ = src.sec_doc(cik, annual["accessionNumber"], annual["primaryDocument"], email)
        out["annual_raw"] = raw or ""
        out["cover"] = cover_flags(raw)
        desc = extract_description(raw, annual["form"])
        if not desc and annual["form"] == "40-F":
            ex = _pick_aif_exhibit(cik, annual, email)
            if ex:
                raw2, _ = src.sec_doc(cik, annual["accessionNumber"], ex, email)
                desc = extract_description(raw2, "40-F")
        out["filing_excerpt"], out["filing_excerpt_source"] = desc, f"{annual['form']} filed {annual['filingDate']}"
    elif latest_periodic:
        raw, _ = src.sec_doc(cik, latest_periodic["accessionNumber"], latest_periodic["primaryDocument"], email)
        out["cover"] = cover_flags(raw)
    return out


def _sec_listing(ctx):
    w, st = ctx["warnings"], ctx["settings"]
    history = _safe("Older filing history", lambda: full_filing_history(ctx["sub"], st.get("SEC_CONTACT_EMAIL", ""), w),
                    ctx["filings"], w)
    listing = listing_history(history, ctx["cik"], ctx["company"], ctx["sub"])
    if listing["kind"] == "Unknown":
        web = _safe("Web IPO lookup", lambda: web_listing_fallback(ctx["company"], st.get("TAVILY_KEY", ""), w), None, w)
        if web:
            listing.update(web)
        else:
            listing["summary"] = ("Public before electronic SEC filing (EDGAR) began; IPO date not found."
                                  if (listing.get("first_edgar_filing") or "9999") <= "1997-12-31"
                                  else "Route to listing could not be determined from public filings.")
    return {"listing": listing}


def _sec_holders(ctx):
    holders, cusips = significant_holders(ctx["filings"], ctx["cik"], ctx["settings"].get("SEC_CONTACT_EMAIL", ""))
    return {"holders": holders, "cusips": cusips}


def _sec_identifiers(ctx):
    ids = identifiers(ctx["company"], ctx["securities"], ctx.get("cusips") or set(),
                      ctx["settings"].get("OPENFIGI_KEY", ""), ctx["warnings"], ctx["used"])
    if ids["entity"].get("LEI"):
        ctx["company"]["lei"] = ids["entity"]["LEI"]
    return {"identifiers": ids}


def _sec_debt(ctx):
    st = ctx["settings"]
    debt = debt_securities(ctx["filings"], ctx["cik"], st.get("SEC_CONTACT_EMAIL", ""), ctx["identifiers"],
                           ctx.get("annual_raw", ""), st.get("OPENFIGI_KEY", ""), ctx["warnings"], ctx["used"])
    debt["total_debt"] = ctx["financials"].get("debt")
    return {"debt": debt}


def _sec_board(ctx):
    return {"board": board_of_directors(ctx["filings"], ctx["cik"], ctx["settings"].get("SEC_CONTACT_EMAIL", ""),
                                        ctx["company"]["name"], ctx["warnings"], ctx["used"])}


def _sec_news(ctx):
    w, st = ctx["warnings"], ctx["settings"]
    us_common = next((s for s in ctx["securities"] if s["country"] == "US" and s["type"] == "Common Stock"), None)
    news = _safe("News", lambda: web_news(ctx["company"], us_common["ticker"] if us_common else "", st.get("TAVILY_KEY", ""),
                                          w, ctx["used"]), [], w)
    events = sorted(_safe("Corporate events", lambda: corporate_events(ctx["filings"], ctx["cik"]), [], w) +
                    _safe("Web events", lambda: web_events(news), [], w), key=lambda e: e["date"], reverse=True)
    events.sort(key=lambda e: e["category"] != "M&A")      # M&A and strategic transactions first
    return {"news": news[:25], "events": events}


def _sec_regm(ctx):
    return {"regm": regm.analyse(to_profile(ctx))}


SECTION_FUNCS = {"annual": _sec_annual, "listing": _sec_listing, "holders": _sec_holders, "identifiers": _sec_identifiers,
                 "debt": _sec_debt, "board": _sec_board, "news": _sec_news, "regm": _sec_regm}
SECTION_DEFAULTS = {
    "annual": {"cover": {}, "annual_raw": "", "filing_excerpt": "", "filing_excerpt_source": ""},
    "listing": {"listing": {"kind": "Unknown", "date": None, "summary": "", "link": "", "first_edgar_filing": None}},
    "holders": {"holders": [], "cusips": set()},
    "identifiers": {"identifiers": {"entity": {"CIK": "", "LEI": "", "LEI status": "", "EIN": ""}, "securities": [], "debt": [], "notes": []}},
    "debt": {"debt": {"bonds": [], "matured_excluded": 0, "documents_read": 0, "total_debt": None}},
    "board": {"board": {"directors": [], "proxy": "", "note": ""}},
    "news": {"news": [], "events": []},
    "regm": {"regm": {"summary": "Safe harbor summary unavailable.", "harbors": [], "facts": [], "actively_traded": None}},
}


def ensure(ctx, name):
    """Load one section (and anything it depends on) into ctx, once."""
    if name in ctx["loaded"]:
        return ctx
    for dep in SECTIONS[name][1]:
        ensure(ctx, dep)
    label = SECTIONS[name][0]
    import copy
    ctx.update(_safe(label, lambda: SECTION_FUNCS[name](ctx), copy.deepcopy(SECTION_DEFAULTS[name]), ctx["warnings"]))
    ctx["loaded"].add(name)
    return ctx


def section_data(ctx, name):
    return {k: ctx[k] for k in SECTION_KEYS[name] if k in ctx}


def to_profile(ctx):
    """The profile dict the page and PDF read; sections not loaded yet are empty."""
    p = {"as_of": ctx["as_of"], "company": ctx["company"], "financials": ctx["financials"], "market": ctx["market"],
         "description": ctx["description"] if "description" in ctx else {"text": "", "source": "", "links": []},
         "securities": ctx["securities"], "filings": ctx["filings"], "warnings": ctx["warnings"],
         "sources": sorted(ctx["used"]), "loaded": sorted(ctx["loaded"])}
    for name, defaults in SECTION_DEFAULTS.items():
        for k, v in defaults.items():
            p[k] = ctx.get(k, v)
    return p


def build_profile(cik, settings, sec_tickers, symdir, progress=lambda msg: None):
    """Everything at once (used for the full PDF and for testing)."""
    ctx = build_base(cik, settings, sec_tickers, symdir)
    for name in USER_SECTIONS:
        progress(SECTIONS[name][0])
        ensure(ctx, name)
    return to_profile(ctx)


def classify(name, is_etf, sec_exchange):
    t = src.classify_security(name, is_etf)
    return t if t != "Other" else "Common Stock"
