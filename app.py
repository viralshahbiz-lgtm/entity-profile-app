"""
Entity Profile: U.S. and Canadian Technology and Biotech companies.

Run locally:   streamlit run app.py
Settings (Streamlit "Secrets" or environment variables):
  SEC_CONTACT_EMAIL   required; the SEC asks for a contact email
  ALPHAVANTAGE_KEY    free key for prices and volumes (market data, ADTV)
  FINNHUB_KEY         free key for news headlines (optional)
"""
import os

import pandas as pd
import streamlit as st

import sources as src
from entity_profile import build_profile
from pdf_report import make_pdf

st.set_page_config(page_title="Entity Profile", page_icon="📇", layout="wide")


def setting(name):
    try:
        if name in st.secrets:
            return str(st.secrets[name])
    except Exception:
        pass
    return os.environ.get(name, "")


SETTINGS = {k: setting(k) for k in ("SEC_CONTACT_EMAIL", "ALPHAVANTAGE_KEY", "FINNHUB_KEY")}


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


# ---------------------------------------------------------------- formatting
def money(v, ccy="", dec=2):
    if v is None:
        return "n/a"
    for div, suf in ((1e12, "T"), (1e9, "B"), (1e6, "M")):
        if abs(v) >= div:
            return f"{ccy} {v / div:,.{dec}f}{suf}".strip()
    return f"{ccy} {v:,.{dec}f}".strip()


STATUS_ICON = {"ok": "🟢", "warn": "🟠", "info": "🔵", "na": "⚪"}


# ---------------------------------------------------------------- sidebar
st.sidebar.title("Entity Profile")
st.sidebar.caption("U.S. and Canadian Technology and Biotech companies · public data only")

if not SETTINGS["SEC_CONTACT_EMAIL"]:
    st.error("Setup needed: add SEC_CONTACT_EMAIL in the app's Secrets (README, step 6).")
    st.stop()

uni = load_universe()
mode = st.sidebar.radio("Find a company", ["Browse Tech & Biotech list", "Look up any ticker"],
                        index=0 if len(uni) else 1)
cik = None
if mode == "Browse Tech & Biotech list":
    if not len(uni):
        st.sidebar.warning("The company list has not been built yet (README, step 5). Use ticker lookup for now.")
    else:
        sectors = st.sidebar.multiselect("Sector", ["Technology", "Biotech"], default=["Technology", "Biotech"])
        countries = st.sidebar.multiselect("Headquarters", ["United States", "Canada"], default=["United States", "Canada"])
        q = st.sidebar.text_input("Search name or ticker").strip().lower()
        f = uni[uni["sector"].isin(sectors) & uni["hq_country"].isin(countries)]
        if q:
            f = f[f["name"].str.lower().str.contains(q, regex=False) | f["tickers"].str.lower().str.contains(q, regex=False)]
        st.sidebar.caption(f"{len(f):,} of {len(uni):,} companies")
        labels = [f"{r.name} ({r.tickers.split()[0]})" for r in f.itertuples()]
        pick = st.sidebar.selectbox("Company", labels, index=None, placeholder="Choose a company")
        if pick:
            cik = f.iloc[labels.index(pick)]["cik"]
else:
    t = st.sidebar.text_input("Ticker (U.S. listing)", placeholder="e.g. SHOP or MRNA").strip().upper()
    if t:
        try:
            match = next((x for x in load_sec_tickers(SETTINGS["SEC_CONTACT_EMAIL"])
                          if x["ticker"] == t.replace(".", "-")), None)
        except src.DataError as e:
            match = None
            st.sidebar.error(str(e))
        if match:
            cik = match["cik"]
            st.sidebar.success(f"{match['name']} · CIK {cik}")
        else:
            st.sidebar.warning("Not found among SEC-registered tickers.")

go = st.sidebar.button("Show profile", type="primary", disabled=cik is None, use_container_width=True)
st.sidebar.divider()
st.sidebar.caption("Market data: " + ("on" if SETTINGS["ALPHAVANTAGE_KEY"] else "off (no Alpha Vantage key)") +
                   " · News: " + ("on" if SETTINGS["FINNHUB_KEY"] else "off (no Finnhub key)"))
st.sidebar.caption("Profiles are cached for 6 hours to save free API calls.")

if go and cik:
    status = st.status("Gathering public data…", expanded=False)
    try:
        st.session_state["profile"] = cached_profile(cik, tuple(sorted(SETTINGS.items())))
        status.update(label="Done", state="complete")
    except src.DataError as e:
        status.update(label="Could not build the profile", state="error")
        st.error(str(e))

p = st.session_state.get("profile")
if not p:
    st.title("Entity Profile")
    st.write("Choose a company in the sidebar and press **Show profile**. Each profile includes market data, "
             "the business description, equity securities, 5%+ holders, corporate events and news from the "
             "last 180 days, and a Regulation M and research safe harbor screen. Export any profile as a "
             "one- to two-page PDF.")
    st.stop()

# ---------------------------------------------------------------- profile
c, m, r = p["company"], p["market"], p["regm"]
pv = m.get("primary") or {}
head, btn = st.columns([4, 1])
with head:
    st.title(c["name"])
    commons = ", ".join(f"{s['ticker']} ({s['exchange']})" for s in p["securities"] if s["type"] == "Common Stock")
    st.caption(f"{commons} · {c['sector']} · {c['industry']} · CIK {c['cik']} · "
               f"HQ {', '.join(x for x in (c['hq_city'], c['hq_country']) if x)} · as of {p['as_of']}")
with btn:
    st.download_button("⬇ Export PDF summary", data=cached_pdf(c["cik"], p["as_of"], p),
                       file_name=f"{(commons.split(' ')[0] or c['cik'])}_entity_profile.pdf",
                       mime="application/pdf", use_container_width=True, type="primary")

if p["warnings"]:
    with st.expander(f"Data notes ({len(p['warnings'])})"):
        for w in p["warnings"]:
            st.write("• " + w)

# Market data
st.subheader("Market data")
ccy = pv.get("currency", "")
cols = st.columns(4)
cols[0].metric("Price", money(pv.get("price"), ccy) if pv else "n/a",
               f"{pv['change_1m_pct']:+.1f}% 1M" if pv.get("change_1m_pct") is not None else None,
               help=f"{pv.get('exchange', '')} close {pv.get('price_date', '')}")
cols[1].metric("Market cap", money(m.get("market_cap"), m.get("market_cap_ccy", "")),
               help=f"Shares outstanding {m.get('shares_out', 0):,.0f} as of {m.get('shares_out_date', '')}" if m.get("shares_out") else None)
cols[2].metric("Enterprise value", money(m.get("enterprise_value"), ccy),
               help=f"Cash {money(m.get('cash'), ccy)}, debt {money(m.get('debt'), ccy)} as of {m.get('bs_date', '')}" if m.get("enterprise_value") is not None else None)
cols[3].metric("52-week range", f"{money(pv.get('low_52w'))} – {money(pv.get('high_52w'))}" if pv.get("high_52w") else "n/a")
cols = st.columns(4)
cols[0].metric("Public float (reported)", money(m.get("public_float_usd"), "US$"),
               help=f"Annual report cover, as of {m.get('public_float_date', '')}")
cols[1].metric("Avg daily volume (60d)", f"{m['adv_shares_total']:,.0f}" if m.get("adv_shares_total") else "n/a")
cols[2].metric("ADTV worldwide (60d)", money(m.get("adtv_usd"), "US$"), help="Average daily value traded across venues, in USD")
cols[3].metric("Venues", ", ".join(v["exchange"] for v in m.get("venues", [])) or "n/a")

# Business description
st.subheader("Business description")
st.write(p["description"] or "_Not available. See the latest annual report._")
if p["description_source"]:
    st.caption(f"Source: {p['description_source']}")

left, right = st.columns([3, 2])
with left:
    st.subheader(f"Equity securities ({len(p['securities'])})")
    st.dataframe(pd.DataFrame([{k: s[k] for k in ("ticker", "name", "type", "exchange", "country")} for s in p["securities"]]),
                 hide_index=True, use_container_width=True)
with right:
    st.subheader("Significant holders (5%+)")
    if p["holders"]:
        st.dataframe(pd.DataFrame([{"Holder": h["name"], "% of class": h["pct"], "Form": h["form"], "Filed": h["date"]}
                                   for h in p["holders"]]), hide_index=True, use_container_width=True,
                     column_config={"% of class": st.column_config.ProgressColumn(format="%.1f%%", min_value=0,
                                                                                  max_value=max(10, max((h["pct"] or 0) for h in p["holders"])))})
    else:
        st.caption("No Schedule 13D/13G filings in the last three years.")

# Events and news
st.subheader("Corporate events and news (last 180 days)")
tab_ev, tab_news = st.tabs([f"Events ({len(p['events'])})", f"News ({len(p['news'])})"])
with tab_ev:
    if p["events"]:
        cats = sorted({e["category"] for e in p["events"]})
        pick = st.multiselect("Category", cats, default=cats, key="evcats")
        ev = [e for e in p["events"] if e["category"] in pick]
        st.dataframe(pd.DataFrame([{"Date": e["date"], "Status": e["status"], "Category": e["category"],
                                    "Event": e["title"], "Why it matters": e["why"], "Filing": e["url"]} for e in ev]),
                     hide_index=True, use_container_width=True,
                     column_config={"Filing": st.column_config.LinkColumn(display_text="open")})
    else:
        st.caption("No relevant filings in the last 180 days.")
with tab_news:
    if p["news"]:
        for n in p["news"]:
            st.markdown(f"**{n['date']}** · [{n['headline']}]({n['url']}) · _{n['source']}_")
    else:
        st.caption("No news loaded. Add a FINNHUB_KEY to show headlines; filed press releases appear under Events.")

# Reg M
st.subheader("Regulation M and research safe harbors")
st.info(r["summary"])
st.caption("Preliminary automated screen from public data. Not legal advice: confirm with Legal and Compliance.")
a, b = st.columns([2, 3])
with a:
    st.markdown("**Inputs**")
    st.dataframe(pd.DataFrame(r["inputs"], columns=["Data point", "Value", "Source"]), hide_index=True, use_container_width=True)
with b:
    st.markdown("**Trading restrictions**")
    st.dataframe(pd.DataFrame([{"": STATUS_ICON[t["status"]], "Rule": t["rule"], "Result": t["result"],
                                "Test": t["test"], "Applies to": t["who"]} for t in r["tests"]]),
                 hide_index=True, use_container_width=True)
st.markdown("**Research safe harbors**")
st.dataframe(pd.DataFrame([{"Safe harbor": h["name"], "Status": h["status"], "Basis": h["basis"],
                            "Firm checks": h["firm_checks"]} for h in r["harbors"]]),
             hide_index=True, use_container_width=True)
for cav in r["caveats"][1:]:
    st.caption(cav)
st.divider()
st.caption("Sources: " + ", ".join(p["sources"]) + ". Public data only; not investment or legal advice.")
