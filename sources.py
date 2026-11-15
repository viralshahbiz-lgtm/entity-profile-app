"""
Data sources for the entity profile page. Public data only.

- SEC EDGAR (free, no key; a contact email is required in the User-Agent)
    company tickers, submissions (filing history), company facts (XBRL),
    filing documents (annual report text, cover-page flags, Schedule 13D/13G)
- Nasdaq Trader symbol directory (free) for security names on U.S. exchanges
- Alpha Vantage (free key) for prices and volumes, U.S. and TSX
- Finnhub (free key, optional) for company news

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
FINNHUB_NEWS = "https://finnhub.io/api/v1/company-news"

OTHER_EXCH = {"A": "NYSE American", "N": "NYSE", "P": "NYSE Arca", "Z": "Cboe BZX", "V": "IEX"}


class DataError(Exception):
    """A source could not be reached or returned nothing usable."""


class QuotaError(DataError):
    """A free-tier API limit was hit."""


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------
_last_sec_call = [0.0]


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


def av_fx(from_ccy, to_ccy, key):
    d = _av({"function": "CURRENCY_EXCHANGE_RATE", "from_currency": from_ccy, "to_currency": to_ccy}, key)
    rate = (d.get("Realtime Currency Exchange Rate") or {}).get("5. Exchange Rate")
    if not rate:
        raise DataError("No exchange rate returned.")
    return float(rate)


# --------------------------------------------------------------------------
# Finnhub (company news, optional)
# --------------------------------------------------------------------------
def finnhub_news(symbol, key, days=180):
    if not key:
        return []
    to = date.today()
    frm = to - timedelta(days=days)
    txt = http_get(FINNHUB_NEWS, params={"symbol": symbol, "from": frm.isoformat(),
                                         "to": to.isoformat(), "token": key})
    items = json.loads(txt or "[]")
    if isinstance(items, dict):        # error object
        raise DataError(items.get("error", "Finnhub returned an error."))
    out = []
    for it in items:
        ts = it.get("datetime")
        out.append({"date": date.fromtimestamp(ts).isoformat() if ts else "",
                    "headline": it.get("headline", ""), "source": it.get("source", ""),
                    "url": it.get("url", ""), "summary": it.get("summary", "")})
    out.sort(key=lambda x: x["date"], reverse=True)
    return out
