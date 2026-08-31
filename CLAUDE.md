# pedidosya-nunez

## Qué es esto

Scraper + dashboard para trackear el histórico de precios de cerveza (fleje,
PTC, dinámica) en **PedidosYa Market, tienda Núñez**. Corre 1 vez por día,
guarda el histórico en JSON, y publica un dashboard HTML estático en GitHub
Pages con varias vistas: evolución por SKU, precio/L, comparador libre de
SKUs (fusiona lo que antes era la pestaña "Luchas"), heatmap de dinámica,
cambios día a día e insights.

Dashboard en vivo: https://ramiro2004mazur-coder.github.io/pedidosya-nunez/

## Cómo correr el scraper manualmente

```bash
cd /Users/ramiromazur/pedidosya-nunez
bash scripts/run_local_scrape.sh
```

Eso hace todo el pipeline (scrape → ingest → build → commit → push) en un
solo paso. Si preferís correr los pasos sueltos:

```bash
cd scraper && /Library/Frameworks/Python.framework/Versions/3.14/bin/python3 scraper.py --out-dir ../data/raw
python3 scripts/ingest_run.py --csv data/raw/YYYY-MM-DD.csv --date YYYY-MM-DD
python3 scripts/build_dashboard_data.py
```

Si `scraper.py` (motor `requests`) da 403, probar el motor alternativo:

```bash
cd scraper && /Library/Frameworks/Python.framework/Versions/3.14/bin/python3 scraper_playwright.py --out-dir ../data/raw
```

`scraper_playwright.py` usa Chrome real (`channel="chrome"`, `headless=False`)
porque PedidosYa bloquea tanto `requests` puro como Chromium headless — ver
"Bloqueo anti-bot" más abajo. Requiere `python3 -m playwright install chromium`
corrido una vez.

## Estructura de archivos

```
scraper/scraper.py             motor "requests" (rapido, el que mas bloquean)
scraper/scraper_playwright.py  motor "navegador real" (Chrome no-headless, mas resiliente)
scraper/common.py              logica compartida entre los dos motores (VENDOR_ID, to_row, etc.)
data/history.json              historico consolidado, FUENTE DE VERDAD (1 fecha = 1 lectura)
data/catalog.json              clasificacion marca/sku -> grupo (CMQ/Competencia) y segmento
data/volume_reference.json     SKU -> volumen en litros (para la columna Precio/L)
data/fights_config.json        enfrentamientos CMQ vs competencia (accesos rapidos del comparador)
data/raw/                      snapshot crudo de cada corrida (1 CSV por fecha, auditoria)
data/logs/                     ingest_warnings.log (SKUs sin catalogo, precios sospechosos, filas descartadas)
docs/index.html                el dashboard (esto es lo que sirve GitHub Pages)
docs/data.json                 GENERADO por build_dashboard_data.py, no se edita a mano
scripts/ingest_run.py          mergea 1 CSV crudo en data/history.json (valida outliers, ver abajo)
scripts/build_dashboard_data.py   data/history.json -> docs/data.json (calcula stats/fights/volumen)
scripts/run_local_scrape.sh    pipeline completo, lo dispara el LaunchAgent local
scripts/migrate_legacy.py      migracion unica del data.json/CSV originales (ya corrida, no re-correr)
scripts/migrate_am_pm.py       migracion unica de 2 lecturas/dia a 1 (ya corrida, no re-correr)
.github/workflows/scrape_and_deploy.yml   workflow manual, cron DESACTIVADO (ver abajo)
```

### Formato de `data/history.json`

```json
{
  "meta": {"tienda": "Nunez", "plataforma": "PedidosYa Market"},
  "dates": ["2026-08-19", "2026-08-20"],
  "pivot": [
    {
      "id": "brahma-cerveza-brahma-chopp-lata-354-ml",
      "marca": "Brahma",
      "sku": "Cerveza Brahma Chopp Lata 354 ml",
      "calibre": "330/355",
      "grupo": "CMQ",
      "segmento": "Core",
      "dates": {
        "2026-08-19": {"fleje": 1769.0, "ptc": 1503.65, "dinamica": 0.15},
        "2026-08-20": {"fleje": 1769.0, "ptc": 1503.65, "dinamica": 0.15, "sospechoso": true},
        "2026-08-28": {"fleje": 1769.0, "ptc": 1179.33, "dinamica": 0.3333, "promo_nominal": "3 x 2"}
      }
    }
  ]
}
```

`promo_nominal` (opcional, solo aparece si ese dia habia una promo tipo
"llevá N pagá M" o "2da unidad al X%") guarda el texto de la promo tal
cual aparece en el sitio ("2 x 1", "3 x 2", "1 ud. al 50% dto"). Se
agregó el 2026-08-28 junto con la deteccion de estos formatos en
`to_row()` — antes, esas promos no se detectaban porque PedidosYa no
tacha el precio para ellas (a diferencia de un %OFF directo), asi que
el scraper las leia como precio de fleje sin descuento. Ver el
docstring de `to_row()` en `scraper/common.py` para el detalle de cada
formato y sus formulas.

**1 fecha = 1 lectura.** No es AM/PM (eso se usó hasta el 18/08/2026, se
migró a una sola lectura diaria porque se confirmó que la dinámica no
cambia según la hora — ver regla más abajo).

## Cómo corre automáticamente — OJO, no es GitHub Actions

El scrapeo diario **no corre en la nube**. Corre localmente en esta Mac,
vía un LaunchAgent de macOS:

- Plist: `~/Library/LaunchAgents/com.pedidosya-nunez.scrape.plist`
- Horario: 10:15 (hora del sistema — la Mac ya está en ART, sin conversión)
- Dispara: `bash scripts/run_local_scrape.sh`, que hace scrape → ingest →
  build → `git add data/ docs/data.json` → commit → push. Ese push dispara
  el redeploy automático de GitHub Pages (sirve desde `docs/` en `main`).
- **Requiere que la Mac esté prendida, despierta y con sesión iniciada** a
  esa hora. Si no, esa corrida se pierde (no hay reintento automático).
- **Desde 2026-08-31, `run_local_scrape.sh` hace fallback automático al
  motor playwright** (`scraper_playwright.py`, Chrome real) si el motor
  `requests` (`scraper.py`) falla — antes solo intentaba `requests` y
  abandonaba directo con `[ERROR]`, lo que forzó varias cargas manuales
  seguidas (27, 29, 30, 31 de agosto) que se podrían haber evitado varios
  de esos días. Si el bloqueo anti-bot afecta también a Chrome real (pasó
  el 31/08, con un challenge de PerimeterX explícito incluso ahí), los dos
  motores fallan y sigue haciendo falta carga manual — no hay forma de
  evitar eso sin proxy pago (descartado, ver "Bloqueo anti-bot" arriba).

El archivo `.github/workflows/scrape_and_deploy.yml` **existe pero su cron
está comentado/desactivado** — solo queda disponible para disparo manual
(`workflow_dispatch`). Se desactivó porque PedidosYa bloquea con 403 las
IPs de datacenter de GitHub Actions.

### Bloqueo anti-bot (contexto para no reinventar la rueda)

PedidosYa usa un anti-bot (Cloudflare / PerimeterX, se vieron ambos) que:
- Bloquea siempre las IPs de datacenter (GitHub Actions, cualquier cloud).
- A veces bloquea también la IP residencial de esta Mac, de forma
  intermitente (a veces se destraba en minutos, a veces tarda horas).
- Solo Chrome real con ventana visible (`channel="chrome", headless=False`)
  demostró pasar el chequeo con algo de consistencia; `requests` puro y
  Chromium headless (con o sin stealth) casi siempre fallan.

Si el scraper falla con 403: reintentar más tarde no es garantía, pero es
lo único que se puede hacer gratis. No hay proxy pago contratado (decisión
explícita del usuario: tiene que ser gratis).

## Reglas importantes para futuras sesiones

1. **No modificar la lógica de parseo de precios** (`to_row()` en
   `scraper/common.py`, o el cálculo de `dinamica` en `ingest_run.py`) sin
   avisar antes y explicar el motivo. Son los puntos más fáciles de romper
   silenciosamente todo el histórico.
2. **Validación de outliers ya implementada**: en `scripts/ingest_run.py`,
   si el PTC de un SKU se desvía más de 50% (`DESVIO_SOSPECHOSO`) respecto
   al último dato previo de ese mismo SKU, se guarda igual (no se
   descarta — podría ser una promo real) pero con `"sospechoso": true` en
   esa fecha, y se loguea en `data/logs/ingest_warnings.log`. No bajar el
   umbral ni cambiar a "descartar en vez de marcar" sin confirmar — ya se
   discutió esa decisión de diseño explícitamente con el usuario.
3. **1 sola lectura por día, no AM/PM.** Se probó con 2 lecturas diarias
   (mañana/noche) y se confirmó que la dinámica no varía según la hora, así
   que no tiene sentido volver a eso. Si en algún momento se reactiva
   2x/día, hay que revisar `scripts/migrate_am_pm.py` como referencia de
   cómo se hizo la migración inversa la primera vez.
4. **No cambiar el formato de `data/history.json`** (ni el pivot, ni las
   claves de fecha, ni los campos por fecha) sin confirmar antes — el
   dashboard (`docs/index.html`) y todos los scripts de `scripts/` asumen
   ese shape exacto.
5. Este proyecto covers **una sola tienda** (Núñez, `VENDOR_ID = 356102` en
   `scraper/common.py`), no las ~27 tiendas de PedidosYa Market. Si se
   quiere escalar a más tiendas, es un cambio de arquitectura, no un
   parámetro.
6. Hay un proyecto hermano, `rappi-nunez` (mismo dashboard, mismo scraper
   adaptado a Rappi), que se mantiene en paralelo con las mismas
   convenciones cuando tiene sentido. No asumir que son el mismo repo.
7. **Múltiples sesiones de Claude Code pueden estar activas sobre este
   repo al mismo tiempo** (le pasó al usuario más de una vez, sin querer).
   Antes de un cambio grande, correr `git status` y `git log --oneline -5`
   para ver si hay trabajo en curso, y si hay dudas, coordinar antes de
   pisar archivos.

## Estado actual (referencia rápida)

- Scoped a la tienda de Núñez únicamente.
- Histórico migrado desde datos previos en Excel/JSON/CSV que ya tenía el
  usuario (`scripts/migrate_legacy.py`), más lo scrapeado desde entonces.
- ~116-117 SKUs en catálogo. Algunos quedan con `grupo`/`segmento`:
  `"Sin clasificar"` cuando aparecen en un scrape pero no estaban en la
  clasificación original — no rompen nada, pero conviene que el usuario
  los revise en `data/catalog.json` de vez en cuando.
- `data/volume_reference.json` tiene el volumen en litros de cada SKU
  (parseado del nombre), usado para la columna Precio/L del dashboard.
