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
    c, r = p["company"], p["regm"]
    tickers = ", ".join(f"{s['ticker']} ({s['exchange']})" for s in p["securities"] if s["type"] == "Common Stock") or "n/a"
    story = [
        Paragraph(escape(c["name"]), S["title"]),
        Paragraph(escape(f"{tickers}  ·  {c['sector']} · {c['industry']}  ·  CIK {c['cik']}  ·  "
                         f"HQ {', '.join(x for x in (c['hq_city'], c['hq_country']) if x)}  ·  "
                         f"Incorporated {c['incorporation']}  ·  {c['filer_category'] or 'filer status n/a'}"), S["sub"]),
        Paragraph(escape(f"Entity profile summary as of {p['as_of']} · public sources: {', '.join(p['sources'])}"), S["sub"]),
        Spacer(1, 5),
        Paragraph("MARKET DATA", S["h"]), market_block(p),
        Paragraph("BUSINESS DESCRIPTION", S["h"]),
        Paragraph(escape((p["description"] or "Not available.")[:lim["desc"]]) +
                  (f" <font color='#5d6878'>[{escape(p['description_source'])}]</font>" if p["description_source"] else ""),
                  S["body"]),
    ]
    secs = p["securities"][: lim["secs"]]
    rows = [[P("Ticker", "cellb"), P("Security", "cellb"), P("Type", "cellb"), P("Exchange", "cellb")]] + \
           [[P(s["ticker"]), P(s["name"]), P(s["type"]), P(s["exchange"])] for s in secs]
    hold = p["holders"][: lim["holders"]]
    hrows = [[P("Holder", "cellb"), P("%", "cellb"), P("Filed", "cellb")]] + \
            [[P(h["name"]), P(f"{h['pct']:.1f}" if h["pct"] is not None else "n/a"), P(h["date"])] for h in hold]
    if len(hrows) == 1:
        hrows.append([P("No Schedule 13D/13G filings in 3 years", "cellm"), "", ""])
    side = Table([[
        [Paragraph(f"EQUITY SECURITIES ({len(p['securities'])})", S["h"]), grid(rows, [0.75 * inch, 1.95 * inch, 0.8 * inch, 0.7 * inch])],
        [Paragraph("SIGNIFICANT HOLDERS (5%+)", S["h"]), grid(hrows, [2.0 * inch, 0.45 * inch, 0.75 * inch])],
    ]], colWidths=[4.35 * inch, W - 4.35 * inch])
    side.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                              ("RIGHTPADDING", (0, 0), (0, 0), 10)]))
    story += [side]

    # Reg M and safe harbors
    story.append(Paragraph("REGULATION M AND RESEARCH SAFE HARBORS (PRELIMINARY SCREEN)", S["h"]))
    story.append(Paragraph(escape(r["summary"]), S["body"]))
    story.append(Spacer(1, 3))
    inp = r["inputs"]
    irows = []
    for i in range(0, len(inp), 2):
        pair = inp[i:i + 2]
        row = []
        for lab, val, srcn in pair:
            row += [P(lab, "cellm"), P(val, "cellb"), P(srcn, "cellm")]
        irows.append(row + [""] * (6 - len(row)))
    story.append(grid(irows, [1.25 * inch, 0.8 * inch, 1.7 * inch] * 2, header=False))
    trows = [[P("Rule", "cellb"), P("Applies to", "cellb"), P("Test", "cellb"), P("Result", "cellb")]]
    for t in r["tests"]:
        trows.append([P(t["rule"], "cellb"), P(t["who"]), P(t["test"], "cellm"),
                      Paragraph(f"<font color='{STATUS[t['status']].hexval()}'><b>{escape(t['result'])}</b></font>"
                                + (f"<br/><font color='#5d6878'>{escape(t['detail'])}</font>" if t["detail"] else ""), S["cell"])])
    story += [Spacer(1, 4), grid(trows, [1.05 * inch, 1.6 * inch, 2.35 * inch, W - 5.0 * inch])]
    hrows2 = [[P("Safe harbor", "cellb"), P("Status", "cellb"), P("Basis", "cellb"), P("Firm checks", "cellb")]]
    for h in r["harbors"]:
        hrows2.append([P(h["name"], "cellb"), P(h["status"], "cellb"), P(h["basis"], "cellm"), P(h["firm_checks"], "cellm")])
    story += [Spacer(1, 4), grid(hrows2, [1.55 * inch, 1.05 * inch, 2.65 * inch, W - 5.25 * inch])]

    # Events and news
    ev = p["events"]
    up = sorted([e for e in ev if e["status"] != "Filed"], key=lambda e: e["date"])
    past = [e for e in ev if e["status"] == "Filed"]
    show = (up + past)[: lim["events"]]
    erows = [[P("Date", "cellb"), P("Category", "cellb"), P("Event", "cellb"), P("Status", "cellb")]] + \
            [[P(e["date"]), P(e["category"]), P(e["title"]), P(e["status"])] for e in show]
    if len(erows) == 1:
        erows.append([P("No control-room-relevant filings in the last 180 days.", "cellm"), "", "", ""])
    story += [KeepTogether([Paragraph(f"CORPORATE EVENTS (LAST 180 DAYS AND ESTIMATED UPCOMING; {len(show)} OF {len(ev)})", S["h"]),
                            grid(erows, [0.75 * inch, 1.3 * inch, W - 2.75 * inch, 0.7 * inch])])]
    news = p["news"][: lim["news"]]
    if news:
        nrows = [[P("Date", "cellb"), P("Headline", "cellb"), P("Source", "cellb")]] + \
                [[P(n["date"]), P(n["headline"]), P(n["source"])] for n in news]
        story += [KeepTogether([Paragraph(f"NEWS (LAST 180 DAYS; {len(news)} OF {len(p['news'])})", S["h"]),
                                grid(nrows, [0.75 * inch, W - 1.85 * inch, 1.1 * inch])])]
    story += [Spacer(1, 6), Paragraph(escape(
        "Public data only: SEC EDGAR filings and XBRL, exchange symbol files, and the market data and news providers listed above. "
        "Estimated dates are worked out from filing history. The Reg M and safe harbor section is an automated preliminary "
        "screen, not legal advice; confirm every determination with Legal and Compliance. " + " ".join(r["caveats"][1:])), S["foot"])]
    return story


def _footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 6.2)
    canvas.setFillColor(MUTED)
    canvas.drawString(0.5 * inch, 0.32 * inch, "Entity profile summary · public data · not investment or legal advice")
    canvas.drawRightString(letter[0] - 0.5 * inch, 0.32 * inch, f"Page {doc.page}")
    canvas.restoreState()


def make_pdf(p):
    limits = [dict(desc=900, secs=10, holders=8, events=14, news=8),
              dict(desc=700, secs=8, holders=6, events=10, news=6),
              dict(desc=550, secs=6, holders=5, events=7, news=4),
              dict(desc=400, secs=5, holders=4, events=5, news=3),
              dict(desc=300, secs=4, holders=3, events=4, news=0)]
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
