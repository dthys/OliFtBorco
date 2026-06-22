#!/usr/bin/env python3
"""
bol.com Order Tracker
Eerste run : haalt alle orders op van de laatste 90 dagen (max API limiet).
Volgende runs : haalt enkel nieuwe orders op en voegt samen in orders.json.
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


def fetch_pages(headers, fulfilment, status, since_date=None):
    """Pagineer door orders voor een specifieke combinatie van parameters."""
    orders, page = [], 1
    while True:
        params = {
            "fulfilment-method": fulfilment,
            "status": status,
            "page": page,
        }
        if since_date:
            params["latest-change-date"] = since_date
        r = requests.get(ORDERS_URL, headers=headers, params=params)
        if r.status_code in (400, 404): break
        r.raise_for_status()
        batch = r.json().get("orders", [])
        if not batch: break
        orders.extend(batch)
        print(f"     [{fulfilment}/{status}] Pagina {page}: {len(batch)} orders")
        page += 1
    return orders


def fetch_all(token, since_date=None):
    """Haal orders op voor FBR+FBB en OPEN+SHIPPED, dedupliceert op orderId."""
    headers = {"Authorization": f"Bearer {token}", "Accept": ACCEPT_HDR}
    seen, all_orders = set(), []

    for fulfilment in ["FBR", "FBB"]:
        for status in ["OPEN", "SHIPPED"]:
            batch = fetch_pages(headers, fulfilment, status, since_date)
            for o in batch:
                if o["orderId"] not in seen:
                    seen.add(o["orderId"])
                    all_orders.append(o)

    return all_orders


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
    found = {str(v) for item in detail.get("orderItems",[]) for v in [
        item.get("offer",{}).get("ean"),
        item.get("product",{}).get("ean"),
        item.get("ean")] if v}
    print(f"   Geen match voor {detail.get(chr(111)+chr(114)+chr(100)+chr(101)+chr(114)+chr(73)+chr(100))} - EANs: {found or chr(40)+chr(110)+chr(111)+chr(110)+chr(101)+chr(41)}")
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
    else:
        since = (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%d")
        print(f"Eerste run: volledige geschiedenis ophalen vanaf {since} (max 90 dagen)")

    raw = fetch_all(token, since_date=since)
    print(f"   {len(raw)} unieke orders opgehaald")

    print("EAN filter toepassen...")
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
