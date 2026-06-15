#!/usr/bin/env python3
"""
bol.com Order Tracker - Data Fetcher
Runs via GitHub Actions to pull orders and save orders.json
"""

import requests
import json
import os
from datetime import datetime, timezone

# ─── CONFIG ───────────────────────────────────────────────────────────────────
# Replace with your bol.com Retailer API credentials
# In GitHub Actions, set these as repository secrets:
#   BOL_CLIENT_ID and BOL_CLIENT_SECRET
CLIENT_ID     = os.environ.get("BOL_CLIENT_ID",     "YOUR_CLIENT_ID_HERE")
CLIENT_SECRET = os.environ.get("BOL_CLIENT_SECRET", "YOUR_CLIENT_SECRET_HERE")

print(f"Using Client ID: {CLIENT_ID[:6]}..." if len(CLIENT_ID) > 6 else f"Client ID: '{CLIENT_ID}'")

# Only include order items matching these EAN codes.
# Leave empty [] to include ALL products.
TRACKED_EANS = [
    "5430004400110",
    "5430004400141",
    "5430004400158",
    "5430004400080",
]

# Output file (committed to repo, served by GitHub Pages)
OUTPUT_FILE = "orders.json"
# ──────────────────────────────────────────────────────────────────────────────

TOKEN_URL  = "https://login.bol.com/token"
ORDERS_URL = "https://api.bol.com/retailer/orders"
ORDER_URL  = "https://api.bol.com/retailer/orders/{order_id}"
ACCEPT_HDR = "application/vnd.retailer.v10+json"


def get_token():
    """Fetch an OAuth2 access token using client credentials."""
    resp = requests.post(
        TOKEN_URL,
        data={"grant_type": "client_credentials"},
        auth=(CLIENT_ID, CLIENT_SECRET),
        headers={"Accept": "application/json"},
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def fetch_all_orders(token):
    """Paginate through all open + shipped orders."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": ACCEPT_HDR,
    }
    orders = []
    for status in ["OPEN", "SHIPPED"]:
        page = 1
        while True:
            params = {"fulfilment-method": "FBR", "status": status, "page": page}
            resp = requests.get(ORDERS_URL, headers=headers, params=params)
            if resp.status_code == 404:
                break  # no more pages
            resp.raise_for_status()
            data = resp.json()
            batch = data.get("orders", [])
            if not batch:
                break
            orders.extend(batch)
            page += 1
    return orders


def fetch_order_detail(token, order_id):
    """Fetch full order detail (includes items with EAN)."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": ACCEPT_HDR,
    }
    resp = requests.get(ORDER_URL.format(order_id=order_id), headers=headers)
    resp.raise_for_status()
    return resp.json()


def ean_matches(order_detail):
    """Return True if any order item matches a tracked EAN (or if no filter)."""
    if not TRACKED_EANS:
        return True
    for item in order_detail.get("orderItems", []):
        offer = item.get("offer", {})
        if offer.get("ean") in TRACKED_EANS:
            return True
        product = item.get("product", {})
        if product.get("ean") in TRACKED_EANS:
            return True
    return False


def simplify_order(detail):
    """Extract the fields we want to display in the dashboard."""
    items = []
    for item in detail.get("orderItems", []):
        offer   = item.get("offer", {})
        product = item.get("product", {})
        items.append({
            "orderItemId":  item.get("orderItemId"),
            "ean":          offer.get("ean") or product.get("ean"),
            "title":        product.get("title", ""),
            "quantity":     item.get("quantity", 1),
            "unitPrice":    item.get("unitPrice", 0),
            "status":       item.get("orderItemStatus", ""),
            "fulfilment":   item.get("fulfilment", {}).get("method", ""),
            "latestDelivery": item.get("fulfilment", {}).get("latestDeliveryDate", ""),
        })

    billing = detail.get("billingDetails", {})
    shipping = detail.get("shipmentDetails", {})

    return {
        "orderId":       detail.get("orderId"),
        "orderPlacedDateTime": detail.get("orderPlacedDateTime"),
        "customerName":  f"{billing.get('firstName', '')} {billing.get('surname', '')}".strip()
                          or shipping.get("firstName", "") + " " + shipping.get("surname", ""),
        "city":          shipping.get("city", ""),
        "countryCode":   shipping.get("countryCode", ""),
        "items":         items,
        "totalAmount":   sum(i["unitPrice"] * i["quantity"] for i in items),
    }


def main():
    print("🔑 Fetching access token...")
    token = get_token()

    print("📦 Fetching order list...")
    raw_orders = fetch_all_orders(token)
    print(f"   Found {len(raw_orders)} orders total.")

    print("🔍 Fetching order details & filtering by EAN...")
    results = []
    for o in raw_orders:
        oid = o.get("orderId")
        try:
            detail = fetch_order_detail(token, oid)
            if ean_matches(detail):
                results.append(simplify_order(detail))
        except Exception as e:
            print(f"   ⚠️  Skipping order {oid}: {e}")

    print(f"   ✅ {len(results)} orders match the EAN filter.")

    output = {
        "lastUpdated": datetime.now(timezone.utc).isoformat(),
        "trackedEans": TRACKED_EANS,
        "orders": results,
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"💾 Saved {len(results)} orders to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
