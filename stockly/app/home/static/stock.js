// Per-stock page: /stocks/<SYMBOL>
// Live part comes from /api/stock/<SYMBOL> and /api/history; the analysis part is whatever the
// agent saved in stocks/<SYMBOL>/report.json (rendered as text only, never as HTML).
(() => {
  const S = window.Stockly;
  const { h, fmt, pct, dir, arrow, cr, rangeBar, lineChart, menuable, stockMenu } = S;
  const $ = (q) => document.querySelector(q);
  const sym = (document.body.dataset.symbol || decodeURIComponent(location.pathname.split('/')[2] || '')).toUpperCase();
  document.title = `${sym} · Stockly`;

  let ctx = null, hist = null, report = null, reportErr = null, costs = null, costKey = '';
  const safeUrl = (u) => typeof u === 'string' && /^https?:\/\//i.test(u) ? u : null;
  const arr = (x) => Array.isArray(x) ? x : x == null || x === '' ? [] : [x];
  const str = (x) => x == null ? '' : typeof x === 'object' ? JSON.stringify(x) : String(x);
  const TONE = { positive: 'up', bullish: 'up', good: 'up', negative: 'down', bearish: 'down', bad: 'down' };
  const tone = (t) => TONE[String(t || '').toLowerCase()] || '';
  const ago = (iso) => {
    const t = Date.parse(iso); if (!t) return '';
    const m = Math.round((Date.now() - t) / 60000);
    return m < 1 ? 'just now' : m < 60 ? `${m} min ago` : m < 1440 ? `${Math.round(m / 60)} h ago` : new Date(t).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' });
  };
  const rs = (v, plus) => v == null ? '—' : (v < 0 ? '−' : plus && v > 0 ? '+' : '') + '₹' + fmt(Math.abs(v));
  const lakhCr = (v) => v == null ? '—' : v >= 1e12 ? '₹' + fmt(v / 1e12) + ' lakh Cr' : cr(v);

  // ---------------- data ----------------
  async function getJSON(u) {
    const r = await fetch(u, { cache: 'no-store' });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) { const e = new Error(j.detail || r.statusText); e.status = r.status; throw e; }
    return j;
  }
  async function loadCtx() {
    try { ctx = (await getJSON(`/api/stock/${encodeURIComponent(sym)}`)).data; }
    catch (e) { if (!ctx) return fail(e); }
  }
  async function loadHist() {
    try {
      const d = (await getJSON(`/api/history/${encodeURIComponent(sym)}?range=1y&interval=1d`)).data;
      hist = (d.candles || []).filter((c) => c.close != null && c.date != null).map((c) => [c.date, c.close]);
      if (ctx && hist.length && ctx.price.last != null) hist[hist.length - 1][1] = ctx.price.last;
    } catch (e) { hist = hist || []; }
  }
  async function loadReport() {
    try {
      const r = await fetch(`/stocks/${encodeURIComponent(sym)}/report.json`, { cache: 'no-store' });
      if (r.status === 404) { report = null; reportErr = null; return; }
      const j = await r.json();
      if (!r.ok) throw new Error(j.detail || r.statusText);
      report = j; reportErr = null;
    } catch (e) { reportErr = e.message; }
  }
  async function loadCosts() {
    const t = report && report.trade;
    if (!t || !(t.entry > 0) || !(t.quantity > 0)) { costs = null; return; }
    const key = JSON.stringify(t); if (key === costKey) return; costKey = key;
    const base = { entry: +t.entry, quantity: Math.round(+t.quantity), side: t.side === 'short' ? 'short' : 'long',
      product: t.product === 'intraday' ? 'intraday' : 'delivery', broker: t.broker || 'zerodha' };
    const run = (exit) => exit > 0 ? fetch('/api/analytics/pnl', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...base, exit: +exit }) })
      .then((r) => r.json()).then((j) => j.data || { error: str(j.detail) }) : null;
    const [target, stop] = await Promise.all([run(t.target), run(t.stop)]);
    costs = { target, stop, base };
  }
  function fail(e) {
    $('#status').replaceChildren(h('span', { class: 'dot' }), h('span', {}, e.status === 404 ? 'Not found' : 'Offline'));
    $('#app').replaceChildren(h('div', { class: 'card err' },
      e.status === 404 || e.status === 422 ? [h('b', {}, sym || 'This symbol'), ' — ', e.message, ' ', h('a', { href: '/', style: 'text-decoration:underline' }, 'Back to market')]
        : 'NSE is not responding right now. Retrying automatically.'));
  }

  // ---------------- render ----------------
  const head = (title, desc, extra) => h('div', { class: 'sh' }, h('h2', {}, title), desc ? h('p', {}, desc) : null, extra || null);
  const fact = (label, value, cls, note) => h('div', { class: 'f' }, h('span', {}, label), h('b', { class: cls || '' }, value), note ? h('small', {}, note) : null);

  function hero(c) {
    const p = c.price, co = c.company, v = c.valuation, tr = c.trading;
    const chips = [co.sector, co.industry, co.basic_industry].filter((x, i, a) => x && a.indexOf(x) === i);
    const frame = S.style === 'candles' ? S.FRAME.year.candles : S.FRAME.year.line;
    const yr = hist && hist.length > 1 ? (hist[hist.length - 1][1] / hist[0][1] - 1) * 100 : null;
    const since = hist && hist.length > 1 ? (() => { const q = S.istParts(hist[0][0]); return `${q.d} ${S.MON[q.m]} '${String(q.y).slice(2)}`; })() : '';
    const peNote = v.pe != null && v.sector_pe != null ? (v.pe > v.sector_pe ? 'above' : v.pe < v.sector_pe ? 'below' : 'equal to') + ` sector ${fmt(v.sector_pe)}` : null;
    return h('section', {},
      h('div', { class: 'card hero sp' },
        h('div', { class: 'head' },
          menuable(h('div', { class: 'name-btn' },
            h('div', { class: 'label' }, [c.symbol, c.main_index, c.series].filter(Boolean).join(' · ')),
            h('h1', { class: 'co' }, (c.company_name || c.symbol).replace(/\s+Limited\.?$/i, ' Ltd')),
            h('div', { class: 'top' },
              h('span', { class: 'big num' }, '₹' + fmt(p.last)),
              h('span', { class: 'chip num chg ' + dir(p.change_pct) }, `${arrow(p.change_pct)} ${p.change > 0 ? '+' : ''}${fmt(p.change)} (${pct(p.change_pct)})`)),
            h('div', { class: 'sub' }, `vs previous close ₹${fmt(p.previous_close)} · NSE as of ${(c.as_of || '').slice(0, 17)}`)),
            () => stockMenu(c.symbol, c.company_name, p.last, p.change_pct), c.links.chart, true),
          h('div', { class: 'tags' }, chips.map((x) => h('span', { class: 'tag' }, x)),
            h('div', { class: 'go3' },
              h('a', { href: c.links.chart, target: '_blank', rel: 'noopener' }, 'Chart ↗'),
              h('a', { href: c.links.fundamentals, target: '_blank', rel: 'noopener' }, 'Fundamentals ↗'),
              h('a', { href: c.links.nse, target: '_blank', rel: 'noopener' }, 'NSE ↗')))),
        h('div', { class: 'chart-head' },
          h('span', { class: 'frame' }, `1 year · ${frame}`),
          yr == null ? null : h('span', { class: 'num ' + dir(yr), style: 'font-size:12.5px;font-weight:600' }, `${pct(yr)} since ${since}`)),
        hist && hist.length > 1
          ? S.mount(h('div', { class: 'chart' }), (el, w) => lineChart(el, w, hist, { mode: 'year', height: innerWidth < 680 ? 200 : 260 }))
          : h('div', { class: 'muted', style: 'height:200px;display:grid;place-items:center;font-size:12.5px' }, hist ? '1-year chart unavailable' : 'Loading chart…'),
        h('div', { class: 'chart-note' }, (S.style === 'candles' ? S.CANDLE_NOTE.year + ' ' : 'Daily closes (Yahoo Finance); last point = latest NSE price. ') + 'Hover for any day.'),
        h('div', { class: 'facts sf num' },
          rangeBar('Day range', p.low, p.high, p.last, p.vwap != null ? `VWAP ₹${fmt(p.vwap)}` : ''),
          rangeBar('52-week range', p.year_low, p.year_high, p.last, p.pct_below_year_high != null ? (p.pct_below_year_high <= 0 ? 'at the high' : `${p.pct_below_year_high.toFixed(1)}% below high`) : ''),
          rangeBar('Circuit band (today\'s allowed range)', p.lower_circuit, p.upper_circuit, p.last)),
        h('div', { class: 'stats num' },
          fact('P/E', fmt(v.pe), '', peNote),
          fact('Market cap', lakhCr(co.market_cap), '', co.free_float_market_cap ? 'free float ' + lakhCr(co.free_float_market_cap) : null),
          fact('Value traded', cr(tr.traded_value), '', tr.volume != null ? fmt(tr.volume) + ' shares' : null),
          fact('Delivery', tr.delivery_pct != null ? tr.delivery_pct.toFixed(1) + '%' : '—', '', 'of traded quantity'),
          fact('Volatility', p.annual_volatility_pct != null ? p.annual_volatility_pct.toFixed(1) + '%' : '—', '', 'annualised · daily ' + (p.daily_volatility_pct ?? '—') + '%'))));
  }

  // ---------- analysis (agent's report.json) — built from the same parts as the home page ----------
  const TONE_LABEL = { up: 'Positive', down: 'Negative' };
  const toneChip = (t) => { const c = tone(t); return c ? h('span', { class: 'chip ' + c }, (c === 'up' ? '▲ ' : '▼ ') + TONE_LABEL[c]) : null; };
  const stanceChip = (s) => {
    const k = String(s || '').toLowerCase(); if (!k) return null;
    const c = tone(k);
    return h('span', { class: 'chip ' + (c || 'muted') }, (c === 'up' ? '▲ ' : c === 'down' ? '▼ ' : '') + (TONE_LABEL[c] || k[0].toUpperCase() + k.slice(1)));
  };
  // numbered rows, same look as the home page stock lists
  const rows = (items, render) => arr(items).map((x, i) => h('div', { class: 'pr' }, h('span', { class: 'rk num' }, i + 1), render(x, i)));
  const textRow = (x) => h('div', { class: 'tx' }, str(x));

  // tabbed card (same markup/classes as "Stocks that stood out")
  const tabState = {};
  function tabbedCard(id, title, views) {
    const keys = Object.keys(views).filter((k) => views[k].items.length);
    if (!keys.length) return null;
    const build = () => {
      const key = keys.includes(tabState[id]) ? tabState[id] : keys[0], v = views[key];
      const card = h('div', { class: 'card tl' },
        h('div', { class: 'ct' }, h('h3', {}, title)),
        keys.length > 1 ? h('div', { class: 'tabs', role: 'tablist', 'aria-label': title }, keys.map((k) => h('button', {
          type: 'button', role: 'tab', 'aria-selected': String(k === key), class: views[k].kind || '',
          onclick: () => { tabState[id] = k; const nc = build(); card.replaceWith(nc); nc.querySelector('[aria-selected="true"]').focus(); },
        }, views[k].tab, h('span', { class: 'cnt num' }, views[k].items.length)))) : null,
        h('div', { class: 'sum' }, v.sum),
        h('div', { class: 'rows' }, v.render(v.items)));
      return card;
    };
    return build();
  }

  function analysis() {
    if (reportErr) return h('section', {}, head('Analysis', null), h('div', { class: 'card err' }, 'The saved report could not be read: ' + reportErr));
    if (!report) return h('section', {}, head('Analysis', 'Written by your agent from Stockly data'),
      h('div', { class: 'card empty' },
        h('div', { class: 'label' }, 'No analysis yet'),
        h('div', { class: 'et' }, 'Ask your agent to analyse ' + sym),
        h('p', {}, 'In Claude Code, Codex, opencode or Copilot, try:'),
        h('code', {}, `analyse ${sym} and make its stock page`),
        h('p', { class: 'muted' }, `It saves stocks/${sym}/report.json and this section fills in by itself.`)));
    const r = report;
    const meta = [r.author ? 'By ' + str(r.author) : 'By your agent', r.updated ? 'updated ' + ago(r.updated) : null, 'not investment advice'].filter(Boolean).join(' · ');

    // 1. verdict — styled like the price card above
    const metrics = arr(r.metrics);
    const verdict = h('div', { class: 'card hero an' },
      r.question ? h('div', { class: 'label' }, 'You asked') : null,
      r.question ? h('div', { class: 'ask-q' }, str(r.question)) : null,
      h('div', { class: 'an-head' }, h('h3', {}, str(r.headline || 'Analysis')), stanceChip(r.stance)),
      arr(r.summary).length ? h('div', { class: 'pts' }, rows(r.summary, textRow)) : null,
      metrics.length ? h('div', { class: 'stats num' }, metrics.map((m) =>
        h('div', { class: 'f' }, h('span', {}, str(m.label)), h('b', { class: tone(m.tone) }, str(m.value)), m.note ? h('small', {}, str(m.note)) : null))) : null);

    // 2. findings — one card per section, two per row
    const secs = arr(r.sections);
    const findings = secs.length ? h('section', {}, head('Findings', 'What the agent looked at, area by area'),
      h('div', { class: 'grid2' }, secs.map((s) => h('div', { class: 'card tl' },
        h('div', { class: 'ct' }, h('h3', {}, str(s.title)), toneChip(s.tone)),
        s.text ? h('div', { class: 'sum wrap-t' }, str(s.text)) : null,
        arr(s.points).length ? h('div', { class: 'rows' }, rows(s.points, textRow)) : null)))) : null;

    // 3. risks / watch and news / sources — tabbed half-width cards like the home page
    const watchCard = tabbedCard('rw', 'Risks & what to watch', {
      risks: { tab: 'Risks', kind: 'down', items: arr(r.risks), sum: 'What could go wrong', render: (it) => rows(it, textRow) },
      watch: { tab: 'What to watch', items: arr(r.watch), sum: 'Signals and events to follow', render: (it) => rows(it, textRow) },
    });
    const newsRow = (n) => {
      const u = safeUrl(n.url);
      return h(u ? 'a' : 'div', { class: 'tx nw2', href: u, target: u ? '_blank' : null, rel: u ? 'noopener' : null },
        h('b', {}, str(n.title) + (u ? ' ↗' : '')),
        h('small', {}, [n.source, n.date].filter(Boolean).map(str).join(' · ') + (n.why ? ' — ' + str(n.why) : '')),
        toneChip(n.tone));
    };
    const srcRow = (s) => { const u = safeUrl(s.url || s); const label = str(s.label || s.url || s);
      return u ? h('a', { class: 'tx nw2', href: u, target: '_blank', rel: 'noopener' }, h('b', {}, label + ' ↗'), h('small', {}, new URL(u).hostname)) : h('div', { class: 'tx' }, label); };
    const newsCard = tabbedCard('ns', 'News & sources', {
      news: { tab: 'News', items: arr(r.news), sum: 'Headlines the agent considered', render: (it) => rows(it, newsRow) },
      sources: { tab: 'Sources', items: arr(r.sources), sum: 'Where the numbers came from', render: (it) => rows(it, srcRow) },
    });
    const more = watchCard || newsCard ? h('section', {}, head('Risks, news & sources', null), h('div', { class: 'grid2' }, watchCard || h('div'), newsCard || h('div'))) : null;

    return [h('section', {}, head('Analysis', meta), verdict), findings, trade(), more];
  }

  function trade() {
    const t = report && report.trade; if (!t || !costs) return null;
    const any = costs.target && !costs.target.error ? costs.target : costs.stop;
    const ch = any && any.charges;
    const row = (label, d) => d && !d.error
      ? h('div', { class: 'trr num' }, h('span', {}, label), h('span', {}, rs(d.gross_profit)), h('span', {}, rs(d.total_charges)), h('b', { class: dir(d.net_profit) }, rs(d.net_profit, true)))
      : d && d.error ? h('div', { class: 'trr' }, h('span', {}, label), h('span', { class: 'muted', style: 'grid-column:2/-1;text-align:left' }, d.error)) : null;
    const f = (label, value, cls, note) => h('div', { class: 'f' }, h('span', {}, label), h('b', { class: cls || '' }, value), note ? h('small', {}, note) : null);
    return h('section', {}, head('Trade plan & costs', `${any ? any.broker_name : costs.base.broker} · ${costs.base.product} · charges from /api/analytics/pnl at official rates`),
      h('div', { class: 'card hero an' },
        h('div', { class: 'stats num', style: 'margin-top:0;padding-top:0;border-top:0' },
          f('Entry', '₹' + fmt(t.entry)),
          f('Stop', t.stop ? '₹' + fmt(t.stop) : '—', 'down', t.stop && t.entry ? pct((t.stop / t.entry - 1) * 100) : null),
          f('Target', t.target ? '₹' + fmt(t.target) : '—', 'up', t.target && t.entry ? pct((t.target / t.entry - 1) * 100) : null),
          f('Quantity', fmt(costs.base.quantity), '', '₹' + fmt(costs.base.quantity * t.entry) + ' invested'),
          f('Break-even', any && any.breakeven_move_per_share != null ? '₹' + fmt(any.breakeven_move_per_share) : '—', '', 'move per share to cover costs')),
        h('div', { class: 'trr hd' }, h('span', {}, 'If it exits at'), h('span', {}, 'Gross'), h('span', {}, 'All charges'), h('span', {}, 'Net')),
        row('Target ₹' + fmt(t.target), costs.target), row('Stop ₹' + fmt(t.stop), costs.stop),
        ch ? h('div', { class: 'chart-note num', style: 'margin-top:10px' }, 'Charges: ' + Object.entries(ch).filter(([, v]) => v).map(([k, v]) => `${k.replace(/_/g, ' ')} ₹${fmt(v)}`).join(' · ') + '. Estimate; your contract note is final.') : null,
        t.note ? h('div', { class: 'chart-note' }, str(t.note)) : null));
  }

  function render() {
    if (!ctx) return;
    const y = scrollY;
    S.resetMounts();
    $('#status').replaceChildren(h('span', { class: 'dot' + (refreshOpen ? ' open' : '') }),
      h('span', {}, `${ctx.symbol} · NSE ${(ctx.as_of || '').slice(0, 17)}`));
    $('#banner').hidden = !ctx.sample;
    if (ctx.sample) $('#banner-text').textContent = 'Offline mode — saved sample data. Not live.';
    $('#app').replaceChildren(hero(ctx), ...[analysis()].flat().filter(Boolean));
    S.drawCharts();
    scrollTo(0, y);
  }

  // ---------------- refresh ----------------
  let refreshOpen = false;
  async function marketOpen() {
    try { const o = (await getJSON('/api/market/overview')).data; return !o.sample && /open/i.test(o.market_status.status || ''); } catch (e) { return false; }
  }
  async function init() {
    if (!sym) return fail({ status: 404, message: 'No symbol in the address.' });
    await Promise.all([loadCtx(), loadReport()]);
    if (!ctx) return setTimeout(init, 30000);
    render();
    await Promise.all([loadHist(), loadCosts()]);
    render();
    refreshOpen = await marketOpen();
    render();
    tick();
  }
  // report: every 10 s (local file, so the page fills while the agent writes); quote: 30 s open / 5 min closed
  let n = 0;
  function tick() {
    setTimeout(async () => {
      if (!document.hidden) {
        n++;
        const before = JSON.stringify(report);
        await loadReport();
        let changed = JSON.stringify(report) !== before;
        if (changed) await loadCosts();
        if (n % (refreshOpen ? 3 : 30) === 0) { await loadCtx(); changed = true; }
        if (changed) render();
      }
      tick();
    }, 10000);
  }
  S.onStyle(render);
  init();
})();
