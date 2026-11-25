#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NQ Desk - robot de actualizacion.

Se ejecuta cada ~10 minutos en GitHub Actions (gratis) y genera los
ficheros JSON de la carpeta /data que lee la web.

Solo usa la libreria estandar de Python: no hay que instalar nada.

Fuentes:
  - Calendario: feed publico de Forex Factory (faireconomy.media), filtrado a USD.
  - Mercados: Yahoo Finance (datos con retraso de ~10-15 min en futuros).
  - Noticias: RSS de CNBC, MarketWatch, Yahoo Finance, Google News y la Reserva Federal,
    filtradas por relevancia para el NQ.
  - Trump: archivo publico de Truth Social (trumpstruth.org), filtrado por palabras clave.
  - Periodico: resumen en espanol con la API gratuita de Google Gemini (opcional).
  - Resultados: Finnhub (opcional, clave gratuita).
"""

import hashlib
import html
import json
import os
import re
import sys
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
MAD = ZoneInfo("Europe/Madrid")
NY = ZoneInfo("America/New_York")
UTC = timezone.utc

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0 Safari/537.36")

GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "").strip()
FINNHUB_KEY = os.environ.get("FINNHUB_API_KEY", "").strip()
FORCE_PERIODICO = os.environ.get("FORCE_PERIODICO", "").strip() == "1"

STATUS = {"sources": {}}


# ----------------------------------------------------------------------------
# Utilidades
# ----------------------------------------------------------------------------

def now_utc():
    return datetime.now(UTC)


def iso(dt):
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s):
    if not s:
        return None
    try:
        s = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except Exception:
        return None


def fetch(url, headers=None, timeout=25, retries=2, data=None, method=None):
    h = {"User-Agent": UA, "Accept": "*/*", "Accept-Language": "en-US,en;q=0.9"}
    if headers:
        h.update(headers)
    last = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=h, data=data, method=method)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (400, 401, 403, 404):
                break
        except Exception as e:  # red, timeout...
            last = e
        time.sleep(1.5 * (attempt + 1))
    raise last


def fetch_json(url, **kw):
    return json.loads(fetch(url, **kw).decode("utf-8", "replace"))


def load(name, default):
    p = os.path.join(DATA, name)
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save(name, obj):
    os.makedirs(DATA, exist_ok=True)
    p = os.path.join(DATA, name)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def ok(source, extra=None):
    STATUS["sources"][source] = {"ok": True, "at": iso(now_utc()), **(extra or {})}


def fail(source, err):
    prev = PREV_STATUS.get("sources", {}).get(source, {})
    STATUS["sources"][source] = {
        "ok": False, "at": iso(now_utc()), "error": str(err)[:200],
        "last_ok": prev.get("at") if prev.get("ok") else prev.get("last_ok"),
    }
    print(f"[ERROR] {source}: {err}", file=sys.stderr)


def uid(*parts):
    return hashlib.sha1("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:14]


TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")


def clean_text(s):
    if not s:
        return ""
    s = html.unescape(s)
    s = re.sub(r"<br\s*/?>|</p>", "\n", s, flags=re.I)
    s = TAG_RE.sub(" ", s)
    s = html.unescape(s)
    s = WS_RE.sub(" ", s).strip()
    return s


def minutes_since(iso_str):
    dt = parse_iso(iso_str)
    if not dt:
        return 1e9
    return (now_utc() - dt).total_seconds() / 60


# ----------------------------------------------------------------------------
# 1) Calendario economico (Forex Factory)
# ----------------------------------------------------------------------------

FF_URLS = [
    "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
    "https://nfs.faireconomy.media/ff_calendar_nextweek.json",
]

# Fechas de decision del FOMC publicadas por la Fed (14:00 hora de Nueva York).
# Sirven para ver reuniones futuras en la vista mensual antes de que Forex Factory
# las publique. Revisa/actualiza esta lista cada ano en federalreserve.gov.
FOMC_DECISIONS = [
    "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17",
    "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-09",
]

TRANSLATE = {
    "Federal Funds Rate": "Decisión de tipos de la Fed",
    "FOMC Statement": "Comunicado del FOMC",
    "FOMC Press Conference": "Rueda de prensa del FOMC",
    "FOMC Meeting Minutes": "Actas del FOMC",
    "FOMC Economic Projections": "Proyecciones económicas del FOMC",
    "CPI m/m": "IPC m/m",
    "CPI y/y": "IPC a/a",
    "Core CPI m/m": "IPC subyacente m/m",
    "Core CPI y/y": "IPC subyacente a/a",
    "PPI m/m": "IPP m/m",
    "Core PPI m/m": "IPP subyacente m/m",
    "PPI y/y": "IPP a/a",
    "Non-Farm Employment Change": "Nóminas no agrícolas (NFP)",
    "Unemployment Rate": "Tasa de desempleo",
    "Average Hourly Earnings m/m": "Salario medio por hora m/m",
    "Core PCE Price Index m/m": "PCE subyacente m/m",
    "Core PCE Price Index y/y": "PCE subyacente a/a",
    "PCE Price Index m/m": "PCE m/m",
    "PCE Price Index y/y": "PCE a/a",
    "Personal Income m/m": "Ingresos personales m/m",
    "Personal Spending m/m": "Gasto personal m/m",
    "Advance GDP q/q": "PIB adelantado t/t",
    "Prelim GDP q/q": "PIB preliminar t/t",
    "Final GDP q/q": "PIB final t/t",
    "Advance GDP Price Index q/q": "Deflactor del PIB adelantado t/t",
    "Prelim GDP Price Index q/q": "Deflactor del PIB preliminar t/t",
    "Retail Sales m/m": "Ventas minoristas m/m",
    "Core Retail Sales m/m": "Ventas minoristas subyacentes m/m",
    "ISM Manufacturing PMI": "PMI manufacturero ISM",
    "ISM Services PMI": "PMI de servicios ISM",
    "ISM Manufacturing Prices": "Precios manufactureros ISM",
    "ISM Services Prices": "Precios de servicios ISM",
    "Flash Manufacturing PMI": "PMI manufacturero (flash)",
    "Flash Services PMI": "PMI de servicios (flash)",
    "Final Manufacturing PMI": "PMI manufacturero (final)",
    "Final Services PMI": "PMI de servicios (final)",
    "Unemployment Claims": "Peticiones de desempleo",
    "JOLTS Job Openings": "Vacantes de empleo JOLTS",
    "ADP Non-Farm Employment Change": "Empleo privado ADP",
    "Challenger Job Cuts y/y": "Despidos Challenger a/a",
    "CB Consumer Confidence": "Confianza del consumidor CB",
    "Prelim UoM Consumer Sentiment": "Confianza del consumidor Michigan (prelim.)",
    "Revised UoM Consumer Sentiment": "Confianza del consumidor Michigan (final)",
    "Prelim UoM Inflation Expectations": "Expectativas de inflación Michigan (prelim.)",
    "Revised UoM Inflation Expectations": "Expectativas de inflación Michigan (final)",
    "Durable Goods Orders m/m": "Pedidos de bienes duraderos m/m",
    "Core Durable Goods Orders m/m": "Pedidos de bienes duraderos subyacentes m/m",
    "Crude Oil Inventories": "Inventarios de crudo (EIA)",
    "Natural Gas Storage": "Almacenamiento de gas natural",
    "Empire State Manufacturing Index": "Índice manufacturero Empire State",
    "Philly Fed Manufacturing Index": "Índice manufacturero Fed de Filadelfia",
    "Richmond Manufacturing Index": "Índice manufacturero de Richmond",
    "Chicago PMI": "PMI de Chicago",
    "Industrial Production m/m": "Producción industrial m/m",
    "Capacity Utilization Rate": "Utilización de la capacidad",
    "Employment Cost Index q/q": "Índice de costes laborales t/t",
    "Prelim Nonfarm Productivity q/q": "Productividad no agrícola (prelim.)",
    "Prelim Unit Labor Costs q/q": "Costes laborales unitarios (prelim.)",
    "Building Permits": "Permisos de construcción",
    "Housing Starts": "Inicios de viviendas",
    "New Home Sales": "Ventas de viviendas nuevas",
    "Existing Home Sales": "Ventas de viviendas existentes",
    "Pending Home Sales m/m": "Ventas de viviendas pendientes m/m",
    "HPI m/m": "Precios de la vivienda FHFA m/m",
    "S&P/CS Composite-20 HPI y/y": "Precios vivienda Case-Shiller a/a",
    "Trade Balance": "Balanza comercial",
    "Goods Trade Balance": "Balanza comercial de bienes",
    "Federal Budget Balance": "Saldo presupuestario federal",
    "Beige Book": "Libro Beige",
    "10-y Bond Auction": "Subasta de bonos a 10 años",
    "30-y Bond Auction": "Subasta de bonos a 30 años",
    "Bank Holiday": "Festivo bancario EE. UU.",
    "Import Prices m/m": "Precios de importación m/m",
    "Wholesale Inventories m/m": "Inventarios mayoristas m/m",
    "Business Inventories m/m": "Inventarios empresariales m/m",
    "Factory Orders m/m": "Pedidos de fábrica m/m",
    "Construction Spending m/m": "Gasto en construcción m/m",
    "Consumer Credit m/m": "Crédito al consumo m/m",
    "Treasury Currency Report": "Informe de divisas del Tesoro",
    "TIC Long-Term Purchases": "Compras de largo plazo TIC",
}

TRANSLATE_RE = [
    (re.compile(r"^Fed Chair (.+) Speaks$"), "Habla el presidente de la Fed ({0})"),
    (re.compile(r"^Fed Chair (.+) Testifies$"), "Comparecencia del presidente de la Fed ({0})"),
    (re.compile(r"^Fed Vice Chair(?: for Supervision)? (.+) Speaks$"), "Habla el vicepresidente de la Fed ({0})"),
    (re.compile(r"^FOMC Member (.+) Speaks$"), "Habla {0} (miembro del FOMC)"),
    (re.compile(r"^Treasury Sec(?:retary)? (.+) Speaks$"), "Habla el secretario del Tesoro ({0})"),
    (re.compile(r"^President (.+) Speaks$"), "Discurso del presidente {0}"),
    (re.compile(r"^(.+) Bond Auction$"), "Subasta de bonos {0}"),
]

KEY_RE = re.compile(
    r"Federal Funds Rate|FOMC Statement|FOMC Press Conference|FOMC Meeting Minutes|"
    r"FOMC Economic Projections|\bCPI\b|Non-Farm Employment Change|Core PCE|Fed Chair",
    re.I)

CATEGORIES = [
    ("Fed", re.compile(r"FOMC|Federal Funds|Fed |Fed$|Beige Book", re.I)),
    ("Inflación", re.compile(r"CPI|PPI|PCE|Price|Inflation|Earnings m/m|Labor Cost", re.I)),
    ("Empleo", re.compile(r"Employment|Unemployment|Claims|JOLTS|Job|Payroll", re.I)),
    ("Crecimiento", re.compile(r"GDP|Retail|PMI|Durable|Production|Confidence|Sentiment|Manufacturing|Orders", re.I)),
    ("Vivienda", re.compile(r"Home|Housing|Building|HPI", re.I)),
    ("Bonos", re.compile(r"Bond|Auction|Treasury", re.I)),
    ("Energía", re.compile(r"Crude|Oil|Natural Gas", re.I)),
]


# ---- FILTRO DEL CALENDARIO (igual que tu filtro de Forex Factory) ----
# Impactos que se muestran: "Alto", "Medio" (añade "Bajo" si algún día lo quieres)
CAL_IMPACTS = {"Alto", "Medio"}
# Tipos de evento que se muestran. Disponibles: "Inflación", "Empleo", "Banco Central",
# "Encuestas de consumidores", "Discursos", "Crecimiento", "Vivienda",
# "Encuestas empresariales", "Bonos", "Varios"
CAL_TYPES = {"Inflación", "Empleo", "Banco Central", "Encuestas de consumidores", "Discursos"}
# Los festivos de EE. UU. se muestran siempre (sirven para saber si hay mercado)
CAL_SHOW_HOLIDAYS = True

FF_TYPES = [
    ("Discursos", re.compile(r"Speaks|Testifies|Testimony", re.I)),
    ("Banco Central", re.compile(r"FOMC|Federal Funds Rate|Beige Book|Monetary Policy|Fed Balance Sheet|Rate Decision", re.I)),
    ("Encuestas de consumidores", re.compile(r"Consumer Confidence|Consumer Sentiment|UoM|Inflation Expectations", re.I)),
    ("Inflación", re.compile(r"\bCPI\b|\bPPI\b|\bPCE\b|Import Prices|Export Prices|GDP Price Index|Price Index", re.I)),
    ("Empleo", re.compile(r"Employment|Unemployment|Claims|JOLTS|Payroll|Hourly Earnings|Job Cuts|Labor Cost|Nonfarm Productivity", re.I)),
    ("Encuestas empresariales", re.compile(r"PMI|ISM|Manufacturing Index|Empire State|Philly Fed|Richmond|Business|NFIB|Chicago", re.I)),
    ("Vivienda", re.compile(r"Home|Housing|Building Permits|HPI|Construction", re.I)),
    ("Bonos", re.compile(r"Bond Auction|Auction|\bTIC\b", re.I)),
    ("Crecimiento", re.compile(r"GDP|Retail Sales|Durable|Industrial Production|Capacity|Personal|Factory Orders|Inventories|Trade Balance|Budget|Consumer Credit", re.I)),
]


def ff_type(title_en):
    for name, rx in FF_TYPES:
        if rx.search(title_en):
            return name
    return "Varios"


def cal_allowed(e):
    if e.get("impact") == "Festivo":
        return CAL_SHOW_HOLIDAYS
    if e.get("impact") not in CAL_IMPACTS:
        return False
    return ff_type(e.get("title_en", "")) in CAL_TYPES


def translate(title):
    if title in TRANSLATE:
        return TRANSLATE[title]
    for rx, tpl in TRANSLATE_RE:
        m = rx.match(title)
        if m:
            return tpl.format(*m.groups())
    return title


def categorize(title):
    for name, rx in CATEGORIES:
        if rx.search(title):
            return name
    return "Otros"


def norm_impact(s):
    s = (s or "").strip().lower()
    return {"high": "Alto", "medium": "Medio", "low": "Bajo", "holiday": "Festivo"}.get(s, "Bajo")


def normalize_ff(raw):
    out = []
    for e in raw:
        if (e.get("country") or "").upper() != "USD":
            continue
        dt = parse_iso(e.get("date"))
        if not dt:
            continue
        title = (e.get("title") or "").strip()
        imp = norm_impact(e.get("impact"))
        out.append({
            "id": uid(title, iso(dt)),
            "title": translate(title),
            "title_en": title,
            "date": iso(dt),
            "impact": imp,
            "key": bool(KEY_RE.search(title)) and imp in ("Alto", "Medio"),
            "category": categorize(title) if imp != "Festivo" else "Festivo",
            "forecast": (e.get("forecast") or "").strip(),
            "previous": (e.get("previous") or "").strip(),
            "actual": (e.get("actual") or "").strip(),
            "source": "Forex Factory",
        })
    for e in out:
        e["type"] = ff_type(e["title_en"]) if e["impact"] != "Festivo" else "Festivo"
    return [e for e in out if cal_allowed(e)]


def update_calendar():
    cal = load("calendar.json", {"events": []})
    events = {e["id"]: e for e in cal.get("events", [])}
    last_fetch = cal.get("fetched_at")
    # Forex Factory pide no abusar del feed: como mucho cada ~25 minutos.
    if minutes_since(last_fetch) >= 25 or not events:
        got_any = False
        for url in FF_URLS:
            try:
                raw = fetch_json(url, headers={"Accept": "application/json"})
                norm = normalize_ff(raw)
                if not norm and raw:
                    continue
                if raw:
                    dates = [parse_iso(e.get("date")) for e in raw if parse_iso(e.get("date"))]
                    lo, hi = min(dates), max(dates)
                    # Sustituye la semana entera (por si un evento se mueve o se elimina)
                    for k in [k for k, v in events.items()
                              if v.get("source") == "Forex Factory"
                              and lo <= parse_iso(v["date"]) <= hi]:
                        del events[k]
                for e in norm:
                    events[e["id"]] = e
                got_any = True
            except Exception as ex:
                if "thisweek" in url:
                    fail("calendario", ex)
                else:
                    print(f"[aviso] semana siguiente no disponible: {ex}", file=sys.stderr)
        if got_any:
            cal["fetched_at"] = iso(now_utc())
            ok("calendario", {"events": len(events)})
    else:
        STATUS["sources"]["calendario"] = PREV_STATUS.get("sources", {}).get(
            "calendario", {"ok": True, "at": last_fetch})

    # Reuniones del FOMC programadas (solo si Forex Factory aun no las tiene)
    for d in FOMC_DECISIONS:
        y, m, dd = map(int, d.split("-"))
        dt = datetime(y, m, dd, 14, 0, tzinfo=NY)
        if dt < now_utc() - timedelta(days=1):
            continue
        same_day = [e for e in events.values()
                    if e.get("title_en") in ("Federal Funds Rate", "FOMC Statement")
                    and parse_iso(e["date"]).astimezone(NY).date() == dt.date()
                    and e.get("source") == "Forex Factory"]
        sid = uid("fomc-sched", d)
        if same_day:
            events.pop(sid, None)
            continue
        events[sid] = {
            "id": sid, "title": "Decisión de tipos de la Fed (programada)",
            "title_en": "FOMC Rate Decision (scheduled)", "date": iso(dt),
            "impact": "Alto", "key": True, "category": "Fed",
            "forecast": "", "previous": "", "actual": "", "source": "Calendario Fed",
        }

    # Conservar ~3 meses de historia
    cutoff = now_utc() - timedelta(days=95)
    evs = [e for e in events.values() if parse_iso(e["date"]) >= cutoff and cal_allowed(e)]
    for e in evs:
        e["type"] = ff_type(e["title_en"]) if e["impact"] != "Festivo" else "Festivo"
    evs.sort(key=lambda e: (e["date"], {"Alto": 0, "Medio": 1, "Bajo": 2, "Festivo": 3}.get(e["impact"], 4)))
    cal["events"] = evs
    save("calendar.json", cal)
    return evs


# ----------------------------------------------------------------------------
# 2) Mercados (Yahoo Finance)
# ----------------------------------------------------------------------------

MAIN_SYMBOLS = [
    ("NQ", "NQ=F", "Nasdaq 100 (futuro)", "pct"),
    ("ES", "ES=F", "S&P 500 (futuro)", "pct"),
    ("YM", "YM=F", "Dow Jones (futuro)", "pct"),
    ("US10Y", "^TNX", "Bono EE. UU. 10 años", "bps"),
    ("CL", "CL=F", "Petróleo WTI", "pct"),
    ("VIX", "^VIX", "Volatilidad (VIX)", "pct"),
    ("DXY", "DX-Y.NYB", "Índice dólar (DXY)", "pct"),
]

HEAVY_SYMBOLS = [
    ("NVDA", "Nvidia"), ("MSFT", "Microsoft"), ("AAPL", "Apple"), ("AMZN", "Amazon"),
    ("META", "Meta"), ("AVGO", "Broadcom"), ("GOOGL", "Alphabet"), ("TSLA", "Tesla"),
    ("NFLX", "Netflix"), ("COST", "Costco"), ("AMD", "AMD"), ("PLTR", "Palantir"),
]


def yahoo_chart(symbol):
    q = urllib.parse.quote(symbol)
    last = None
    for host in ("query1", "query2"):
        url = (f"https://{host}.finance.yahoo.com/v8/finance/chart/{q}"
               f"?range=3mo&interval=1d&includePrePost=false")
        try:
            j = fetch_json(url, headers={"Accept": "application/json"}, retries=1)
            res = j["chart"]["result"][0]
            return res
        except Exception as e:
            last = e
    raise last


def compute_quote(res, mode):
    meta = res.get("meta", {})
    tzname = meta.get("exchangeTimezoneName") or "America/New_York"
    try:
        tz = ZoneInfo(tzname)
    except Exception:
        tz = NY
    ts = res.get("timestamp") or []
    closes = (res.get("indicators", {}).get("quote") or [{}])[0].get("close") or []
    bars = [(datetime.fromtimestamp(t, UTC).astimezone(tz).date(), c)
            for t, c in zip(ts, closes) if c is not None]
    if not bars:
        raise ValueError("sin datos")
    price = meta.get("regularMarketPrice") or bars[-1][1]
    mtime = meta.get("regularMarketTime")
    mdate = datetime.fromtimestamp(mtime, UTC).astimezone(tz).date() if mtime else bars[-1][0]

    # cierre anterior = ultima barra con fecha anterior a la sesion actual
    prev_bars = [b for b in bars if b[0] < mdate]
    prev_close = prev_bars[-1][1] if prev_bars else bars[0][1]

    week_start = mdate - timedelta(days=mdate.weekday())
    month_start = mdate.replace(day=1)
    wk = [b for b in bars if b[0] < week_start]
    mo = [b for b in bars if b[0] < month_start]
    week_ref = wk[-1][1] if wk else bars[0][1]
    month_ref = mo[-1][1] if mo else bars[0][1]

    def chg(ref):
        if not ref:
            return None
        if mode == "bps":
            return round((price - ref) * 100, 1)
        return round((price - ref) / ref * 100, 2)

    spark = [round(c, 4) for _, c in bars[-30:]]
    if bars[-1][0] < mdate:
        spark.append(round(price, 4))
    return {
        "price": round(price, 4),
        "prev_close": round(prev_close, 4),
        "d": chg(prev_close), "w": chg(week_ref), "m": chg(month_ref),
        "mode": mode,
        "market_time": iso(datetime.fromtimestamp(mtime, UTC)) if mtime else None,
        "spark": spark,
        "currency": meta.get("currency"),
    }


def update_markets():
    prev = load("markets.json", {"main": [], "heavy": []})
    prev_main = {x["sym"]: x for x in prev.get("main", [])}
    prev_heavy = {x["sym"]: x for x in prev.get("heavy", [])}
    main, heavy, errors = [], [], 0
    for sym, ysym, name, mode in MAIN_SYMBOLS:
        try:
            q = compute_quote(yahoo_chart(ysym), mode)
            main.append({"sym": sym, "name": name, **q, "stale": False})
        except Exception as e:
            errors += 1
            print(f"[aviso] {ysym}: {e}", file=sys.stderr)
            if sym in prev_main:
                main.append({**prev_main[sym], "stale": True})
        time.sleep(0.4)
    for sym, name in HEAVY_SYMBOLS:
        try:
            q = compute_quote(yahoo_chart(sym), "pct")
            q.pop("spark", None)
            heavy.append({"sym": sym, "name": name, **q, "stale": False})
        except Exception as e:
            errors += 1
            if sym in prev_heavy:
                heavy.append({**prev_heavy[sym], "stale": True})
        time.sleep(0.3)
    out = {"updated_at": iso(now_utc()), "main": main, "heavy": heavy}
    if main:
        save("markets.json", out)
    if errors and not main:
        fail("mercados", "Yahoo Finance no respondió")
    else:
        ok("mercados", {"errors": errors})
    return out


# ----------------------------------------------------------------------------
# 3) Noticias filtradas (RSS)
# ----------------------------------------------------------------------------

GN = "https://news.google.com/rss/search?hl=en-US&gl=US&ceid=US:en&q="
NEWS_FEEDS = [
    ("CNBC", "https://www.cnbc.com/id/100003114/device/rss/rss.html"),
    ("CNBC", "https://www.cnbc.com/id/20910258/device/rss/rss.html"),
    ("CNBC", "https://www.cnbc.com/id/10000664/device/rss/rss.html"),
    ("CNBC", "https://www.cnbc.com/id/19854910/device/rss/rss.html"),
    ("MarketWatch", "https://feeds.content.dowjones.io/public/rss/mw_topstories"),
    ("MarketWatch", "https://feeds.content.dowjones.io/public/rss/mw_marketpulse"),
    ("Yahoo Finance", "https://finance.yahoo.com/news/rssindex"),
    ("Google News", GN + urllib.parse.quote("Nasdaq futures when:1d")),
    ("Google News", GN + urllib.parse.quote("Nasdaq 100 OR \"tech stocks\" when:1d")),
    ("Google News", GN + urllib.parse.quote("Federal Reserve rates OR inflation when:1d")),
    ("Google News", GN + urllib.parse.quote("Nvidia OR Microsoft OR Apple stock when:1d")),
    ("Google News", GN + urllib.parse.quote("tariffs stocks OR \"trade war\" when:1d")),
    ("Google News", GN + urllib.parse.quote("Treasury yields when:1d")),
]

FED_FEEDS = [
    ("Fed · Política monetaria", "https://www.federalreserve.gov/feeds/press_monetary.xml"),
    ("Fed · Discursos", "https://www.federalreserve.gov/feeds/speeches.xml"),
    ("Fed · Testimonios", "https://www.federalreserve.gov/feeds/testimony.xml"),
]

# (patron, puntos). Se suman: una noticia necesita >= 3 puntos para entrar.
NEWS_KW = [
    (r"\bnasdaq\b", 4), (r"\bnq\b", 3), (r"tech(nology)? stocks|tech shares|big tech|megacap|magnificent seven", 4),
    (r"\bfed\b|federal reserve|\bfomc\b|powell|rate cut|rate hike|interest rates?", 4),
    (r"inflation|\bcpi\b|\bpce\b|\bppi\b|consumer prices", 4),
    (r"jobs report|payrolls|nonfarm|unemployment|jobless claims|labor market", 3),
    (r"treasury yields?|10-year|bond yields?|bond market", 3),
    (r"tariffs?|trade war|trade deal|export controls?|sanctions", 3),
    (r"nvidia|semiconductors?|chips?\b|chipmakers?|\bai\b|artificial intelligence", 3),
    (r"\bapple\b|microsoft|amazon|\bmeta\b|alphabet|google|tesla|broadcom|netflix|\bamd\b|palantir", 2),
    (r"s&p 500|wall street|stock market|stocks|shares|equities|futures", 2),
    (r"earnings|guidance|revenue", 1), (r"recession|gdp|economy|economic", 2),
    (r"dollar|oil prices?|crude|opec", 1), (r"china|beijing|\bxi\b", 2),
    (r"trump", 1), (r"treasury secretary|white house", 1), (r"volatility|\bvix\b|sell-?off|rally", 2),
]
NEWS_NEG = [
    r"\bnfl\b|\bnba\b|soccer|football|celebrity|recipe|horoscope|lottery",
    r"credit card|mortgage rates? today|best (savings|cd)|retirement savings|social security check",
    r"how to|sponsored|coupon|deal of the day|black friday deals|gift guide",
]
NEWS_CATS = [
    ("Fed y tipos", r"\bfed\b|federal reserve|fomc|powell|rate cut|rate hike|interest rate|yields?|treasur"),
    ("Macro", r"inflation|cpi|pce|ppi|jobs|payroll|unemployment|gdp|economy|recession|retail sales|consumer"),
    ("Tecnológicas", r"nasdaq|nvidia|apple|microsoft|amazon|meta|alphabet|google|tesla|broadcom|chip|semiconductor|\bai\b|tech"),
    ("Geopolítica y aranceles", r"tariff|trade|china|sanction|war|iran|russia|ukraine|israel|export"),
    ("Energía y dólar", r"oil|crude|opec|dollar|gold"),
]
NEWS_KW_C = [(re.compile(p, re.I), w) for p, w in NEWS_KW]
NEWS_NEG_C = [re.compile(p, re.I) for p in NEWS_NEG]
NEWS_CATS_C = [(n, re.compile(p, re.I)) for n, p in NEWS_CATS]


def parse_feed(xml_bytes):
    """Devuelve una lista de dicts {title, link, summary, date} de RSS o Atom."""
    items = []
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        # algunos feeds traen basura antes del XML
        txt = xml_bytes.decode("utf-8", "replace")
        i = txt.find("<")
        root = ET.fromstring(txt[i:].encode("utf-8"))

    def strip_ns(tag):
        return tag.split("}", 1)[-1] if "}" in tag else tag

    for el in root.iter():
        t = strip_ns(el.tag)
        if t not in ("item", "entry"):
            continue
        d = {"title": "", "link": "", "summary": "", "date": None, "source": ""}
        for ch in el:
            ct = strip_ns(ch.tag)
            text = (ch.text or "").strip()
            if ct == "title":
                d["title"] = clean_text(text)
            elif ct == "link":
                d["link"] = text or ch.attrib.get("href", "") or d["link"]
            elif ct in ("description", "summary", "content", "encoded") and not d["summary"]:
                d["summary"] = clean_text(text)
            elif ct in ("pubDate", "published", "updated", "date") and not d["date"]:
                dt = None
                try:
                    dt = parsedate_to_datetime(text)
                except Exception:
                    dt = parse_iso(text)
                if dt and dt.tzinfo is None:
                    dt = dt.replace(tzinfo=UTC)
                d["date"] = dt
            elif ct == "source":
                d["source"] = clean_text(text)
            elif ct == "guid" and not d["link"] and text.startswith("http"):
                d["link"] = text
        if d["title"]:
            items.append(d)
    return items


def score_news(title, summary):
    text = f"{title} {summary[:300]}"
    if any(rx.search(text) for rx in NEWS_NEG_C):
        return 0
    s = 0
    for rx, w in NEWS_KW_C:
        if rx.search(title):
            s += w
        elif rx.search(summary[:300]):
            s += w / 2
    return s


def news_cat(text):
    for n, rx in NEWS_CATS_C:
        if rx.search(text):
            return n
    return "Mercado"


def norm_title(t):
    t = re.sub(r"\s+-\s+[^-]{2,40}$", "", t)  # quita " - Reuters" de Google News
    return re.sub(r"[^a-z0-9]+", " ", t.lower()).strip()[:70]


def update_news():
    prev = load("news.json", {"items": []})
    cutoff = now_utc() - timedelta(hours=48)
    seen, items, errors = set(), [], 0
    for src, url in NEWS_FEEDS:
        try:
            for it in parse_feed(fetch(url)):
                if not it["date"] or it["date"] < cutoff:
                    continue
                title = it["title"]
                source = src
                if src == "Google News":
                    m = re.search(r"\s+-\s+([^-]{2,40})$", title)
                    if m:
                        source = m.group(1).strip()
                        title = title[:m.start()].strip()
                    it["summary"] = ""
                sc = score_news(title, it["summary"])
                if sc < 3:
                    continue
                key = norm_title(title)
                if key in seen:
                    continue
                seen.add(key)
                items.append({
                    "id": uid(key), "title": title, "summary": it["summary"][:280],
                    "link": it["link"], "source": source, "date": iso(it["date"]),
                    "score": round(sc, 1), "category": news_cat(title + " " + it["summary"][:200]),
                })
        except Exception as e:
            errors += 1
            print(f"[aviso] feed {url[:70]}: {e}", file=sys.stderr)
    if not items and prev.get("items"):
        fail("noticias", "ningún feed respondió")
        return prev
    # conserva titulos de la ejecucion anterior que sigan en ventana
    for p in prev.get("items", []):
        if parse_iso(p["date"]) and parse_iso(p["date"]) >= cutoff and norm_title(p["title"]) not in seen:
            seen.add(norm_title(p["title"]))
            items.append(p)
    items.sort(key=lambda x: x["date"], reverse=True)
    items = items[:120]
    out = {"updated_at": iso(now_utc()), "items": items}
    save("news.json", out)
    ok("noticias", {"items": len(items), "feed_errors": errors})
    return out


def update_fed():
    prev = load("fed.json", {"items": []})
    items, errors = [], 0
    for src, url in FED_FEEDS:
        try:
            for it in parse_feed(fetch(url))[:15]:
                if not it["date"]:
                    continue
                items.append({
                    "id": uid(it["title"], it["link"]), "title": it["title"],
                    "summary": it["summary"][:300], "link": it["link"],
                    "source": src, "date": iso(it["date"]),
                })
        except Exception as e:
            errors += 1
            print(f"[aviso] fed {url}: {e}", file=sys.stderr)
    if not items:
        fail("fed", "feeds de la Fed sin respuesta")
        return prev
    items.sort(key=lambda x: x["date"], reverse=True)
    out = {"updated_at": iso(now_utc()), "items": items[:40], "summary": prev.get("summary")}
    save("fed.json", out)
    ok("fed", {"items": len(items)})
    return out


# ----------------------------------------------------------------------------
# 4) Trump (Truth Social via trumpstruth.org)
# ----------------------------------------------------------------------------

TRUMP_FEED = "https://trumpstruth.org/feed"

TRUMP_HIGH = [
    r"tariffs?", r"\bchina\b|\bxi\b|beijing", r"federal reserve|\bthe fed\b|\bfed\b|powell|fed chair",
    r"interest rates?|rate cuts?|cut rates", r"stock market|\bstocks\b|nasdaq|\bdow\b|s&p|wall street",
    r"trade deal|trade war|\btrade\b", r"sanctions?|embargo", r"semiconductors?|\bchips?\b|nvidia",
    r"\bapple\b|microsoft|google|amazon|\bmeta\b|tesla", r"inflation|recession|economy",
    r"\btax(es)?\b|tax cuts?", r"debt ceiling|government shutdown|shutdown|deficit",
    r"\bwar\b|missiles?|strike on|military action|iran|russia|ukraine|north korea|taiwan",
    r"\boil\b|opec|gasoline|energy prices", r"treasur(y|ies)|bonds?|\bdollar\b|currency",
    r"executive order", r"export controls?|\bban\b",
]
TRUMP_MED = [
    r"\bdeal\b|negotiat", r"\bjobs\b|employment|manufacturing|factories", r"mexico|canada|europe|\beu\b|japan|india|korea",
    r"\btech\b|artificial intelligence|\bai\b", r"crypto|bitcoin", r"\bbanks?\b|banking", r"\bmarkets?\b",
    r"\bprices?\b|affordab", r"investment|invest", r"\bgdp\b|growth", r"\bcompan(y|ies)\b|\bceo\b",
]
TRUMP_TAGS = [
    ("Aranceles", r"tariff"), ("China", r"china|\bxi\b|beijing|taiwan"), ("Fed", r"\bfed\b|federal reserve|powell|fed chair|interest rate|rate cut"),
    ("Bolsa", r"stock market|stocks|nasdaq|\bdow\b|s&p|wall street|\bmarkets?\b"), ("Comercio", r"trade|deal|export"),
    ("Tecnológicas", r"chip|semiconductor|nvidia|apple|microsoft|google|amazon|meta|tesla|\bai\b|\btech\b"),
    ("Impuestos", r"\btax"), ("Geopolítica", r"\bwar\b|missile|iran|russia|ukraine|korea|military|strike"),
    ("Energía", r"\boil\b|opec|gasoline|energy"), ("Economía", r"inflation|recession|economy|jobs|gdp|prices"),
    ("Deuda / Gobierno", r"debt|shutdown|deficit|treasur|bond"), ("Cripto", r"crypto|bitcoin"),
]
TRUMP_HIGH_C = [re.compile(p, re.I) for p in TRUMP_HIGH]
TRUMP_MED_C = [re.compile(p, re.I) for p in TRUMP_MED]
TRUMP_TAGS_C = [(n, re.compile(p, re.I)) for n, p in TRUMP_TAGS]


def trump_score(text):
    hi = sum(1 for rx in TRUMP_HIGH_C if rx.search(text))
    md = sum(1 for rx in TRUMP_MED_C if rx.search(text))
    if hi >= 2 or (hi >= 1 and md >= 1 and len(text) > 140):
        level = "Alto"
    elif hi >= 1 or md >= 2:
        level = "Medio"
    elif md >= 1:
        level = "Bajo"
    else:
        level = None
    tags = [n for n, rx in TRUMP_TAGS_C if rx.search(text)][:4]
    return level, tags, hi * 2 + md


def update_trump():
    prev = load("trump.json", {"posts": []})
    known = {p["id"]: p for p in prev.get("posts", [])}
    try:
        feed = parse_feed(fetch(TRUMP_FEED))
    except Exception as e:
        fail("trump", e)
        return prev, []
    new_candidates = []
    for it in feed:
        text = it["summary"] or it["title"]
        text = re.sub(r"\s*Original Post:?\s*https?://\S+\s*$", "", text).strip()
        if len(text) < 3:
            continue
        pid = uid(it["link"] or text[:80])
        if pid in known:
            continue
        level, tags, sc = trump_score(text)
        if not level:
            continue
        post = {
            "id": pid, "text": text[:1500], "link": it["link"],
            "date": iso(it["date"]) if it["date"] else iso(now_utc()),
            "impact": level, "tags": tags, "score": sc, "ai_note": "", "ai": False,
            "detected_at": iso(now_utc()),
        }
        known[pid] = post
        new_candidates.append(post)
    cutoff = now_utc() - timedelta(days=10)
    posts = [p for p in known.values() if parse_iso(p["date"]) and parse_iso(p["date"]) >= cutoff]
    posts.sort(key=lambda p: p["date"], reverse=True)
    out = {"updated_at": iso(now_utc()), "posts": posts[:80], "checked": len(feed)}
    save("trump.json", out)
    ok("trump", {"new": len(new_candidates)})
    return out, new_candidates


# ----------------------------------------------------------------------------
# 5) Resultados empresariales (Finnhub, opcional)
# ----------------------------------------------------------------------------

EARN_SYMBOLS = ["NVDA", "MSFT", "AAPL", "AMZN", "META", "AVGO", "GOOGL", "TSLA",
                "NFLX", "COST", "AMD", "PLTR", "ASML", "QCOM", "ADBE", "MU"]


def yahoo_opener():
    """Sesion con cookie + crumb de Yahoo Finance (necesaria para quoteSummary)."""
    import http.cookiejar
    cj = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    op.addheaders = [("User-Agent", UA), ("Accept", "*/*"), ("Accept-Language", "en-US,en;q=0.9")]
    for u in ("https://fc.yahoo.com", "https://finance.yahoo.com/"):
        try:
            op.open(u, timeout=20).read(1000)
        except Exception:
            pass
    crumb = op.open("https://query1.finance.yahoo.com/v1/test/getcrumb", timeout=20).read().decode().strip()
    if not crumb or "<" in crumb:
        raise RuntimeError("sin crumb de Yahoo")
    return op, crumb


def rv(d, k):
    v = (d or {}).get(k)
    if isinstance(v, dict):
        return v.get("raw")
    return v


def earnings_yahoo():
    op, crumb = yahoo_opener()
    items, last = [], []
    for s in EARN_SYMBOLS:
        try:
            url = (f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{s}"
                   f"?modules=calendarEvents,earningsHistory&crumb={urllib.parse.quote(crumb)}")
            j = json.loads(op.open(url, timeout=20).read().decode("utf-8"))
            res = (j.get("quoteSummary", {}).get("result") or [{}])[0]
            ce = (res.get("calendarEvents") or {}).get("earnings") or {}
            dates = ce.get("earningsDate") or []
            if dates:
                ts = rv(dates[0], "raw") if isinstance(dates[0], dict) else dates[0]
                dt = datetime.fromtimestamp(ts, UTC).astimezone(NY)
                h = dt.hour + dt.minute / 60
                hour = "amc" if h >= 16 else ("bmo" if 0 < h < 9.5 else "")
                items.append({
                    "sym": s, "date": dt.strftime("%Y-%m-%d"), "hour": hour,
                    "estimated": bool(ce.get("isEarningsDateEstimate")) or len(dates) > 1,
                    "eps_est": rv(ce, "earningsAverage"), "rev_est": rv(ce, "revenueAverage"),
                    "eps_act": None, "rev_act": None,
                })
            hist = (res.get("earningsHistory") or {}).get("history") or []
            if hist:
                hh = hist[-1]
                q = rv(hh, "quarter")
                last.append({
                    "sym": s, "quarter_end": datetime.fromtimestamp(q, UTC).strftime("%Y-%m-%d") if q else "",
                    "eps_act": rv(hh, "epsActual"), "eps_est": rv(hh, "epsEstimate"),
                    "surprise": round(rv(hh, "surprisePercent") * 100, 1) if rv(hh, "surprisePercent") is not None else None,
                })
        except Exception as e:
            print(f"[aviso] resultados {s}: {e}", file=sys.stderr)
        time.sleep(0.4)
    return items, last


def earnings_finnhub():
    frm = (now_utc() - timedelta(days=10)).strftime("%Y-%m-%d")
    to = (now_utc() + timedelta(days=100)).strftime("%Y-%m-%d")
    items = []
    for s in EARN_SYMBOLS:
        url = (f"https://finnhub.io/api/v1/calendar/earnings?from={frm}&to={to}"
               f"&symbol={s}&token={urllib.parse.quote(FINNHUB_KEY)}")
        j = fetch_json(url, retries=1)
        for e in j.get("earningsCalendar", []) or []:
            items.append({
                "sym": e.get("symbol"), "date": e.get("date"), "hour": e.get("hour") or "",
                "eps_est": e.get("epsEstimate"), "eps_act": e.get("epsActual"),
                "rev_est": e.get("revenueEstimate"), "rev_act": e.get("revenueActual"), "estimated": False,
            })
        time.sleep(1.1)
    return items


def update_earnings():
    prev = load("earnings.json", {"items": [], "enabled": False})
    if minutes_since(prev.get("updated_at")) < 360 and prev.get("enabled") and prev.get("items"):
        STATUS["sources"]["resultados"] = PREV_STATUS.get("sources", {}).get("resultados", {"ok": True, "at": prev.get("updated_at")})
        return prev
    try:
        items, last = earnings_yahoo()
        source = "Yahoo Finance"
        if FINNHUB_KEY:
            try:
                fh = earnings_finnhub()
                if fh:
                    items, source = fh, "Finnhub"
            except Exception as e:
                print(f"[aviso] Finnhub: {e}", file=sys.stderr)
        if not items and not last:
            raise RuntimeError("sin datos de resultados")
        items.sort(key=lambda x: (x["date"] or "", x["sym"] or ""))
        # Guarda las fechas en las que cada empresa ya presento (para el resumen)
        today = now_utc().astimezone(NY).strftime("%Y-%m-%d")
        reported = {(r["sym"], r["date"]): r for r in prev.get("reported", [])}
        for it in prev.get("items", []) + items:
            if it.get("date") and it["date"] < today:
                reported[(it["sym"], it["date"])] = {"sym": it["sym"], "date": it["date"], "hour": it.get("hour", "")}
        cutoff = (now_utc() - timedelta(days=120)).strftime("%Y-%m-%d")
        reported = sorted([r for r in reported.values() if r["date"] >= cutoff], key=lambda r: r["date"], reverse=True)
        out = {"enabled": True, "source": source, "items": items, "last": last, "reported": reported,
               "summary": prev.get("summary"), "updated_at": iso(now_utc())}
        save("earnings.json", out)
        ok("resultados", {"items": len(items)})
        return out
    except Exception as e:
        fail("resultados", e)
        return prev


# ----------------------------------------------------------------------------
# 6) Gemini (IA gratuita) para el periodico y la clasificacion de Trump
# ----------------------------------------------------------------------------

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"


def gemini_models():
    """Lista de modelos candidatos, del preferido al menos preferido."""
    if GEMINI_MODEL:
        return [GEMINI_MODEL]
    cached = PREV_STATUS.get("gemini_model")
    cands = []
    try:
        j = fetch_json(f"{GEMINI_BASE}/models?pageSize=200",
                       headers={"x-goog-api-key": GEMINI_KEY}, retries=1)
        for m in j.get("models", []):
            name = m.get("name", "").replace("models/", "")
            methods = m.get("supportedGenerationMethods", [])
            if "generateContent" not in methods:
                continue
            low = name.lower()
            if "gemini" not in low or "flash" not in low:
                continue
            if any(x in low for x in ("image", "tts", "live", "audio", "embedding", "vision", "robotics", "computer")):
                continue
            nums = re.findall(r"\d+(?:\.\d+)?", low)
            ver = float(nums[0]) if nums else 0
            stable = not any(x in low for x in ("preview", "exp", "experimental"))
            lite = "lite" in low
            cands.append(((stable, ver, not lite), name))
        cands.sort(reverse=True)
    except Exception as e:
        print(f"[aviso] no se pudo listar modelos Gemini: {e}", file=sys.stderr)
    names = [n for _, n in cands]
    if cached and cached in names:
        names.remove(cached)
        names.insert(0, cached)
    if not names:
        names = [cached] if cached else []
        names += ["gemini-flash-latest", "gemini-flash-lite-latest"]
    return names[:5]


def gemini_json(prompt, max_tokens=4096):
    if not GEMINI_KEY:
        raise RuntimeError("sin GEMINI_API_KEY")
    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.3,
            "maxOutputTokens": max_tokens,
            "responseMimeType": "application/json",
        },
    }
    last = None
    for model in gemini_models():
        url = f"{GEMINI_BASE}/models/{model}:generateContent"
        try:
            raw = fetch(url, headers={"Content-Type": "application/json",
                                      "x-goog-api-key": GEMINI_KEY},
                        data=json.dumps(body).encode("utf-8"), method="POST",
                        timeout=90, retries=1)
            j = json.loads(raw.decode("utf-8"))
            parts = j["candidates"][0]["content"]["parts"]
            text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
            text = text.strip()
            if text.startswith("```"):
                text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
            STATUS["gemini_model"] = model
            return json.loads(text), model
        except Exception as e:
            detail = ""
            if isinstance(e, urllib.error.HTTPError):
                try:
                    detail = e.read().decode("utf-8", "replace")[:300]
                except Exception:
                    pass
            print(f"[aviso] Gemini {model}: {e} {detail}", file=sys.stderr)
            last = e
    raise last or RuntimeError("Gemini no disponible")


def classify_trump_ai(trump, new_posts):
    """Pide a Gemini que valore el impacto de los posts nuevos en el NQ."""
    if not GEMINI_KEY or not new_posts:
        return trump
    batch = new_posts[:15]
    lines = "\n".join(f"[{i}] {p['text'][:700]}" for i, p in enumerate(batch))
    prompt = f"""Eres analista de un trader de futuros del Nasdaq 100 (NQ).
Valora cada publicación de Donald Trump en Truth Social según su posible impacto en el NQ.
Responde SOLO con JSON: {{"items":[{{"i":0,"impacto":"Alto|Medio|Bajo|Ninguno","nota":"una frase en español explicando por qué podría (o no) mover el NQ"}}]}}
Criterios: Alto = aranceles, China, la Fed/tipos, guerra, sanciones, tecnológicas o anuncios económicos concretos.
Medio = política económica o comercial general. Bajo = mención indirecta. Ninguno = política interna, ataques personales, elecciones, felicitaciones.
No inventes datos. Publicaciones:
{lines}"""
    try:
        res, model = gemini_json(prompt, max_tokens=2048)
        by_id = {p["id"]: p for p in trump["posts"]}
        for it in res.get("items", []):
            i = it.get("i")
            if not isinstance(i, int) or i >= len(batch):
                continue
            p = by_id.get(batch[i]["id"])
            if not p:
                continue
            imp = (it.get("impacto") or "").capitalize()
            if imp == "Ninguno":
                p["impact"] = "Ninguno"
            elif imp in ("Alto", "Medio", "Bajo"):
                p["impact"] = imp
            p["ai_note"] = (it.get("nota") or "")[:300]
            p["ai"] = True
        # Los "Ninguno" se guardan (para no volver a analizarlos) pero la web los oculta
        save("trump.json", trump)
    except Exception as e:
        print(f"[aviso] clasificación IA de Trump: {e}", file=sys.stderr)
    return trump


FED_PROMPT = """Eres analista de la Reserva Federal para un trader de futuros del Nasdaq 100 (NQ) que NO quiere leer los comunicados.
Fecha actual (Madrid): {now}.
Con SOLO la información de abajo, resume en español, de forma muy sencilla y profesional, qué está diciendo la Fed.
No inventes nada que no esté abajo. Fechas en formato "24 nov".
Devuelve SOLO JSON:
{{
 "resumen": "2-3 frases muy sencillas: qué mensaje está dando la Fed últimamente",
 "tono": "Halcón|Paloma|Neutral",
 "tono_explicacion": "una frase sencilla: qué significa ese tono para el NQ (halcón = tipos altos más tiempo, suele pesar en tecnológicas; paloma = recortes, suele ayudar)",
 "puntos": [{{"fecha": "24 nov", "quien": "Waller / FOMC / Powell…", "titulo": "título corto en español", "resumen": "1-2 frases sencillas", "impacto": "Alto|Medio|Bajo"}}],
 "que_vigilar": "una frase: próxima cita o dato de la Fed a vigilar"
}}
Entre 3 y 8 "puntos", del más reciente al más antiguo; omite los que no tengan relación con la política monetaria.

COMUNICACIONES RECIENTES DE LA FED:
{items}

PRÓXIMOS EVENTOS DE LA FED EN EL CALENDARIO:
{agenda}
"""


def fed_page_text(url):
    try:
        raw = fetch(url, retries=1, timeout=20).decode("utf-8", "replace")
        m = re.search(r'<div[^>]+id="article"[^>]*>(.*)', raw, re.S) or re.search(r"<main[^>]*>(.*)", raw, re.S)
        txt = clean_text(m.group(1) if m else raw)
        return txt[:2500]
    except Exception:
        return ""


def update_fed_summary(fed, calendar):
    if not GEMINI_KEY:
        return fed
    items = [f for f in fed.get("items", []) if parse_iso(f["date"]) >= now_utc() - timedelta(days=45)]
    if not items:
        return fed
    sig = uid(*[f["id"] for f in items[:12]])
    summ = fed.get("summary") or {}
    if summ.get("sig") == sig and minutes_since(summ.get("generated_at")) < 24 * 60:
        return fed
    lines = []
    for i, f in enumerate(items[:12]):
        extra = fed_page_text(f["link"]) if i < 4 and f.get("link") else ""
        lines.append(f"- {fmt_mad(f['date'], '%d/%m')} | {f['source']} | {f['title']} | {f.get('summary', '')[:200]}"
                     + (f"\n  Extracto: {extra}" if extra else ""))
    agenda = [f"- {fmt_mad(e['date'])} | {e['title']}" for e in calendar
              if e.get("category") == "Fed" and parse_iso(e["date"]) >= now_utc()][:8]
    prompt = FED_PROMPT.format(now=now_utc().astimezone(MAD).strftime("%d/%m/%Y %H:%M"),
                               items="\n".join(lines), agenda="\n".join(agenda) or "(ninguno)")
    try:
        res, model = gemini_json(prompt, max_tokens=3000)
        res["sig"] = sig
        res["generated_at"] = iso(now_utc())
        fed["summary"] = res
        save("fed.json", fed)
        ok("fed_ia", {"model": model})
    except Exception as e:
        fail("fed_ia", f"Gemini: {e}")
    return fed


EARN_NEWS = GN + urllib.parse.quote(
    "earnings (Nvidia OR Microsoft OR Apple OR Amazon OR Meta OR Broadcom OR Alphabet OR Tesla OR Netflix OR AMD OR Palantir OR Costco) when:14d")

EARN_PROMPT = """Eres analista de resultados empresariales para un trader de futuros del Nasdaq 100 (NQ) que NO quiere leer informes.
Fecha actual (Madrid): {now}.
Con SOLO la información de abajo, resume en español, de forma muy sencilla y profesional, los últimos resultados de las grandes tecnológicas
y qué han supuesto para el Nasdaq. No inventes cifras ni fechas que no estén abajo. Fechas en formato "19 nov".
Devuelve SOLO JSON:
{{
 "resumen": "2-3 frases muy sencillas: cómo han ido los últimos resultados de las grandes y cómo ha reaccionado el mercado",
 "puntos": [{{"fecha": "19 nov", "empresa": "Nvidia", "titulo": "título corto", "resumen": "1-2 frases sencillas: qué presentó y cómo reaccionó la acción", "resultado": "Supera|En línea|Decepciona|Sin datos", "impacto": "Alto|Medio|Bajo"}}],
 "proximos": "una frase con los próximos resultados importantes y sus fechas",
 "que_vigilar": "una frase: qué vigilar en la próxima temporada o presentación"
}}
Entre 3 y 8 "puntos", del más reciente al más antiguo. "impacto" = cuánto movió o puede mover al NQ (Nvidia, Microsoft, Apple suelen ser Alto).

ÚLTIMO TRIMESTRE PRESENTADO (BPA real vs estimado):
{last}

FECHAS EN LAS QUE YA PRESENTARON:
{reported}

PRÓXIMOS RESULTADOS:
{upcoming}

TITULARES RECIENTES SOBRE RESULTADOS:
{news}
"""


def update_earnings_summary():
    earn = load("earnings.json", {})
    if not GEMINI_KEY or not earn.get("enabled"):
        return earn
    heads = []
    try:
        for it in parse_feed(fetch(EARN_NEWS))[:40]:
            if not it["date"]:
                continue
            t = it["title"]
            m = re.search(r"\s+-\s+([^-]{2,40})$", t)
            src = m.group(1).strip() if m else ""
            t = t[:m.start()].strip() if m else t
            heads.append({"title": t, "source": src, "date": iso(it["date"])})
    except Exception as e:
        print(f"[aviso] titulares de resultados: {e}", file=sys.stderr)
    heads.sort(key=lambda h: h["date"], reverse=True)
    heads = heads[:25]
    sig = uid(json.dumps(earn.get("last", []), sort_keys=True), json.dumps(earn.get("reported", [])[:10]),
              *[h["title"] for h in heads[:10]])
    summ = earn.get("summary") or {}
    fresh = minutes_since(summ.get("generated_at"))
    if summ and ((summ.get("sig") == sig and fresh < 24 * 60) or fresh < 180):
        return earn
    today = now_utc().astimezone(NY).strftime("%Y-%m-%d")
    last = "\n".join(f"- {x['sym']} (trimestre cerrado {x.get('quarter_end','')}): BPA real {x.get('eps_act')} vs estimado {x.get('eps_est')}, sorpresa {x.get('surprise')}%"
                     for x in earn.get("last", [])) or "(sin datos)"
    reported = "\n".join(f"- {r['sym']}: {r['date']} {r.get('hour','')}" for r in earn.get("reported", [])[:20]) or "(sin datos)"
    upcoming = "\n".join(f"- {x['sym']}: {x['date']} {x.get('hour','')}{' (estimada)' if x.get('estimated') else ''}"
                         for x in earn.get("items", []) if x.get("date", "") >= today)[:3000] or "(sin datos)"
    news = "\n".join(f"- {fmt_mad(h['date'], '%d/%m')} | {h['source']} | {h['title']}" for h in heads) or "(sin titulares)"
    prompt = EARN_PROMPT.format(now=now_utc().astimezone(MAD).strftime("%d/%m/%Y %H:%M"),
                                last=last, reported=reported, upcoming=upcoming, news=news)
    try:
        res, model = gemini_json(prompt, max_tokens=3000)
        res["sig"] = sig
        res["generated_at"] = iso(now_utc())
        earn["summary"] = res
        save("earnings.json", earn)
        ok("resultados_ia", {"model": model})
    except Exception as e:
        fail("resultados_ia", f"Gemini: {e}")
    return earn


# ----------------------------------------------------------------------------
# 7) Periodico diario
# ----------------------------------------------------------------------------

# (dias de la semana 0=lunes, hora Madrid, id, nombre)
EDITIONS = [
    ((0, 1, 2, 3, 4), 7, "manana", "Edición de mañana"),
    ((0, 1, 2, 3, 4), 15, "preapertura", "Previa de la apertura de Nueva York"),
    ((0, 1, 2, 3, 4), 22, "cierre", "Resumen del cierre"),
    ((5,), 10, "semanal", "Resumen de la semana"),
    ((6,), 18, "previa", "Previa de la semana"),
]


def current_edition(now_mad):
    """La edicion mas reciente cuya hora ya ha pasado."""
    best = None
    for back in range(0, 3):
        day = now_mad - timedelta(days=back)
        for days, hour, eid, name in EDITIONS:
            if day.weekday() not in days:
                continue
            start = day.replace(hour=hour, minute=0, second=0, microsecond=0)
            if start <= now_mad and (best is None or start > best[0]):
                best = (start, eid, name)
        if best:
            break
    return best


def fmt_mad(iso_str, fmt="%a %d %H:%M"):
    dt = parse_iso(iso_str)
    return dt.astimezone(MAD).strftime(fmt) if dt else ""


def build_context(edition_id, calendar, markets, news, trump, fed):
    now = now_utc()
    lines = []
    lines.append("MERCADOS (variación día / semana / mes):")
    for q in markets.get("main", []):
        unit = " pb" if q.get("mode") == "bps" else "%"
        lines.append(f"- {q['sym']} {q['name']}: {q['price']} | D {q['d']}{unit} | S {q['w']}{unit} | M {q['m']}{unit}")
    hv = sorted(markets.get("heavy", []), key=lambda x: abs(x.get("d") or 0), reverse=True)[:6]
    if hv:
        lines.append("Pesos pesados del Nasdaq (día): " + ", ".join(f"{h['sym']} {h['d']}%" for h in hv))

    horizon = 7 if edition_id in ("semanal", "previa") else 2
    lines.append(f"\nCALENDARIO (hora de Madrid, próximos {horizon} días, solo USD):")
    for e in calendar:
        dt = parse_iso(e["date"])
        if now - timedelta(hours=12) <= dt <= now + timedelta(days=horizon) and e["impact"] in ("Alto", "Medio", "Festivo"):
            extra = []
            if e.get("forecast"):
                extra.append(f"previsión {e['forecast']}")
            if e.get("previous"):
                extra.append(f"anterior {e['previous']}")
            if e.get("actual"):
                extra.append(f"real {e['actual']}")
            lines.append(f"- {fmt_mad(e['date'])} | {e['impact']}{' | CLAVE' if e.get('key') else ''} | {e['title']} ({e['title_en']}) {'; '.join(extra)}")
    if edition_id == "semanal":
        lines.append("\nEVENTOS DE LA SEMANA QUE TERMINA:")
        for e in calendar:
            dt = parse_iso(e["date"])
            if now - timedelta(days=7) <= dt <= now and e["impact"] == "Alto":
                lines.append(f"- {fmt_mad(e['date'])} | {e['title']} | real {e.get('actual') or 'n/d'} | previsión {e.get('forecast') or 'n/d'}")

    lines.append("\nNOTICIAS FILTRADAS (índice, hora Madrid, fuente, titular, resumen):")
    window = 24 * 6 if edition_id == "semanal" else 20
    ns = [n for n in news.get("items", []) if parse_iso(n["date"]) >= now - timedelta(hours=window)]
    ns.sort(key=lambda n: (n["score"], n["date"]), reverse=True)
    ns = ns[:45]
    for i, n in enumerate(ns):
        lines.append(f"[{i}] {fmt_mad(n['date'])} | {n['source']} | {n['title']} | {n['summary'][:200]}")

    tp = [p for p in trump.get("posts", []) if parse_iso(p["date"]) >= now - timedelta(hours=30)]
    if tp:
        lines.append("\nPUBLICACIONES DE TRUMP RELEVANTES (últimas 30 h):")
        for p in tp[:10]:
            lines.append(f"- {fmt_mad(p['date'])} | impacto {p['impact']} | {p['text'][:400]}")
    fd = [f for f in fed.get("items", []) if parse_iso(f["date"]) >= now - timedelta(days=3)]
    if fd:
        lines.append("\nRESERVA FEDERAL (últimos 3 días):")
        for f in fd[:8]:
            lines.append(f"- {fmt_mad(f['date'])} | {f['source']} | {f['title']}")
    return "\n".join(lines), ns


PERIODICO_PROMPT = """Eres el editor jefe de "NQ Desk", un periódico financiero para un trader profesional de futuros del Nasdaq 100 (NQ).
Edición: {edition_name}. Fecha y hora actual en Madrid: {now_mad}.

Con SOLO la información de abajo, escribe en español de España el periódico de esta edición.
Reglas:
- Céntrate exclusivamente en lo que puede mover el NQ. Nada de relleno.
- No inventes cifras, citas ni eventos. Si un dato no está abajo, no lo menciones.
- Las horas, siempre en hora de Madrid.
- Tono profesional, directo y claro. No des recomendaciones de compra o venta.
- En "fuentes" pon los índices [n] de las noticias usadas.

Devuelve SOLO JSON con esta forma exacta:
{{
 "titular": "titular principal (máx. 110 caracteres)",
 "en_pocas_palabras": ["4-6 frases MUY sencillas, como si se lo explicaras a un amigo que no es economista: qué está pasando, por qué importa y qué puede significar para el NQ. Sin tecnicismos; si usas uno (por ejemplo PCE o FOMC), explícalo en la misma frase."],
 "resumen": "2-3 frases con lo esencial para el NQ",
 "tono": "Positivo|Negativo|Mixto|Neutral",
 "tono_motivo": "una frase",
 "claves": [{{"titulo": "...", "detalle": "1-2 frases", "impacto": "Alto|Medio|Bajo", "fuentes": [0]}}],
 "secciones": [{{"nombre": "Fed y tipos|Macro|Tecnológicas|Geopolítica y aranceles|Energía y dólar|Trump", "puntos": [{{"texto": "1-2 frases", "fuentes": [0]}}]}}],
 "agenda": [{{"hora": "Mié 16:00", "evento": "...", "por_que_importa": "una frase"}}],
 "riesgos": ["riesgo o factor a vigilar, una frase"]
}}
Entre 3 y 6 "claves", entre 2 y 6 "secciones" (solo las que tengan contenido), "agenda" con los eventos de impacto Alto/Medio próximos (puede estar vacía), y 2-4 "riesgos".

DATOS:
{context}
"""


def periodico_fallback(edition, news, calendar):
    now = now_utc()
    ns = [n for n in news.get("items", []) if parse_iso(n["date"]) >= now - timedelta(hours=20)]
    ns.sort(key=lambda n: (n["score"], n["date"]), reverse=True)
    secs = {}
    for n in ns[:30]:
        secs.setdefault(n["category"], []).append(
            {"texto": n["title"], "links": [{"title": n["source"], "url": n["link"]}]})
    agenda = []
    for e in calendar:
        dt = parse_iso(e["date"])
        if now <= dt <= now + timedelta(days=2) and e["impact"] in ("Alto", "Medio"):
            agenda.append({"hora": fmt_mad(e["date"]), "evento": e["title"], "por_que_importa": ""})
    top = ns[0]["title"] if ns else "Sin titulares relevantes todavía"
    return {
        "titular": top, "resumen": "Resumen automático sin IA: añade la clave gratuita de Gemini para recibir el periódico redactado en español.",
        "tono": "", "tono_motivo": "", "claves": [],
        "secciones": [{"nombre": k, "puntos": v[:6]} for k, v in secs.items()],
        "agenda": agenda[:12], "riesgos": [],
    }


def update_periodico(calendar, markets, news, trump, fed):
    per = load("periodico.json", {})
    now_mad = now_utc().astimezone(MAD)
    ed = current_edition(now_mad)
    if not ed:
        return per
    start, eid, ename = ed
    edition_key = f"{start.strftime('%Y-%m-%d')}-{eid}"
    have_ai = per.get("ai") or not GEMINI_KEY
    needs_simple = bool(GEMINI_KEY) and per.get("ai") and "en_pocas_palabras" not in (per.get("content") or {})
    if per.get("edition_key") == edition_key and have_ai and not FORCE_PERIODICO and not needs_simple:
        return per

    context, used_news = build_context(eid, calendar, markets, news, trump, fed)
    content, model, ai = None, None, False
    if GEMINI_KEY:
        try:
            prompt = PERIODICO_PROMPT.format(
                edition_name=ename, now_mad=now_mad.strftime("%A %d/%m/%Y %H:%M"), context=context)
            content, model = gemini_json(prompt, max_tokens=6000)
            content.setdefault("en_pocas_palabras", [])
            ai = True

            def links(idx):
                out = []
                for i in idx or []:
                    if isinstance(i, int) and 0 <= i < len(used_news):
                        n = used_news[i]
                        out.append({"title": n["source"], "url": n["link"]})
                return out[:3]
            for c in content.get("claves", []) or []:
                c["links"] = links(c.pop("fuentes", []))
            for s in content.get("secciones", []) or []:
                for p in s.get("puntos", []) or []:
                    p["links"] = links(p.pop("fuentes", []))
            ok("periodico", {"model": model})
        except Exception as e:
            fail("periodico", f"Gemini: {e}")
            content = None
    if content is None:
        # Si ya habia una edicion con IA de hoy, no la machacamos con la version sin IA
        if per.get("ai") and per.get("edition_key", "").startswith(start.strftime("%Y-%m-%d")):
            return per
        content = periodico_fallback(eid, news, calendar)
        if not GEMINI_KEY:
            ok("periodico", {"model": None})

    archive = per.get("archive", [])
    if per.get("edition_key") and per.get("edition_key") != edition_key and per.get("ai"):
        archive.insert(0, {k: per[k] for k in ("edition_key", "edition", "edition_name", "generated_at", "content") if k in per})
    archive = archive[:10]
    out = {
        "edition_key": edition_key, "edition": eid, "edition_name": ename,
        "generated_at": iso(now_utc()), "ai": ai, "model": model,
        "content": content, "archive": archive,
    }
    save("periodico.json", out)
    return out


# ----------------------------------------------------------------------------
# Principal
# ----------------------------------------------------------------------------

PREV_STATUS = {}


def main():
    global PREV_STATUS
    os.makedirs(DATA, exist_ok=True)
    PREV_STATUS = load("status.json", {})
    if PREV_STATUS.get("demo"):
        # Primera ejecucion real: borra los datos de demostracion
        for f in os.listdir(DATA):
            if f.endswith(".json"):
                os.remove(os.path.join(DATA, f))
        PREV_STATUS = {}
    if PREV_STATUS.get("gemini_model"):
        STATUS["gemini_model"] = PREV_STATUS["gemini_model"]

    def safe(fn, name, default):
        try:
            return fn()
        except Exception as e:
            traceback.print_exc()
            fail(name, e)
            return default

    calendar = safe(update_calendar, "calendario", load("calendar.json", {}).get("events", []))
    markets = safe(update_markets, "mercados", load("markets.json", {"main": [], "heavy": []}))
    news = safe(update_news, "noticias", load("news.json", {"items": []}))
    fed = safe(update_fed, "fed", load("fed.json", {"items": []}))
    trump_res = safe(update_trump, "trump", (load("trump.json", {"posts": []}), []))
    trump, new_posts = trump_res
    trump = safe(lambda: classify_trump_ai(trump, new_posts), "trump_ia", trump)
    fed = safe(lambda: update_fed_summary(fed, calendar), "fed_ia", fed)
    safe(update_earnings, "resultados", None)
    safe(update_earnings_summary, "resultados_ia", None)
    safe(lambda: update_periodico(calendar, markets, news, trump, fed), "periodico", None)

    STATUS["updated_at"] = iso(now_utc())
    STATUS["demo"] = False
    STATUS["gemini"] = bool(GEMINI_KEY)
    STATUS["finnhub"] = bool(FINNHUB_KEY)
    save("status.json", STATUS)
    bad = [k for k, v in STATUS["sources"].items() if not v.get("ok")]
    print("OK" if not bad else f"Terminado con avisos en: {', '.join(bad)}")


if __name__ == "__main__":
    main()
