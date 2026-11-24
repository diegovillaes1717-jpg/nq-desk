# NQ Desk · Guía de puesta en marcha (gratis, unos 15 minutos)

NQ Desk es tu web de noticias para el **NQ (futuros del Nasdaq 100)**. Se actualiza sola cada ~10 minutos y es gratis:

- **GitHub** guarda la web y ejecuta el "robot" que descarga los datos (gratis).
- **GitHub Pages** la publica en internet con una dirección tipo `https://tuusuario.github.io/nq-desk/` (gratis).
- **Google Gemini** redacta el periódico en español (clave gratuita, sin tarjeta).

No hace falta saber programar: solo seguir los pasos.

---

## Paso 1 · Crear la cuenta de GitHub

1. Entra en <https://github.com/signup>.
2. Pon tu email, una contraseña y un nombre de usuario. **El nombre de usuario formará parte de la dirección de tu web** (por ejemplo `juantrader` → `juantrader.github.io`).
3. Confirma el email con el código que te llega.
4. Si te ofrece planes de pago, elige **Free**.

## Paso 2 · Crear el repositorio (la "carpeta" de tu web)

1. Arriba a la derecha pulsa **+** → **New repository**.
2. **Repository name:** `nq-desk`
3. Marca **Public**. Es obligatorio para que la web y la automatización sean gratis. Tus claves secretas siguen siendo privadas.
4. **No** marques "Add a README file".
5. Pulsa **Create repository**.

## Paso 3 · Subir los archivos

1. Descomprime el archivo `nq-desk.zip` en tu ordenador.
2. En la página del repositorio recién creado, pulsa el enlace **uploading an existing file**.
3. Abre la carpeta descomprimida `nq-desk`, selecciona **todo su contenido** (`index.html`, `README.md`, `workflow-actualizar.txt` y las carpetas `assets`, `data` y `scripts`) y arrástralo a la página de GitHub.
4. Espera a que terminen de subir y pulsa **Commit changes**.

## Paso 4 · Crear el robot de actualización

Este archivo va en una carpeta oculta, así que se crea a mano. Solo hay que copiar y pegar:

1. En el repositorio, pulsa **Add file** → **Create new file**.
2. En el nombre del archivo escribe exactamente: `.github/workflows/actualizar.yml`
   (al escribir cada `/` GitHub crea la carpeta automáticamente).
3. Abre en tu ordenador el archivo `workflow-actualizar.txt`, copia **todo** su contenido y pégalo en el cuadro grande.
4. Pulsa **Commit changes…** y otra vez **Commit changes**.

## Paso 5 · Activar la web (GitHub Pages)

1. En el repositorio entra en **Settings** (pestaña de arriba) → menú izquierdo **Pages**.
2. En **Source** elige **GitHub Actions**.

## Paso 6 · Clave gratuita de Gemini (para el periódico en español)

1. Entra en <https://aistudio.google.com/apikey> con tu cuenta de Google.
2. Pulsa **Create API key** (si te pregunta por un proyecto, deja el que propone o crea uno nuevo).
3. Copia la clave (empieza por `AIza…`).
4. En GitHub, en tu repositorio: **Settings** → **Secrets and variables** → **Actions** → **New repository secret**.
   - **Name:** `GEMINI_API_KEY`
   - **Secret:** pega la clave
   - Pulsa **Add secret**.

> La clave queda guardada en secreto: no aparece en la web ni en los archivos públicos. El robot usa unas 5–20 peticiones al día, muy por debajo del límite gratuito. No hace falta añadir tarjeta.

## Paso 7 (opcional) · Resultados de las grandes tecnológicas

La sección "Resultados" (fechas de resultados de Nvidia, Apple, Microsoft…) necesita otra clave gratuita:

1. Regístrate en <https://finnhub.io/register> y copia tu **API key** del panel.
2. Guárdala igual que en el paso 6 con el nombre `FINNHUB_API_KEY`.

## Paso 8 · Primer arranque

1. Entra en la pestaña **Actions** del repositorio.
2. A la izquierda pulsa **Actualizar datos NQ Desk** → botón **Run workflow**. En "Regenerar el periódico ahora" escribe `1` → **Run workflow**.
3. Espera 2–3 minutos hasta que aparezca un círculo verde ✓.
4. Tu web ya está en: **`https://TU-USUARIO.github.io/nq-desk/`**
   (también la ves en **Settings → Pages**).

A partir de aquí se actualiza sola cada ~10 minutos. Guárdala en favoritos o en la pantalla de inicio del móvil.

---

## Qué hace cada sección

| Sección | Qué muestra | Fuente | Frecuencia |
|---|---|---|---|
| **Panel** | Resumen: próximo evento clave con cuenta atrás, mercados, eventos de hoy, Trump, periódico y titulares | Todas | ~10 min |
| **Calendario** | Vistas semanal y mensual, solo eventos USD, en hora de Madrid. FOMC, IPC, NFP, PCE y presidente de la Fed en **rojo "CLAVE"** | Forex Factory | ~30 min |
| **Periódico** | Edición redactada por IA: 07:00, 15:00 (previa de Nueva York) y 22:00 entre semana; resumen semanal el sábado y previa de la semana el domingo. Más todos los titulares filtrados | CNBC, MarketWatch, Yahoo Finance, Google News, Fed + Gemini | ~10 min (titulares) |
| **Trump** | Solo publicaciones de Truth Social con posible impacto en el NQ, con nivel de impacto y una nota de la IA. Aviso emergente y contador en el menú cuando hay un post nuevo | trumpstruth.org | ~10 min |
| **Mercados** | NQ, ES, Dow, bono a 10 años, petróleo, VIX y dólar con variación diaria/semanal/mensual + mapa de calor del Nasdaq 100 + pesos pesados | Yahoo Finance, TradingView | ~10 min |
| **Resultados** | Fechas y estimaciones de resultados de las grandes del Nasdaq | Finnhub (opcional) | 6 h |
| **Fed** | Próxima decisión de tipos con cuenta atrás, agenda de la Fed, comunicados y discursos | Fed + Forex Factory | ~10 min |

**Límites honestos:**
- Los precios de los futuros llegan con unos 10–15 minutos de retraso (los datos en tiempo real de CME son de pago). Para operar, usa tu plataforma.
- GitHub ejecuta el robot "cada 10 minutos", pero a veces se retrasa. Un post de Trump puede tardar de 5 a 20 minutos en aparecer.
- Forex Factory publica la semana actual y, a veces, la siguiente. El calendario mensual se va completando solo, y las reuniones del FOMC ya aparecen con antelación.

---

## Si algo no funciona

- **La web dice "Sin actualizar":** entra en **Actions**. Si ves una ✗ roja, pulsa en ella para ver el error. Puedes relanzarlo con **Run workflow**.
- **Abajo de la web hay un punto rojo** junto a una fuente: esa fuente falló en la última actualización. Si es algo puntual, se arregla solo en la siguiente.
- **El periódico dice "Modo sin IA":** revisa que el secreto se llame exactamente `GEMINI_API_KEY`. Si Google cambia los modelos, el robot elige el disponible automáticamente. También puedes forzar uno creando en **Settings → Secrets and variables → Actions → Variables** una variable `GEMINI_MODEL` (por ejemplo `gemini-flash-latest`).
- **Error "deployment… not allowed" al publicar:** en **Settings → Environments → github-pages**, comprueba que la rama `main` está permitida.
- **GitHub pausa los robots programados** si un repositorio pasa 60 días sin actividad. Los commits del propio robot cuentan como actividad, pero si alguna vez lo ves desactivado, en **Actions** pulsa **Enable workflow**.

## Personalizar (opcional)

Todo está en `scripts/update.py` y se edita desde la web de GitHub (icono del lápiz):

- `KEY_RE`: qué eventos se marcan como **CLAVE** (rojo).
- `NEWS_KW`: palabras que hacen relevante una noticia y su peso.
- `TRUMP_HIGH` / `TRUMP_MED`: temas de Trump de impacto alto o medio.
- `EDITIONS`: horas del periódico.
- `FOMC_DECISIONS`: fechas de las reuniones de la Fed. Añade las del año próximo cuando la Fed las publique.

---

*Contenido informativo. No es asesoramiento financiero.*
