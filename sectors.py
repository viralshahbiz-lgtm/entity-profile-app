"""Sector and country rules. Edit the SIC ranges here to widen or narrow the universe."""

# SEC Standard Industrial Classification (SIC) codes
TECH_SIC = [(3570, 3579),   # computer and office equipment
            (3600, 3699),   # electronic equipment, semiconductors, communications equipment
            (7370, 7379)]   # software, programming, data processing, IT services
BIOTECH_SIC = [(2833, 2836),  # medicinal chemicals, pharmaceuticals, diagnostics, biological products
               (8731, 8731)]  # commercial physical and biological research

US_STATES = set("""AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV
NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY PR""".split())
# EDGAR codes for Canadian provinces and Canada (federal)
CANADA_CODES = {"A0", "A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9", "B0", "Z4"}


def sector_for_sic(sic):
    try:
        s = int(sic)
    except (TypeError, ValueError):
        return "Other"
    if any(lo <= s <= hi for lo, hi in TECH_SIC):
        return "Technology"
    if any(lo <= s <= hi for lo, hi in BIOTECH_SIC):
        return "Biotech"
    return "Other"


def country_for_code(code, desc=""):
    c = (code or "").upper()
    if c in US_STATES:
        return "United States"
    if c in CANADA_CODES or "CANADA" in (desc or "").upper():
        return "Canada"
    return (desc or c).title() if (desc or c) else ""
