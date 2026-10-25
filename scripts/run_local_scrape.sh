#!/bin/bash
# Corrida local (temporal, mientras GitHub Actions este bloqueado por IP).
# Pensado para dispararse desde launchd 1 vez por dia (10:15 ART, ver
# ~/Library/LaunchAgents/com.pedidosya-nunez.scrape.plist). Todo lo que
# hace queda en el log de scripts/local_run.log para poder revisar
# corridas desatendidas.
set -uo pipefail

REPO="/Users/ramiromazur/pedidosya-nunez"
LOG="$REPO/scripts/local_run.log"
PY=/Library/Frameworks/Python.framework/Versions/3.14/bin/python3
export PATH="/Library/Frameworks/Python.framework/Versions/3.14/bin:/usr/bin:/bin:/usr/sbin:/sbin"

cd "$REPO" || exit 1

# Aviso el mismo dia: notificacion de macOS + marca en scripts/ALERTA_SCRAPER.txt
# (se borra cuando una corrida sale bien). Asi una falla no pasa 10 dias sin verse.
alertar() {
  echo "$(date '+%Y-%m-%d %H:%M') $1" >> "$REPO/scripts/ALERTA_SCRAPER.txt"
  /usr/bin/osascript -e "display notification \"$1\" with title \"Scraper PedidosYa Nunez FALLO\" sound name \"Basso\"" 2>/dev/null || true
}
{
  echo "===== $(date '+%Y-%m-%d %H:%M:%S %z') ====="

  git pull --rebase --quiet origin main || echo "[WARN] git pull fallo, sigo con lo local"

  cd scraper || exit 1
  "$PY" scraper.py --out-dir ../data/raw
  SCRAPE_STATUS=$?

  if [ $SCRAPE_STATUS -ne 0 ]; then
    echo "[WARN] scraper.py (motor requests) fallo (status $SCRAPE_STATUS), probando motor alternativo (Chrome real via playwright)."
    "$PY" scraper_playwright.py --out-dir ../data/raw
    SCRAPE_STATUS=$?
  fi
  cd "$REPO" || exit 1

  if [ $SCRAPE_STATUS -ne 0 ]; then
    echo "[ERROR] los dos motores fallaron (status $SCRAPE_STATUS), no ingesto ni commiteo."
    alertar "Los dos motores fallaron (probable 403 anti-bot). Hoy sin datos."
    exit 1
  fi

  FECHA=$(TZ=America/Argentina/Buenos_Aires date '+%Y-%m-%d')
  CSV="data/raw/${FECHA}.csv"

  if [ ! -f "$CSV" ]; then
    echo "[ERROR] no encuentro $CSV despues de scrapear."
    alertar "No se genero $CSV despues de scrapear."
    exit 1
  fi

  # Sanity check: si trae 0 SKUs o <70% de la lectura anterior, no ingesto y aviso.
  N_HOY=$(( $(wc -l < "$CSV") - 1 ))
  PREV_CSV=$(ls data/raw/*.csv | grep -v "$CSV" | sort | tail -1)
  N_PREV=$(( $(wc -l < "$PREV_CSV") - 1 ))
  if [ "$N_HOY" -le 0 ] || [ "$N_HOY" -lt $(( N_PREV * 70 / 100 )) ]; then
    echo "[ERROR] $CSV trae $N_HOY filas vs $N_PREV de $PREV_CSV, no ingesto."
    alertar "Scrapeo trajo $N_HOY SKUs (antes $N_PREV). No se ingesto."
    exit 1
  fi

  "$PY" scripts/ingest_run.py --csv "$CSV" --date "$FECHA"
  "$PY" scripts/build_dashboard_data.py

  git add data/ docs/data.json
  if git diff --cached --quiet; then
    echo "Sin cambios de datos, no se commitea."
  else
    git commit -q -m "data: corte $FECHA (corrida local)"
    if git push -q origin main; then
      echo "[OK] pusheado"
      rm -f "$REPO/scripts/ALERTA_SCRAPER.txt"
    else
      echo "[ERROR] git push fallo"; alertar "git push fallo"
    fi
  fi

  echo "===== fin $(date '+%Y-%m-%d %H:%M:%S %z') ====="
  echo
} >> "$LOG" 2>&1
