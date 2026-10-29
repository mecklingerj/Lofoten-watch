"""
Norrøna Outlet-Wächter: Lofoten-Jacken in XL (Farbe egal)

Liest die Outlet-Seite (Nuxt-Shop, Daten im eingebetteten __NUXT_DATA__-Block),
filtert auf Kollektion Lofoten + Jacken & Tops + Größe XL mit Bestand > 0
und meldet per ntfy, sobald ein Modell neu in XL verfügbar ist.
Fehler werden einmal gemeldet (nicht stündlich) und die Erholung ebenfalls.
"""
import json
import os
import re
import sys
from pathlib import Path

import requests

BASE = "https://www.norrona.com"
PAGE_URL = f"{BASE}/de/de/produkte/reduziert/herren"
CONCEPT = "lofoten"
TYPE_ID = "jackets_tops"          # Jacken, Anoraks, Westen, Hoodies …
SIZE = "XL"
STATE = Path("xl_state.json")
NTFY_TOPIC = os.environ.get("NTFY_TOPIC")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "de-DE,de;q=0.9",
}

SPECIAL = {"Reactive", "ShallowReactive", "Ref", "ShallowRef", "EmptyRef",
           "EmptyShallowRef", "Date", "Set", "Map", "NuxtError", "Island"}


# ---------- Benachrichtigung ----------

def notify(title: str, body: str, click: str = PAGE_URL) -> None:
    print(f"[NOTIFY] {title}\n{body}")
    if NTFY_TOPIC:
        requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=body.encode("utf-8"),
            headers={"Title": title.encode("utf-8"), "Priority": "high", "Click": click},
            timeout=20,
        )


# ---------- Daten holen und dekodieren ----------

def load_payload() -> list:
    r = requests.get(PAGE_URL, headers=HEADERS, timeout=30)
    r.raise_for_status()
    m = re.search(r'<script[^>]*id="__NUXT_DATA__"[^>]*>(.*?)</script>', r.text, re.S)
    if not m:
        raise RuntimeError(f"Kein __NUXT_DATA__ gefunden (HTTP {r.status_code}, "
                           f"{len(r.text)} Zeichen) – Seite umgebaut oder blockiert")
    return json.loads(m.group(1))


def make_resolver(arr: list):
    """Dekodiert das Nuxt/devalue-Format: Werte referenzieren sich über Array-Indizes."""
    cache: dict[int, object] = {}

    def rv(i, depth=0):
        if not isinstance(i, int) or isinstance(i, bool):
            return i
        if i < 0 or i >= len(arr) or depth > 60:
            return None
        if i in cache:
            return cache[i]
        v = arr[i]
        if isinstance(v, list):
            if v and isinstance(v[0], str) and v[0] in SPECIAL:
                out = v[1] if v[0] == "Date" else (rv(v[1], depth + 1) if len(v) > 1 else None)
            else:
                out = [rv(x, depth + 1) for x in v]
        elif isinstance(v, dict):
            out = {k: rv(x, depth + 1) for k, x in v.items()}
        else:
            out = v
        cache[i] = out
        return out

    return rv


def extract_products(arr: list) -> list[dict]:
    rv = make_resolver(arr)
    return [rv(i) for i, v in enumerate(arr)
            if isinstance(v, dict) and {"variants", "concept", "slug"} <= v.keys()]


def name_of(obj, key="name"):
    return (obj or {}).get(key) if isinstance(obj, dict) else None


def available_in_size(products: list[dict]) -> tuple[dict[str, dict], int]:
    """Lofoten-Jackenmodelle mit Bestand in SIZE. Rückgabe: (Treffer, Anzahl Lofoten-Jacken gesamt)."""
    result, n_relevant = {}, 0
    for p in products:
        if (name_of(p.get("concept")) or "").lower() != CONCEPT:
            continue
        if name_of(p.get("type"), "id") != TYPE_ID:
            continue
        n_relevant += 1
        colors, total = [], 0
        for v in p.get("variants") or []:
            for entry in v.get("stock") or []:
                s = (entry or {}).get("s") or []
                if len(s) >= 2 and isinstance(s[0], str) and s[0].endswith(f" {SIZE}") \
                        and isinstance(s[1], (int, float)) and s[1] > 0:
                    colors.append(name_of(v.get("color"), "description") or "?")
                    total += int(s[1])
        if total:
            url = f"{BASE}/de/de/produkt/{CONCEPT}/{p['slug']}"
            result[url] = {"name": p.get("name", "?"), "color": ", ".join(colors), "stock": total}
    return result, n_relevant


# ---------- Zustand ----------

def load_state() -> dict:
    if not STATE.exists():
        return {"models": None, "failing": False}
    try:
        data = json.loads(STATE.read_text())
    except json.JSONDecodeError:
        return {"models": None, "failing": False}   # kaputte Datei -> neu aufbauen
    if isinstance(data, list):                        # altes Format
        return {"models": [], "failing": False}       # alte URLs ungültig -> leere Basis
    return {"models": data.get("models"), "failing": bool(data.get("failing"))}


def save_state(models, failing: bool) -> None:
    STATE.write_text(json.dumps({"models": sorted(models) if models is not None else None,
                                 "failing": failing}, indent=2, ensure_ascii=False))


# ---------- Ablauf ----------

def main() -> None:
    state = load_state()

    try:
        products = extract_products(load_payload())
        if not products:
            raise RuntimeError("0 Produkte im Outlet gefunden – Seitenstruktur geändert?")
        current, n_relevant = available_in_size(products)
        if n_relevant == 0:
            raise RuntimeError(f"Keine {CONCEPT}-Jacken unter {len(products)} Outlet-Produkten "
                               "– Filter passt nicht mehr?")
    except Exception as e:
        print(f"FEHLER: {type(e).__name__}: {e}")
        if not state["failing"]:                      # nur beim ersten Fehler melden
            notify("Lofoten-Wächter: Abfrage fehlgeschlagen",
                   f"{type(e).__name__}: {e}\n\nWeitere Fehler werden nicht erneut gemeldet.")
        save_state(state["models"], failing=True)
        return

    if state["failing"]:
        notify("Lofoten-Wächter läuft wieder", "Die Abfrage funktioniert wieder.")

    print(f"{len(products)} Outlet-Produkte, davon {n_relevant} {CONCEPT}-Jacken; "
          f"{len(current)} Modell(e) in {SIZE} vorrätig:")
    for url, info in sorted(current.items()):
        print(f"   {info['name']} | {info['color']} | {SIZE}: {info['stock']} | {url}")

    previous = state["models"]
    if previous is None:
        print("Erster Lauf: Stand gespeichert, keine Meldung.")
    else:
        new = {u: i for u, i in current.items() if u not in set(previous)}
        if new:
            body = "\n".join(f"{i['name']} – {i['color']} ({SIZE}: {i['stock']})\n{u}"
                             for u, i in sorted(new.items()))
            click = next(iter(new)) if len(new) == 1 else PAGE_URL
            notify(f"Neu im Outlet in {SIZE}: {len(new)} Lofoten-Artikel", body, click)
        else:
            print("Nichts Neues.")

    save_state(current.keys(), failing=False)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # letzte Absicherung: nie still abstürzen
        notify("Lofoten-Wächter: Skriptfehler", f"{type(e).__name__}: {e}")
        raise
