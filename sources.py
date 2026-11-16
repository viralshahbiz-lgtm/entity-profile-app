"""
Data sources for the entity profile page. Public data only.

- SEC EDGAR (free, no key; a contact email is required in the User-Agent)
    company tickers, submissions (filing history), company facts (XBRL),
    filing documents (annual report text, cover-page flags, Schedule 13D/13G)
- Nasdaq Trader symbol directory (free) for security names on U.S. exchanges
- Twelve Data (free key) for prior-close prices and volumes on U.S. listings
- Alpha Vantage (free key) for TSX prices and as a backup for U.S. prices
- Tavily web search (free key) for news, events, description and IPO summaries
- GDELT news search (free, no key) as a news fallback
- Wikipedia (free, no key) as a description fallback
- GLEIF (free, no key) for the LEI and the ISINs mapped to it
- OpenFIGI (free, optional key) for FIGIs, exchange tickers and security types

Every function returns plain Python data so the app and the PDF can share it.
"""
import csv
import io
import json
import re
import time
from datetime import date, timedelta

import requests

SEC_TICKERS = "https://www.sec.gov/files/company_tickers_exchange.json"
SEC_SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik}.json"
SEC_FACTS = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
SEC_ARCHIVE = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}"
NASDAQ_LISTED = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
OTHER_LISTED = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"
AV_URL = "https://www.alphavantage.co/query"
TD_URL = "https://api.twelvedata.com"
TAVILY_URL = "https://api.tavily.com/search"
GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
WIKI_API = "https://en.wikipedia.org/w/api.php"
WIKI_SUMMARY = "https://en.wikipedia.org/api/rest_v1/page/summary/{title}"
GLEIF_RECORDS = "https://api.gleif.org/api/v1/lei-records"
OPENFIGI_URL = "https://api.openfigi.com/v3/mapping"

OTHER_EXCH = {"A": "NYSE American", "N": "NYSE", "P": "NYSE Arca", "Z": "Cboe BZX", "V": "IEX"}


class DataError(Exception):
    """A source could not be reached or returned nothing usable."""


class QuotaError(DataError):
    """A free-tier API limit was hit."""


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------
_last_sec_call = [0.0]


def http_post(url, payload, headers=None, timeout=40):
    """POST JSON with retries; returns parsed JSON."""
    for attempt in range(3):
        try:
            r = requests.post(url, json=payload, headers=headers or {}, timeout=timeout)
            if r.status_code == 429:
                raise QuotaError("Rate limit reached at " + url.split("/")[2])
            if r.status_code in (401, 403):
                raise DataError(f"{url.split('/')[2]} rejected the API key. Check it in the app settings.")
            r.raise_for_status()
            return r.json()
        except (QuotaError, DataError):
            raise
        except Exception as e:
            if attempt == 2:
                raise DataError(f"Could not reach {url.split('/')[2]}: {e}")
            time.sleep(1.5 * (attempt + 1))


def http_get(url, params=None, user_agent=None, timeout=30, sec=False):
    """GET with retries. SEC calls are throttled to stay under 10 per second."""
    headers = {"User-Agent": user_agent or "entity-profile-app"}
    for attempt in range(3):
        if sec:
            wait = 0.12 - (time.time() - _last_sec_call[0])
            if wait > 0:
                time.sleep(wait)
            _last_sec_call[0] = time.time()
        try:
            r = requests.get(url, params=params, headers=headers, timeout=timeout)
            if r.status_code == 404:
                return None
            if r.status_code == 429:
                raise QuotaError("Rate limit reached at " + url.split("/")[2])
            r.raise_for_status()
            return r.text
        except QuotaError:
            raise
        except Exception as e:  # network blips: retry, then give up
            if attempt == 2:
                raise DataError(f"Could not reach {url.split('/')[2]}: {e}")
            time.sleep(1.5 * (attempt + 1))


# --------------------------------------------------------------------------
# SEC EDGAR
# --------------------------------------------------------------------------
def sec_ua(email):
    if not email or "@" not in email:
        raise DataError("Set SEC_CONTACT_EMAIL in the app settings (the SEC requires a contact email).")
    return f"entity-profile-app {email}"


def sec_tickers(email):
    """All SEC-registered tickers with exchange: list of dicts (cik, name, ticker, exchange)."""
    txt = http_get(SEC_TICKERS, user_agent=sec_ua(email), sec=True)
    data = json.loads(txt)
    f = {k: i for i, k in enumerate(data["fields"])}
    return [{"cik": str(r[f["cik"]]).zfill(10), "name": r[f["name"]],
             "ticker": (r[f["ticker"]] or "").upper(), "exchange": r[f["exchange"]] or ""}
            for r in data["data"]]


def sec_submissions(cik, email):
    txt = http_get(SEC_SUBMISSIONS.format(cik=cik), user_agent=sec_ua(email), sec=True)
    if not txt:
        raise DataError(f"No SEC record for CIK {cik}.")
    return json.loads(txt)


def sec_facts(cik, email):
    txt = http_get(SEC_FACTS.format(cik=cik), user_agent=sec_ua(email), sec=True, timeout=60)
    return json.loads(txt) if txt else {}


def sec_doc(cik, accession, doc, email):
    url = SEC_ARCHIVE.format(cik=int(cik), acc=accession.replace("-", ""), doc=doc)
    return http_get(url, user_agent=sec_ua(email), sec=True, timeout=60), url


def filing_url(cik, accession, doc):
    return SEC_ARCHIVE.format(cik=int(cik), acc=accession.replace("-", ""), doc=doc)


# --------------------------------------------------------------------------
# Nasdaq Trader symbol directory (security names and types on U.S. exchanges)
# --------------------------------------------------------------------------
def _pipe(text):
    lines = [l for l in text.splitlines() if l and not l.startswith("File Creation Time")]
    return list(csv.DictReader(io.StringIO("\n".join(lines)), delimiter="|"))


def us_symbol_directory():
    """ticker -> {name, exchange, is_etf}. Tickers use '.' for share classes (BRK.B)."""
    out = {}
    for r in _pipe(http_get(NASDAQ_LISTED) or ""):
        if r.get("Test Issue") != "Y":
            out[r["Symbol"].upper()] = {"name": r["Security Name"], "exchange": "Nasdaq",
                                        "is_etf": r.get("ETF") == "Y"}
    for r in _pipe(http_get(OTHER_LISTED) or ""):
        if r.get("Test Issue") != "Y":
            out[r["ACT Symbol"].upper()] = {"name": r["Security Name"],
                                            "exchange": OTHER_EXCH.get(r.get("Exchange", ""), r.get("Exchange", "")),
                                            "is_etf": r.get("ETF") == "Y"}
    return out


def classify_security(name, is_etf=False):
    if is_etf:
        return "ETF/ETP"
    n = (name or "").lower()
    for key, label in [("warrant", "Warrant"), (" right", "Right"), ("unit", "Unit"),
                       ("preferred", "Preferred"), ("depositary", "ADR/ADS"),
                       ("note", "Note/Debt"), ("debenture", "Note/Debt"),
                       ("common", "Common Stock"), ("ordinary", "Common Stock"),
                       ("class a", "Common Stock"), ("class b", "Common Stock"),
                       ("subordinate voting", "Common Stock"), ("shares", "Common Stock")]:
        if key in n:
            return label
    return "Other"


# --------------------------------------------------------------------------
# Alpha Vantage (prices and volumes)
# --------------------------------------------------------------------------
def _av(params, key):
    if not key:
        raise DataError("No Alpha Vantage key set, so market data is unavailable.")
    txt = http_get(AV_URL, params=dict(params, apikey=key))
    data = json.loads(txt or "{}")
    msg = data.get("Note") or data.get("Information")
    if msg:
        raise QuotaError("Alpha Vantage free limit reached (25 calls a day). Market data will return tomorrow, "
                         "or add a premium key.")
    if "Error Message" in data:
        raise DataError(f"Alpha Vantage has no data for {params.get('symbol') or params.get('keywords')}.")
    return data


def av_daily(symbol, key):
    """Last ~100 trading days: list of (date, close, volume), oldest first."""
    d = _av({"function": "TIME_SERIES_DAILY", "symbol": symbol, "outputsize": "compact"}, key)
    ts = d.get("Time Series (Daily)") or {}
    return sorted((k, float(v["4. close"]), float(v["5. volume"])) for k, v in ts.items())


def av_weekly(symbol, key):
    """Weekly bars: list of (date, high, low, close, volume), oldest first."""
    d = _av({"function": "TIME_SERIES_WEEKLY", "symbol": symbol}, key)
    ts = d.get("Weekly Time Series") or {}
    return sorted((k, float(v["2. high"]), float(v["3. low"]), float(v["4. close"]), float(v["5. volume"]))
                  for k, v in ts.items())


def av_search_tsx(company_name, key):
    """Find the Toronto (TSX, .TRT) or TSX Venture (.TRV) listing for a company name."""
    words = re.sub(r"\b(inc|corp|corporation|ltd|limited|plc|co|company)\b\.?", "", company_name, flags=re.I)
    d = _av({"function": "SYMBOL_SEARCH", "keywords": words.strip()[:40]}, key)
    for m in d.get("bestMatches", []):
        sym, region = m.get("1. symbol", ""), m.get("4. region", "")
        if region.lower().startswith("toronto") or sym.endswith((".TRT", ".TRV")):
            return {"symbol": sym, "name": m.get("2. name", ""), "currency": m.get("8. currency", "CAD"),
                    "exchange": "TSXV" if sym.endswith(".TRV") else "TSX"}
    return None


# --------------------------------------------------------------------------
# Twelve Data (free Basic plan: U.S. equities, forex; 8 calls a minute, 800 a day)
# --------------------------------------------------------------------------
def _td(path, params, key):
    if not key:
        raise DataError("No Twelve Data key set.")
    txt = http_get(f"{TD_URL}/{path}", params=dict(params, apikey=key))
    data = json.loads(txt or "{}")
    if isinstance(data, dict) and data.get("status") == "error":
        code = data.get("code")
        if code == 429:
            raise QuotaError("Twelve Data free limit reached (8 calls a minute, 800 a day).")
        if code in (401, 403):
            raise DataError(f"Twelve Data: {data.get('message', 'key not accepted or symbol not on the free plan')}")
        raise DataError(f"Twelve Data has no data for {params.get('symbol')}: {data.get('message', '')[:120]}")
    return data


def td_daily(symbol, key, bars=300):
    """Daily bars, oldest first: list of (date, high, low, close, volume). One API credit."""
    d = _td("time_series", {"symbol": symbol, "interval": "1day", "outputsize": bars}, key)
    rows = []
    for v in d.get("values") or []:
        try:
            rows.append((v["datetime"][:10], float(v["high"]), float(v["low"]), float(v["close"]),
                         float(v.get("volume") or 0)))
        except (KeyError, TypeError, ValueError):
            continue
    return sorted(rows)


def td_fx(from_ccy, to_ccy, key):
    d = _td("exchange_rate", {"symbol": f"{from_ccy}/{to_ccy}"}, key)
    if not d.get("rate"):
        raise DataError("No exchange rate returned.")
    return float(d["rate"])


def av_fx(from_ccy, to_ccy, key):
    d = _av({"function": "CURRENCY_EXCHANGE_RATE", "from_currency": from_ccy, "to_currency": to_ccy}, key)
    rate = (d.get("Realtime Currency Exchange Rate") or {}).get("5. Exchange Rate")
    if not rate:
        raise DataError("No exchange rate returned.")
    return float(rate)


# --------------------------------------------------------------------------
# Web search (Tavily): news, events, description and IPO summaries
# --------------------------------------------------------------------------
def tavily(query, key, topic="general", days=None, max_results=10, answer=True):
    """Returns {"answer": str, "results": [{title, url, content, date, source}]}."""
    if not key:
        raise DataError("No Tavily key set, so web search is off.")
    payload = {"query": query, "topic": topic, "max_results": max_results,
               "search_depth": "basic", "include_answer": "basic" if answer else False}
    if days:
        payload["days"] = days
    data = http_post(TAVILY_URL, dict(payload, api_key=key), headers={"Authorization": f"Bearer {key}"})
    results = []
    for r in data.get("results") or []:
        url = r.get("url", "")
        results.append({"title": r.get("title", ""), "url": url, "content": (r.get("content") or "")[:400],
                        "date": (r.get("published_date") or "").strip(), "source": url.split("/")[2] if "//" in url else ""})
    return {"answer": data.get("answer") or "", "results": results}


# --------------------------------------------------------------------------
# GDELT news search (free, no key; covers roughly the last 3 months)
# --------------------------------------------------------------------------
def gdelt_news(phrase, max_records=75, timespan="3m", extra=""):
    q = f'"{phrase}" {extra} sourcelang:english'.replace("  ", " ")
    txt = http_get(GDELT_URL, params={"query": q, "mode": "ArtList", "format": "json", "maxrecords": max_records,
                                      "timespan": timespan, "sort": "DateDesc"})
    try:
        arts = json.loads(txt or "{}").get("articles") or []
    except json.JSONDecodeError:          # GDELT answers bad queries with plain text
        return []
    out = []
    for a in arts:
        sd = a.get("seendate", "")
        out.append({"title": a.get("title", ""), "url": a.get("url", ""), "content": "",
                    "date": f"{sd[:4]}-{sd[4:6]}-{sd[6:8]}" if len(sd) >= 8 else "", "source": a.get("domain", "")})
    return out


# --------------------------------------------------------------------------
# Wikipedia summary (free, no key)
# --------------------------------------------------------------------------
def wikipedia_summary(company_name):
    txt = http_get(WIKI_API, params={"action": "query", "list": "search", "srsearch": f"{company_name} company",
                                     "format": "json", "srlimit": 3})
    hits = (json.loads(txt or "{}").get("query") or {}).get("search") or []
    core = clean_name(company_name).lower().split()
    for h in hits:
        title = h.get("title", "")
        if core and core[0] in title.lower():
            s = json.loads(http_get(WIKI_SUMMARY.format(title=requests.utils.quote(title.replace(" ", "_"))) or "{}"))
            extract = s.get("extract", "")
            if re.search(r"\b(company|corporation|firm|developer|maker|provider|manufacturer|biotech|pharmaceutical)\b",
                         extract, re.I):
                return {"text": extract, "url": (s.get("content_urls") or {}).get("desktop", {}).get("page", ""),
                        "title": title}
    return None


def clean_name(name):
    n = re.sub(r"[,.]", " ", name or "")
    n = re.sub(r"\b(inc|corp|corporation|ltd|limited|plc|co|company|holdings|group|sa|nv|ag|lp)\b", " ", n, flags=re.I)
    return re.sub(r"\s+", " ", n).strip()


# --------------------------------------------------------------------------
# GLEIF: LEI and mapped ISINs (free, CC0)
# --------------------------------------------------------------------------
def gleif_find_lei(legal_name, countries=("US", "CA")):
    """Best LEI match for a company name in the given countries, or None."""
    target = clean_name(legal_name).lower()
    for flt in ("filter[entity.legalName]", "filter[fulltext]"):
        txt = http_get(GLEIF_RECORDS, params={flt: legal_name if flt.endswith("legalName]") else clean_name(legal_name),
                                              "page[size]": 15})
        for rec in json.loads(txt or "{}").get("data") or []:
            ent = rec["attributes"]["entity"]
            nm = ent["legalName"]["name"]
            ctry = (ent.get("legalAddress") or {}).get("country", "")
            if clean_name(nm).lower() == target and (not countries or ctry in countries or
                                                     (ent.get("jurisdiction") or "")[:2] in countries):
                return {"lei": rec["id"], "legal_name": nm, "status": ent.get("status", ""),
                        "jurisdiction": ent.get("jurisdiction", "")}
    return None


def gleif_isins(lei, max_pages=5):
    isins = []
    for page in range(1, max_pages + 1):
        txt = http_get(f"{GLEIF_RECORDS}/{lei}/isins", params={"page[size]": 200, "page[number]": page})
        data = json.loads(txt or "{}")
        isins += [d["attributes"]["isin"] for d in data.get("data") or []]
        last = ((data.get("meta") or {}).get("pagination") or {}).get("lastPage", 1)
        if page >= last:
            break
    return sorted(set(isins))


# --------------------------------------------------------------------------
# Identifier helpers
# --------------------------------------------------------------------------
def isin_valid(isin):
    if not re.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}\d", isin or ""):
        return False
    digits = "".join(str(int(ch, 36)) for ch in isin[:-1])
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch) * (2 if i % 2 == 0 else 1)
        total += d // 10 + d % 10
    return (10 - total % 10) % 10 == int(isin[-1])


def cusip_from_isin(isin):
    """U.S. and Canadian ISINs embed the 9-character CUSIP (or CINS)."""
    return isin[2:11] if isin and isin[:2] in ("US", "CA") else ""


def cusip_kind(cusip):
    """Issue code (characters 7-8): two digits usually mean equity; letters usually mean debt."""
    code = (cusip or "")[6:8]
    return "Equity" if code.isdigit() else ("Debt / other" if code else "")


def isin_from_cusip(cusip, country="US"):
    base = country + cusip
    digits = "".join(str(int(ch, 36)) for ch in base)
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch) * (2 if i % 2 == 0 else 1)
        total += d // 10 + d % 10
    return base + str((10 - total % 10) % 10)


# --------------------------------------------------------------------------
# OpenFIGI: FIGIs, exchange tickers and security types (free; optional key)
# --------------------------------------------------------------------------
COMPOSITE_EXCH = {"US": "United States (composite)", "CN": "Canada (composite)"}


def openfigi_map(jobs, key=""):
    """jobs: list of {"idType", "idValue"}; returns list (same order) of lists of FIGI rows."""
    headers = {"Content-Type": "application/json"}
    if key:
        headers["X-OPENFIGI-APIKEY"] = key
    size = 100 if key else 5
    out = []
    for i in range(0, len(jobs), size):
        resp = http_post(OPENFIGI_URL, jobs[i:i + size], headers=headers)
        for r in resp:
            out.append(r.get("data") or [])
        if not key and i + size < len(jobs):
            time.sleep(2.5)                  # stay under 25 requests a minute without a key
    return out
