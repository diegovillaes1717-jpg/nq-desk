/* NQ Desk · lógica de la web (sin dependencias) */
(function () {
  'use strict';

  var TZ = 'Europe/Madrid';
  var ET = 'America/New_York';
  var FILES = ['status', 'calendar', 'markets', 'news', 'trump', 'periodico', 'fed', 'earnings'];
  var REFRESH_MS = 60 * 1000;
  var TABS = ['panel', 'calendario', 'periodico', 'trump', 'mercados', 'resultados', 'fed'];

  var S = {
    d: {}, tab: 'panel', loaded: false,
    calView: 'week', weekOff: 0, monthOff: 0,
    imp: { Alto: true, Medio: true }, onlyKey: false,
    newsCat: 'Todas', trumpFilter: 'Todos', perIdx: -1,
    tvLoaded: false, toastedTrump: {}
  };

  /* ---------------- utilidades ---------------- */
  function $(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function safeUrl(u) { return /^https?:\/\//i.test(u || '') ? esc(u) : '#'; }
  function D(x) { return x instanceof Date ? x : new Date(x); }
  var fmtCache = {};
  function fmt(date, opts, tz) {
    var k = JSON.stringify(opts) + (tz || TZ);
    if (!fmtCache[k]) fmtCache[k] = new Intl.DateTimeFormat('es-ES', Object.assign({ timeZone: tz || TZ }, opts));
    return fmtCache[k].format(D(date));
  }
  function hm(d) { return fmt(d, { hour: '2-digit', minute: '2-digit', hour12: false }); }
  function parts(date, tz) {
    var p = {};
    new Intl.DateTimeFormat('en-US', {
      timeZone: tz || TZ, year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false, weekday: 'short'
    }).formatToParts(D(date)).forEach(function (x) { p[x.type] = x.value; });
    var wd = { Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6, Sun: 0 }[p.weekday];
    return { y: +p.year, m: +p.month, d: +p.day, h: +p.hour % 24, mi: +p.minute, s: +p.second, wd: wd };
  }
  function dayKey(date, tz) {
    var p = parts(date, tz);
    return p.y + '-' + String(p.m).padStart(2, '0') + '-' + String(p.d).padStart(2, '0');
  }
  // fecha/hora "de pared" en una zona -> Date (UTC)
  function zoned(y, m, d, h, mi, tz) {
    var guess = Date.UTC(y, m - 1, d, h, mi);
    for (var i = 0; i < 2; i++) {
      var p = parts(new Date(guess), tz);
      var asUtc = Date.UTC(p.y, p.m - 1, p.d, p.h, p.mi);
      guess += Date.UTC(y, m - 1, d, h, mi) - asUtc;
    }
    return new Date(guess);
  }
  function keyToDate(k) { var a = k.split('-'); return zoned(+a[0], +a[1], +a[2], 12, 0, TZ); }
  function addDays(k, n) {
    var a = k.split('-');
    var t = new Date(Date.UTC(+a[0], +a[1] - 1, +a[2] + n));
    return t.getUTCFullYear() + '-' + String(t.getUTCMonth() + 1).padStart(2, '0') + '-' + String(t.getUTCDate()).padStart(2, '0');
  }
  function weekdayOfKey(k) { var a = k.split('-'); return new Date(Date.UTC(+a[0], +a[1] - 1, +a[2])).getUTCDay(); }
  function ago(iso) {
    if (!iso) return '';
    var m = Math.round((Date.now() - D(iso).getTime()) / 60000);
    if (m < 1) return 'ahora mismo';
    if (m < 60) return 'hace ' + m + ' min';
    var h = Math.floor(m / 60);
    if (h < 24) return 'hace ' + h + ' h' + (m % 60 && h < 6 ? ' ' + (m % 60) + ' min' : '');
    var dd = Math.floor(h / 24);
    return 'hace ' + dd + (dd === 1 ? ' día' : ' días');
  }
  function countdown(ms) {
    if (ms <= 0) return '00:00';
    var s = Math.floor(ms / 1000), d = Math.floor(s / 86400), h = Math.floor(s % 86400 / 3600),
      m = Math.floor(s % 3600 / 60), ss = s % 60;
    if (d > 0) return d + ' d ' + h + ' h ' + String(m).padStart(2, '0') + ' min';
    if (h > 0) return h + ' h ' + String(m).padStart(2, '0') + ' min';
    return String(m).padStart(2, '0') + ':' + String(ss).padStart(2, '0');
  }
  function cap(s) { return s ? s.charAt(0).toUpperCase() + s.slice(1) : s; }
  function num(v, dec) {
    if (v == null || isNaN(v)) return '—';
    return Number(v).toLocaleString('en-US', { minimumFractionDigits: dec, maximumFractionDigits: dec });
  }
  function priceDec(sym, p) {
    if (sym === 'US10Y' || sym === 'VIX' || sym === 'DXY' || sym === 'CL') return 2;
    return p >= 1000 ? 2 : 2;
  }
  function chg(v, mode) {
    if (v == null || isNaN(v)) return '<span class="flat">—</span>';
    var cls = v > 0 ? 'up' : v < 0 ? 'down' : 'flat';
    var txt = (v > 0 ? '+' : '') + (mode === 'bps' ? num(v, 1) + 'pb' : num(v, 2) + '%');
    return '<span class="' + cls + '">' + txt + '</span>';
  }
  function events() { return (S.d.calendar && S.d.calendar.events) || []; }
  function isFed(e) { return e.category === 'Fed'; }

  /* ---------------- carga de datos ---------------- */
  function loadAll() {
    var t = Date.now();
    return Promise.all(FILES.map(function (f) {
      return fetch('data/' + f + '.json?t=' + t, { cache: 'no-store' })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (j) { if (j) S.d[f] = j; })
        .catch(function () { });
    })).then(function () {
      S.loaded = true;
      checkTrumpNew();
      renderAll();
    });
  }

  /* ---------------- navegación ---------------- */
  function setTab(t) {
    if (TABS.indexOf(t) < 0) t = 'panel';
    S.tab = t;
    TABS.forEach(function (x) { $('tab-' + x).hidden = x !== t; });
    document.querySelectorAll('.nav a').forEach(function (a) { a.classList.toggle('active', a.dataset.tab === t); });
    if (t === 'trump') markTrumpSeen();
    renderTab(t);
    if (t === 'mercados') loadTV();
  }
  window.addEventListener('hashchange', function () { setTab(location.hash.slice(1)); window.scrollTo(0, 0); });

  /* ---------------- render general ---------------- */
  function renderAll() {
    renderHeader();
    renderAlert();
    renderTab(S.tab);
    renderFooter();
  }
  function renderTab(t) {
    if (!S.loaded) return;
    var fn = { panel: renderPanel, calendario: renderCalendar, periodico: renderPeriodico, trump: renderTrump,
      mercados: renderMarkets, resultados: renderEarnings, fed: renderFed }[t];
    fn && fn();
  }

  function renderHeader() {
    var st = S.d.status || {};
    $('demo-banner').hidden = !st.demo;
    var live = $('live-status'), txt = $('live-text');
    live.className = 'live';
    if (!st.updated_at) { txt.textContent = 'Sin datos todavía'; live.classList.add('warn'); return; }
    var mins = (Date.now() - D(st.updated_at).getTime()) / 60000;
    if (mins > 45) { live.classList.add('err'); txt.textContent = 'Sin actualizar ' + ago(st.updated_at); }
    else if (mins > 25) { live.classList.add('warn'); txt.textContent = 'Actualizado ' + ago(st.updated_at); }
    else { live.classList.add('ok'); txt.textContent = 'En vivo · ' + ago(st.updated_at); }
  }

  function tick() {
    var now = new Date();
    $('clock').textContent = cap(fmt(now, { weekday: 'short', day: 'numeric', month: 'short' })) + ' · ' +
      fmt(now, { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }) + ' Madrid';
    document.querySelectorAll('[data-cd]').forEach(function (el) {
      var target = +el.getAttribute('data-cd');
      el.textContent = countdown(target - Date.now());
    });
  }

  /* ---------------- próximo evento clave ---------------- */
  function nextKey() {
    var now = Date.now();
    var evs = events().filter(function (e) { return e.impact !== 'Festivo'; });
    var live = evs.filter(function (e) {
      var t = D(e.date).getTime(); return e.key && t <= now && now - t < 20 * 60000;
    })[0];
    if (live) return { e: live, now: true };
    var up = evs.filter(function (e) { return D(e.date).getTime() > now; });
    var k = up.filter(function (e) { return e.key; })[0] || up.filter(function (e) { return e.impact === 'Alto'; })[0];
    return k ? { e: k, now: false } : null;
  }
  function renderAlert() {
    var el = $('next-alert'), n = nextKey();
    if (!n) { el.hidden = true; return; }
    var e = n.e, t = D(e.date).getTime();
    el.hidden = false;
    el.className = 'alert' + (n.now ? ' now' : '');
    el.innerHTML = '<div class="l"><span class="tag">' + (n.now ? 'PUBLICADO AHORA' : (e.key ? 'PRÓXIMO EVENTO CLAVE' : 'PRÓXIMO ALTO IMPACTO')) + '</span>' +
      '<span class="t">' + esc(e.title) + '</span>' +
      '<span class="w">' + cap(fmt(e.date, { weekday: 'short', day: 'numeric', month: 'short' })) + ' · ' + hm(e.date) + '</span>' +
      (e.forecast ? '<span class="w">Previsión ' + esc(e.forecast) + (e.previous ? ' · Anterior ' + esc(e.previous) : '') + '</span>' : '') +
      '</div>' + (n.now ? '<span class="cd">' + ago(e.date) + '</span>' : '<span class="cd" data-cd="' + t + '">' + countdown(t - Date.now()) + '</span>');
  }

  /* ---------------- sesión y contrato ---------------- */
  function thirdFriday(y, m) {
    var first = new Date(Date.UTC(y, m - 1, 1)).getUTCDay();
    var day = 1 + ((5 - first + 7) % 7) + 14;
    return day;
  }
  function contractInfo() {
    var now = Date.now(), codes = { 3: 'H', 6: 'M', 9: 'U', 12: 'Z' }, list = [];
    var y0 = parts(new Date(), ET).y;
    [y0, y0 + 1].forEach(function (y) {
      [3, 6, 9, 12].forEach(function (m) {
        var d = thirdFriday(y, m);
        var expiry = zoned(y, m, d, 9, 30, ET);
        var roll = zoned(y, m, d - 8, 9, 30, ET);
        list.push({ code: 'NQ' + codes[m] + String(y).slice(-1), expiry: expiry, roll: roll, y: y, m: m });
      });
    });
    for (var i = 0; i < list.length - 1; i++) {
      if (list[i].roll.getTime() > now) return { active: list[i], next: list[i + 1] };
    }
    return { active: list[list.length - 2], next: list[list.length - 1] };
  }
  function sessionInfo() {
    var p = parts(new Date(), ET), wd = p.wd, h = p.h + p.mi / 60;
    var status, cls;
    if (wd === 6 || (wd === 5 && h >= 17) || (wd === 0 && h < 18)) { status = 'Cerrado'; cls = 'closed'; }
    else if (h >= 17 && h < 18) { status = 'Pausa diaria'; cls = 'pause'; }
    else { status = 'Abierto'; cls = 'open'; }
    var rth = wd >= 1 && wd <= 5 && h >= 9.5 && h < 16;
    var todayET = parts(new Date(), ET);
    var open = zoned(todayET.y, todayET.m, todayET.d, 9, 30, ET);
    var close = zoned(todayET.y, todayET.m, todayET.d, 16, 0, ET);
    var tk = dayKey(new Date());
    var hol = events().filter(function (e) { return e.impact === 'Festivo' && D(e.date).getTime() > Date.now() - 86400000; })[0];
    return { status: status, cls: cls, rth: rth, open: open, close: close, hol: hol, holToday: hol && dayKey(hol.date) === tk };
  }
  function sessionCard() {
    var s = sessionInfo(), c = contractInfo();
    var daysRoll = Math.ceil((c.active.roll.getTime() - Date.now()) / 86400000);
    var dfmt = { weekday: 'short', day: 'numeric', month: 'short' };
    return '<div class="card"><div class="card-h"><h3>Sesión y contrato</h3><span class="status-pill ' + s.cls + '">CME ' + s.status.toUpperCase() + '</span></div>' +
      '<div class="kv"><span class="k">Sesión regular NY</span><span class="v">' + hm(s.open) + ' – ' + hm(s.close) + ' ' + (s.rth ? '<span class="up">· abierta</span>' : '') + '</span></div>' +
      '<div class="kv"><span class="k">Contrato activo</span><span class="v" style="color:var(--accent);font-weight:700">' + c.active.code + '</span></div>' +
      '<div class="kv"><span class="k">Rollover a ' + c.next.code + '</span><span class="v">' + cap(fmt(c.active.roll, dfmt)) + (daysRoll <= 10 ? ' <span style="color:var(--med-ink)">(' + daysRoll + ' d)</span>' : '') + '</span></div>' +
      '<div class="kv"><span class="k">Vencimiento ' + c.active.code + '</span><span class="v">' + cap(fmt(c.active.expiry, dfmt)) + '</span></div>' +
      (s.hol ? '<div class="kv"><span class="k">Próximo festivo EE. UU.</span><span class="v" style="color:var(--med-ink)">' + cap(fmt(s.hol.date, dfmt)) + '</span></div>' : '') +
      '<div class="sub" style="margin-top:8px">Horas en horario de Madrid. Rollover estimado: 8 días antes del vencimiento.</div></div>';
  }

  /* ---------------- tiles de mercado ---------------- */
  function spark(arr, big) {
    if (!arr || arr.length < 2) return '';
    var w = 120, h = big ? 50 : 34, mn = Math.min.apply(null, arr), mx = Math.max.apply(null, arr), r = mx - mn || 1;
    var pts = arr.map(function (v, i) { return (i / (arr.length - 1) * w).toFixed(1) + ',' + (h - 3 - (v - mn) / r * (h - 6)).toFixed(1); }).join(' ');
    var col = arr[arr.length - 1] >= arr[0] ? 'var(--up)' : 'var(--down)';
    return '<svg viewBox="0 0 ' + w + ' ' + h + '" preserveAspectRatio="none" aria-hidden="true" style="height:' + h + 'px"><polyline fill="none" stroke="' + col + '" stroke-width="1.6" vector-effect="non-scaling-stroke" points="' + pts + '"/></svg>';
  }
  function tilesHTML(big) {
    var m = (S.d.markets && S.d.markets.main) || [];
    if (!m.length) return '<div class="empty">Los datos de mercado aparecerán tras la primera actualización.</div>';
    return '<div class="tiles">' + m.map(function (q) {
      return '<div class="tile' + (big ? ' big' : '') + (q.stale ? ' stale' : '') + '" title="' + (q.market_time ? 'Último dato: ' + esc(fmt(q.market_time, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })) : '') + '">' +
        '<div class="h"><span class="sym">' + esc(q.sym) + '</span><span class="nm">' + esc(q.name) + '</span></div>' +
        '<div class="px">' + num(q.price, priceDec(q.sym, q.price)) + (q.sym === 'US10Y' ? '<span style="font-size:14px">%</span>' : '') + '</div>' +
        spark(q.spark, big) +
        '<div class="chg3"><div><div class="l">DÍA</div><div class="v">' + chg(q.d, q.mode) + '</div></div>' +
        '<div><div class="l">SEM</div><div class="v">' + chg(q.w, q.mode) + '</div></div>' +
        '<div><div class="l">MES</div><div class="v">' + chg(q.m, q.mode) + '</div></div></div></div>';
    }).join('') + '</div>';
  }

  /* ---------------- eventos ---------------- */
  function valsHTML(e) {
    var v = [];
    if (e.actual) v.push('Real <b>' + esc(e.actual) + '</b>');
    if (e.forecast) v.push('Prev. <b>' + esc(e.forecast) + '</b>');
    if (e.previous) v.push('Ant. <b>' + esc(e.previous) + '</b>');
    return v.length ? '<div class="vals">' + v.join(' · ') + '</div>' : '';
  }
  function evPass(e) {
    if (e.impact === 'Festivo') return true;
    if (S.onlyKey && !e.key) return false;
    return !!S.imp[e.impact];
  }
  function evCard(e, nextId) {
    var past = D(e.date).getTime() < Date.now() - 5 * 60000;
    var allDay = e.impact === 'Festivo';
    if (allDay) return '<div class="ev hol"><div class="top"><span class="tm">Todo el día</span><span class="pill Festivo">FESTIVO</span></div><div class="ti">' + esc(e.title) + '</div><div class="vals">Horario reducido o mercado cerrado en EE. UU.</div></div>';
    var cls = 'ev' + (e.key ? ' key' : '') + (past ? ' past' : '') + (e.id === nextId ? ' next' : '');
    return '<div class="' + cls + '" title="' + esc(e.title_en) + ' · ' + esc(e.category) + '"><div class="top"><span class="tm">' + hm(e.date) + '</span>' +
      (e.key ? '<span class="pill key">CLAVE</span>' : '<span class="pill ' + e.impact + '">' + e.impact.toUpperCase() + '</span>') +
      '</div><div class="ti">' + esc(e.title) + '</div>' + valsHTML(e) + '</div>';
  }
  function todayEvents() {
    var k = dayKey(new Date());
    return events().filter(function (e) { return dayKey(e.date) === k; });
  }
  function todayRow(e) {
    var past = D(e.date).getTime() < Date.now() - 5 * 60000;
    if (e.impact === 'Festivo') return '<div class="today-ev"><span class="tm">—</span><span class="ti">' + esc(e.title) + '</span><span class="pill Festivo">FESTIVO</span></div>';
    return '<div class="today-ev' + (e.key ? ' key' : '') + (past ? ' past' : '') + '"><span class="tm">' + hm(e.date) + '</span><span class="ti">' + esc(e.title) +
      (e.forecast || e.actual ? '<div class="sub" style="' + (e.key ? 'color:#FECACA' : '') + '">' + (e.actual ? 'Real ' + esc(e.actual) + ' · ' : '') + (e.forecast ? 'Prev. ' + esc(e.forecast) : '') + '</div>' : '') +
      '</span>' + (e.key ? '<span class="pill key">CLAVE</span>' : '<span class="pill ' + e.impact + '">' + e.impact.toUpperCase() + '</span>') + '</div>';
  }

  /* ---------------- PANEL ---------------- */
  function renderPanel() {
    var tev = todayEvents();
    var tomorrowK = addDays(dayKey(new Date()), 1);
    var tmr = events().filter(function (e) { return dayKey(e.date) === tomorrowK && (e.impact === 'Alto' || e.key); });
    var posts = trumpPosts().slice(0, 3);
    var per = S.d.periodico, pc = per && per.content;
    var news = ((S.d.news && S.d.news.items) || []).slice(0, 8);

    var html = tilesHTML(false);
    html += '<div class="row"><div class="grow" style="display:flex;flex-direction:column;gap:20px">';
    html += '<div class="card"><div class="card-h"><div><h2>Hoy · ' + cap(fmt(new Date(), { weekday: 'long', day: 'numeric', month: 'long' })) + '</h2><div class="sub">Eventos USD que afectan al NQ · hora de Madrid</div></div><a class="link-more" href="#calendario">Ver calendario →</a></div>';
    html += tev.length ? '<div class="list">' + tev.map(todayRow).join('') + '</div>' : '<div class="empty">Hoy no hay eventos económicos relevantes para el NQ.</div>';
    if (tmr.length) html += '<div class="section-label" style="margin-top:16px">Mañana (alto impacto)</div><div class="list">' + tmr.map(todayRow).join('') + '</div>';
    html += '</div>';

    html += '<div class="card"><div class="card-h"><div><h2>Periódico</h2><div class="sub">' + (per ? esc(per.edition_name || '') + ' · ' + ago(per.generated_at) : 'Pendiente de la primera edición') + '</div></div><a class="link-more" href="#periodico">Leer completo →</a></div>';
    if (pc) {
      html += '<div class="paper-head"><h1 style="font-size:22px">' + esc(pc.titular) + '</h1><p class="lead" style="font-size:15px">' + esc(pc.resumen) + '</p></div>';
      if (pc.claves && pc.claves.length) html += '<div class="grid-auto" style="margin-top:14px">' + pc.claves.slice(0, 3).map(claveHTML).join('') + '</div>';
    } else html += '<div class="empty">El periódico se genera a las 07:00, 15:00 y 22:00 (hora de Madrid).</div>';
    html += '</div>';

    html += '<div class="card"><div class="card-h"><h2>Últimos titulares filtrados</h2><a class="link-more" href="#periodico">Ver todos →</a></div>';
    html += news.length ? '<div class="list">' + news.map(newsItem).join('') + '</div>' : '<div class="empty">Sin titulares todavía.</div>';
    html += '</div></div>';

    html += '<aside class="side"><div class="card"><div class="card-h"><h3>Trump</h3><a class="link-more" href="#trump">Ver todo →</a></div>';
    html += posts.length ? '<div class="list">' + posts.map(function (p) { return postHTML(p, true); }).join('') + '</div>' : '<div class="empty">Sin publicaciones relevantes recientes.</div>';
    html += '</div>' + sessionCard() + '</aside></div>';
    $('tab-panel').innerHTML = html;
  }

  /* ---------------- CALENDARIO ---------------- */
  function calToolbar(label) {
    return '<div class="card-h"><div><h2>Calendario económico</h2><div class="sub">Forex Factory · USD · impacto alto y medio · inflación, empleo, banco central, encuestas de consumidores y discursos · hora de Madrid</div></div>' +
      '<div class="toolbar"><div class="seg" role="group" aria-label="Vista"><button data-act="view" data-v="week" class="' + (S.calView === 'week' ? 'on' : '') + '">Semanal</button><button data-act="view" data-v="month" class="' + (S.calView === 'month' ? 'on' : '') + '">Mensual</button></div>' +
      '<button class="btn icon" data-act="prev" aria-label="Anterior">‹</button><button class="btn" data-act="today">Hoy</button><button class="btn icon" data-act="next" aria-label="Siguiente">›</button>' +
      '<strong style="min-width:150px">' + label + '</strong></div></div>' +
      '<div class="toolbar" style="margin-bottom:14px">' +
      ['Alto', 'Medio'].map(function (i) { return '<button class="fchip' + (S.imp[i] ? ' on' : '') + '" data-act="imp" data-v="' + i + '"><span class="dot-i ' + i + '"></span>' + i + '</button>'; }).join('') +
      '<button class="fchip' + (S.onlyKey ? ' on' : '') + '" data-act="key"><span class="dot-i" style="background:var(--key)"></span>Solo clave (FOMC, IPC, NFP, PCE…)</button></div>';
  }
  function renderCalendar() {
    var el = $('tab-calendario');
    var html = '<div class="card">';
    var evs = events().filter(evPass);
    var nk = nextKey(), nextId = nk && !nk.now ? nk.e.id : null;
    var today = dayKey(new Date());
    if (S.calView === 'week') {
      var wd = weekdayOfKey(today), monday = addDays(today, -((wd + 6) % 7) + S.weekOff * 7);
      var keys = []; for (var i = 0; i < 7; i++) keys.push(addDays(monday, i));
      var byDay = {}; keys.forEach(function (k) { byDay[k] = []; });
      evs.forEach(function (e) { var k = dayKey(e.date); if (byDay[k]) byDay[k].push(e); });
      var show = keys.filter(function (k, i) { return i < 5 || byDay[k].length; });
      var label = cap(fmt(keyToDate(monday), { day: 'numeric', month: 'short' })) + ' – ' + fmt(keyToDate(keys[6]), { day: 'numeric', month: 'short', year: 'numeric' });
      html += calToolbar(label);
      html += '<div class="week-scroll"><div class="week" style="grid-template-columns:repeat(' + show.length + ',minmax(0,1fr))">';
      show.forEach(function (k) {
        var dt = keyToDate(k);
        html += '<div class="day"><div class="day-h' + (k === today ? ' today' : '') + '"><div class="n">' + cap(fmt(dt, { weekday: 'long' })) + (k === today ? ' · hoy' : '') + '</div><div class="d">' + fmt(dt, { day: 'numeric', month: 'short' }) + '</div></div>';
        html += byDay[k].length ? byDay[k].map(function (e) { return evCard(e, nextId); }).join('') : '<div class="empty" style="padding:12px;font-size:12px">Sin eventos</div>';
        html += '</div>';
      });
      html += '</div></div>';
      var hasAny = show.some(function (k) { return byDay[k].length; });
      if (!hasAny && S.weekOff > 0) html += '<p class="sub" style="margin-top:12px">Forex Factory publica el calendario semana a semana: esta semana aparecerá automáticamente cuando esté disponible.</p>';
    } else {
      var tp = today.split('-'), y = +tp[0], m = +tp[1] + S.monthOff;
      while (m > 12) { m -= 12; y++; } while (m < 1) { m += 12; y--; }
      var first = y + '-' + String(m).padStart(2, '0') + '-01';
      var start = addDays(first, -((weekdayOfKey(first) + 6) % 7));
      var byDay2 = {};
      evs.forEach(function (e) { var k = dayKey(e.date); (byDay2[k] = byDay2[k] || []).push(e); });
      html += calToolbar(cap(fmt(keyToDate(first), { month: 'long', year: 'numeric' })));
      html += '<div class="week-scroll"><div class="month">' + ['LUN', 'MAR', 'MIÉ', 'JUE', 'VIE', 'SÁB', 'DOM'].map(function (w) { return '<div class="wd">' + w + '</div>'; }).join('');
      for (var c = 0; c < 42; c++) {
        var k = addDays(start, c), inMonth = +k.split('-')[1] === m;
        if (c >= 35 && !inMonth) break;
        var list = (byDay2[k] || []).slice().sort(function (a, b) { return (b.key - a.key) || (a.date < b.date ? -1 : 1); });
        var shown = list.slice(0, 5);
        html += '<button class="mcell' + (inMonth ? '' : ' out') + (k === today ? ' today' : '') + '" data-act="gotoday" data-v="' + k + '"><span class="num">' + (+k.split('-')[2]) + '</span>' +
          shown.map(function (e) {
            if (e.impact === 'Festivo') return '<span class="mev"><span class="dot-i Festivo"></span><span class="txt">Festivo EE. UU.</span></span>';
            return '<span class="mev' + (e.key ? ' key' : '') + '">' + (e.key ? '' : '<span class="dot-i ' + e.impact + '"></span>') + '<span class="tm">' + hm(e.date) + '</span><span class="txt">' + esc(e.title) + '</span></span>';
          }).join('') + (list.length > 5 ? '<span class="mmore">+' + (list.length - 5) + ' más</span>' : '') + '</button>';
      }
      html += '</div></div><p class="sub" style="margin-top:12px">Pulsa un día para verlo en la vista semanal. Las semanas futuras se completan automáticamente cuando Forex Factory las publica; las reuniones del FOMC programadas ya aparecen.</p>';
    }
    html += '</div>';
    el.innerHTML = html;
  }

  /* ---------------- PERIÓDICO ---------------- */
  function linksHTML(ls) {
    if (!ls || !ls.length) return '';
    return '<div class="srcs">' + ls.map(function (l) { return '<a href="' + safeUrl(l.url) + '" target="_blank" rel="noopener">' + esc(l.title) + ' ↗</a>'; }).join('') + '</div>';
  }
  function claveHTML(c) {
    return '<div class="clave"><div style="display:flex;justify-content:space-between;gap:8px;align-items:start"><h4>' + esc(c.titulo) + '</h4>' +
      (c.impacto ? '<span class="pill ' + esc(c.impacto) + '">' + esc(c.impacto).toUpperCase() + '</span>' : '') + '</div><p>' + esc(c.detalle) + '</p>' + linksHTML(c.links) + '</div>';
  }
  function newsItem(n) {
    return '<div class="news-item"><div class="meta"><span class="chip">' + esc(n.category) + '</span><span>' + esc(n.source) + '</span><span>· ' + hm(n.date) + ' (' + ago(n.date) + ')</span></div>' +
      '<a class="t" href="' + safeUrl(n.link) + '" target="_blank" rel="noopener">' + esc(n.title) + '</a>' + (n.summary ? '<p>' + esc(n.summary.slice(0, 220)) + '</p>' : '') + '</div>';
  }
  function renderPeriodico() {
    var per = S.d.periodico, el = $('tab-periodico');
    var html = '';
    if (!per || !per.content) {
      html += '<div class="card"><div class="empty">Todavía no hay ninguna edición. El periódico se genera a las 07:00, 15:00 y 22:00 los días laborables, el sábado a las 10:00 (resumen semanal) y el domingo a las 18:00 (previa de la semana).</div></div>';
    } else {
      var ed = S.perIdx >= 0 && per.archive && per.archive[S.perIdx] ? per.archive[S.perIdx] : per;
      var c = ed.content;
      var editions = [per].concat(per.archive || []);
      html += '<div class="card"><div class="card-h"><div><div class="section-label">' + esc(ed.edition_name || 'Edición') + '</div><div class="sub">' +
        cap(fmt(ed.generated_at, { weekday: 'long', day: 'numeric', month: 'long' })) + ' · ' + hm(ed.generated_at) + ' · ' +
        (per.ai || ed === per && per.ai ? 'Redactado con IA' + (ed.model || per.model ? ' (' + esc(ed.model || per.model) + ')' : '') : 'Modo sin IA') + '</div></div>';
      if (editions.length > 1) {
        html += '<div class="toolbar">' + editions.slice(0, 6).map(function (x, i) {
          var idx = i - 1;
          return '<button class="fchip' + (S.perIdx === idx ? ' on' : '') + '" data-act="per" data-v="' + idx + '">' + (i === 0 ? 'Actual' : cap(fmt(x.generated_at, { weekday: 'short' })) + ' ' + hm(x.generated_at)) + '</button>';
        }).join('') + '</div>';
      }
      html += '</div><div class="paper-head"><h1>' + esc(c.titular) + '</h1><p class="lead">' + esc(c.resumen) + '</p>' +
        (c.tono ? '<div><span class="tono ' + esc(c.tono) + '">Tono del mercado: ' + esc(c.tono) + '</span> <span class="sub">' + esc(c.tono_motivo || '') + '</span></div>' : '') + '</div></div>';

      if (c.claves && c.claves.length) html += '<div class="card"><div class="card-h"><h2>Las claves</h2></div><div class="grid-auto">' + c.claves.map(claveHTML).join('') + '</div></div>';

      html += '<div class="row"><div class="grow" style="display:flex;flex-direction:column;gap:20px">';
      (c.secciones || []).forEach(function (s) {
        if (!s.puntos || !s.puntos.length) return;
        html += '<div class="card"><div class="section-label">' + esc(s.nombre) + '</div><ul class="pts">' + s.puntos.map(function (p) {
          return '<li>' + esc(p.texto) + (p.links && p.links.length ? ' ' + linksHTML(p.links) : '') + '</li>';
        }).join('') + '</ul></div>';
      });
      html += '</div><aside class="side">';
      if (c.agenda && c.agenda.length) html += '<div class="card"><div class="card-h"><h3>Agenda</h3></div>' + c.agenda.map(function (a) {
        return '<div class="agenda-row"><div class="h">' + esc(a.hora) + '</div><div><div class="e">' + esc(a.evento) + '</div>' + (a.por_que_importa ? '<div class="w">' + esc(a.por_que_importa) + '</div>' : '') + '</div></div>';
      }).join('') + '</div>';
      if (c.riesgos && c.riesgos.length) html += '<div class="card"><div class="card-h"><h3>A vigilar</h3></div><ul class="pts">' + c.riesgos.map(function (r) { return '<li>' + esc(r) + '</li>'; }).join('') + '</ul></div>';
      html += '</aside></div>';
    }
    // titulares
    var items = (S.d.news && S.d.news.items) || [];
    var cats = ['Todas'];
    items.forEach(function (n) { if (cats.indexOf(n.category) < 0) cats.push(n.category); });
    var shown = items.filter(function (n) { return S.newsCat === 'Todas' || n.category === S.newsCat; });
    html += '<div class="card"><div class="card-h"><div><h2>Titulares filtrados</h2><div class="sub">Últimas 48 h · solo noticias con impacto potencial en el NQ · ' + items.length + ' titulares</div></div>' +
      '<div class="toolbar">' + cats.map(function (c) { return '<button class="fchip' + (S.newsCat === c ? ' on' : '') + '" data-act="cat" data-v="' + esc(c) + '">' + esc(c) + '</button>'; }).join('') + '</div></div>';
    html += shown.length ? '<div class="list">' + shown.slice(0, 60).map(newsItem).join('') + '</div>' : '<div class="empty">Sin titulares en esta categoría.</div>';
    html += '</div>';
    el.innerHTML = html;
  }

  /* ---------------- TRUMP ---------------- */
  function trumpPosts() {
    return ((S.d.trump && S.d.trump.posts) || []).filter(function (p) { return p.impact === 'Alto' || p.impact === 'Medio' || p.impact === 'Bajo'; });
  }
  function seenTs() { try { return +localStorage.getItem('nq_trump_seen') || 0; } catch (e) { return 0; } }
  function markTrumpSeen() {
    try { localStorage.setItem('nq_trump_seen', String(Date.now())); } catch (e) { }
    updateBadge();
  }
  function unseen() {
    var ts = seenTs();
    return trumpPosts().filter(function (p) { return p.impact !== 'Bajo' && D(p.detected_at || p.date).getTime() > ts; });
  }
  function updateBadge() {
    var n = S.tab === 'trump' ? 0 : unseen().length, b = $('trump-badge');
    b.hidden = !n; b.textContent = n;
    document.title = (n ? '(' + n + ') ' : '') + 'NQ Desk · Noticias del Nasdaq 100';
  }
  function checkTrumpNew() {
    var st = S.d.status || {};
    if (st.demo) { updateBadge(); return; }
    var first = !Object.keys(S.toastedTrump).length && !S._trumpInit;
    S._trumpInit = true;
    var list = unseen();
    list.slice(0, 3).forEach(function (p) {
      if (S.toastedTrump[p.id]) return;
      S.toastedTrump[p.id] = 1;
      if (S.tab !== 'trump') toast(p);
    });
    if (first) list.forEach(function (p) { S.toastedTrump[p.id] = 1; });
    updateBadge();
  }
  function toast(p) {
    var t = document.createElement('div');
    t.className = 'toast ' + p.impact;
    t.innerHTML = '<div class="tt">NUEVO POST DE TRUMP · IMPACTO ' + esc(p.impact).toUpperCase() + '</div><div class="tx">' + esc(p.text) + '</div>' +
      '<div class="ac"><button class="btn" data-x>Cerrar</button><a class="btn" href="#trump">Ver</a></div>';
    t.querySelector('[data-x]').onclick = function () { t.remove(); };
    t.querySelector('a').onclick = function () { t.remove(); };
    $('toasts').appendChild(t);
    setTimeout(function () { t.remove(); }, 30000);
  }
  function postHTML(p, compact) {
    var isNew = D(p.detected_at || p.date).getTime() > seenTs() && S.tab !== 'trump';
    var txt = compact && p.text.length > 260 ? p.text.slice(0, 260) + '…' : p.text;
    return '<div class="post ' + esc(p.impact) + (isNew ? ' new' : '') + '"><div class="meta"><span>Truth Social · ' + cap(fmt(p.date, { weekday: 'short', day: 'numeric', month: 'short' })) + ' ' + hm(p.date) + ' (' + ago(p.date) + ')</span>' +
      '<span class="pill ' + esc(p.impact) + '">IMPACTO ' + esc(p.impact).toUpperCase() + '</span></div>' +
      '<div class="txt">' + esc(txt) + '</div>' +
      (p.ai_note ? '<div class="ai"><strong>Análisis:</strong> ' + esc(p.ai_note) + '</div>' : '') +
      '<div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap"><div class="tags">' + (p.tags || []).map(function (t) { return '<span class="chip">' + esc(t) + '</span>'; }).join('') + '</div>' +
      (p.link ? '<a class="link-more" href="' + safeUrl(p.link) + '" target="_blank" rel="noopener">Ver original ↗</a>' : '') + '</div></div>';
  }
  function renderTrump() {
    var all = trumpPosts();
    var list = all.filter(function (p) { return S.trumpFilter === 'Todos' || p.impact === S.trumpFilter; });
    var tr = S.d.trump || {};
    var html = '<div class="card"><div class="card-h"><div><h2>Trump · publicaciones que pueden mover el NQ</h2><div class="sub">Truth Social filtrado por temas de mercado (aranceles, China, Fed, tecnológicas, guerra, impuestos…). Revisado ' + ago(tr.updated_at) + '. Los avisos aparecen en la web en cuanto el robot detecta un post nuevo.</div></div>' +
      '<div class="toolbar">' + ['Todos', 'Alto', 'Medio', 'Bajo'].map(function (f) { return '<button class="fchip' + (S.trumpFilter === f ? ' on' : '') + '" data-act="tf" data-v="' + f + '">' + (f === 'Todos' ? 'Todos' : '<span class="dot-i ' + f + '"></span>' + f) + '</button>'; }).join('') + '</div></div>';
    html += list.length ? '<div class="list">' + list.map(function (p) { return postHTML(p, false); }).join('') + '</div>' : '<div class="empty">No hay publicaciones relevantes en los últimos días.</div>';
    html += '</div>';
    $('tab-trump').innerHTML = html;
  }

  /* ---------------- MERCADOS ---------------- */
  function renderMarkets() {
    var mk = S.d.markets || {};
    var html = '<div class="card"><div class="card-h"><div><h2>Mercados</h2><div class="sub">Variación diaria, semanal (desde el cierre del viernes) y mensual (desde el cierre del mes anterior) · Yahoo Finance, futuros con ~10-15 min de retraso · ' + (mk.updated_at ? 'actualizado ' + ago(mk.updated_at) : '') + '</div></div></div>' + tilesHTML(true) + '</div>';
    var hv = mk.heavy || [];
    html += '<div class="row"><div class="grow"><div class="card" style="height:100%"><div class="card-h"><div><h2>Mapa de calor Nasdaq 100</h2><div class="sub">TradingView · qué está tirando del índice ahora</div></div></div><div class="tv-box" id="tv-heatmap"></div></div></div>';
    html += '<aside class="side"><div class="card"><div class="card-h"><div><h3>Pesos pesados del NQ</h3><div class="sub">Las acciones que más mueven el índice</div></div></div>';
    if (hv.length) {
      html += '<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Acción</th><th class="num">Precio</th><th class="num">Día</th><th class="num">Sem</th><th class="num">Mes</th></tr></thead><tbody>' +
        hv.map(function (q) { return '<tr><td title="' + esc(q.name) + '"><strong style="color:var(--accent)">' + esc(q.sym) + '</strong></td><td class="num">' + num(q.price, 2) + '</td><td class="num">' + chg(q.d) + '</td><td class="num">' + chg(q.w) + '</td><td class="num">' + chg(q.m) + '</td></tr>'; }).join('') +
        '</tbody></table></div>';
    } else html += '<div class="empty">Sin datos todavía.</div>';
    html += '</div></aside></div>';
    // Conserva el widget de TradingView entre refrescos (no recargarlo cada minuto)
    var oldBox = $('tv-heatmap');
    var keep = oldBox && oldBox.childNodes.length ? oldBox : null;
    if (keep) keep.parentNode.removeChild(keep);
    $('tab-mercados').innerHTML = html;
    if (keep) { var nb = $('tv-heatmap'); nb.parentNode.replaceChild(keep, nb); }
    else { S.tvLoaded = false; if (S.tab === 'mercados') loadTV(); }
  }
  function loadTV() {
    var box = $('tv-heatmap');
    if (!box || S.tvLoaded || box.childNodes.length) return;
    S.tvLoaded = true;
    var c = document.createElement('div'); c.className = 'tradingview-widget-container'; c.style.height = '100%';
    var w = document.createElement('div'); w.className = 'tradingview-widget-container__widget'; w.style.height = '100%';
    c.appendChild(w);
    var s = document.createElement('script');
    s.src = 'https://s3.tradingview.com/external-embedding/embed-widget-stock-heatmap.js'; s.async = true;
    s.textContent = JSON.stringify({
      exchanges: [], dataSource: 'NASDAQ100', grouping: 'sector', blockSize: 'market_cap_basic', blockColor: 'change',
      locale: 'es', symbolUrl: '', colorTheme: 'dark', hasTopBar: false, isDataSetEnabled: false, isZoomEnabled: true,
      hasSymbolTooltip: true, isMonoSize: false, width: '100%', height: '100%'
    });
    c.appendChild(s);
    box.appendChild(c);
  }

  /* ---------------- RESULTADOS ---------------- */
  var NAMES = { NVDA: 'Nvidia', MSFT: 'Microsoft', AAPL: 'Apple', AMZN: 'Amazon', META: 'Meta', AVGO: 'Broadcom', GOOGL: 'Alphabet', TSLA: 'Tesla', NFLX: 'Netflix', COST: 'Costco', AMD: 'AMD', PLTR: 'Palantir', ASML: 'ASML', QCOM: 'Qualcomm', ADBE: 'Adobe', MU: 'Micron' };
  function hourTxt(h) { return { bmo: 'Antes de la apertura', amc: 'Tras el cierre', dmh: 'Durante la sesión' }[h] || 'Hora por confirmar'; }
  function renderEarnings() {
    var er = S.d.earnings || {};
    var html = '<div class="card"><div class="card-h"><div><h2>Resultados de las grandes del Nasdaq</h2><div class="sub">Nvidia, Microsoft, Apple, Amazon, Meta, Broadcom, Alphabet, Tesla y otras con mucho peso en el NQ</div></div></div>';
    if (!er.enabled) {
      html += '<div class="empty" style="text-align:left;line-height:1.6">Esta sección es opcional. Para activarla, crea una clave gratuita en <a href="https://finnhub.io/register" target="_blank" rel="noopener">finnhub.io</a> y guárdala en GitHub con el nombre <strong>FINNHUB_API_KEY</strong> (la guía explica cómo, son 2 minutos).</div>';
    } else {
      var today = dayKey(new Date());
      var items = er.items || [];
      var up = items.filter(function (x) { return x.date >= today; });
      var past = items.filter(function (x) { return x.date < today; }).reverse();
      html += up.length ? '<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Fecha</th><th>Empresa</th><th>Momento</th><th class="num">BPA estimado</th><th class="num">Faltan</th></tr></thead><tbody>' + up.map(function (x) {
        var days = Math.round((keyToDate(x.date) - keyToDate(today)) / 86400000);
        return '<tr class="' + (days <= 7 ? 'soon' : '') + '"><td>' + cap(fmt(keyToDate(x.date), { weekday: 'short', day: 'numeric', month: 'short' })) + '</td><td><strong style="color:var(--accent)">' + esc(x.sym) + '</strong> <span class="sub">' + esc(NAMES[x.sym] || '') + '</span></td><td>' + hourTxt(x.hour) + '</td><td class="num">' + (x.eps_est != null ? num(x.eps_est, 2) : '—') + '</td><td class="num">' + (days === 0 ? '<span style="color:var(--high-ink)">HOY</span>' : days + ' d') + '</td></tr>';
      }).join('') + '</tbody></table></div>' : '<div class="empty">No hay resultados programados en los próximos meses.</div>';
      if (past.length) {
        html += '<div class="section-label" style="margin-top:20px">Publicados recientemente</div><div class="tbl-wrap"><table class="tbl"><thead><tr><th>Fecha</th><th>Empresa</th><th class="num">BPA real</th><th class="num">Estimado</th><th class="num">Sorpresa</th></tr></thead><tbody>' + past.map(function (x) {
          var s = x.eps_act != null && x.eps_est ? (x.eps_act - x.eps_est) / Math.abs(x.eps_est) * 100 : null;
          return '<tr><td>' + cap(fmt(keyToDate(x.date), { weekday: 'short', day: 'numeric', month: 'short' })) + '</td><td><strong style="color:var(--accent)">' + esc(x.sym) + '</strong></td><td class="num">' + (x.eps_act != null ? num(x.eps_act, 2) : '—') + '</td><td class="num">' + (x.eps_est != null ? num(x.eps_est, 2) : '—') + '</td><td class="num">' + (s != null ? chg(s) : '—') + '</td></tr>';
        }).join('') + '</tbody></table></div>';
      }
    }
    html += '</div>';
    $('tab-resultados').innerHTML = html;
  }

  /* ---------------- FED ---------------- */
  function renderFed() {
    var now = Date.now();
    var dec = events().filter(function (e) {
      return /Federal Funds Rate|FOMC Rate Decision/.test(e.title_en) && D(e.date).getTime() > now - 3600000;
    })[0];
    var fedEv = events().filter(function (e) { return isFed(e) && D(e.date).getTime() > now - 3600000; }).slice(0, 14);
    var items = (S.d.fed && S.d.fed.items) || [];
    var html = '<div class="row"><div class="grow" style="display:flex;flex-direction:column;gap:20px">';
    html += '<div class="card"><div class="card-h"><div><h2>Próxima decisión de tipos (FOMC)</h2><div class="sub">Comunicado a las ' + (dec ? hm(dec.date) : '20:00') + ' y rueda de prensa 30 min después (hora de Madrid)</div></div></div>';
    if (dec) {
      var t = D(dec.date).getTime();
      html += '<div style="display:flex;flex-wrap:wrap;gap:24px;align-items:center"><div><div class="sub">Fecha</div><div style="font-size:20px;font-weight:800">' + cap(fmt(dec.date, { weekday: 'long', day: 'numeric', month: 'long' })) + ' · ' + hm(dec.date) + '</div></div>' +
        '<div><div class="sub">Cuenta atrás</div><div class="big-count" data-cd="' + t + '">' + countdown(t - now) + '</div></div></div>';
    } else html += '<div class="empty">Sin fecha disponible.</div>';
    html += '<div class="toolbar" style="margin-top:14px"><a class="btn" href="https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html" target="_blank" rel="noopener">Probabilidades CME FedWatch ↗</a><a class="btn" href="https://www.federalreserve.gov/newsevents/calendar.htm" target="_blank" rel="noopener">Calendario oficial de la Fed ↗</a></div></div>';

    html += '<div class="card"><div class="card-h"><div><h2>Comunicados y discursos recientes</h2><div class="sub">Fuente: federalreserve.gov</div></div></div>';
    html += items.length ? '<div class="list">' + items.slice(0, 20).map(function (f) {
      return '<div class="news-item"><div class="meta"><span class="chip">' + esc(f.source.replace('Fed · ', '')) + '</span><span>' + cap(fmt(f.date, { weekday: 'short', day: 'numeric', month: 'short' })) + ' (' + ago(f.date) + ')</span></div><a class="t" href="' + safeUrl(f.link) + '" target="_blank" rel="noopener">' + esc(f.title) + '</a></div>';
    }).join('') + '</div>' : '<div class="empty">Sin datos todavía.</div>';
    html += '</div></div><aside class="side"><div class="card"><div class="card-h"><h3>Agenda de la Fed</h3></div>';
    html += fedEv.length ? '<div class="list">' + fedEv.map(function (e) {
      return '<div class="today-ev' + (e.key ? ' key' : '') + '"><span class="tm" style="width:auto">' + cap(fmt(e.date, { weekday: 'short', day: 'numeric' })) + ' ' + hm(e.date) + '</span><span class="ti">' + esc(e.title) + '</span></div>';
    }).join('') + '</div>' : '<div class="empty">Sin eventos de la Fed en el calendario próximo.</div>';
    html += '</div></aside></div>';
    $('tab-fed').innerHTML = html;
  }

  /* ---------------- footer ---------------- */
  function renderFooter() {
    var st = S.d.status || {}, src = st.sources || {};
    var names = { calendario: 'Calendario', mercados: 'Mercados', noticias: 'Noticias', fed: 'Fed', trump: 'Trump', periodico: 'Periódico', resultados: 'Resultados' };
    $('footer').innerHTML = '<div class="srcrow">' + Object.keys(names).filter(function (k) { return src[k]; }).map(function (k) {
      var s = src[k];
      return '<span class="src' + (s.ok ? '' : ' bad') + '" title="' + esc(s.ok ? 'OK ' + ago(s.at) : (s.error || 'Error')) + '"><span class="dot-s"></span>' + names[k] + '</span>';
    }).join('') + (st.updated_at ? '<span>Última actualización: ' + hm(st.updated_at) + ' (' + ago(st.updated_at) + ')</span>' : '') + '</div>' +
      '<div>Fuentes: Forex Factory, Yahoo Finance, CNBC, MarketWatch, Google News, Reserva Federal, Truth Social (vía trumpstruth.org), TradingView' + (st.finnhub ? ', Finnhub' : '') + (st.gemini ? '. Resúmenes redactados con Google Gemini' : '') + '. Los precios de futuros tienen retraso. Contenido informativo: no es asesoramiento financiero.</div>';
  }

  /* ---------------- eventos de interfaz ---------------- */
  document.addEventListener('click', function (ev) {
    var b = ev.target.closest('[data-act]');
    if (!b) return;
    var a = b.getAttribute('data-act'), v = b.getAttribute('data-v');
    if (a === 'view') { S.calView = v; }
    else if (a === 'prev') { S.calView === 'week' ? S.weekOff-- : S.monthOff--; }
    else if (a === 'next') { S.calView === 'week' ? S.weekOff++ : S.monthOff++; }
    else if (a === 'today') { S.weekOff = 0; S.monthOff = 0; }
    else if (a === 'imp') { S.imp[v] = !S.imp[v]; }
    else if (a === 'key') { S.onlyKey = !S.onlyKey; }
    else if (a === 'gotoday') {
      var today = dayKey(new Date());
      var mondayT = addDays(today, -((weekdayOfKey(today) + 6) % 7));
      var mondayV = addDays(v, -((weekdayOfKey(v) + 6) % 7));
      S.weekOff = Math.round((keyToDate(mondayV) - keyToDate(mondayT)) / (7 * 86400000));
      S.calView = 'week';
    }
    else if (a === 'cat') { S.newsCat = v; }
    else if (a === 'tf') { S.trumpFilter = v; }
    else if (a === 'per') { S.perIdx = +v; }
    renderTab(S.tab);
  });

  /* ---------------- arranque ---------------- */
  setTab((location.hash || '#panel').slice(1));
  tick();
  setInterval(tick, 1000);
  loadAll();
  setInterval(function () { loadAll(); }, REFRESH_MS);
  // Re-render ligero cada minuto para "hace X min" y eventos pasados
  setInterval(function () { renderHeader(); renderAlert(); }, 30000);
})();
