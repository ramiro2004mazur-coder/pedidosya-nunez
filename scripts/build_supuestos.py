"""
Genera data/supuestos.json: valores SUPUESTOS (no relevados) para dias sin
lectura, para que el dashboard pueda mostrar algo en gris/punteado en vez de
un hueco. NUNCA se escriben en data/history.json: el historico sigue siendo
solo datos reales, y KPIs/stats/insights no usan estos valores.

Regla del supuesto: cada dia del hueco replica fleje/PTC/dinamica del mismo
dia de la semana de la ultima lectura REAL anterior al hueco (ej: martes
13/10 <- martes 06/10). Las fechas que no son lectura real (ej: 11/10, que
fue copia del 10/10) se excluyen como fuente via NO_REALES.

Un hueco puede fijar "fuente" (fecha real a replicar en todos sus dias) en vez
de la regla del mismo dia de la semana: {"desde", "hasta", "fuente": "YYYY-MM-DD", "motivo"}.

Uso:
    python3 scripts/build_supuestos.py
"""

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import HISTORY_PATH, load_json, save_json  # noqa: E402

SUPUESTOS_PATH = HISTORY_PATH.parent / "supuestos.json"

# Huecos sin lectura a completar con supuesto (inclusive).
HUECOS = [
    {"desde": "2026-10-13", "hasta": "2026-10-21",
     "motivo": "Scraper bloqueado (403 anti-bot PerimeterX) y Mac sin conexion/apagada"},
]

# Fechas del historico que no son lectura real, no sirven como fuente.
NO_REALES = {"2026-10-11", "2026-10-23", "2026-10-24"}  # copias (11 <- 10/10; 23 y 24 <- 25/10)


def dias(desde, hasta):
    d, h = date.fromisoformat(desde), date.fromisoformat(hasta)
    while d <= h:
        yield d
        d += timedelta(days=1)


def main():
    history = load_json(HISTORY_PATH, None)
    if history is None:
        sys.exit(f"No existe {HISTORY_PATH}")
    reales = set(history["dates"]) - NO_REALES

    fechas, pivot = {}, {}
    for hueco in HUECOS:
        for d in dias(hueco["desde"], hueco["hasta"]):
            key = d.isoformat()
            if key in history["dates"]:
                continue  # hay lectura real, no se pisa
            if hueco.get("fuente"):
                fuente = date.fromisoformat(hueco["fuente"])
                if hueco["fuente"] not in reales:
                    sys.exit(f"La fuente {hueco['fuente']} no es una lectura real")
            else:
                fuente = d - timedelta(days=7)
            while fuente.isoformat() not in reales:
                fuente -= timedelta(days=7)
                if fuente < d - timedelta(days=70):
                    fuente = None
                    break
            if fuente is None:
                continue
            fechas[key] = fuente.isoformat()
            for p in history["pivot"]:
                v = p["dates"].get(fechas[key])
                if v:
                    pivot.setdefault(p["id"], {})[key] = {
                        "fleje": v["fleje"], "ptc": v["ptc"], "dinamica": v["dinamica"],
                        "fuente": fechas[key],
                    }
                    if v.get("promo_nominal"):
                        pivot[p["id"]][key]["promo_nominal"] = v["promo_nominal"]

    save_json(SUPUESTOS_PATH, {
        "nota": "SUPUESTO, no relevado: replica la lectura real del mismo dia de la semana anterior. "
                "No forma parte del historico ni de los KPIs.",
        "huecos": HUECOS,
        "fechas": fechas,
        "pivot": pivot,
    })
    print(f"[OK] {SUPUESTOS_PATH}: {len(fechas)} dias supuestos, {len(pivot)} SKUs")
    for k, v in sorted(fechas.items()):
        print(f"     {k} <- {v}")


if __name__ == "__main__":
    main()
