#!/usr/bin/env python3
"""
bol.com Order Tracker - Data Fetcher

Smart sync:
  First run  -> fetches ALL available orders (no date filter)
  Next runs  -> fetches only orders changed since last saved order date
               and merges them into orders.json
"""

import requests, json, os
from datetime import datetime, timezone, timedelta

# --- CONFIG ---
CLIENT_ID     = os.environ.get("BOL_CLIENT_ID",     "YOUR_CLIENT_ID_HERE")
CLIENT_SECRET = os.environ.get("BOL_CLIENT_SECRET", "YOUR_CLIENT_SECRET_HERE")

# Only show orders containing these EAN codes. Leave [] for all products.
TRACKED_EANS = [
  "5430004400110",
  "5430004400141",
  "5430004400158",
  "5430004400080",
]

OUTPUT_FILE = "orders.json"
TOKEN_URL   = "https://login.bol.com/token"
ORDERS_URL  = "https://api.bol.com/retailer/orders"
ACCEPT_HDR  = "application/vnd.retailer.v10+json"


def get_token():
    resp = requests.post(
        TOKEN_URL,
        data={"grant_type": "client_credentials"},
        auth=(CLIENT_ID, CLIENT_SECRET),
        headers={"Accept": "application/json"},
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def load_existing():
    """Returns (orders_dict keyed by orderId, since_date or None)."""
    if not os.path.exists(OUTPUT_FILE):
        return {}, None
    with open(OUTPUT_FILE, encoding="utf-8") as f:
        data = json.load(f)
    orders = {o["orderId"]: o for o in data.get("orders", [])}
    if not orders:
        return {}, None
    latest = max(o["orderPlacedDateTime"] for o in orders.values() if o.get("orderPlacedDateTime"))
    since  = (datetime.fromisoformat(latest.replace("Z", "+00:00")) - timedelta(days=1)).strftime("%Y-%m-%d")
    return orders, since


def fetch_order_list(token, since_date=None):
    """
    Paginate through orders.
    since_date=None  -> no date filter (first run, gets everything available)
    since_date=str   -> adds latest-change-date filter (incremental runs)
    """
    if since_date:
        print(f"   Incremental: fetching orders changed since {since_date}")
    else:
        print("   First run: fetching ALL available orders (no date filter)")

    headers = {"Authorization": f"Bearer {token}", "Accept": ACCEPT_HDR}
    orders, page = [], 1
    while True:
        params = {"fulfilment-method": "ALL", "status": "ALL", "page": page}
        if since_date:
            params["latest-change-date"] = since_date
        resp = requests.get(ORDERS_URL, headers=headers, params=params)
        if resp.status_code == 404: break
        resp.raise_for_status()
        batch = resp.json().get("orders", [])
        if not batch: break
        orders.extend(batch)
        print(f"   Page {page}: {len(batch)} orders")
        page += 1
    return orders


def fetch_order_detail(token, order_id):
    headers = {"Authorization": f"Bearer {token}", "Accept": ACCEPT_HDR}
    resp = requests.get(f"{ORDERS_URL}/{order_id}", headers=headers)
    resp.raise_for_status()
    return resp.json()


def ean_matches(detail):
    if not TRACKED_EANS: return True
    for item in detail.get("orderItems", []):
        if item.get("offer", {}).get("ean") in TRACKED_EANS: return True
        if item.get("product", {}).get("ean") in TRACKED_EANS: return True
    return False


def simplify_order(detail):
    items = []
    for item in detail.get("orderItems", []):
        offer, product = item.get("offer", {}), item.get("product", {})
        items.append({
            "orderItemId":    item.get("orderItemId"),
            "ean":            offer.get("ean") or product.get("ean"),
            "title":          product.get("title", ""),
            "quantity":       item.get("quantity", 1),
            "unitPrice":      item.get("unitPrice", 0),
            "status":         item.get("orderItemStatus", ""),
            "fulfilment":     item.get("fulfilment", {}).get("method", ""),
            "latestDelivery": item.get("fulfilment", {}).get("latestDeliveryDate", ""),
        })
    b = detail.get("billingDetails", {})
    s = detail.get("shipmentDetails", {})
    return {
        "orderId":             detail.get("orderId"),
        "orderPlacedDateTime": detail.get("orderPlacedDateTime"),
        "customerName":        f"{b.get(chr(70)+chr(105)+chr(114)+chr(115)+chr(116)+chr(78)+chr(97)+chr(109)+chr(101),chr(32))} {b.get(chr(115)+chr(117)+chr(114)+chr(110)+chr(97)+chr(109)+chr(101),chr(32))}".strip(),
        "city":                s.get("city", ""),
        "countryCode":         s.get("countryCode", ""),
        "items":               items,
        "totalAmount":         sum(i["unitPrice"] * i["quantity"] for i in items),
    }


def main():
    print("Fetching access token...")
    token = get_token()

    existing, since = load_existing()
    if existing:
        print(f"Incremental sync: {len(existing)} orders already saved.")
    else:
        print("First run: no existing data found.")

    # First run: since=None (no date filter)
    # Next runs: since=date string
    raw = fetch_order_list(token, since_date=since)
    print(f"   {len(raw)} orders returned by API")

    print("Filtering by EAN and fetching details...")
    new_count = 0
    for o in raw:
        oid = o.get("orderId")
        try:
            detail = fetch_order_detail(token, oid)
            if ean_matches(detail):
                existing[oid] = simplify_order(detail)
                new_count += 1
        except Exception as e:
            print(f"   Skipping {oid}: {e}")

    all_orders = sorted(existing.values(),
        key=lambda o: o.get("orderPlacedDateTime") or "", reverse=True)

    output = {
        "lastUpdated": datetime.now(timezone.utc).isoformat(),
        "trackedEans": TRACKED_EANS,
        "orders":      all_orders,
    }
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"Done: {new_count} new/updated, {len(all_orders)} total saved.")


if __name__ == "__main__":
    main()
