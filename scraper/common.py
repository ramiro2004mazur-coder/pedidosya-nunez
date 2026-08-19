"""
Piezas compartidas entre los dos motores del scraper:
- scraper.py            (requests puro, mas liviano, PedidosYa lo bloquea con 403/PerimeterX)
- scraper_playwright.py (navegador real headless, mas robusto ante el anti-bot)

Ambos terminan con la misma lista de dicts "producto crudo de la API de
PedidosYa" y usan estas funciones para convertirlos a filas de CSV con el
mismo formato, la misma resiliencia por SKU y las mismas convenciones de
archivo/slot.
"""

import argparse
import csv
import os
import re
from pathlib import Path
from zoneinfo import ZoneInfo

VENDOR_ID = 356102        # id de la tienda de Nunez en PedidosYa Market
ZONA = "Nunez"
KEYWORD = "cerveza"
TZ = ZoneInfo("America/Argentina/Buenos_Aires")

BASE = "https://www.pedidosya.com.ar/groceries/web/v1"
HOME = "https://www.pedidosya.com.ar/"

DEFAULT_OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"
CSV_FIELDS = ["zona", "marca", "descripcion", "calibre", "fleje", "precio", "descuento"]


def build_arg_parser():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    ap.add_argument("--fecha", default=None, help="YYYY-MM-DD (default: hoy en ART)")
    return ap


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


def guardar_csv(rows, out_dir, fecha):
    out_dir.mkdir(parents=True, exist_ok=True)
    destino = out_dir / f"{fecha}.csv"
    with destino.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, delimiter=";")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return destino


def reportar_y_guardar(rows, errores, out_dir, fecha):
    """Guarda el CSV, imprime el resumen y escribe GITHUB_OUTPUT si corresponde.
    Devuelve el Path del CSV guardado (o sale del proceso con exit 1 si no
    hay nada que guardar)."""
    import sys

    if not rows:
        print("\n[ERROR] Ningun producto se pudo parsear.")
        sys.exit(1)

    destino = guardar_csv(rows, out_dir, fecha)
    con_desc = sum(1 for r in rows if r["descuento"] and r["descuento"] > 0)

    print(f"\n[OK] {len(rows)} cervezas guardadas ({con_desc} con descuento)")
    print(f"     -> {destino}")
    if errores:
        print(f"\n[WARN] {len(errores)} productos descartados (no rompieron la corrida):")
        for e in errores:
            print("   -", e)

    gha_out = os.environ.get("GITHUB_OUTPUT")
    if gha_out:
        with open(gha_out, "a", encoding="utf-8") as f:
            f.write(f"csv_path={destino.resolve()}\n")
            f.write(f"fecha={fecha}\n")

    return destino
