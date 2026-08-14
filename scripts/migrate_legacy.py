"""
Migracion unica de los datos previos (data.json + CSV crudos historicos) al
nuevo formato consolidado data/history.json + data/catalog.json.

No se vuelve a correr en cada scrapeo (eso lo hace ingest_run.py). Es un
script de una sola vez para arrancar el historico.

Uso:
    python3 scripts/migrate_legacy.py \
        --legacy-json /ruta/data.json \
        --csv 2026-08-10:AM=/ruta/a.csv \
        --csv 2026-08-11:AM=/ruta/b.csv \
        ...
"""

import argparse
import csv as csvmod
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (  # noqa: E402
    CATALOG_PATH,
    HISTORY_PATH,
    bucket_calibre,
    catalog_key,
    load_json,
    log_warning,
    save_json,
    slugify,
)


def build_catalog(legacy_pivot):
    catalog = {}
    for p in legacy_pivot:
        if not (p.get("marca") or "").strip() or not (p.get("sku") or "").strip():
            continue
        key = catalog_key(p["marca"], p["sku"])
        catalog[key] = {
            "id": slugify(p["marca"], p["sku"]),
            "marca": p["marca"],
            "sku": p["sku"],
            "calibre": p["calibre"],
            "grupo": p["grupo"],
            "segmento": p["segmento"],
        }
    return catalog


def read_csv_rows(path):
    """Lee el CSV crudo del scraper. Deduplica bloques repetidos (visto en
    algunos exports historicos: header+data aparece dos veces separado por
    una linea '=======')."""
    raw = Path(path).read_text(encoding="utf-8-sig")
    blocks = [b for b in raw.split("=======") if b.strip()]
    seen = set()
    rows = []
    for block in blocks:
        lines = [l for l in block.strip().splitlines() if l.strip()]
        if not lines:
            continue
        reader = csvmod.DictReader(lines, delimiter=";")
        for r in reader:
            fp = (r.get("marca"), r.get("descripcion"), r.get("precio"))
            if fp in seen:
                continue
            seen.add(fp)
            rows.append(r)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--legacy-json", required=True, help="data.json historico (pivot)")
    ap.add_argument(
        "--csv",
        action="append",
        default=[],
        metavar="FECHA:SLOT=PATH",
        help="ej: 2026-08-11:AM=/ruta/archivo.csv (repetible)",
    )
    args = ap.parse_args()

    legacy = load_json(args.legacy_json, None)
    if legacy is None:
        sys.exit(f"No pude leer {args.legacy_json}")

    catalog = build_catalog(legacy["pivot"])

    # Arranca el pivot nuevo ya con todo el historico dia-a-dia del data.json
    # legacy, usando el ultimo horario de generacion de meta como slot AM
    # (son corridas unicas por dia, sin AM/PM real todavia).
    pivot_by_key = {}
    legacy_skipped = 0
    for p in legacy["pivot"]:
        if not (p.get("marca") or "").strip() or not (p.get("sku") or "").strip():
            legacy_skipped += 1
            log_warning(
                f"{args.legacy_json}: entrada del legacy sin marca/sku descartada: {p}",
                log_file="migration_warnings.log",
            )
            continue
        key = catalog_key(p["marca"], p["sku"])
        entry = pivot_by_key.setdefault(
            key,
            {
                "id": catalog[key]["id"],
                "marca": p["marca"],
                "sku": p["sku"],
                "calibre": p["calibre"],
                "grupo": p["grupo"],
                "segmento": p["segmento"],
                "dates": {},
            },
        )
        for date, vals in p["dates"].items():
            if vals.get("ptc") is None:
                legacy_skipped += 1
                log_warning(
                    f"{args.legacy_json}: registro sin precio descartado ({p['marca']} | {p['sku']} @ {date})",
                    log_file="migration_warnings.log",
                )
                continue
            entry["dates"][f"{date}_AM"] = vals
    if legacy_skipped:
        print(f"[WARN] {legacy_skipped} entradas invalidas del data.json legacy descartadas (ver log)")

    # Ahora aplica los CSV crudos indicados (si el dia:slot ya vino del
    # data.json legacy, el CSV crudo gana porque es la fuente primaria).
    warnings = []
    for spec in args.csv:
        try:
            fechaslot, path = spec.split("=", 1)
            date, slot = fechaslot.split(":")
        except ValueError:
            sys.exit(f"--csv mal formado: {spec}")
        rows = read_csv_rows(path)
        matched = 0
        for r in rows:
            try:
                marca = (r.get("marca") or "").strip()
                descripcion = (r.get("descripcion") or "").strip()
                if not marca or not descripcion or not r.get("precio"):
                    continue
                key = catalog_key(marca, descripcion)
                if key not in catalog:
                    cal = bucket_calibre(r.get("calibre"))
                    catalog[key] = {
                        "id": slugify(marca, descripcion),
                        "marca": marca,
                        "sku": descripcion,
                        "calibre": cal,
                        "grupo": "Sin clasificar",
                        "segmento": "Sin clasificar",
                    }
                    warnings.append(
                        f"{path}: SKU nuevo sin catalogo -> '{marca} | {descripcion}' "
                        "(agregado como 'Sin clasificar', revisar manualmente)"
                    )
                cat = catalog[key]
                entry = pivot_by_key.setdefault(
                    key,
                    {
                        "id": cat["id"],
                        "marca": cat["marca"],
                        "sku": cat["sku"],
                        "calibre": cat["calibre"],
                        "grupo": cat["grupo"],
                        "segmento": cat["segmento"],
                        "dates": {},
                    },
                )
                precio = float(r["precio"])
                fleje = float(r.get("fleje") or precio)
                dinamica = round((1 - precio / fleje), 4) if fleje else 0.0
                entry["dates"][f"{date}_{slot}"] = {
                    "fleje": fleje,
                    "ptc": precio,
                    "dinamica": max(dinamica, 0.0),
                }
                matched += 1
            except Exception as e:  # noqa: BLE001 - migracion: nunca cortar por 1 fila
                warnings.append(f"{path}: fila invalida ({e}): {r}")
        print(f"[OK] {path} -> {matched} filas cargadas en {date}_{slot}")

    for w in warnings:
        log_warning(w, log_file="migration_warnings.log")

    pivot = [p for p in pivot_by_key.values() if p["dates"]]
    all_dates = sorted({d for p in pivot for d in p["dates"]})

    history = {
        "meta": {
            "tienda": "Nunez",
            "plataforma": "PedidosYa Market",
            "sku_count": len(pivot),
        },
        "dates": all_dates,
        "pivot": pivot,
    }

    save_json(HISTORY_PATH, history)
    save_json(CATALOG_PATH, list(catalog.values()))
    print(f"\n[OK] history.json -> {HISTORY_PATH} ({len(pivot)} SKUs, {len(all_dates)} slots)")
    print(f"[OK] catalog.json -> {CATALOG_PATH} ({len(catalog)} SKUs)")
    if warnings:
        print(f"[WARN] {len(warnings)} avisos -> data/logs/migration_warnings.log")


if __name__ == "__main__":
    main()
