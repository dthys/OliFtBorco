#!/usr/bin/env python3
"""bol.com Order Tracker"""
import requests, json, os
from datetime import datetime, timezone, timedelta

CLIENT_ID     = os.environ.get("BOL_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("BOL_CLIENT_SECRET", "")

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
    r = requests.post(TOKEN_URL,
        data={"grant_type": "client_credentials"},
        auth=(CLIENT_ID, CLIENT_SECRET),
        headers={"Accept": "application/json"})
    r.raise_for_status()
    return r.json()["access_token"]


def load_existing():
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


def fetch_order_list(token, since_date):
    """Haal alle orders op. EAN zit direct in orderItems[].ean."""
    print(f"   Orders ophalen vanaf {since_date}...")
    headers = {"Authorization": f"Bearer {token}", "Accept": ACCEPT_HDR}
    orders, page = [], 1
    while True:
        r = requests.get(ORDERS_URL, headers=headers, params={
            "fulfilment-method": "ALL",
            "status": "ALL",
            "latest-change-date": since_date,
            "page": page,
        })
        if r.status_code == 404: break
        r.raise_for_status()
        batch = r.json().get("orders", [])
        if not batch: break
        orders.extend(batch)
        print(f"   Pagina {page}: {len(batch)} orders")
        page += 1
    return orders


def order_has_tracked_ean(order):
    """Check EAN direct in de orders list response (geen extra API call nodig)."""
    if not TRACKED_EANS:
        return True
    for item in order.get("orderItems", []):
        if item.get("ean") in TRACKED_EANS:
            return True
    return False


def fetch_order_detail(token, order_id):
    """Haal volledige details op (prijs, klant, adres etc.)"""
    headers = {"Authorization": f"Bearer {token}", "Accept": ACCEPT_HDR}
    r = requests.get(f"{ORDERS_URL}/{order_id}", headers=headers)
    r.raise_for_status()
    return r.json()


def simplify_order(order_summary, detail):
    """Combineer list-data en detail-data tot een dashboard record."""
    items = []
    for item in order_summary.get("orderItems", []):
        items.append({
            "orderItemId":    item.get("orderItemId"),
            "ean":            item.get("ean"),
            "quantity":       item.get("quantity", 1),
            "status":         item.get("fulfilmentStatus", ""),
            "fulfilment":     item.get("fulfilmentMethod", ""),
        })
    # Voeg prijs en klantinfo toe uit detail response
    if detail:
        b = detail.get("billingDetails", {})
        s = detail.get("shipmentDetails", {})
        for i, item in enumerate(detail.get("orderItems", [])):
            if i < len(items):
                items[i]["title"]          = item.get("product", {}).get("title", "")
                items[i]["unitPrice"]      = item.get("unitPrice", 0)
                items[i]["latestDelivery"] = item.get("fulfilment", {}).get("latestDeliveryDate", "")
    else:
        b, s = {}, {}
    return {
        "orderId":             order_summary.get("orderId"),
        "orderPlacedDateTime": order_summary.get("orderPlacedDateTime"),
        "customerName":        f"{b.get(chr(70)+chr(105)+chr(114)+chr(115)+chr(116)+chr(78)+chr(97)+chr(109)+chr(101),chr(32))} {b.get(chr(115)+chr(117)+chr(114)+chr(110)+chr(97)+chr(109)+chr(101),chr(32))}".strip(),
        "city":                s.get("city", ""),
        "countryCode":         s.get("countryCode", ""),
        "items":               items,
        "totalAmount":         sum(i.get("unitPrice", 0) * i.get("quantity", 1) for i in items),
    }


def main():
    print("Toegangstoken ophalen...")
    token = get_token()
    existing, since = load_existing()

    if since:
        print(f"Incrementele sync: {len(existing)} orders opgeslagen, controleer vanaf {since}")
    else:
        since = (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%d")
        print(f"Eerste run: volledige geschiedenis ophalen vanaf {since}")

    raw = fetch_order_list(token, since)
    print(f"   {len(raw)} orders opgehaald")

    # Filter op EAN direct uit de list response (snel, geen extra API calls)
    matched = [o for o in raw if order_has_tracked_ean(o)]
    print(f"   {len(matched)} orders matchen de EAN filter")

    # Haal details op enkel voor gematchte orders
    print("Details ophalen voor gematchte orders...")
    new_count = 0
    for o in matched:
        oid = o.get("orderId")
        try:
            detail = fetch_order_detail(token, oid)
            existing[oid] = simplify_order(o, detail)
            new_count += 1
        except Exception as e:
            print(f"   Fout bij {oid}: {e}")
            existing[oid] = simplify_order(o, None)
            new_count += 1

    all_orders = sorted(existing.values(),
        key=lambda o: o.get("orderPlacedDateTime") or "", reverse=True)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump({
            "lastUpdated": datetime.now(timezone.utc).isoformat(),
            "trackedEans": TRACKED_EANS,
            "orders":      all_orders,
        }, f, indent=2, ensure_ascii=False)

    print(f"Klaar: {new_count} nieuw/bijgewerkt, {len(all_orders)} totaal opgeslagen.")

if __name__ == "__main__":
    main()
