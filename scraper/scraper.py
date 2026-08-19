"""
scraper.py — motor "requests" (v4, tienda unica, 1 lectura diaria, resiliente por SKU)
-----------------------------------------------------------------------------
Scraper de precios de cerveza en la tienda de Nunez de PedidosYa Market,
via su API interna, usando `requests` puro (sin navegador).

Aviso: PedidosYa esta devolviendo 403 / captcha de PerimeterX a este motor
(tanto desde IPs de datacenter como, a veces, desde IP residencial). Si
falla, probar scraper_playwright.py, que usa un navegador real y es mas
dificil de distinguir de un usuario real.

Si un producto individual falla al parsearse, se loguea y se sigue con
el resto (no se corta toda la corrida por un SKU raro). Si falla la
conexion/API entera, sale con codigo de error (eso si debe frenar la
corrida de CI).

Corre 1 vez por dia (10:15 ART). Antes corria 2 veces (AM/PM) para ver
variacion intradia, pero se confirmo que la dinamica de PedidosYa no
cambia segun la hora del dia, asi que se simplifico a una sola lectura.

Uso:
    python3 scraper.py
    python3 scraper.py --fecha 2026-08-20 --out-dir ../data/raw
"""

import sys
import time
from datetime import datetime

import requests

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

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


def session():
    s = requests.Session()
    s.headers.update({
        "User-Agent": UA,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "es-AR,es;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": "https://www.pedidosya.com.ar/",
        "Origin": "https://www.pedidosya.com.ar",
        "Connection": "keep-alive",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        "sec-ch-ua": '"Chromium";v="126", "Not.A/Brand";v="24", "Google Chrome";v="126"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "X-PeYa-Application-Id": "web",
        "X-PeYa-Client": "web",
    })
    try:
        s.get(HOME, timeout=20)
        time.sleep(0.5)
    except Exception:
        pass
    return s


def get_categories(s, vendor_id):
    r = s.get(f"{BASE}/vendors/{vendor_id}/categories", timeout=20)
    r.raise_for_status()
    out = []

    def walk(cats, parent=None):
        for c in cats:
            out.append({"id": c["id"], "name": c.get("name", ""),
                        "qty": c.get("children_qty"), "parent": parent})
            if c.get("children"):
                walk(c["children"], c.get("name"))

    walk(r.json().get("categories", []))
    return out


def get_products(s, vendor_id, category_id, limit=50, max_pages=30):
    items = []
    for page in range(max_pages):
        r = s.get(f"{BASE}/vendors/{vendor_id}/products",
                  params={"categoryId": category_id, "limit": limit, "page": page},
                  timeout=20)
        r.raise_for_status()
        d = r.json()
        items += d.get("items", [])
        if d.get("lastPage") or not d.get("items"):
            break
        time.sleep(0.4)
    return items


def get_all_beers(s, vendor_id, keyword):
    cats = get_categories(s, vendor_id)
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
        for it in get_products(s, vendor_id, c["id"]):
            by_id[str(it["id"])] = it
    return list(by_id.values())


def main():
    args = build_arg_parser().parse_args()
    ahora = datetime.now(TZ)
    fecha = args.fecha or ahora.strftime("%Y-%m-%d")

    print("=" * 55)
    print("  Scraper PedidosYa Market - Nunez (motor: requests)")
    print(f"  Vendor: {VENDOR_ID}  |  Zona: {ZONA}  |  Fecha: {fecha}")
    print("=" * 55)

    s = session()
    try:
        productos = get_all_beers(s, VENDOR_ID, KEYWORD)
    except requests.HTTPError as e:
        code = e.response.status_code if e.response is not None else "?"
        print(f"\n[ERROR HTTP {code}] {e}")
        sys.exit(1)
    except requests.RequestException as e:
        print(f"\n[ERROR de red] {e}")
        sys.exit(1)

    if not productos:
        print("\n[ERROR] Sin productos. Revisa el VENDOR_ID.")
        sys.exit(1)

    rows, errores = productos_a_filas(productos)
    reportar_y_guardar(rows, errores, args.out_dir, fecha)


if __name__ == "__main__":
    main()
