#!/usr/bin/env python3
"""
bol.com Order Tracker
Gebruikt /shipments endpoint (zoals de Streamlit app) - geeft alle verzonden orders.
EAN zit in orderDetail["orderItems"][i]["product"]["ean"].
"""
import requests, json, os, time
from datetime import datetime, timezone

CLIENT_ID     = os.environ.get("BOL_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("BOL_CLIENT_SECRET", "")

TRACKED_EANS = [
    "5430004400110",
    "5430004400141",
    "5430004400158",
    "5430004400080",
]

OUTPUT_FILE   = "orders.json"
TOKEN_URL     = "https://login.bol.com/token"
BASE_URL      = "https://api.bol.com/retailer"
ACCEPT_HDR    = "application/vnd.retailer.v10+json"


def get_token():
    r = requests.post(TOKEN_URL,
        data={"grant_type": "client_credentials"},
        auth=(CLIENT_ID, CLIENT_SECRET),
        headers={"Accept": "application/json"})
    r.raise_for_status()
    return r.json()["access_token"]


def load_existing():
    if not os.path.exists(OUTPUT_FILE):
        return {}
    with open(OUTPUT_FILE, encoding="utf-8") as f:
        data = json.load(f)
    return {o["orderId"]: o for o in data.get("orders", [])}


def fetch_shipments(token, existing_order_ids):
    """
    Haal alle shipments op via /shipments (FBR + FBB).
    Stopt zodra we een shipment tegenkomen waarvan de order al opgeslagen is.
    """
    headers = {"Authorization": f"Bearer {token}", "Accept": ACCEPT_HDR}
    all_shipments = []
    for method in ["FBR", "FBB"]:
        page = 1
        stop = False
        while not stop:
            print(f"   [{method}] Pagina {page}...")
            r = requests.get(f"{BASE_URL}/shipments", headers=headers,
                params={"page": page, "fulfilment-method": method})
            if r.status_code == 404: break
            r.raise_for_status()
            batch = r.json().get("shipments", [])
            if not batch: break
            for s in batch:
                order_id = str(s["order"]["orderId"])
                if order_id in existing_order_ids:
                    stop = True
                    break
                all_shipments.append(s)
            page += 1
    return all_shipments


def fetch_order_detail(token, order_id):
    headers = {"Authorization": f"Bearer {token}", "Accept": ACCEPT_HDR}
    r = requests.get(f"{BASE_URL}/orders/{order_id}", headers=headers)
    r.raise_for_status()
    return r.json()


def detail_has_tracked_ean(detail):
    """EAN zit in detail["orderItems"][i]["product"]["ean"] (zoals in de Streamlit app)."""
    if not TRACKED_EANS: return True
    for item in detail.get("orderItems", []):
        ean = item.get("product", {}).get("ean", "")
        if str(ean) in TRACKED_EANS:
            return True
    return False


def simplify_order(order_id, shipment, detail):
    items = []
    for item in detail.get("orderItems", []):
        product = item.get("product", {})
        items.append({
            "orderItemId":    item.get("orderItemId"),
            "ean":            product.get("ean", ""),
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
        "orderId":             order_id,
        "orderPlacedDateTime": detail.get("orderPlacedDateTime", ""),
        "shipmentDateTime":    shipment.get("shipmentDateTime", ""),
        "customerName":        f"{b.get(chr(70)+chr(105)+chr(114)+chr(115)+chr(116)+chr(78)+chr(97)+chr(109)+chr(101),chr(32))} {b.get(chr(115)+chr(117)+chr(114)+chr(110)+chr(97)+chr(109)+chr(101),chr(32))}".strip(),
        "city":                s.get("city", ""),
        "countryCode":         s.get("countryCode", ""),
        "items":               items,
        "totalAmount":         sum(i.get("unitPrice", 0) * i.get("quantity", 1) for i in items),
    }


def main():
    print("Toegangstoken ophalen...")
    token = get_token()

    existing = load_existing()
    print(f"   {len(existing)} orders al opgeslagen")

    print("Shipments ophalen (stopt zodra bestaande orders gevonden worden)...")
    shipments = fetch_shipments(token, set(existing.keys()))
    print(f"   {len(shipments)} nieuwe shipments gevonden")

    print("EAN filter + details ophalen...")
    new_count = 0
    seen_orders = set()
    for s in shipments:
        order_id = str(s["order"]["orderId"])
        if order_id in seen_orders: continue
        seen_orders.add(order_id)
        try:
            time.sleep(0.05)
            detail = fetch_order_detail(token, order_id)
            if detail_has_tracked_ean(detail):
                existing[order_id] = simplify_order(order_id, s, detail)
                new_count += 1
                print(f"   Match: {order_id}")
        except Exception as e:
            print(f"   Fout bij {order_id}: {e}")

    all_orders = sorted(existing.values(),
        key=lambda o: o.get("shipmentDateTime") or o.get("orderPlacedDateTime") or "",
        reverse=True)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump({
            "lastUpdated": datetime.now(timezone.utc).isoformat(),
            "trackedEans": TRACKED_EANS,
            "orders":      all_orders,
        }, f, indent=2, ensure_ascii=False)

    print(f"Klaar: {new_count} nieuw opgeslagen, {len(all_orders)} totaal.")

if __name__ == "__main__":
    main()
