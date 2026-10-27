"""
Norrøna Lofoten-Jacken-Wächter
Prüft die Kategorieseite, vergleicht die Produkt-Links mit dem letzten Stand
und schickt bei neuen Artikeln eine Push-Nachricht über ntfy.sh.
"""
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import requests
from playwright.sync_api import sync_playwright

URL = "https://www.norrona.com/de-DE/o/herren/jacken/?Concept=lofoten"
STATE = Path("seen.json")
NTFY_TOPIC = os.environ.get("NTFY_TOPIC")  # z.B. "julius-lofoten-8f3k2x" – zufällig wählen!
PRODUCT_RE = re.compile(r"^/de-de/produkte/lofoten/([^/]+)/?$")
CATEGORY_SLUGS = {"herren", "damen", "kinder", "unisex", "junior"}


def fetch_products() -> set[str]:
    with sync_playwright() as p:
        # Nutzt den auf GitHub-Runnern vorinstallierten Google Chrome (spart den Browser-Download)
        browser = p.chromium.launch(headless=True, channel="chrome")
        page = browser.new_page(
            locale="de-DE",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
            ),
        )
        page.goto(URL, wait_until="networkidle", timeout=60_000)
        # Lazy Loading: bis zum Ende scrollen
        for _ in range(10):
            page.mouse.wheel(0, 4000)
            page.wait_for_timeout(800)
        # Nur Links außerhalb von Kopfzeile, Menü und Fußzeile
        hrefs = page.eval_on_selector_all(
            "a[href]",
            "els => els.filter(e => !e.closest('header, nav, footer')).map(e => e.href)",
        )
        browser.close()

    products = set()
    for h in hrefs:
        u = urlsplit(urljoin(URL, h))
        m = PRODUCT_RE.match(u.path.lower())
        # Nur echte Produktseiten /produkte/lofoten/<modell>/, keine Kategorien
        if m and m.group(1) not in CATEGORY_SLUGS:
            products.add(f"{u.scheme}://{u.netloc}{u.path}")
    return products


def notify(title: str, body: str) -> None:
    print(f"[NOTIFY] {title}\n{body}")
    if NTFY_TOPIC:
        requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=body.encode("utf-8"),
            headers={"Title": title.encode("utf-8"), "Priority": "high", "Click": URL},
            timeout=20,
        )


def main() -> None:
    current = fetch_products()

    # Schutz vor stillem Ausfall: 0 Treffer = Seite geändert oder Bot-Block
    if not current:
        notify("Lofoten-Wächter: 0 Produkte gefunden",
               "Scraper liefert nichts – Seite geändert oder blockiert. Bitte prüfen.")
        sys.exit(1)

    seen = set(json.loads(STATE.read_text())) if STATE.exists() else None

    if seen is None:
        print(f"Erster Lauf: {len(current)} Produkte gespeichert, keine Meldung.")
        for c in sorted(current):
            print("  ", c)
    else:
        new = current - seen
        if new:
            notify(f"{len(new)} neue Lofoten-Jacke(n) bei Norrøna",
                   "\n".join(sorted(new)))
        else:
            print(f"Nichts Neues ({len(current)} Produkte).")
        current |= seen  # Vereinigung: verhindert Doppel-Alarme durch flackerndes Lazy Loading

    STATE.write_text(json.dumps(sorted(current), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
