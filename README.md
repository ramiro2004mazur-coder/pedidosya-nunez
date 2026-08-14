# PedidosYa Nunez — historico de precios de cerveza

Scraper + dashboard automatizado para trackear precios de cerveza en la
tienda de Nunez de PedidosYa Market. Corre 2 veces por dia (10:15 y 19:00
ART), consolida el historico y publica el dashboard en GitHub Pages.

> **Estado actual (temporal):** PedidosYa devuelve 403 a las IPs de
> datacenter de GitHub Actions, asi que el cron en la nube esta
> **desactivado** (`.github/workflows/scrape_and_deploy.yml` solo queda
> disponible para disparo manual). El scrapeo 2x/dia corre **localmente en
> esta Mac** via `launchd`, ver seccion [Corrida local](#corrida-local-temporal)
> abajo. Cuando se resuelva el bloqueo de IP (proxy o Oracle Cloud Free
> Tier) se vuelve a activar el cron de GitHub Actions.

## Estructura

```
scraper/scraper.py         scraper (API interna de PedidosYa), 1 sola tienda
data/history.json          historico consolidado, fuente de verdad (AM/PM por dia)
data/catalog.json          clasificacion marca/sku -> grupo (CMQ/Competencia) y segmento
data/fights_config.json    definicion de las "luchas" CMQ vs Competencia
data/raw/                  snapshot crudo de cada corrida (auditoria)
data/logs/                 avisos de SKUs sin clasificar / filas descartadas
docs/index.html            dashboard (esto es lo que sirve GitHub Pages)
docs/data.json             generado, no se edita a mano
scripts/migrate_legacy.py  migracion unica del data.json/CSV viejos (ya corrida)
scripts/ingest_run.py      mergea 1 corrida nueva en data/history.json
scripts/build_dashboard_data.py   data/history.json -> docs/data.json (stats/fights)
scripts/run_local_scrape.sh       corrida completa local (scrape+ingest+build+push), la dispara launchd
.github/workflows/scrape_and_deploy.yml   workflow manual (cron desactivado, ver arriba)
```

LaunchAgent (fuera del repo, vive en la Mac): `~/Library/LaunchAgents/com.pedidosya-nunez.scrape.plist`

## Setup unico (a hacer vos, no lo hace el workflow)

1. Crear el repo en GitHub y pushear este proyecto.
2. **Settings → Pages → Source: "Deploy from a branch" → Branch: `main` / `docs`.**
   Con esto, cada vez que el workflow commitea un cambio en `docs/data.json`,
   GitHub Pages se re-despliega solo (no hace falta un job de deploy aparte).
3. Revisar `VENDOR_ID` en `scraper/scraper.py` (356102) — confirmar que sigue
   siendo el id correcto de la tienda de Nunez.
4. Revisar `data/logs/migration_warnings.log` y `data/catalog.json`: hay
   ~16 SKUs que aparecen en los CSV crudos pero no estaban en tu clasificacion
   original (quedaron con `grupo`/`segmento` = "Sin clasificar"). Editalos a
   mano en `catalog.json` con el grupo/segmento correcto; el proximo build
   los toma de ahi.

## Como corre

Cada trigger del cron (`.github/workflows/scrape_and_deploy.yml`):
1. `scraper/scraper.py --slot AM|PM` — pega contra la API de PedidosYa,
   guarda `data/raw/YYYY-MM-DD_AM.csv` (o `_PM`). Si un producto puntual
   falla al parsearse se loguea y se sigue (no corta la corrida); si falla
   toda la conexion/API, el job falla (asi corresponde).
2. `scripts/ingest_run.py` — mergea ese CSV en `data/history.json`. Filas
   invalidas se descartan y quedan logueadas en `data/logs/ingest_warnings.log`,
   nunca rompen la corrida. SKUs nuevos sin catalogo quedan como
   "Sin clasificar" para revisar despues.
3. `scripts/build_dashboard_data.py` — recalcula `docs/data.json` (stats,
   fights) a partir del historico.
4. Commit + push de `data/` y `docs/data.json`. Ese push dispara el redeploy
   de Pages.

## Correr manualmente

```bash
pip install -r scraper/requirements.txt
python3 scraper/scraper.py --slot AM          # o --slot PM, o sin flag (autodetecta)
python3 scripts/ingest_run.py --csv data/raw/2026-08-14_AM.csv --date 2026-08-14 --slot AM
python3 scripts/build_dashboard_data.py
```

También se puede disparar el workflow a mano desde la pestaña *Actions* →
*Run workflow* (con slot forzado opcional) — pero hoy va a fallar con 403
por el bloqueo de IP mencionado arriba, salvo que se le agregue un proxy.

## Corrida local (temporal)

Mientras el cron de GitHub Actions esta desactivado, `scripts/run_local_scrape.sh`
corre 2x/dia desde esta Mac via un LaunchAgent
(`~/Library/LaunchAgents/com.pedidosya-nunez.scrape.plist`, 10:15 y 19:00,
hora del sistema — la Mac ya esta en ART asi que no hace falta convertir).
El script hace `git pull`, scrapea, ingesta, regenera `docs/data.json` y
pushea a `main` (lo que dispara el redeploy de Pages).

**Requisito:** la Mac tiene que estar prendida, despierta y con tu sesion
iniciada (no en la pantalla de login) a esas horas, o esa corrida se
pierde — no hay reintento automatico.

Logs:
- `scripts/local_run.log` — log propio del script (que hizo, que commiteo).
- `scripts/launchd.out.log` / `scripts/launchd.err.log` — stdout/stderr crudo de launchd.

Administrar el LaunchAgent:
```bash
# ver si esta cargado
launchctl list | grep pedidosya-nunez

# forzar una corrida ya mismo (sin esperar al horario)
launchctl kickstart -k gui/$(id -u)/com.pedidosya-nunez.scrape

# desactivar temporalmente
launchctl bootout gui/$(id -u)/com.pedidosya-nunez.scrape

# volver a activar
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.pedidosya-nunez.scrape.plist
```

## Formato de `data/history.json`

```json
{
  "meta": {"tienda": "Nunez", "plataforma": "PedidosYa Market"},
  "dates": ["2026-08-13_AM", "2026-08-14_AM", "2026-08-14_PM"],
  "pivot": [
    {
      "id": "brahma-brahma-chopp-lata-354-ml",
      "marca": "Brahma",
      "sku": "Cerveza Brahma Chopp Lata 354 ml",
      "calibre": "330/355",
      "grupo": "CMQ",
      "segmento": "Core",
      "dates": {
        "2026-08-14_AM": {"fleje": 1769.0, "ptc": 1503.65, "dinamica": 0.15},
        "2026-08-14_PM": {"fleje": 1769.0, "ptc": 1450.0, "dinamica": 0.18}
      }
    }
  ]
}
```
