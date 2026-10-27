"""
Norrøna Outlet-Wächter: Lofoten-Jacken in XL
Fragt die JSON-Schnittstelle der Outlet-Seite ab und meldet per ntfy,
sobald eine Outlet-Farbvariante in Größe XL neu auf Lager ist.
"""
import json
import os
import sys
from pathlib import Path

import requests

BASE = "https://www.norrona.com"
PAGE_URL = f"{BASE}/de-DE/o/herren/?Category=Jackets&Concept=lofoten"
API_URL = f"{BASE}/de-DE/o/herren/json"
PARAMS = {"Category": "Jackets", "Concept": "lofoten"}
SIZE = "XL"
STATE = Path("xl_state.json")
NTFY_TOPIC = os.environ.get("NTFY_TOPIC")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "de-DE,de;q=0.9",
    "Referer": PAGE_URL,
}


def notify(title: str, body: str, click: str = PAGE_URL) -> None:
    print(f"[NOTIFY] {title}\n{body}")
    if NTFY_TOPIC:
        requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=body.encode("utf-8"),
            headers={"Title": title.encode("utf-8"), "Priority": "high", "Click": click},
            timeout=20,
        )


def fetch_products() -> list[dict]:
    products, page = [], 1
    while True:
        r = requests.get(API_URL, params={**PARAMS, "page": page, "size": 50},
                         headers=HEADERS, timeout=30)
        r.raise_for_status()
        data = r.json()
        batch = data.get("Products") or []
        products += batch
        if not batch or len(products) >= data.get("TotalMatching", 0) or page >= 10:
            return products
        page += 1


def available_in_size(products: list[dict]) -> dict[str, dict]:
    """Outlet-Modelle, die in SIZE vorrätig sind – Farbe egal (Schlüssel = URL ohne ?color=)."""
    result = {}
    for p in products:
        for v in p.get("OutletVariants") or []:
            stock = next((s.get("Inventory", 0) for s in v.get("SizeVariations") or []
                          if s.get("Size") == SIZE), 0)
            if stock and stock > 0 and v.get("Url"):
                model = BASE + v["Url"].split("?")[0]
                entry = result.setdefault(model, {"name": p.get("Name", "?"),
                                                  "colors": [], "stock": 0})
                entry["colors"].append(v.get("ColorName", "?"))
                entry["stock"] += stock
    for e in result.values():
        e["color"] = ", ".join(e["colors"])
    return result


def main() -> None:
    try:
        products = fetch_products()
    except Exception as e:  # Block, Seitenumbau, kein JSON …
        notify("Lofoten-Wächter: Abfrage fehlgeschlagen", f"{type(e).__name__}: {e}")
        sys.exit(1)

    # Schutz vor stillem Ausfall: Die Kategorie selbst darf nie leer sein
    if not products:
        notify("Lofoten-Wächter: 0 Produkte gefunden",
               "Die Schnittstelle liefert nichts – Seite geändert oder blockiert. Bitte prüfen.")
        sys.exit(1)

    current = available_in_size(products)
    previous = set(json.loads(STATE.read_text())) if STATE.exists() else None

    print(f"{len(products)} Outlet-Produkte geprüft, {len(current)} davon in {SIZE} vorrätig:")
    for url, info in sorted(current.items()):
        print(f"   {info['name']} | {info['color']} | {SIZE}: {info['stock']} | {url}")

    if previous is None:
        print("Erster Lauf: Stand gespeichert, keine Meldung.")
    else:
        new = {u: i for u, i in current.items() if u not in previous}
        if new:
            body = "\n".join(f"{i['name']} – {i['color']} ({SIZE}: {i['stock']})\n{u}"
                             for u, i in sorted(new.items()))
            click = next(iter(new)) if len(new) == 1 else PAGE_URL
            notify(f"Neu im Outlet in {SIZE}: {len(new)} Lofoten-Artikel", body, click)
        else:
            print("Nichts Neues.")

    STATE.write_text(json.dumps(sorted(current), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
