"""
Norrøna Lofoten-Jacken-Wächter
Prüft die Kategorieseite, vergleicht die Produkt-Links mit dem letzten Stand
und schickt bei neuen Artikeln eine Push-Nachricht über ntfy.sh.
"""
import json
import os
import sys
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import requests
from playwright.sync_api import sync_playwright

URL = "https://www.norrona.com/de-DE/o/herren/?Category=Jackets&Concept=lofoten"
STATE = Path("seen.json")
NTFY_TOPIC = os.environ.get("NTFY_TOPIC")  # z.B. "julius-lofoten-8f3k2x" – zufällig wählen!
KEYWORD = "lofoten"


def fetch_products() -> set[str]:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
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
        hrefs = page.eval_on_selector_all("a[href]", "els => els.map(e => e.href)")
        browser.close()

    products = set()
    for h in hrefs:
        u = urlsplit(urljoin(URL, h))
        path = u.path.lower()
        # Produktlinks: enthalten "lofoten", sind aber nicht die Kategorieseite selbst
        if KEYWORD in path and "/o/" not in path:
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
