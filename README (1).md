# Entity Profile: U.S. and Canadian Technology and Biotech companies

A simple web page. Pick a company and it pulls together, from public sources:

- **Market data:** price, 1-month change, 52-week range, market cap, enterprise value, reported public float, average daily volume, and worldwide ADTV.
- **Business description:** taken from the latest 10-K, 20-F or 40-F.
- **Equity securities:** common shares, warrants, units and preferreds on U.S. exchanges, plus the TSX line for Canadian companies.
- **Significant holders:** 5%+ holders from Schedule 13D and 13G filings.
- **Corporate events and news, last 180 days:** M&A, offerings and shelf registrations, activism, management changes, earnings, distress, press releases and news headlines, plus estimated upcoming dates.
- **Regulation M and research safe harbors:**
  - Rule 101 and 102 restricted-period tiers, Rule 104 and 105 reminders, and UMIR 7.7 for TSX listings.
  - Rule 139(a)(1) and (a)(2), the JOBS Act EGC research provision, FINRA 2241 quiet periods and Rule 137.
  - The data behind each result: ADTV, public float, EGC, WKSI, shell status, reporting history and late filings.
- **Export PDF:** a one- to two-page summary.

It runs free on **Streamlit Community Cloud**, a hosting service for small Python web apps. Setup takes about 30 minutes, all in a web browser.

---

## Where the data comes from

| Section | Source | Key needed? |
|---|---|---|
| Company record, industry, incorporation, HQ, filer status | SEC EDGAR | No (contact email only) |
| Business description, EGC / WKSI / shell flags | Latest annual report on EDGAR (Inline XBRL cover page) | No |
| Shares outstanding, public float, cash, debt, revenue | SEC XBRL company facts | No |
| 5%+ holders | Schedule 13D/13G filings on EDGAR | No |
| Corporate events | Company's EDGAR filing history | No |
| Security names (U.S.) | Nasdaq Trader symbol directory | No |
| Prices, volumes, TSX listing, CAD/USD rate | Alpha Vantage | Free key |
| News headlines | Finnhub | Free key (optional) |

**Which companies are included:** U.S. and Canadian companies listed on Nasdaq, NYSE, NYSE American or Cboe, with a Technology or Biotech industry code (SIC):
- **Technology:** 3570–3579, 3600–3699 and 7370–7379.
- **Biotech:** 2833–2836 and 8731.

To change these ranges, edit `sectors.py`. Canadian companies are included when they are registered with the SEC, which covers most larger TSX technology and biotech names. Companies listed only on the TSX or TSXV have no free source for filings, so they are not in the list.

---

## Before you start

1. **Compliance:** if this will be public and in your own name, check whether it needs pre-approval as an outside activity. Use personal accounts and a personal email throughout.
2. **Data terms:** SEC data is free to use. The free Alpha Vantage and Finnhub plans are intended for personal and non-commercial use. Before showing their prices or news on a public site, read their terms and upgrade or ask permission if needed.

---

## Setup, step by step

### Step 1: Get two free API keys (5 minutes)

1. **Alpha Vantage** (prices and volumes): go to **https://www.alphavantage.co/support/#api-key**, fill in the short form and copy the key it shows you. The free key allows 25 requests a day, which is about 8 new company profiles a day. Profiles you have already opened are reused for 6 hours.
2. **Finnhub** (news, optional): go to **https://finnhub.io/register**, sign up, and copy the API key from your dashboard.

Save both keys somewhere safe, such as a note on your phone. You'll paste them in step 6.

### Step 2: Create the GitHub project

1. Sign in at **https://github.com** (create a free account first if you don't have one).
2. Click **+** (top right) > **New repository**.
3. **Name:** `entity-profile-app`. Choose **Public**, tick **Add a README file**, then click **Create repository**.

### Step 3: Upload the files

1. Unzip the download on your computer.
2. In your new repository, click **Add file** > **Upload files**.
3. Open the unzipped `entity-profile-app` folder, select **everything inside it** (all the `.py` files, `requirements.txt`, `README.md`, and the `data` and `setup` folders), and drag it onto the page.
4. Click **Commit changes**. If GitHub asks whether to replace README.md, say yes.

### Step 4: Add your SEC contact email

The SEC asks every automated download to include a contact email.

1. In the repository, click **Settings** > **Secrets and variables** > **Actions** > **New repository secret**.
2. **Name:** `SEC_CONTACT_EMAIL`. **Secret:** your personal email. Click **Add secret**.

### Step 5: Build the Technology and Biotech company list

1. Click **Add file** > **Create new file**.
2. File name: type exactly `.github/workflows/universe.yml`
3. Open `setup/universe.yml` from the unzipped folder in Notepad or TextEdit. Select all, copy, paste it into GitHub, and click **Commit changes** (twice).
4. Click the **Actions** tab. If asked, click the green button to enable workflows.
5. Click **Refresh company list** > **Run workflow** > **Run workflow**.
6. Wait 20 to 30 minutes for a green tick. A file `data/universe.csv` then appears in your repository.

From then on it refreshes itself every Sunday.

> If the run fails at "Save the list" with a permission error: go to **Settings** > **Actions** > **General** > **Workflow permissions**, choose **Read and write permissions**, click **Save**, and run it again.

### Step 6: Put the page online with Streamlit (5 minutes)

1. Go to **https://share.streamlit.io** and click **Continue with GitHub**. Allow it to see your repositories.
2. Click **Create app** > **Deploy a public app from GitHub**.
3. **Repository:** `your-username/entity-profile-app`. **Branch:** `main`. **Main file path:** `app.py`.
4. Optionally choose a web address under **App URL**, for example `entity-profile`.
5. Click **Advanced settings**. In the **Secrets** box, paste the following, replacing the parts in quotes with your own values:

   ```
   SEC_CONTACT_EMAIL = "you@example.com"
   ALPHAVANTAGE_KEY = "your-alpha-vantage-key"
   FINNHUB_KEY = "your-finnhub-key"
   ```

   Leave `FINNHUB_KEY = ""` if you skipped Finnhub.
6. Click **Save**, then **Deploy**. The first start takes 2 to 3 minutes. Your page is then live at an address like `https://entity-profile.streamlit.app`.

### Step 7: Use it

1. In the left panel, keep **Browse Tech & Biotech list** selected. Filter by sector and headquarters if you like, and type part of a name or ticker.
2. Choose the company and press **Show profile**. The first view of a company takes 20 to 60 seconds while the data is gathered.
3. Click **Export PDF summary** (top right) to download the one- to two-page PDF.

To look up a company that isn't in the list, choose **Look up any ticker** and type its U.S. ticker.

---

## Everyday tasks

- **Change your keys:** at share.streamlit.io, open your app's menu (⋮) > **Settings** > **Secrets**.
- **Change the page:** edit a file on GitHub (pencil icon) and commit. Streamlit updates the live page within a minute.
- **Refresh the company list now:** **Actions** > **Refresh company list** > **Run workflow**.
- **The app "goes to sleep":** free Streamlit apps sleep after a few days without visitors. Click **Yes, get this app back up** on the page; it wakes in about a minute.

## If something goes wrong

| What you see | What to do |
|---|---|
| "Setup needed: add SEC_CONTACT_EMAIL" | Add it in Streamlit **Secrets** (step 6). The spelling must match exactly. |
| "The company list has not been built yet" | Finish step 5 and wait for the green tick; the page picks the list up on its next restart. |
| "Alpha Vantage free limit reached" | You've used the 25 free calls for today. Market data returns tomorrow; everything else still works. |
| Market data shows "n/a" for one company | Alpha Vantage has no prices for that ticker. The rest of the profile is unaffected. |
| "Could not reach www.sec.gov" | The SEC was busy. Wait a minute and press **Show profile** again. |
| The business description is missing | Some annual reports are laid out unusually. Open the latest 10-K or 40-F from the SEC link. |
| The app shows a red error box | Copy the message and send it to me. |

## How the Reg M section works

| Test | Basis |
|---|---|
| Actively traded (no Rule 101 restricted period) | ADTV at least US$1M and public float at least US$150M |
| One business day | ADTV at least US$100K and float at least US$25M |
| Five business days | Everything else |
| Rule 102 | No actively-traded exception for the issuer's own security |
| Rule 139(a)(1) | 12+ months of SEC reporting, no late filings in 12 months, float at least US$75M, not a shell or blank-check company, no bankruptcy filing in 3 years. Foreign private issuers have an alternative path that needs a US$700M worldwide float |
| EGC | The emerging growth company box on the latest annual report cover (revenue cap US$1.235B) |
| FINRA 2241 | 10 days after an IPO and 3 days after a follow-on for managers and co-managers; none for EGC offerings |
| UMIR 7.7 | Highly liquid if Reg M actively traded, or 100+ trades and C$1M+ value per day |

**Approximations to keep in mind:**
- **ADTV:** a 60-calendar-day average from free daily prices, converted to US$. Reg M measures ADTV over the two full calendar months before filing, or 60 days ending within 10 days of pricing, so recompute at the actual date.
- **Public float:** the figure reported on the annual report cover, measured at the end of the second fiscal quarter.
- **Firm-side conditions:** some conditions depend on facts only the firm knows, such as whether a report is in the regular course or an initiation. The page lists these as "Firm checks".

This is a preliminary screen, not legal advice.

## Files

| File | What it does |
|---|---|
| `app.py` | The web page |
| `entity_profile.py` | Gathers one company's data |
| `regm.py` | Reg M and safe harbor rules |
| `pdf_report.py` | Builds the PDF summary |
| `sources.py` | Talks to SEC, Nasdaq Trader, Alpha Vantage and Finnhub |
| `sectors.py` | Technology and Biotech industry codes; U.S. and Canada location rules |
| `build_universe.py` | Builds `data/universe.csv` (run weekly by GitHub) |
| `setup/universe.yml` | The weekly schedule you paste into GitHub in step 5 |

**Run it on your own computer (optional):**
1. Install Python from python.org.
2. Open a terminal in this folder and run `pip install -r requirements.txt`.
3. Set your keys as environment variables.
4. Run `streamlit run app.py`.
