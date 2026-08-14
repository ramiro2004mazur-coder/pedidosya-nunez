#!/bin/bash
# Corrida local (temporal, mientras GitHub Actions este bloqueado por IP).
# Pensado para dispararse desde launchd 2x/dia. Todo lo que hace queda en
# el log de scripts/local_run.log para poder revisar corridas desatendidas.
set -uo pipefail

REPO="/Users/ramiromazur/pedidosya-nunez"
LOG="$REPO/scripts/local_run.log"
PY=/Library/Frameworks/Python.framework/Versions/3.14/bin/python3
export PATH="/Library/Frameworks/Python.framework/Versions/3.14/bin:/usr/bin:/bin:/usr/sbin:/sbin"

cd "$REPO" || exit 1
{
  echo "===== $(date '+%Y-%m-%d %H:%M:%S %z') ====="

  git pull --rebase --quiet origin main || echo "[WARN] git pull fallo, sigo con lo local"

  cd scraper || exit 1
  "$PY" scraper.py --out-dir ../data/raw
  SCRAPE_STATUS=$?
  cd "$REPO" || exit 1

  if [ $SCRAPE_STATUS -ne 0 ]; then
    echo "[ERROR] scraper.py fallo (status $SCRAPE_STATUS), no ingesto ni commiteo."
    exit 1
  fi

  FECHA=$(TZ=America/Argentina/Buenos_Aires date '+%Y-%m-%d')
  HORA=$(TZ=America/Argentina/Buenos_Aires date '+%H')
  if [ "$HORA" -lt 15 ]; then SLOT=AM; else SLOT=PM; fi
  CSV="data/raw/${FECHA}_${SLOT}.csv"

  if [ ! -f "$CSV" ]; then
    echo "[ERROR] no encuentro $CSV despues de scrapear."
    exit 1
  fi

  "$PY" scripts/ingest_run.py --csv "$CSV" --date "$FECHA" --slot "$SLOT"
  "$PY" scripts/build_dashboard_data.py

  git add data/ docs/data.json
  if git diff --cached --quiet; then
    echo "Sin cambios de datos, no se commitea."
  else
    git commit -q -m "data: corte $FECHA $SLOT (corrida local)"
    git push -q origin main && echo "[OK] pusheado" || echo "[ERROR] git push fallo"
  fi

  echo "===== fin $(date '+%Y-%m-%d %H:%M:%S %z') ====="
  echo
} >> "$LOG" 2>&1
