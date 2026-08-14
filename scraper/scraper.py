"""
scraper.py (v3 - tienda unica, slots AM/PM, resiliente por SKU)
-----------------------------------------------------------------
Scraper de precios de cerveza en la tienda de Nunez de PedidosYa Market,
via su API interna.

Si un producto individual falla al parsearse, se loguea y se sigue con
el resto (no se corta toda la corrida por un SKU raro). Si falla la
conexion/API entera, sale con codigo de error (eso si debe frenar la
corrida de CI).

Uso:
    python3 scraper.py --slot AM
    python3 scraper.py --slot PM --out-dir ../data/raw
    python3 scraper.py                       # autodetecta AM/PM por hora (America/Argentina/Buenos_Aires)
"""

import argparse
import csv
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

# --------------------------------------------------------------------------- #
VENDOR_ID = 356102        # id de la tienda de Nunez en PedidosYa Market
ZONA = "Nunez"
KEYWORD = "cerveza"
TZ = ZoneInfo("America/Argentina/Buenos_Aires")

BASE = "https://www.pedidosya.com.ar/groceries/web/v1"
HOME = "https://www.pedidosya.com.ar/"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

DEFAULT_OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"
CSV_FIELDS = ["zona", "marca", "descripcion", "calibre", "fleje", "precio", "descuento"]


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


def to_row(p):
    nombre = p.get("name", "")
    marca = p.get("defaultBrandName") or ""
    pr = p.get("pricing") or {}
    precio = pr.get("price")
    fleje = pr.get("beforePrice") or precio
    desc = 0
    for c in (p.get("campaigns") or []):
        cfg = c.get("configuration") or {}
        if cfg.get("type") == "PERCENTAGE" and cfg.get("value"):
            desc = int(round(cfg["value"])); break
    if desc == 0 and fleje and precio and fleje > precio:
        desc = int(round((1 - precio / fleje) * 100))
    size = p.get("size") or {}
    content = size.get("content"); unit = (size.get("unit") or "").lower()
    if content and unit in ("ml", "cc"):
        calibre = f"{int(content)} ml"
    elif content and unit == "l":
        calibre = f"{int(float(content)*1000)} ml"
    else:
        m = re.search(r"(\d+(?:[\.,]\d+)?)\s*(ml|cc)", nombre.lower())
        calibre = f"{int(float(m.group(1).replace(',', '.')))} ml" if m else "-"
    if not precio:
        raise ValueError(f"producto sin precio: {nombre!r} (id={p.get('id')})")
    return {"zona": ZONA, "marca": marca, "descripcion": nombre,
            "calibre": calibre, "fleje": fleje, "precio": precio, "descuento": desc}


def productos_a_filas(productos):
    """Convierte cada producto a fila de forma resiliente: si uno falla se
    loguea y se sigue con el resto (requisito: 1 SKU roto no rompe la corrida)."""
    rows, errores = [], []
    for p in productos:
        try:
            rows.append(to_row(p))
        except Exception as e:  # noqa: BLE001 - por diseno: nunca cortar la corrida por 1 SKU
            pid = p.get("id") if isinstance(p, dict) else "?"
            errores.append(f"producto id={pid} descartado: {e}")
    return rows, errores


def resolver_slot(explicit_slot):
    if explicit_slot:
        return explicit_slot
    hora = datetime.now(TZ).hour
    return "AM" if hora < 15 else "PM"


def guardar_csv(rows, out_dir, fecha, slot):
    out_dir.mkdir(parents=True, exist_ok=True)
    destino = out_dir / f"{fecha}_{slot}.csv"
    with destino.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, delimiter=";")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return destino


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slot", choices=["AM", "PM"], default=None,
                    help="si no se pasa, se autodetecta por hora en America/Argentina/Buenos_Aires")
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    ap.add_argument("--fecha", default=None, help="YYYY-MM-DD (default: hoy en ART)")
    args = ap.parse_args()

    ahora = datetime.now(TZ)
    fecha = args.fecha or ahora.strftime("%Y-%m-%d")
    slot = resolver_slot(args.slot)

    print("=" * 55)
    print("  Scraper PedidosYa Market - Nunez")
    print(f"  Vendor: {VENDOR_ID}  |  Zona: {ZONA}  |  Slot: {fecha}_{slot}")
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
    if not rows:
        print("\n[ERROR] Ningun producto se pudo parsear.")
        sys.exit(1)

    destino = guardar_csv(rows, args.out_dir, fecha, slot)
    con_desc = sum(1 for r in rows if r["descuento"] and r["descuento"] > 0)

    print(f"\n[OK] {len(rows)} cervezas guardadas ({con_desc} con descuento)")
    print(f"     -> {destino}")
    if errores:
        print(f"\n[WARN] {len(errores)} productos descartados (no rompieron la corrida):")
        for e in errores:
            print("   -", e)

    # Para que el workflow sepa que rutas/valores usar en los pasos siguientes.
    gha_out = __import__("os").environ.get("GITHUB_OUTPUT")
    if gha_out:
        with open(gha_out, "a", encoding="utf-8") as f:
            f.write(f"csv_path={destino.resolve()}\n")
            f.write(f"fecha={fecha}\n")
            f.write(f"slot={slot}\n")


if __name__ == "__main__":
    main()
