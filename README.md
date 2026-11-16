# Entity Profile: U.S. and Canadian Technology and Biotech companies

A simple web page. Start typing a company name or ticker, pick a match, and the page pulls together public information:

- **Market data (prior close):** the last completed session's close with 1-day and 1-month change, 52-week range, market cap, enterprise value, public float, shares outstanding, average daily volume and worldwide ADTV.
- **Business description:** a short summary written from web search results, with a Wikipedia or annual report fallback.
- **How and when it went public:** one line, either the IPO date, or that it went public by merging with a SPAC / blank-check company (with the SPAC's name and completion date). Spin-offs, direct listings and Canadian cross-listings get a one-line label too.
- **Security identifiers:** tickers on every listing, ISIN, CUSIP, FIGI, composite and share-class FIGI, LEI and CIK. Debt ISINs mapped to the issuer are listed separately.
- **Debt securities:** outstanding notes, bonds and convertibles with coupon, maturity, size, CUSIP/ISIN/FIGI and exchange listing (matured issues hidden), plus total debt from the balance sheet.
- **Significant holders:** 5%+ holders from Schedule 13D and 13G filings.
- **Corporate events and news, last 90 days:** from SEC filings and from web news search, sorted into categories (M&A, capital markets, management, regulatory/clinical, legal, earnings and others). Estimated upcoming dates are included.
- **Research safe harbor summary:** Rule 139, JOBS Act EGC research and FINRA 2241 quiet periods, with the key facts behind them (EGC status, Reg M actively traded, ADTV, float).
- **Export PDF:** a one- to two-page summary.

It runs free on **Streamlit Community Cloud**, a hosting service for small Python web apps. Setup takes about 30 minutes, all in a web browser.

---

## Where the data comes from

| Section | Source | Key needed? |
|---|---|---|
| Company record, filings, holders, IPO evidence, financial facts | SEC EDGAR | No (contact email only) |
| Description summary, news, IPO date when EDGAR can't tell | Tavily web search | Free key: 1,000 searches a month, no card |
| News when there is no Tavily key | GDELT news search | No |
| Description when web search has nothing | Wikipedia | No |
| LEI and the ISINs mapped to it | GLEIF (ISIN-to-LEI mapping, CC0 licence) | No |
| FIGIs, exchange tickers, security types | OpenFIGI | No (an optional free key raises limits) |
| Prior-close prices and volumes, U.S. listings | Twelve Data | Free key: 800 calls a day (1 per company) |
| TSX listing and prices; backup for U.S. prices | Alpha Vantage | Free key: 25 calls a day |
| Debt securities | SEC offering documents (last 3 years), GLEIF debt ISINs described through OpenFIGI, exchange-listed notes on the 10-K cover | No |
| Security names on U.S. exchanges | Nasdaq Trader symbol directory | No |

**Identifiers and their limits:**
- **CUSIPs:** U.S. and Canadian CUSIPs are characters 3–11 of the ISIN. CUSIPs reported on 13D/13G cover pages fill gaps.
- **SEDOL:** licensed by LSEG, with no free source, so the page says so rather than leaving it blank.
- **Publishing CUSIPs:** CUSIP data is owned by CUSIP Global Services. Check licensing before showing CUSIPs on a public website.

**Which companies are included:** U.S. and Canadian companies listed on Nasdaq, NYSE, NYSE American or Cboe, with a Technology or Biotech industry code:
- **Technology:** SIC 3570–3579, 3600–3699 and 7370–7379.
- **Biotech:** SIC 2833–2836 and 8731.

To change the ranges, edit `sectors.py`. To search any U.S.-listed company, switch on **Include every SEC-listed company** in the side panel.

---

## Before you start

1. **Compliance:** if this will be public and in your name, check whether it needs pre-approval as an outside activity. Use personal accounts and a personal email.
2. **Data terms:** SEC, GLEIF and Wikipedia data are free to reuse. Tavily, Twelve Data, Alpha Vantage and OpenFIGI have their own terms. Twelve Data's free plan is for internal, non-display use, so showing its prices on a public page needs a paid licence.

---

## Setup, step by step

### Step 1: Get two free API keys (5 minutes)

1. **Tavily** (web search): go to **https://app.tavily.com**, sign up (no credit card), and copy your API key. It starts with `tvly-`. Each company profile uses about 3 searches.
2. **Twelve Data** (U.S. prior-close prices): go to **https://twelvedata.com/register**, sign up (no card), and copy the API key from your dashboard. The free plan covers U.S. listings, 800 calls a day; each company uses 1.
3. **Alpha Vantage** (TSX prices and a U.S. backup): go to **https://www.alphavantage.co/support/#api-key** and copy the key. 25 calls a day; needed for Canadian companies' TSX line.
4. *(Optional)* **OpenFIGI**: create a free account at **https://www.openfigi.com** and copy the API key from your account page. It only makes identifier lookups faster.

### Step 2: Create the GitHub project

1. Sign in at **https://github.com**.
2. Click **+** > **New repository**.
3. **Name:** `entity-profile-app`. Choose **Public**, tick **Add a README file**, then click **Create repository**.

*(If you already created this repository for the earlier version, open it and go straight to Step 3; uploading the new files replaces the old ones.)*

### Step 3: Upload the files

1. Unzip the download.
2. In the repository, click **Add file** > **Upload files**.
3. Select **everything inside** the `entity-profile-app` folder (all `.py` files, `requirements.txt`, `README.md`, and the `data` and `setup` folders) and drag it onto the page.
4. Click **Commit changes**. Say yes if asked to replace files.

### Step 4: Add your SEC contact email

1. Go to **Settings** > **Secrets and variables** > **Actions** > **New repository secret**.
2. **Name:** `SEC_CONTACT_EMAIL`. **Secret:** your personal email. Click **Add secret**.

### Step 5: Build the Technology and Biotech company list

1. Click **Add file** > **Create new file**.
2. File name: `.github/workflows/universe.yml`
3. Open `setup/universe.yml` from the unzipped folder in Notepad or TextEdit. Copy everything, paste it into GitHub, and click **Commit changes** (twice).
4. Click **Actions**. Enable workflows if asked, then click **Refresh company list** > **Run workflow**.
5. Wait 20 to 30 minutes for a green tick. `data/universe.csv` then appears.

It refreshes itself every Sunday.

> If it fails at "Save the list" with a permission error: go to **Settings** > **Actions** > **General** > **Workflow permissions** > **Read and write permissions** > **Save**, then run it again.

### Step 6: Put the page online with Streamlit

1. Go to **https://share.streamlit.io** and click **Continue with GitHub**.
2. Click **Create app** > **Deploy a public app from GitHub**.
3. **Repository:** `your-username/entity-profile-app`. **Branch:** `main`. **Main file:** `app.py`.
4. Click **Advanced settings**. Paste the following into **Secrets**, using your own values:

   ```
   SEC_CONTACT_EMAIL = "you@example.com"
   TAVILY_KEY = "tvly-your-key"
   TWELVEDATA_KEY = "your-twelve-data-key"
   ALPHAVANTAGE_KEY = "your-alpha-vantage-key"
   OPENFIGI_KEY = ""
   ```

5. Click **Save**, then **Deploy**. After 2 to 3 minutes the page is live, at an address like `https://entity-profile.streamlit.app`.

*(Already deployed the earlier version? Open the app's ⋮ menu > **Settings** > **Secrets**, add `TAVILY_KEY` and `OPENFIGI_KEY`, and remove `FINNHUB_KEY`. The page updates by itself after Step 3.)*

### Step 7: Use it

1. Click the search box at the top and **start typing** a company name or ticker. Matches appear as you type. Use the side panel to limit the list by sector or headquarters country.
2. Pick a company. The profile builds in 20 to 60 seconds the first time and is reused for 6 hours.
3. Click **Export PDF summary** to download the one- to two-page PDF.

---

## If something goes wrong

| What you see | What to do |
|---|---|
| "Setup needed: add SEC_CONTACT_EMAIL" | Add it in Streamlit **Secrets**. The spelling must match exactly. |
| "Web search is off" in Data notes | Add `TAVILY_KEY`. News still comes from GDELT, and the description from Wikipedia or the annual report. |
| "Tavily rejected the API key" | Copy the key again from app.tavily.com; it starts with `tvly-`. |
| "Twelve Data free limit reached" | 8 calls a minute or 800 a day were used. Wait a minute; the page falls back to Alpha Vantage if that key is set. |
| "Alpha Vantage free limit reached" | The 25 free calls are used up for today. U.S. prices still come from Twelve Data. |
| Prior close date is a day or more ago | Expected: the page shows the last completed trading session, so on weekends and holidays it shows the previous trading day. |
| Debt securities shows none | Many tech and biotech companies have no public bonds. Older debt appears only if GLEIF maps its ISIN to the company or it is exchange-listed. |
| LEI shows "not found" | GLEIF had no exact name match in the U.S. or Canada. Identifiers from tickers (FIGI) still appear. |
| ISIN or CUSIP blank for a security | GLEIF has no ISIN mapped for that line yet; CUSIPs from 13D/13G filings are used when available. |
| "IPO date not found" | The company listed before electronic SEC filing and web search found no date. |
| "Could not reach …" | That service was busy. Pick the company again in a minute. |

## How the page decides "how and when it went public"

| Evidence in the SEC filing history | Line shown |
|---|---|
| 8-K item 5.06 (company left shell status), or a SPAC-style former name such as "... Acquisition Corp" with a merger filing (S-4/F-4/DEFM14A) | Went public by merging with a SPAC / blank-check company (SPAC name); completed (date) |
| S-1/F-1, then a 424B4 final prospectus | IPO on (date of the 424B4) |
| Form 10-12B | Spin-off |
| Form 40FR12B or 40-F | Canadian company cross-listed in the U.S. (MJDS) |
| Registration and exchange listing without a 424B4 | Direct listing |
| None of these (listed before EDGAR) | IPO date from web search, if found |

## News links

News comes from web search (Tavily news, or GDELT without a key) for the last 90 days. Only links to individual articles are kept: stock quote pages, company profiles, home pages, social media and section fronts are dropped. Headlines are clickable on the page and in the PDF.

## Research safe harbor summary: what it checks

- **Rule 139(a)(1) issuer-specific research:**
  - 12+ months of SEC reporting, with no late filings in the last 12 months.
  - Public float of at least US$75M.
  - Not a shell or blank-check company, and no bankruptcy filing in 3 years.
- **Rule 139(a)(2) industry research:** the issuer is an SEC reporting company.
- **JOBS Act EGC research:** the emerging growth company box on the latest annual report cover.
- **FINRA 2241 quiet period:**
  - None for EGC offerings.
  - Otherwise 10 days after an IPO and 3 days after a follow-on for managers and co-managers.
  - An exception is likely when the stock is Reg M "actively traded" (ADTV at least US$1M and float at least US$150M) and Rule 139 is available.

This is a preliminary screen, not legal advice. Firm-side conditions (regular course, not an initiation, the firm's role in an offering) need confirming.

## Files

| File | What it does |
|---|---|
| `app.py` | The web page |
| `entity_profile.py` | Gathers one company's data, including identifiers, listing history, events and news |
| `regm.py` | Research safe harbor summary |
| `pdf_report.py` | Builds the PDF summary |
| `sources.py` | Connects to SEC, Tavily, GDELT, Wikipedia, GLEIF, OpenFIGI, Alpha Vantage and Nasdaq Trader |
| `sectors.py` | Technology and Biotech industry codes; U.S. and Canada rules |
| `build_universe.py` | Builds `data/universe.csv` (run weekly by GitHub) |
| `setup/universe.yml` | The weekly schedule you paste into GitHub in step 5 |
