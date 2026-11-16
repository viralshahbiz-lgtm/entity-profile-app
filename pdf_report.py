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


def L(text, url, style="cell"):
    """Table cell whose text is a clickable link (when a URL is known)."""
    if not url:
        return P(text, style)
    return Paragraph(f"<link href='{escape(url)}' color='#1f4fa8'>{escape(str(text))}</link>", S[style])


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
        ("Prior close", f"{ccy} {num(pv.get('price'))}" if pv else "n/a", f"{pv.get('exchange', '')} {pv.get('price_date', '')}"),
        ("1-day / 1-month change", (f"{pv['change_1d_pct']:+.2f}%" if pv.get("change_1d_pct") is not None else "n/a") + " / " +
         (f"{pv['change_1m_pct']:+.1f}%" if pv.get("change_1m_pct") is not None else "n/a"), pv.get("provider", "") if pv else ""),
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


def range_drawing(v):
    """52-week range bar with a marker at the prior close."""
    from reportlab.graphics.shapes import Drawing, Rect, Circle, String
    lo, hi, px = v.get("low_52w"), v.get("high_52w"), v.get("price")
    if lo is None or hi is None or px is None or hi <= lo:
        return None
    w, x0, bar_w = W, 0, W
    d = Drawing(w, 30)
    seg = bar_w / 3
    for k, col in enumerate(("#c0392b", "#e6b33c", "#1d7a4c")):
        d.add(Rect(x0 + k * seg, 12, seg, 6, fillColor=colors.HexColor(col), strokeColor=None))
    pos = max(0.0, min(1.0, (px - lo) / (hi - lo)))
    d.add(Circle(x0 + pos * bar_w, 15, 5, fillColor=INK, strokeColor=colors.white, strokeWidth=1.2))
    ccy = v.get("currency", "")
    d.add(String(x0, 22, f"52-week low {ccy} {lo:,.2f}", fontName="Helvetica", fontSize=6.6, fillColor=MUTED))
    d.add(String(x0 + bar_w, 22, f"52-week high {ccy} {hi:,.2f}", fontName="Helvetica", fontSize=6.6, fillColor=MUTED,
                 textAnchor="end"))
    lab = f"Prior close {ccy} {px:,.2f} ({v.get('exchange', '')}, {pos * 100:.0f}% of range, {(px / hi - 1) * 100:+.1f}% vs high)"
    anchor = "start" if pos < 0.25 else ("end" if pos > 0.75 else "middle")
    d.add(String(x0 + pos * bar_w, 2, lab, fontName="Helvetica-Bold", fontSize=6.8, fillColor=INK, textAnchor=anchor))
    return d


def build_story(p, lim):
    c, r, ids, lst = p["company"], p["regm"], p["identifiers"], p["listing"]
    tickers = ", ".join(f"{s['ticker']} ({s['exchange']})" for s in p["securities"] if s["type"] == "Common Stock") or "n/a"
    story = [
        Paragraph(escape(c["name"]), S["title"]),
        Paragraph(escape(f"{tickers}  ·  {c['sector']} · {c['industry']}  ·  "
                         f"HQ {', '.join(x for x in (c['hq_city'], c['hq_country']) if x)}  ·  "
                         f"Incorporated {c['incorporation']}  ·  {c['filer_category'] or 'filer status n/a'}"), S["sub"]),
        Paragraph(escape(f"Entity profile summary as of {p['as_of']} · public sources: {', '.join(p['sources'])}"), S["sub"]),
    ]
    # 1. Company description
    d = p["description"]
    story += [Paragraph("COMPANY DESCRIPTION", S["h"]),
              Paragraph(escape(_trim(d["text"] or "Not available.", lim["desc"])) +
                        (f" <font color='#5d6878'>[{escape(d['source'])}]</font>" if d["source"] else ""), S["body"])]
    # 2. Market data with 52-week range bar
    story += [Paragraph("MARKET DATA", S["h"]), market_block(p)]
    pv = (p["market"].get("primary") or {})
    rd = range_drawing(pv) if pv else None
    if rd:
        story += [Spacer(1, 3), rd]
    # 3. Equity securities and identifiers
    e = ids["entity"]
    story.append(Paragraph("EQUITY SECURITIES AND IDENTIFIERS", S["h"]))
    story.append(Paragraph(escape(f"CIK {e['CIK']} · LEI {e['LEI'] or 'not found'}" + (f" · EIN {e['EIN']}" if e.get('EIN') else "")
                                  + " · SEDOL: licensed, not in free sources"), S["cellm"]))
    rows = [[P(h, "cellb") for h in ("Ticker", "Exchange", "Type", "ISIN", "CUSIP", "Composite FIGI")]]
    for x in ids["securities"][: lim["ids"]]:
        rows.append([P(x["ticker"]), P(x["exchange"]), P(x["type"]), P(x["isin"] or "n/a"), P(x["cusip"] or "n/a"),
                     P(x["composite_figi"] or "n/a")])
    story += [Spacer(1, 2), grid(rows, [0.8 * inch, 0.95 * inch, 1.35 * inch, 1.3 * inch, 1.05 * inch, W - 5.45 * inch])]
    # 4. Fixed income
    dbt = p.get("debt") or {"bonds": []}
    td = dbt.get("total_debt")
    story.append(Paragraph(f"FIXED INCOME SECURITIES ({len(dbt['bonds'])} OUTSTANDING"
                           + (f"; TOTAL DEBT {escape(td['unit'])} {num(td['value'])} AS OF {escape(td['date'])}" if td else "") + ")", S["h"]))
    if dbt["bonds"]:
        drows = [[P(h, "cellb") for h in ("Security", "Coupon", "Maturity", "Amount", "CUSIP", "Listed")]]
        for b in dbt["bonds"][: lim["debt"]]:
            drows.append([L(b["description"], b.get("link")), P(b["coupon"]), P(b["maturity"]),
                          P(num(b["principal"], 0) if b["principal"] else ""), P(b["cusip"] or "n/a"), P(b["listed"])])
        story.append(grid(drows, [W - 4.6 * inch, 0.6 * inch, 0.95 * inch, 0.75 * inch, 0.85 * inch, 1.45 * inch]))
    else:
        story.append(Paragraph("No publicly issued notes or bonds found.", S["cellm"]))
    # 5. How and when it went public
    if lst.get("summary"):
        story += [Paragraph("HOW AND WHEN IT WENT PUBLIC", S["h"]),
                  Paragraph(f"<b>{escape(lst['summary'])}</b>" +
                            (f" <link href='{escape(lst['link'])}' color='#1f4fa8'>source</link>" if lst.get("link") else ""),
                            S["body"])]
    # 6. Holders
    hold = p["holders"][: lim["holders"]]
    hrows = [[P("Holder", "cellb"), P("% of class", "cellb"), P("Form", "cellb"), P("Filed", "cellb")]] + \
            [[P(h["name"]), P(f"{h['pct']:.1f}%" if h["pct"] is not None else "n/a"), P(h["form"]), P(h["date"])] for h in hold]
    if len(hrows) == 1:
        hrows.append([P("No Schedule 13D/13G filings in 3 years", "cellm"), "", "", ""])
    story += [Paragraph(f"SIGNIFICANT HOLDERS (5%+; {len(hold)} OF {len(p['holders'])})", S["h"]),
              grid(hrows, [W - 2.6 * inch, 0.8 * inch, 0.9 * inch, 0.9 * inch])]
    # 7. News (M&A and strategic first) and events
    news = p["news"][: lim["news"]]
    if news:
        nrows = [[P("Date", "cellb"), P("Headline", "cellb"), P("Source", "cellb")]]
        for n in news:
            tag = ("<font color='#a5640b'><b>[RUMORED M&amp;A]</b></font> " if n.get("rumored") else
                   "<font color='#b3261e'><b>[M&amp;A]</b></font> ") if n.get("mna") else ""
            nrows.append([P(n["date"]), Paragraph(tag + f"<link href='{escape(n['url'])}' color='#1f4fa8'>"
                                                        f"{escape(_trim(n['title'], 150))}</link>", S["cell"]), P(n["source"])])
        n_mna = sum(1 for n in p["news"] if n.get("mna"))
        story += [KeepTogether([Paragraph(f"NEWS, LAST 90 DAYS ({n_mna} M&amp;A / STRATEGIC FIRST; {len(news)} OF {len(p['news'])})", S["h"]),
                                grid(nrows, [0.75 * inch, W - 2.05 * inch, 1.3 * inch])])]
    evs = [x for x in p["events"] if x["status"] in ("Filed", "Estimated")]       # web items are already in News
    up = sorted([x for x in evs if x["status"] == "Estimated"], key=lambda x: x["date"])
    rest = [x for x in evs if x["status"] != "Estimated"]
    show = (rest + up[:2])[: lim["events"]]
    if show:
        erows = [[P(h, "cellb") for h in ("Date", "Category", "Event (SEC filings)", "Form")]] + \
                [[P(x["date"]), P(x["category"]), L(_trim(x["title"], 140), x.get("url")),
                  P(x["form"] if x["status"] != "Estimated" else "Estimated")] for x in show]
        story += [KeepTogether([Paragraph(f"CORPORATE EVENTS FROM SEC FILINGS ({len(show)} OF {len(evs)})", S["h"]),
                                grid(erows, [0.75 * inch, 1.35 * inch, W - 3.3 * inch, 1.2 * inch])])]
    # 8. Safe harbor summary
    block = [Paragraph("RESEARCH SAFE HARBOR SUMMARY", S["h"]), Paragraph(escape(r["summary"]), S["body"])]
    if r.get("harbors"):
        hrows2 = [[P("Safe harbor", "cellb"), P("Status", "cellb"), P("Basis", "cellb")]] + \
                 [[P(n, "cellb"), P(st, "cellb"), P(b, "cellm")] for n, st, b in r["harbors"]]
        block += [Spacer(1, 3), grid(hrows2, [2.1 * inch, 1.9 * inch, W - 4.0 * inch])]
    story += [KeepTogether(block)]
    # 9. Board of directors
    bd = p.get("board") or {"directors": []}
    if bd["directors"]:
        brows = [[P(h, "cellb") for h in ("Director", "Experience", "Other public company affiliations")]]
        for x in bd["directors"][: lim["board"]]:
            others = "; ".join(x["other_public_boards"]) or x.get("proxy_other_boards") or "None found"
            brows.append([Paragraph(f"<link href='{escape(x['web_url'])}' color='#1f4fa8'><b>{escape(x['name'])}</b></link>"
                                    f"<br/><font color='#5d6878'>{escape(x['role'])}</font>", S["cell"]),
                          P(_trim(x["bio"], lim["bio"]) if lim["bio"] and x["bio"] else "See proxy statement", "cellm"), P(_trim(others, 160), "cellm")])
        story += [Paragraph(f"BOARD OF DIRECTORS ({min(len(bd['directors']), lim['board'])} OF {len(bd['directors'])})", S["h"]),
                  grid(brows, [1.45 * inch, W - 3.45 * inch, 2.0 * inch])]
    story += [Spacer(1, 6), Paragraph(escape(
        "Public data only: SEC EDGAR, GLEIF, OpenFIGI, exchange symbol files, web search and the market data providers named above. "
        "Web summaries are machine-generated; check the linked sources. CUSIPs are owned by CUSIP Global Services; SEDOLs are "
        "licensed by LSEG. The safe harbor summary is a preliminary screen, not legal advice."), S["foot"])]
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
    limits = [dict(desc=320, ids=8, debt=8, holders=5, events=8, news=10, board=12, bio=200),
              dict(desc=300, ids=6, debt=6, holders=4, events=6, news=8, board=10, bio=150),
              dict(desc=260, ids=5, debt=5, holders=3, events=5, news=6, board=8, bio=110),
              dict(desc=220, ids=4, debt=4, holders=3, events=4, news=5, board=8, bio=0),
              dict(desc=200, ids=3, debt=3, holders=2, events=3, news=4, board=6, bio=0)]
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
