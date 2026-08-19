"""
Genera docs/data.json (lo que consume el dashboard) a partir de
data/history.json + data/fights_config.json, calculando stats/fights/meta.

Se corre despues de cada ingest_run.py.
"""

import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (  # noqa: E402
    DASHBOARD_DATA_PATH,
    FIGHTS_PATH,
    HISTORY_PATH,
    VOLUME_REFERENCE_PATH,
    load_json,
    save_json,
)


def attach_volumes(pivot, volume_rows):
    """Suma volumen_l (litros) a cada fila del pivot por id. Si un SKU no
    tiene entrada en la tabla de referencia, vuelumen_l queda en None (el
    dashboard lo muestra como N/D, nunca rompe)."""
    by_id = {v["id"]: v["volumen_l"] for v in volume_rows}
    sin_volumen = 0
    for p in pivot:
        vol = by_id.get(p["id"])
        p["volumen_l"] = vol
        if vol is None:
            sin_volumen += 1
    return sin_volumen


def build_stats(pivot):
    groups = defaultdict(list)
    for p in pivot:
        for date, v in p["dates"].items():
            groups[(p["marca"], p["grupo"], p["segmento"])].append((date, v["dinamica"], v["ptc"]))

    stats = []
    for (marca, grupo, segmento), vals in groups.items():
        dates_seen = {v[0] for v in vals}
        dates_din = {v[0] for v in vals if v[1] > 0}
        stats.append(
            {
                "marca": marca,
                "grupo": grupo,
                "segmento": segmento,
                "dias": len(dates_seen),
                "dias_dinamica": len(dates_din),
                "max_dinamica": max(v[1] for v in vals),
                "avg_dinamica": sum(v[1] for v in vals) / len(vals),
                "avg_ptc": sum(v[2] for v in vals) / len(vals),
            }
        )
    return stats


def main():
    history = load_json(HISTORY_PATH, None)
    if history is None:
        sys.exit(f"No existe {HISTORY_PATH}, corre migrate_legacy.py o ingest_run.py primero")

    fights = load_json(FIGHTS_PATH, [])
    pivot = history["pivot"]
    dates = sorted(history.get("dates") or {d for p in pivot for d in p["dates"]})

    volume_rows = load_json(VOLUME_REFERENCE_PATH, [])
    sin_volumen = attach_volumes(pivot, volume_rows)

    registros_validos = sum(len(p["dates"]) for p in pivot)

    dashboard = {
        "pivot": pivot,
        "dates": dates,
        "stats": build_stats(pivot),
        "fights": fights,
        "meta": {
            "generado": datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S"),
            "sku_rows": len(pivot),
            "registros_validos": registros_validos,
            "dias": len(dates),
            "plataforma": "PedidosYa",
            "tienda": "Nunez",
        },
    }

    save_json(DASHBOARD_DATA_PATH, dashboard)
    print(f"[OK] {DASHBOARD_DATA_PATH} generado: {len(pivot)} SKUs, {len(dates)} slots")
    if sin_volumen:
        print(f"[WARN] {sin_volumen} SKUs sin volumen en {VOLUME_REFERENCE_PATH.name} (se muestran como N/D)")


if __name__ == "__main__":
    main()
