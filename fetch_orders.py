#!/usr/bin/env python3
"""
bol.com Order Tracker
First run  : scant 90 dagen terug in wekelijkse blokken voor volledige geschiedenis.
Next runs  : haalt enkel nieuwe orders op en voegt ze samen in orders.json
"""
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


def fetch_page(headers, params):
    r = requests.get(ORDERS_URL, headers=headers, params=params)
    if r.status_code == 404: return []
    r.raise_for_status()
    return r.json().get("orders", [])


def fetch_all_history(token, days_back=90):
    """Scan terug in wekelijkse blokken om volledige geschiedenis op te halen."""
    headers = {"Authorization": f"Bearer {token}", "Accept": ACCEPT_HDR}
    seen, all_orders = set(), []

    def add_batch(batch):
        for o in batch:
            if o["orderId"] not in seen:
                seen.add(o["orderId"])
                all_orders.append(o)

    # Eerst zonder datumfilter (actieve orders)
    print("   Blok: geen datumfilter (actieve orders)")
    page = 1
    while True:
        batch = fetch_page(headers, {"fulfilment-method": "ALL", "status": "ALL", "page": page})
        if not batch: break
        add_batch(batch)
        page += 1

    # Dan wekelijkse blokken terug in de tijd
    today = datetime.now(timezone.utc).date()
    for week in range(0, days_back, 7):
        d = (today - timedelta(days=week + 7)).isoformat()
        print(f"   Blok: latest-change-date={d}")
        page = 1
        while True:
            batch = fetch_page(headers, {
                "fulfilment-method": "ALL",
                "status": "ALL",
                "page": page,
                "latest-change-date": d,
            })
            if not batch: break
            add_batch(batch)
            page += 1

    print(f"   Totaal unieke orders gevonden: {len(all_orders)}")
    return all_orders


def fetch_incremental(token, since_date):
    """Haal enkel orders op gewijzigd sinds since_date."""
    print(f"   Incrementeel: orders gewijzigd sinds {since_date}")
    headers = {"Authorization": f"Bearer {token}", "Accept": ACCEPT_HDR}
    orders, page = [], 1
    while True:
        batch = fetch_page(headers, {
            "fulfilment-method": "ALL",
            "status": "ALL",
            "page": page,
            "latest-change-date": since_date,
        })
        if not batch: break
        orders.extend(batch)
        page += 1
    return orders


def fetch_order_detail(token, order_id):
    headers = {"Authorization": f"Bearer {token}", "Accept": ACCEPT_HDR}
    r = requests.get(f"{ORDERS_URL}/{order_id}", headers=headers)
    r.raise_for_status()
    return r.json()


def ean_matches(detail):
    if not TRACKED_EANS: return True
    for item in detail.get("orderItems", []):
        for ean in [
            item.get("offer", {}).get("ean"),
            item.get("product", {}).get("ean"),
            item.get("ean"),
        ]:
            if ean and str(ean) in TRACKED_EANS:
                return True
    found = {str(v) for item in detail.get("orderItems",[]) for v in [item.get("offer",{}).get("ean"), item.get("product",{}).get("ean"), item.get("ean")] if v}
    print(f"   Geen EAN match voor {detail.get(chr(111)+chr(114)+chr(100)+chr(101)+chr(114)+chr(73)+chr(100))} - gevonden: {found or chr(40)+chr(110)+chr(111)+chr(110)+chr(101)+chr(41)}")
    return False


def simplify_order(detail):
    items = []
    for item in detail.get("orderItems", []):
        offer, product = item.get("offer", {}), item.get("product", {})
        items.append({
            "orderItemId":    item.get("orderItemId"),
            "ean":            offer.get("ean") or product.get("ean") or item.get("ean"),
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
    print("Toegangstoken ophalen...")
    token = get_token()
    existing, since = load_existing()

    if since:
        print(f"Incrementele sync: {len(existing)} orders opgeslagen, controleer vanaf {since}")
        raw = fetch_incremental(token, since)
    else:
        print("Eerste run: 90 dagen geschiedenis ophalen in wekelijkse blokken...")
        raw = fetch_all_history(token, days_back=90)

    print(f"   {len(raw)} orders te verwerken")
    print("EAN filter toepassen en details ophalen...")
    new_count = 0
    for o in raw:
        oid = o.get("orderId")
        try:
            detail = fetch_order_detail(token, oid)
            if ean_matches(detail):
                existing[oid] = simplify_order(detail)
                new_count += 1
        except Exception as e:
            print(f"   Overslaan {oid}: {e}")

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
