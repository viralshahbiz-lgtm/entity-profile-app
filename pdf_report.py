"""
One- to two-page PDF summary of a profile (Letter size).

make_pdf(profile) -> bytes. Long sections are trimmed automatically so the
summary never runs past two pages.
"""
import io
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

INK = colors.HexColor("#16202e")
MUTED = colors.HexColor("#5d6878")
LINE = colors.HexColor("#d9dee5")
SOFT = colors.HexColor("#f2f4f7")
ACCENT = colors.HexColor("#1f4fa8")
STATUS = {"ok": colors.HexColor("#1d7a4c"), "warn": colors.HexColor("#a5640b"),
          "info": ACCENT, "na": MUTED}

S = {
    "title": ParagraphStyle("t", fontName="Helvetica-Bold", fontSize=16, leading=19, textColor=INK),
    "sub": ParagraphStyle("s", fontName="Helvetica", fontSize=7.8, leading=10, textColor=MUTED),
    "h": ParagraphStyle("h", fontName="Helvetica-Bold", fontSize=8.2, leading=10, textColor=ACCENT,
                        spaceBefore=7, spaceAfter=3),
    "body": ParagraphStyle("b", fontName="Helvetica", fontSize=7.6, leading=9.6, textColor=INK),
    "cell": ParagraphStyle("c", fontName="Helvetica", fontSize=7, leading=8.6, textColor=INK),
    "cellb": ParagraphStyle("cb", fontName="Helvetica-Bold", fontSize=7, leading=8.6, textColor=INK),
    "cellm": ParagraphStyle("cm", fontName="Helvetica", fontSize=6.6, leading=8, textColor=MUTED),
    "lab": ParagraphStyle("l", fontName="Helvetica", fontSize=6.5, leading=8, textColor=MUTED),
    "val": ParagraphStyle("v", fontName="Helvetica-Bold", fontSize=8.6, leading=10.5, textColor=INK),
    "foot": ParagraphStyle("f", fontName="Helvetica", fontSize=6.2, leading=7.6, textColor=MUTED),
}
W = letter[0] - 1.0 * inch


def P(text, style="cell"):
    return Paragraph(escape(str(text if text is not None else "")), S[style])


def num(v, dec=2):
    if v is None:
        return "n/a"
    for div, suf in ((1e12, "T"), (1e9, "B"), (1e6, "M")):
        if abs(v) >= div:
            return f"{v / div:,.{dec}f}{suf}"
    return f"{v:,.{dec}f}" if abs(v) < 1000 else f"{v:,.0f}"


def grid(rows, widths, header=True, zebra=False):
    t = Table(rows, colWidths=widths, repeatRows=1 if header else 0)
    st = [("VALIGN", (0, 0), (-1, -1), "TOP"),
          ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
          ("TOPPADDING", (0, 0), (-1, -1), 1.6), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.6),
          ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE)]
    if header:
        st += [("LINEBELOW", (0, 0), (-1, 0), 0.8, INK)]
    t.setStyle(TableStyle(st))
    return t


def market_block(p):
    m = p["market"]
    pv = m.get("primary") or {}
    ccy = pv.get("currency", "")
    rng = (f"{num(pv.get('low_52w'))} – {num(pv.get('high_52w'))}" if pv.get("high_52w") else "n/a")
    cells = [
        ("Price", f"{ccy} {num(pv.get('price'))}" if pv else "n/a", f"{pv.get('exchange', '')} {pv.get('price_date', '')}"),
        ("1-month change", f"{pv['change_1m_pct']:+.1f}%" if pv.get("change_1m_pct") is not None else "n/a", ""),
        ("52-week range", rng, f"high wk {pv.get('high_52w_week', '')}" if pv else ""),
        ("Market cap", f"{m.get('market_cap_ccy', '')} {num(m.get('market_cap'))}" if m.get("market_cap") else "n/a",
         f"shares {num(m.get('shares_out'))} ({m.get('shares_out_date', '')})" if m.get("shares_out") else ""),
        ("Enterprise value", f"{ccy} {num(m.get('enterprise_value'))}" if m.get("enterprise_value") is not None else "n/a",
         f"cash {num(m.get('cash'))}, debt {num(m.get('debt'))}" if m.get("enterprise_value") is not None else ""),
        ("Public float", f"US$ {num(m.get('public_float_usd'))}" if m.get("public_float_usd") else "n/a",
         f"as of {m.get('public_float_date', '')}" if m.get("public_float_usd") else ""),
        ("Avg daily volume", num(m.get("adv_shares_total"), 0) if m.get("adv_shares_total") else "n/a", "60 days, all venues"),
        ("ADTV (worldwide)", f"US$ {num(m.get('adtv_usd'))}" if m.get("adtv_usd") is not None else "n/a", "60-day average value"),
    ]
    rows, row = [], []
    for lab, val, sub in cells:
        row.append([P(lab, "lab"), P(val, "val"), P(sub, "cellm")])
        if len(row) == 4:
            rows.append(row)
            row = []
    if row:
        rows.append(row + [""] * (4 - len(row)))
    t = Table(rows, colWidths=[W / 4] * 4)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), SOFT), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("BOX", (0, 0), (-1, -1), 0.4, LINE), ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.white),
                           ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    return t


def build_story(p, lim):
    c, r, ids, lst = p["company"], p["regm"], p["identifiers"], p["listing"]
    tickers = ", ".join(f"{s['ticker']} ({s['exchange']})" for s in p["securities"] if s["type"] == "Common Stock") or "n/a"
    story = [
        Paragraph(escape(c["name"]), S["title"]),
        Paragraph(escape(f"{tickers}  ·  {c['sector']} · {c['industry']}  ·  "
                         f"HQ {', '.join(x for x in (c['hq_city'], c['hq_country']) if x)}  ·  "
                         f"Incorporated {c['incorporation']}  ·  {c['filer_category'] or 'filer status n/a'}"), S["sub"]),
        Paragraph(escape(f"Entity profile summary as of {p['as_of']} · public sources: {', '.join(p['sources'])}"), S["sub"]),
        Spacer(1, 4),
        Paragraph("MARKET DATA", S["h"]), market_block(p),
    ]
    d = p["description"]
    story += [Paragraph("BUSINESS DESCRIPTION", S["h"]),
              Paragraph(escape(_trim(d["text"] or "Not available.", lim["desc"])) +
                        (f" <font color='#5d6878'>[{escape(d['source'])}]</font>" if d["source"] else ""), S["body"])]

    # How and when it went public
    ipo_txt = f"<b>{escape(lst['method'])}</b>" + (f" · <b>{escape(lst['date'])}</b>" if lst["date"] else "")
    ev = "; ".join(f"{f} {dt}" for f, dt, _ in lst["evidence"][:4])
    if ev:
        ipo_txt += f" <font color='#5d6878'>(EDGAR: {escape(ev)})</font>"
    story += [Paragraph("HOW AND WHEN IT WENT PUBLIC", S["h"]), Paragraph(ipo_txt, S["body"])]
    if lst.get("web") and lim["ipo"]:
        story.append(Paragraph(escape(_trim(lst["web"]["text"], lim["ipo"])) +
                               " <font color='#5d6878'>[web search summary]</font>", S["body"]))

    # Identifiers
    e = ids["entity"]
    story.append(Paragraph("SECURITY IDENTIFIERS", S["h"]))
    story.append(Paragraph(escape(f"CIK {e['CIK']} · LEI {e['LEI'] or 'not found'}"
                                  + (f" · EIN {e['EIN']}" if e.get('EIN') else "")
                                  + (f" · {len(ids['debt'])} debt/other ISINs mapped to the issuer" if ids["debt"] else "")
                                  + " · SEDOL: licensed, not in free sources"), S["cellm"]))
    rows = [[P(h, "cellb") for h in ("Ticker", "Exchange", "Type", "ISIN", "CUSIP", "Composite FIGI")]]
    for x in ids["securities"][: lim["ids"]]:
        rows.append([P(x["ticker"]), P(x["exchange"]), P(x["type"]), P(x["isin"] or "n/a"), P(x["cusip"] or "n/a"),
                     P(x["composite_figi"] or "n/a")])
    story += [Spacer(1, 2), grid(rows, [0.8 * inch, 0.95 * inch, 1.35 * inch, 1.3 * inch, 1.05 * inch, W - 5.45 * inch])]

    # Holders
    hold = p["holders"][: lim["holders"]]
    hrows = [[P("Holder", "cellb"), P("% of class", "cellb"), P("Form", "cellb"), P("Filed", "cellb")]] + \
            [[P(h["name"]), P(f"{h['pct']:.1f}%" if h["pct"] is not None else "n/a"), P(h["form"]), P(h["date"])] for h in hold]
    if len(hrows) == 1:
        hrows.append([P("No Schedule 13D/13G filings in 3 years", "cellm"), "", "", ""])
    story += [Paragraph(f"SIGNIFICANT HOLDERS (5%+; {len(hold)} OF {len(p['holders'])})", S["h"]),
              grid(hrows, [W - 2.6 * inch, 0.8 * inch, 0.9 * inch, 0.9 * inch])]

    # Events and news
    evs = p["events"]
    up = sorted([x for x in evs if x["status"] == "Estimated"], key=lambda x: x["date"])
    rest = [x for x in evs if x["status"] != "Estimated"]
    show = (up[:2] + rest)[: lim["events"]]
    erows = [[P(h, "cellb") for h in ("Date", "Category", "Event", "Source")]] + \
            [[P(x["date"]), P(x["category"]), P(_trim(x["title"], 140)), P(x["form"] if x["status"] != "Estimated" else "Estimated")]
             for x in show]
    if len(erows) == 1:
        erows.append([P("No events found in the last 90 days.", "cellm"), "", "", ""])
    story += [KeepTogether([Paragraph(f"CORPORATE EVENTS (LAST 90 DAYS; {len(show)} OF {len(evs)})", S["h"]),
                            grid(erows, [0.75 * inch, 1.35 * inch, W - 3.3 * inch, 1.2 * inch])])]
    news = p["news"][: lim["news"]]
    if news:
        nrows = [[P("Date", "cellb"), P("Headline", "cellb"), P("Source", "cellb")]] + \
                [[P(n["date"]), P(_trim(n["title"], 150)), P(n["source"])] for n in news]
        story += [KeepTogether([Paragraph(f"NEWS (LAST 90 DAYS; {len(news)} OF {len(p['news'])})", S["h"]),
                                grid(nrows, [0.75 * inch, W - 2.05 * inch, 1.3 * inch])])]

    # Safe harbor summary
    frows = [[P(lab, "cellm") for lab, _ in r["facts"]], [P(v, "cellb") for _, v in r["facts"]]]
    hrows2 = [[P("Safe harbor", "cellb"), P("Status", "cellb"), P("Basis", "cellb")]] + \
             [[P(n, "cellb"), P(st, "cellb"), P(b, "cellm")] for n, st, b in r["harbors"]]
    story += [KeepTogether([Paragraph("RESEARCH SAFE HARBOR SUMMARY", S["h"]), Paragraph(escape(r["summary"]), S["body"]),
                            Spacer(1, 3), grid(frows, [W / len(r["facts"])] * len(r["facts"]), header=False), Spacer(1, 3),
                            grid(hrows2, [2.1 * inch, 1.9 * inch, W - 4.0 * inch])])]
    story += [Spacer(1, 6), Paragraph(escape(
        "Public data only: SEC EDGAR, GLEIF, OpenFIGI, exchange symbol files, web search and the market data provider named above. "
        "Web summaries are machine-generated from search results and should be checked against the linked sources. "
        "CUSIPs are owned by CUSIP Global Services; SEDOLs are licensed by LSEG. The safe harbor summary is a preliminary "
        "screen, not legal advice."), S["foot"])]
    return story


def _trim(text, n):
    text = " ".join((text or "").split())
    if len(text) <= n:
        return text
    cut = text[:n]
    return (cut.rsplit(". ", 1)[0] + ".") if ". " in cut[n // 2:] else cut.rsplit(" ", 1)[0] + "…"


def _footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 6.2)
    canvas.setFillColor(MUTED)
    canvas.drawString(0.5 * inch, 0.32 * inch, "Entity profile summary · public data · not investment or legal advice")
    canvas.drawRightString(letter[0] - 0.5 * inch, 0.32 * inch, f"Page {doc.page}")
    canvas.restoreState()


def make_pdf(p):
    limits = [dict(desc=900, ipo=500, ids=10, holders=6, events=14, news=10),
              dict(desc=700, ipo=380, ids=8, holders=5, events=10, news=7),
              dict(desc=550, ipo=280, ids=6, holders=4, events=8, news=5),
              dict(desc=420, ipo=200, ids=5, holders=3, events=6, news=3),
              dict(desc=300, ipo=0, ids=4, holders=3, events=4, news=0)]
    pdf = None
    for lim in limits:
        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=letter, leftMargin=0.5 * inch, rightMargin=0.5 * inch,
                                topMargin=0.45 * inch, bottomMargin=0.5 * inch,
                                title=f"{p['company']['name']} entity profile", author="Entity profile app")
        doc.build(build_story(p, lim), onFirstPage=_footer, onLaterPages=_footer)
        pdf = buf.getvalue()
        if doc.page <= 2:
            break
    return pdf
