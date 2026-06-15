# 📦 Bol.com Order Tracker

A dashboard to track your bol.com retailer orders, shareable via GitHub Pages.

## How it works

```
GitHub Actions (runs hourly)
    └─▶ fetch_orders.py  (calls bol.com API)
            └─▶ orders.json  (saved to repo)
                    └─▶ index.html  (reads JSON, renders dashboard)
                            └─▶ GitHub Pages  (your friend opens the URL)
```

---

## Setup (5 steps)

### 1. Create a GitHub repository

1. Go to [github.com/new](https://github.com/new)
2. Name it e.g. `bol-order-tracker`
3. Set it to **Public** (required for free GitHub Pages)
4. Upload all files from this folder

### 2. Add your bol.com API credentials as Secrets

Never put credentials directly in code. Instead:

1. Go to your repo → **Settings** → **Secrets and variables** → **Actions**
2. Click **New repository secret** and add:
   - `BOL_CLIENT_ID` → your Client ID
   - `BOL_CLIENT_SECRET` → your Client Secret

> Get your credentials at [bol.com partner platform](https://partnerplatform.bol.com) under API credentials.

### 3. Configure your EAN filter

Open `fetch_orders.py` and edit the `TRACKED_EANS` list:

```python
TRACKED_EANS = [
    "8710123456789",  # Product A
    "8710987654321",  # Product B
]
```

Leave it as `[]` to track **all** your products.

### 4. Enable GitHub Pages

1. Go to your repo → **Settings** → **Pages**
2. Under **Source**, select **Deploy from a branch**
3. Choose branch: `main`, folder: `/ (root)`
4. Click **Save**

Your dashboard will be live at:
`https://YOUR-USERNAME.github.io/bol-order-tracker/`

### 5. Run the workflow once manually

1. Go to **Actions** tab in your repo
2. Click **Fetch Bol.com Orders**
3. Click **Run workflow**

After ~30 seconds, `orders.json` will be updated and the dashboard will show your orders.

---

## Dashboard features

- 🔍 **Filter by date range** — your friend can choose any period
- 🏷️ **Filter by EAN** — drill into a specific product
- 📊 **Live stats** — order count, units sold, revenue
- 🔄 **Auto-refreshes** every 5 minutes
- 📱 **Mobile-friendly**

## Adjusting sync frequency

Edit `.github/workflows/update-orders.yml` and change the cron schedule:

```yaml
- cron: '0 * * * *'      # every hour (default)
- cron: '*/30 * * * *'   # every 30 minutes
- cron: '0 */6 * * *'    # every 6 hours
```

## File overview

| File | Purpose |
|------|---------|
| `fetch_orders.py` | Python script that calls bol.com API and writes `orders.json` |
| `index.html` | The web dashboard served via GitHub Pages |
| `orders.json` | Auto-generated data file (committed by GitHub Actions) |
| `.github/workflows/update-orders.yml` | Scheduled GitHub Actions workflow |
