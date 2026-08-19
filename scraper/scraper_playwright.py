"""
scraper_playwright.py — motor "navegador real" (Playwright + stealth)
-----------------------------------------------------------------------
Mismo scraper que scraper.py pero pegandole a la API de PedidosYa desde
JS ejecutado DENTRO de un Chromium real (headless), no desde `requests`.
Motivo: PedidosYa (PerimeterX) esta bloqueando el motor `requests` con
403/captcha, tanto desde IPs de datacenter (GitHub Actions) como a veces
desde IP residencial. Un navegador real que ejecuta JS, tiene el stack de
red/TLS de Chrome de verdad y pasa por playwright-stealth (parcha las
señales tipicas de deteccion de headless) es mucho mas dificil de
distinguir de un usuario real.

Requisitos (una sola vez):
    pip install -r requirements.txt
    python3 -m playwright install chromium

Corre 1 vez por dia (10:15 ART) — igual que scraper.py, ver ese archivo
para el motivo de por que se dejo de correr 2x/dia.

Uso: identico a scraper.py
    python3 scraper_playwright.py
    python3 scraper_playwright.py --fecha 2026-08-20 --out-dir ../data/raw
"""

import json
import random
import sys
import time
import urllib.parse
from datetime import datetime

from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

from common import (
    BASE,
    HOME,
    KEYWORD,
    TZ,
    VENDOR_ID,
    ZONA,
    build_arg_parser,
    productos_a_filas,
    reportar_y_guardar,
)


class ApiError(Exception):
    def __init__(self, status, url, body=""):
        super().__init__(f"HTTP {status} en {url}: {body[:200]}")
        self.status = status


def api_fetch(page, url, params=None):
    full_url = url
    if params:
        full_url = f"{url}?{urllib.parse.urlencode(params)}"
    result = page.evaluate(
        """
        async (url) => {
            try {
                const r = await fetch(url, {
                    method: "GET",
                    headers: {"Accept": "application/json"},
                    credentials: "include",
                });
                const text = await r.text();
                return {status: r.status, text: text};
            } catch (err) {
                return {status: 0, text: String(err)};
            }
        }
        """,
        full_url,
    )
    if result["status"] != 200:
        raise ApiError(result["status"], full_url, result["text"])
    return json.loads(result["text"])


def get_categories(page, vendor_id):
    data = api_fetch(page, f"{BASE}/vendors/{vendor_id}/categories")
    out = []

    def walk(cats, parent=None):
        for c in cats:
            out.append({"id": c["id"], "name": c.get("name", ""),
                        "qty": c.get("children_qty"), "parent": parent})
            if c.get("children"):
                walk(c["children"], c.get("name"))

    walk(data.get("categories", []))
    return out


def get_products(page, vendor_id, category_id, limit=50, max_pages=30):
    items = []
    for pageno in range(max_pages):
        d = api_fetch(page, f"{BASE}/vendors/{vendor_id}/products",
                       params={"categoryId": category_id, "limit": limit, "page": pageno})
        items += d.get("items", [])
        if d.get("lastPage") or not d.get("items"):
            break
        time.sleep(random.uniform(0.5, 1.1))
    return items


def get_all_beers(page, vendor_id, keyword):
    cats = get_categories(page, vendor_id)
    target = [c for c in cats if keyword.lower() in (c["name"] or "").lower()]
    if not target:
        print(f"[AVISO] No hay categorias con '{keyword}'. Disponibles:")
        for c in cats[:40]:
            print("   ", c["name"])
        return []
    print("[INFO] Categorias de cerveza:")
    for c in target:
        print(f"   - {c['name']} (declara {c['qty']})")
    by_id = {}
    for c in target:
        for it in get_products(page, vendor_id, c["id"]):
            by_id[str(it["id"])] = it
        time.sleep(random.uniform(0.3, 0.8))
    return list(by_id.values())


def main():
    args = build_arg_parser().parse_args()
    ahora = datetime.now(TZ)
    fecha = args.fecha or ahora.strftime("%Y-%m-%d")

    print("=" * 55)
    print("  Scraper PedidosYa Market - Nunez (motor: playwright)")
    print(f"  Vendor: {VENDOR_ID}  |  Zona: {ZONA}  |  Fecha: {fecha}")
    print("=" * 55)

    stealth = Stealth()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            locale="es-AR",
            timezone_id="America/Argentina/Buenos_Aires",
            viewport={"width": 1366, "height": 850},
        )
        stealth.apply_stealth_sync(context)
        page = context.new_page()

        try:
            page.goto(HOME, wait_until="load", timeout=45000)
        except Exception as e:
            print(f"\n[ERROR] no pude cargar la home: {e}")
            browser.close()
            sys.exit(1)

        # dwell time + un scroll, para parecer un usuario real antes de pegarle a la API
        time.sleep(random.uniform(1.5, 3.0))
        try:
            page.mouse.wheel(0, random.randint(300, 900))
        except Exception:
            pass
        time.sleep(random.uniform(0.5, 1.2))

        try:
            productos = get_all_beers(page, VENDOR_ID, KEYWORD)
        except ApiError as e:
            print(f"\n[ERROR HTTP {e.status}] {e}")
            browser.close()
            sys.exit(1)
        except Exception as e:  # noqa: BLE001 - cualquier falla de red/playwright
            print(f"\n[ERROR] {e}")
            browser.close()
            sys.exit(1)

        browser.close()

    if not productos:
        print("\n[ERROR] Sin productos. Revisa el VENDOR_ID.")
        sys.exit(1)

    rows, errores = productos_a_filas(productos)
    reportar_y_guardar(rows, errores, args.out_dir, fecha)


if __name__ == "__main__":
    main()
