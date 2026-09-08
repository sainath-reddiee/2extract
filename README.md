# 2extract geo + mobile scraping

Python scrapers that send traffic through [2extract](https://docs.2extract.com/) residential and mobile proxies. Targeting is set on the **proxy username**, not on headers.

Two pipelines:

1. **Geo** — resolve a place through the Geo API, then scrape as if you were in that country / city / ZIP.
2. **Mobile** — send the same request through a carrier IP (`-isp-310260` is T-Mobile US in the docs).

Official docs used while building this folder: [Quick start](https://docs.2extract.com/getting-started/quick-start.md), [Authentication](https://docs.2extract.com/proxy-products/configuration/authentication.md), [Geo targeting](https://docs.2extract.com/proxy-products/configuration/geo-targeting.md), [Mobile proxies](https://docs.2extract.com/proxy-products/mobile/introduction-use-cases.md), [Python + Requests](https://docs.2extract.com/integrations/frameworks/python-requests.md), [Geo API](https://docs.2extract.com/public-api/geo.md), [Acceptable Use Policy](https://docs.2extract.com/legal/acceptable-use-policy.md).

---

## What you must do (I cannot do these for you)

Everything below is account / billing / secret work on [2extract.com](https://2extract.com). The code in this folder will fail until these are done.

### 1. Create an account

Sign up and open the dashboard: [https://2extract.com/app](https://2extract.com/app).

### 2. Verify identity if you will deposit more than $50

Unverified accounts have a **$50 lifetime deposit cap**. Optional for a small test. Process: Profile → Start Verification (Didit, government ID + selfie). Guide: [KYC](https://docs.2extract.com/guides/kyc.md).

### 3. Top up the account balance

Pay-as-you-go proxies bill this wallet. **Minimum top-up is $10** via Stripe.

1. Dashboard → **Billing**
2. Choose an amount → **Top Up** → pay

Residential and mobile traffic are both charged from this same balance. Mobile is the more expensive product. Guide: [Billing & usage](https://docs.2extract.com/guides/billing-usage.md).

### 4. Create an API key

Needed for geo lookup, balance checks, and optional proxy creation from this repo.

1. Dashboard → **API Keys** → **Create API Key**
2. Enable at least: `geo:read`, `proxies:read`, `proxies:write`, `balance:read`
3. Copy the key immediately (`2xt_...`). It is shown **once**.

Docs: [API keys](https://docs.2extract.com/public-api/api-keys.md). Put it in `.env` as `TWOEXTRACT_API_KEY`.

### 5. Create two proxies

Create **one residential** proxy and **one mobile** proxy. One residential proxy already covers every country — the country is a username parameter, so do **not** create a proxy per market.

**Names are immutable.** Allowed characters: lowercase letters, digits, underscores. **No hyphens** (a hyphen is the parameter separator).

| Proxy name (suggested) | Type | Used by |
| --- | --- | --- |
| `geo_scraper` | Residential, HTTP(S) | `scripts/first_request.py`, `scripts/scrape_geo.py` |
| `mobile_scraper` | Mobile, HTTP(S) | `scripts/scrape_mobile.py` |

**Dashboard path**

1. **My Proxies** → **+ Create Proxy**
2. Name `geo_scraper`, type Residential, leave defaults, create
3. Repeat for `mobile_scraper`, type Mobile
4. On each proxy’s settings page, **Copy Credentials** in `username:password@host:port` form

Host/port are always `proxy.2extract.net:5555`.

**Or from this repo** (after step 4, with a funded account):

```powershell
python scripts/provision_proxies.py
```

Then paste the returned username + password into `.env`. The password is not emailed.

Optional: set a monthly spend cap on each proxy so a runaway script cannot drain the wallet. Docs: [Create proxy](https://docs.2extract.com/public-api/proxies.md).

### 6. Put secrets in `.env`

From this folder:

```powershell
copy .env.example .env
```

Fill in:

- `TWOEXTRACT_USERNAME` / `TWOEXTRACT_PASSWORD` — residential (`geo_scraper`)
- `TWOEXTRACT_MOBILE_USERNAME` / `TWOEXTRACT_MOBILE_PASSWORD` — mobile (`mobile_scraper`)
- `TWOEXTRACT_API_KEY`

Username must be the **base** value only, for example `2xt-customer-xxxx-proxy-geo_scraper`. Do not paste `-country-us` onto it; the scripts add targeting.

### 7. Install Python deps

Python 3.10+ recommended. From this `2extract` folder:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 8. Prove the gateway works

```powershell
python scripts\account_status.py
python scripts\first_request.py
```

You should see spendable funds and a JSON object with an exit IP that is **not** your home IP. If this fails, stop — geo/mobile scrapes will fail the same way. Common causes: [407](https://docs.2extract.com/help/common-problems/407-proxy-authentication-required.md) (bad username/password), zero balance, or targeting already glued onto the username.

### 9. Resolve geo codes (do not guess)

City/state slugs are not English names. `Los Angeles` must become `losangeles`. Look them up:

```powershell
python scripts\lookup_geo.py --country US --state California --city "Los Angeles" --zips
python scripts\lookup_geo.py --country IN
```

Catalogs: [countries](https://docs.2extract.com/data/countries.md), [states](https://docs.2extract.com/data/states.md), [cities](https://docs.2extract.com/data/cities.md), [ZIPs](https://docs.2extract.com/data/zips.md).

### 10. Run eCommerce price monitoring

This is the easiest 2extract residential use case: scrape product name, price, and stock as a local US shopper. Source is the public practice store [books.toscrape.com](https://books.toscrape.com/) (100 products by default). A sticky `-session` keeps one IP for the whole browse.

Writes sheets **eCommerce prices** and **Price summary** in `data/output/2extract_results.xlsx`.

```powershell
python scripts\scrape_ecommerce.py
python scripts\scrape_geo.py
python scripts\scrape_ecommerce.py --count 100 --country us
```

### 11. Run the mobile scraper

Look up a carrier code in the [ISP catalog](https://docs.2extract.com/data/isp.md). Default `310260` is T-Mobile US from the [mobile quick start](https://docs.2extract.com/proxy-products/mobile/quick-start.md).

`-isp` **cannot** be combined with `-country` / `-state` / `-city` / `-zip`.

```powershell
python scripts\scrape_mobile.py
python scripts\scrape_mobile.py --isp 310260 --sticky
```

`--sticky` adds `-session-...-time-10` so the carrier IP stays still for the run. Mobile sessions drop more often than residential; the client retries 502/504. Writes the **Mobile scrape** sheet in `data/output/2extract_results.xlsx`.

### 12. Stay inside the rules

Read the [AUP](https://docs.2extract.com/legal/acceptable-use-policy.md) before you point these scripts at other sites. Do not use this network for unauthorized access, account farming, scalping, spam, or anything illegal. Only collect public pages you are allowed to collect. Cap spend on the proxy. Watch usage on the proxy settings page.

---

## What this folder already contains

| Path | Role |
| --- | --- |
| `twextract/username.py` | Builds `...-country-us-city-losangeles` and rejects illegal combos |
| `twextract/client.py` | HTTPS proxy to `proxy.2extract.net:5555`, retries 502/504 |
| `twextract/api.py` | REST: geo, balance, plans, create proxy (`X-API-Key`) |
| `twextract/excel_export.py` | Formatted Excel workbook (`data/output/2extract_results.xlsx`) |
| `twextract/mobile_scrape.py` | Carrier scrape + mobile User-Agent |
| `locations.json` | Sample markets (codes taken from the docs) |
| `scripts/` | Commands above |
| `tests/test_username.py` | Username rules, no network |

```
2extract/
  .env.example
  locations.json
  requirements.txt
  twextract/
  scripts/
  tests/
  data/output/
```

---

## Targeting cheatsheet

Gateway: `https://USERNAME:PASSWORD@proxy.2extract.net:5555`

| Goal | Username suffix |
| --- | --- |
| Germany | `-country-de` |
| California | `-country-us-state-california` |
| Los Angeles | `-country-us-state-california-city-losangeles` |
| ZIP 90210 | `-country-us-zip-90210` |
| T-Mobile US (mobile proxy) | `-isp-310260` |
| Sticky IP 30 min | `-session-abc123-time-30` |
| Sticky, fail if IP dies | `-session-abc123-const` |

Hard rules:

- `city` / `state` / `zip` require `country`
- geo **or** `asn`/`isp`, never both
- `-const` has **no value**
- new targeting → new session id
- HTTP(S) for scraping; SOCKS5 is for non-web TCP

---

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| `Missing TWOEXTRACT_USERNAME` | `.env` is in this folder, not the repo root |
| 407 / `proxy '...' inactive` | My Proxies → open the proxy → **Actions** → set Status to **Active**. Credentials can be correct and still 407 while Inactive. |
| `parameter conflict` | Drop `-country` when using `-isp` |
| `dependency missing` | Add `-country` next to `-city` |
| `No available proxies for the requested target` | Broaden city/ZIP to country |
| `Zero balance` | Billing top-up |
| `Session IP is offline` | Retry, or omit `-const` |
| Steam price missing | Page layout changed; exit IP JSON still proves geo routing |

Verbose curl (from the [auth docs](https://docs.2extract.com/proxy-products/configuration/authentication.md)):

```powershell
curl -v "https://api.ipify.org?format=json" --proxy "https://proxy.2extract.net:5555" --proxy-user "YOUR_USERNAME:YOUR_PASSWORD"
```

Read `X-2extract-Error` or `X-Proxy-Error` before changing anything else.

Offline check of username rules:

```powershell
python -m unittest tests.test_username
```
