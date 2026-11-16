"""
Entity Profile: U.S. and Canadian Technology and Biotech companies (public data only).

Run locally:   streamlit run app.py
Settings (Streamlit "Secrets" or environment variables):
  SEC_CONTACT_EMAIL   required; the SEC asks for a contact email
  TAVILY_KEY          free key for web search (description summary, IPO summary, news)
  TWELVEDATA_KEY      free key for prior-close prices on U.S. listings (800 calls a day)
  ALPHAVANTAGE_KEY    free key for TSX prices and as a U.S. backup (25 calls a day)
  OPENFIGI_KEY        optional; raises OpenFIGI rate limits
"""
import os

import pandas as pd
import streamlit as st

import sources as src
from entity_profile import build_profile
from pdf_report import make_pdf

st.set_page_config(page_title="Entity Profile", page_icon="📇", layout="wide")
KEYS = ("SEC_CONTACT_EMAIL", "TAVILY_KEY", "TWELVEDATA_KEY", "ALPHAVANTAGE_KEY", "OPENFIGI_KEY")


def setting(name):
    try:
        if name in st.secrets:
            return str(st.secrets[name])
    except Exception:
        pass
    return os.environ.get(name, "")


SETTINGS = {k: setting(k) for k in KEYS}


# ---------------------------------------------------------------- cached data
@st.cache_data(ttl=24 * 3600, show_spinner=False)
def load_sec_tickers(email):
    return src.sec_tickers(email)


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def load_symbol_directory():
    try:
        return src.us_symbol_directory()
    except src.DataError:
        return {}


@st.cache_data(ttl=7 * 24 * 3600, show_spinner=False)
def load_universe():
    path = os.path.join(os.path.dirname(__file__), "data", "universe.csv")
    if os.path.exists(path):
        return pd.read_csv(path, dtype=str).fillna("")
    return pd.DataFrame(columns=["cik", "name", "tickers", "exchange", "sector", "industry", "hq_city", "hq_country"])


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def cached_profile(cik, settings_items):
    settings = dict(settings_items)
    return build_profile(cik, settings, load_sec_tickers(settings["SEC_CONTACT_EMAIL"]), load_symbol_directory())


@st.cache_data(show_spinner=False)
def cached_pdf(cik, as_of, _profile):
    return make_pdf(_profile)


def money(v, ccy="", dec=2):
    if v is None:
        return "n/a"
    for div, suf in ((1e12, "T"), (1e9, "B"), (1e6, "M")):
        if abs(v) >= div:
            return f"{ccy} {v / div:,.{dec}f}{suf}".strip()
    return f"{ccy} {v:,.{dec}f}".strip()


def links_md(links):
    return " · ".join(f"[{(t or u)[:60]}]({u})" for t, u in links if u)


# ---------------------------------------------------------------- setup check
if not SETTINGS["SEC_CONTACT_EMAIL"]:
    st.error("Setup needed: add SEC_CONTACT_EMAIL in the app's Secrets (README, step 6).")
    st.stop()

# ---------------------------------------------------------------- sidebar filters
st.sidebar.title("Entity Profile")
st.sidebar.caption("U.S. and Canadian Technology and Biotech companies · public data only")
uni = load_universe()
sectors = st.sidebar.multiselect("Sector", ["Technology", "Biotech"], default=["Technology", "Biotech"])
countries = st.sidebar.multiselect("Headquarters", ["United States", "Canada"], default=["United States", "Canada"])
all_listed = st.sidebar.toggle("Include every SEC-listed company", value=not len(uni),
                               help="Search all companies with a U.S. listing, not only Technology and Biotech.")
st.sidebar.divider()
st.sidebar.caption(
    "Web search: " + ("on" if SETTINGS["TAVILY_KEY"] else "off (no Tavily key; news falls back to GDELT)") +
    "  \nU.S. prices: " + ("Twelve Data" if SETTINGS["TWELVEDATA_KEY"] else ("Alpha Vantage" if SETTINGS["ALPHAVANTAGE_KEY"] else "off")) +
    "  \nTSX prices: " + ("Alpha Vantage" if SETTINGS["ALPHAVANTAGE_KEY"] else "off (needs Alpha Vantage key)") +
    "  \nProfiles are cached for 6 hours to save free API calls.")

# ---------------------------------------------------------------- type-ahead company search
options = {}
f = uni[uni["sector"].isin(sectors) & uni["hq_country"].isin(countries)] if len(uni) else uni
for r in f.itertuples():
    options[f"{r.name} — {r.tickers.split()[0] if r.tickers else ''} · {r.sector} · {r.hq_country}"] = r.cik
if all_listed:
    try:
        seen = set(options.values())
        for t in load_sec_tickers(SETTINGS["SEC_CONTACT_EMAIL"]):
            if t["exchange"] in ("Nasdaq", "NYSE", "CBOE") and t["cik"] not in seen:
                seen.add(t["cik"])
                options[f"{t['name']} — {t['ticker']} · {t['exchange']}"] = t["cik"]
    except src.DataError as e:
        st.sidebar.error(str(e))

st.title("Entity Profile")
pick = st.selectbox("Company", sorted(options, key=str.lower), index=None,
                    placeholder=f"Start typing a company name or ticker ({len(options):,} companies)…",
                    label_visibility="collapsed")
if pick:
    cik = options[pick]
    if st.session_state.get("cik") != cik:
        with st.status("Gathering public data…", expanded=False) as status:
            try:
                st.session_state["profile"] = cached_profile(cik, tuple(sorted(SETTINGS.items())))
                st.session_state["cik"] = cik
                status.update(label="Done", state="complete")
            except src.DataError as e:
                status.update(label="Could not build the profile", state="error")
                st.error(str(e))

p = st.session_state.get("profile")
if not p:
    st.write("Type a company name or ticker above. Matches appear as you type. Each profile shows market data, "
             "a business description summary, how and when the company went public, security identifiers, "
             "5%+ holders, corporate events and news from the last 90 days, and a research safe harbor summary. "
             "Any profile can be exported as a one- to two-page PDF.")
    if not len(uni):
        st.info("The Technology and Biotech list has not been built yet (README, step 5). "
                "Until then, every SEC-listed company is searchable.")
    st.stop()

# ---------------------------------------------------------------- profile
c, m, r, ids, lst = p["company"], p["market"], p["regm"], p["identifiers"], p["listing"]
pv = m.get("primary") or {}


def range_bar(v):
    """Visual: where the prior close sits inside the 52-week range."""
    lo, hi, px = v.get("low_52w"), v.get("high_52w"), v.get("price")
    if lo is None or hi is None or px is None or hi <= lo:
        return ""
    pos = max(0.0, min(1.0, (px - lo) / (hi - lo))) * 100
    off_hi, off_lo = (px / hi - 1) * 100, (px / lo - 1) * 100
    ccy = v.get("currency", "")
    return f"""
<div style="margin:6px 0 14px 0;font-family:sans-serif">
  <div style="display:flex;justify-content:space-between;font-size:0.8em;color:#5d6878">
    <span>{v.get('exchange', '')} · 52-week range</span><span>{pos:.0f}% of range · {off_hi:+.1f}% vs high · {off_lo:+.1f}% vs low</span>
  </div>
  <div style="position:relative;height:14px;margin:6px 0 4px 0;border-radius:7px;
              background:linear-gradient(90deg,#c0392b 0%,#e6b33c 50%,#1d7a4c 100%);opacity:0.85"></div>
  <div style="position:relative;height:0">
    <div style="position:absolute;left:calc({pos:.1f}% - 9px);top:-22px;width:18px;height:18px;border-radius:50%;
                background:#16202e;border:3px solid white;box-shadow:0 0 3px rgba(0,0,0,.5)"></div>
  </div>
  <div style="display:flex;justify-content:space-between;font-size:0.85em;margin-top:4px">
    <span>Low <b>{ccy} {lo:,.2f}</b> <span style="color:#5d6878">(wk {v.get('low_52w_week', '')})</span></span>
    <span>Prior close <b>{ccy} {px:,.2f}</b></span>
    <span>High <b>{ccy} {hi:,.2f}</b> <span style="color:#5d6878">(wk {v.get('high_52w_week', '')})</span></span>
  </div>
</div>"""


head, btn = st.columns([4, 1])
with head:
    st.header(c["name"])
    commons = ", ".join(f"{s['ticker']} ({s['exchange']})" for s in p["securities"] if s["type"] == "Common Stock")
    st.caption(f"{commons} · {c['sector']} · {c['industry']} · HQ {', '.join(x for x in (c['hq_city'], c['hq_country']) if x)} "
               f"· Incorporated {c['incorporation']} · as of {p['as_of']}")
with btn:
    st.download_button("⬇ Export PDF summary", data=cached_pdf(c["cik"], p["as_of"], p),
                       file_name=f"{(commons.split(' ')[0] or c['cik'])}_entity_profile.pdf",
                       mime="application/pdf", use_container_width=True, type="primary")
if p["warnings"]:
    with st.expander(f"Data notes ({len(p['warnings'])})"):
        for w in p["warnings"]:
            st.write("• " + w)

# 1. Company description
st.subheader("Company description")
d = p["description"]
st.write(d["text"] or "_Not available._")
if d["source"]:
    st.caption(f"Source: {d['source']}" + (f" · {links_md(d['links'][:2])}" if d["links"] else ""))

# 2. Market data
st.subheader("Market data")
ccy = pv.get("currency", "")
cols = st.columns(4)
cols[0].metric(f"Prior close{' (' + pv['price_date'] + ')' if pv.get('price_date') else ''}",
               money(pv.get("price"), ccy) if pv else "n/a",
               f"{pv['change_1d_pct']:+.2f}% on the day" if pv.get("change_1d_pct") is not None else None,
               help=f"{pv.get('exchange', '')} close from {pv.get('provider', '')}. 1-month change: "
                    + (f"{pv['change_1m_pct']:+.1f}%" if pv.get("change_1m_pct") is not None else "n/a"))
cols[1].metric("Market cap", money(m.get("market_cap"), m.get("market_cap_ccy", "")))
cols[2].metric("Enterprise value", money(m.get("enterprise_value"), ccy),
               help=f"Cash {money(m.get('cash'), ccy)}, debt {money(m.get('debt'), ccy)}" if m.get("enterprise_value") is not None else None)
cols[3].metric("1-month change", f"{pv['change_1m_pct']:+.1f}%" if pv.get("change_1m_pct") is not None else "n/a")
for v in m.get("venues", []):
    bar = range_bar(v)
    if bar:
        st.markdown(bar, unsafe_allow_html=True)
cols = st.columns(4)
cols[0].metric("Public float (reported)", money(m.get("public_float_usd"), "US$"),
               help=f"Annual report cover, as of {m.get('public_float_date', '')}")
cols[1].metric("Shares outstanding", f"{m['shares_out']:,.0f}" if m.get("shares_out") else "n/a")
cols[2].metric("Avg daily volume (60d)", f"{m['adv_shares_total']:,.0f}" if m.get("adv_shares_total") else "n/a")
cols[3].metric("ADTV worldwide (60d)", money(m.get("adtv_usd"), "US$"))

# 3. Equity securities and identifiers
st.subheader("Equity securities and identifiers")
e = ids["entity"]
st.write(f"**CIK** {e['CIK']} · **LEI** {e['LEI'] or 'not found'}" + (f" ({e['LEI status']})" if e.get("LEI status") else "")
         + (f" · **EIN** {e['EIN']}" if e.get("EIN") else ""))
if ids["securities"]:
    st.dataframe(pd.DataFrame([{"Ticker": x["ticker"], "Exchange": x["exchange"], "Type": x["type"], "ISIN": x["isin"],
                                "CUSIP": x["cusip"], "FIGI": x["figi"], "Composite FIGI": x["composite_figi"],
                                "Share class FIGI": x["share_class_figi"], "SEDOL": x["sedol"]} for x in ids["securities"]]),
                 hide_index=True, use_container_width=True)
for n in ids["notes"]:
    st.caption(n)

# 4. Fixed income
dbt = p.get("debt") or {"bonds": []}
st.subheader(f"Fixed income securities ({len(dbt['bonds'])} outstanding)")
td = dbt.get("total_debt")
st.caption((f"Total debt on the balance sheet: {money(td['value'], td['unit'])} as of {td['date']} (SEC XBRL). " if td else "")
           + f"Searched {dbt.get('documents_read', 0)} recent offering documents, the issuer's GLEIF-mapped ISINs and the "
             "annual report cover." + (f" {dbt['matured_excluded']} matured issues hidden." if dbt.get("matured_excluded") else ""))
if dbt["bonds"]:
    st.dataframe(pd.DataFrame([{"Security": b["description"], "Coupon": (b["coupon"] + "%") if b["coupon"] and b["coupon"] != "Floating" else b["coupon"],
                                "Maturity": b["maturity"], "Amount": money(b["principal"], "US$") if b["principal"] else "",
                                "CUSIP": b["cusip"], "ISIN": b["isin"], "FIGI": b["figi"], "Exchange-listed": b["listed"],
                                "Source": ", ".join(b["sources"]), "Document": b["link"]} for b in dbt["bonds"]]),
                 hide_index=True, use_container_width=True,
                 column_config={"Document": st.column_config.LinkColumn(display_text="open")})
    st.caption("Corporate bond trade prices are reported to FINRA TRACE; search by CUSIP at finra.org (Fixed Income Data).")
else:
    st.caption("No publicly issued notes or bonds found. Bank loans and private placements are not public securities.")

# 5. How and when it went public
st.subheader("How and when it went public")
if lst.get("summary"):
    st.markdown(f"**{lst['summary']}**" + (f"  [source]({lst['link']})" if lst.get("link") else ""))
else:
    st.caption("Not available.")

# 6. Holders
st.subheader("Significant holders (5%+)")
if p["holders"]:
    st.dataframe(pd.DataFrame([{"Holder": h["name"], "% of class": h["pct"], "Form": h["form"], "Filed": h["date"]}
                               for h in p["holders"]]), hide_index=True, use_container_width=True,
                 column_config={"% of class": st.column_config.ProgressColumn(
                     format="%.1f%%", min_value=0, max_value=max(10, max((h["pct"] or 0) for h in p["holders"])))})
else:
    st.caption("No Schedule 13D/13G filings in the last three years.")

# 7. News and events: M&A and strategic transactions first
st.subheader("News and corporate events (last 90 days)")
mna = [n for n in p["news"] if n.get("mna")]
if mna:
    with st.container(border=True):
        st.markdown("#### 🔶 M&A and strategic transactions")
        for n in mna:
            tag = "🟠 **RUMORED** · " if n.get("rumored") else "🔴 **REPORTED** · "
            st.markdown(f"{tag}**{n['date'] or 'undated'}** · [{n['title']}]({n['url']}) · _{n['source']}_")
else:
    st.caption("No M&A or strategic-transaction news found in the last 90 days.")
tab_news, tab_ev = st.tabs([f"All news ({len(p['news'])})", f"Corporate events ({len(p['events'])})"])
with tab_news:
    for n in p["news"]:
        badge = ("🟠 Rumored M&A · " if n.get("rumored") else "🔴 M&A · ") if n.get("mna") else ""
        st.markdown(f"{badge}**{n['date'] or 'undated'}** · [{n['title']}]({n['url']}) · _{n['source']}_")
    if not p["news"]:
        st.caption("No news found in the last 90 days.")
with tab_ev:
    if p["events"]:
        cats = sorted({x["category"] for x in p["events"]})
        chosen = st.multiselect("Category", cats, default=cats, key="evcats")
        st.dataframe(pd.DataFrame([{"Date": x["date"], "Category": x["category"], "Event": x["title"],
                                    "Status": x["status"], "Source": x["form"], "Link": x["url"]}
                                   for x in p["events"] if x["category"] in chosen]),
                     hide_index=True, use_container_width=True,
                     column_config={"Link": st.column_config.LinkColumn(display_text="open")})
        st.caption("M&A first. Filed = SEC filing · Reported / Rumored = web news · Estimated = worked out from filing history.")
    else:
        st.caption("No events found in the last 90 days.")

# 8. Safe harbor summary
st.subheader("Research safe harbor summary")
st.info(r["summary"])
if r.get("facts"):
    fc = st.columns(len(r["facts"]))
    for col, (lab, val) in zip(fc, r["facts"]):
        col.metric(lab, val)
if r.get("harbors"):
    st.dataframe(pd.DataFrame(r["harbors"], columns=["Safe harbor", "Status", "Basis"]), hide_index=True, use_container_width=True)

# 9. Board of directors
bd = p.get("board") or {"directors": []}
st.subheader(f"Board of directors ({len(bd['directors'])})")
if bd["directors"]:
    st.caption(bd.get("note", "") + (f" Biographies from the {bd['proxy']}." if bd.get("proxy") else ""))
    for x in bd["directors"]:
        others = x["other_public_boards"] or ([x["proxy_other_boards"]] if x.get("proxy_other_boards") else [])
        with st.container(border=True):
            st.markdown(f"**{x['name']}** · {x['role']}  ·  [SEC filings]({x['edgar_url']}) · [Web profile search]({x['web_url']})")
            if x["bio"]:
                st.write(x["bio"])
            st.caption("Other public company affiliations: " + ("; ".join(others) if others else "none found in SEC filings"))
else:
    st.caption(bd.get("note") or "Board information not available.")
st.divider()
st.caption("Sources: " + ", ".join(p["sources"]) + ". Public data only; not investment or legal advice.")
