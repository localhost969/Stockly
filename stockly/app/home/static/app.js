(() => {
  const $ = (q) => document.querySelector(q);
  const SVGNS = 'http://www.w3.org/2000/svg';
  function h(tag, attrs, ...kids) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v == null || v === false) continue;
      if (k === 'class') el.className = v;
      else if (k === 'style') el.style.cssText = v;
      else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, v);
    }
    for (const kid of kids.flat()) if (kid != null && kid !== false) el.append(kid.nodeType ? kid : String(kid));
    return el;
  }
  function sv(tag, attrs, ...kids) {
    const el = document.createElementNS(SVGNS, tag);
    for (const [k, v] of Object.entries(attrs || {})) if (v != null) el.setAttribute(k, v);
    for (const kid of kids.flat()) if (kid != null) el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
    return el;
  }

  // ---------- format ----------
  const nf = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 2 });
  const nf0 = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 });
  const fmt = (n) => n == null ? '—' : nf.format(n);
  const pct = (n) => n == null ? '—' : (n > 0 ? '+' : n < 0 ? '−' : '') + Math.abs(n).toFixed(2) + '%';
  const dir = (n) => n > 0 ? 'up' : n < 0 ? 'down' : 'muted';
  const arrow = (n) => n > 0 ? '▲' : n < 0 ? '▼' : '';
  const cr = (v) => v == null ? '—' : '₹' + nf0.format(v / 1e7) + ' Cr';
  const titleCase = (t) => (t || '').toLowerCase().replace(/\b\w/g, (m) => m.toUpperCase()).replace(/\bLimited\b\.?/, 'Ltd').replace(/\bLtd\b\.?/, 'Ltd');
  const short = (n) => n.replace(/^NIFTY /, '').replace(/ INDEX$/, '');
  const ist = (t) => new Date(t * 1000).toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', hour12: false });
  // green/red tint whose strength grows with the size of the move (full strength at ±cap %)
  function tint(p, cap = 3) {
    if (p == null || p === 0) return 'var(--flat)';
    const a = Math.min(1, 0.18 + 0.82 * Math.min(Math.abs(p), cap) / cap);
    return `rgba(var(--${p > 0 ? 'up' : 'down'}-rgb),${a.toFixed(2)})`;
  }

  // ---------- destinations ----------
  const enc = encodeURIComponent;
  const DEST = {
    chart: (sym) => `https://www.tradingview.com/chart/?symbol=${enc('NSE:' + sym.replace(/[&-]/g, '_'))}`,
    fundamentals: (sym) => `https://www.screener.in/company/${enc(sym)}/consolidated/`,
    nse: (sym) => `https://www.nseindia.com/get-quotes/equity?symbol=${enc(sym)}`,
  };
  // A "menu" = { kind, title, sub, last, chg, items:[{t, d, src, url}] }
  const SRC = { Stockly: ['ST', 'st', 'this app'], TradingView: ['TV', 'tv', 'tradingview.com'], Screener: ['S', 'sc', 'screener.in'], NSE: ['NSE', 'nse', 'nseindia.com'] };
  const stockMenu = (sym, name, price, chg) => ({
    kind: 'Stock', title: sym, sub: titleCase(name), last: price, chg,
    items: [{ t: 'Stock page', d: 'Live quote, every index it is in, and your agent\'s analysis', src: 'Stockly', url: `/stocks/${enc(sym)}` },
            { t: 'Price chart', d: 'Interactive chart with indicators and drawing tools', src: 'TradingView', url: DEST.chart(sym) },
            { t: 'Fundamentals', d: 'Financials, ratios, peers, shareholding', src: 'Screener', url: DEST.fundamentals(sym) },
            { t: 'Official NSE quote', d: 'Filings, announcements, corporate actions, F&O', src: 'NSE', url: DEST.nse(sym) }],
  });
  const indexItems = (L) => [{ t: 'Index chart', d: 'Interactive chart with indicators', src: 'TradingView', url: L.chart },
    ...(L.stocks ? [{ t: 'Stocks in this index', d: 'Every member stock with its move today', src: L.stocks.source, url: L.stocks.url }] : []),
    ...(L.nse ? [{ t: 'NSE live market watch', d: 'Official live prices of member stocks', src: 'NSE', url: L.nse }] : [])];
  const indexMenu = (i, kind, sub) => ({ kind: kind || 'Index', title: i.name, sub: sub || '', last: i.last, chg: i.change_pct, items: indexItems(i.links) });

  // ---------- destination sheet (full-screen, blurred background) ----------
  const sheet = $('#sheet');
  let msel = 0, lastFocus = null;
  function openMenu(anchor, m) {
    lastFocus = anchor;
    const opts = m.items.map((it, i) => {
      const [mono, cls, host] = SRC[it.src] || [it.src, 'nse', ''];
      return h('a', { class: 'opt', href: it.url, target: '_blank', rel: 'noopener', 'data-i': i, onclick: () => setTimeout(closeMenu, 50), onmouseenter: () => mark(i) },
        h('span', { class: 'badge ' + cls }, mono),
        h('span', { style: 'min-width:0' }, h('div', { class: 't' }, it.t), h('div', { class: 'd' }, it.d + ' · ' + host)),
        h('span', { class: 'go' }, h('kbd', {}, i + 1), h('span', { class: 'ar' }, '→')));
    });
    sheet.replaceChildren(h('div', { class: 'sheet', onclick: (e) => e.stopPropagation() },
      h('div', { class: 'top' },
        h('div', { class: 'kind' }, m.kind),
        h('div', { class: 'title' }, m.title),
        m.sub ? h('div', { class: 'subt' }, m.sub) : null,
        (m.last != null || m.chg != null) ? h('div', { class: 'quote num' }, m.last != null ? h('b', {}, (m.kind === 'Stock' ? '₹' : '') + fmt(m.last)) : null,
          m.chg != null ? h('span', { class: 'chip ' + dir(m.chg) }, arrow(m.chg) + ' ' + pct(m.chg)) : null) : null,
        h('button', { class: 'x', 'aria-label': 'Close', onclick: closeMenu }, '×')),
      h('div', { class: 'opts' }, opts),
      h('div', { class: 'foot' }, h('span', {}, 'Opens in a new tab'), h('span', {}, `1–${opts.length} or ↑ ↓ Enter · Esc to close`))));
    sheet.hidden = false;
    document.body.classList.add('locked');
    requestAnimationFrame(() => sheet.classList.add('show'));
    mark(0); opts[0] && opts[0].focus({ preventScroll: true });
  }
  function mark(i) {
    const opts = sheet.querySelectorAll('.opt'); if (!opts.length) return;
    msel = (i + opts.length) % opts.length;
    opts.forEach((o, k) => o.classList.toggle('on', k === msel));
  }
  function closeMenu() {
    if (sheet.hidden) return;
    sheet.classList.remove('show');
    document.body.classList.remove('locked');
    setTimeout(() => { sheet.hidden = true; sheet.replaceChildren(); }, 160);
    lastFocus && lastFocus.focus && lastFocus.focus({ preventScroll: true });
  }
  sheet.addEventListener('click', closeMenu);
  document.addEventListener('keydown', (e) => {
    if (sheet.hidden) return;
    const opts = sheet.querySelectorAll('.opt');
    if (['Escape', 'ArrowDown', 'ArrowUp', 'Tab', 'Enter'].includes(e.key) || /^[1-9]$/.test(e.key)) e.stopPropagation();
    if (e.key === 'Escape') { e.preventDefault(); closeMenu(); }
    else if (e.key === 'ArrowDown' || (e.key === 'Tab' && !e.shiftKey)) { e.preventDefault(); mark(msel + 1); opts[msel].focus(); }
    else if (e.key === 'ArrowUp' || (e.key === 'Tab' && e.shiftKey)) { e.preventDefault(); mark(msel - 1); opts[msel].focus(); }
    else if (e.key === 'Enter') { e.preventDefault(); opts[msel] && opts[msel].click(); }
    else if (/^[1-9]$/.test(e.key) && opts[+e.key - 1]) { e.preventDefault(); window.open(opts[+e.key - 1].href, '_blank', 'noopener'); closeMenu(); }
  }, true);
  // the element opens the sheet; ctrl/cmd-click goes straight to the first destination
  function menuable(el, menu, direct, plain) {
    if (!plain) el.classList.add('clickable');
    el.tabIndex = 0;
    el.setAttribute('role', 'button');
    el.addEventListener('click', (e) => { e.stopPropagation(); if (e.metaKey || e.ctrlKey) { window.open(direct, '_blank'); return; } openMenu(el, menu()); });
    el.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openMenu(el, menu()); } });
    return el;
  }

  // ---------- chart style ----------
  const styleHooks = [];
  let chartStyle = 'line';
  try { chartStyle = localStorage.getItem('stockly.chartStyle') === 'candles' ? 'candles' : 'line'; } catch (e) {}
  function paintToggle() { document.querySelectorAll('#style button').forEach((b) => b.setAttribute('aria-checked', String(b.dataset.v === chartStyle))); }
  document.querySelectorAll('#style button').forEach((b) => b.addEventListener('click', () => {
    if (chartStyle === b.dataset.v) return;
    chartStyle = b.dataset.v;
    try { localStorage.setItem('stockly.chartStyle', chartStyle); } catch (e) {}
    paintToggle(); if (data) render(); styleHooks.forEach((f) => f());
  }));
  paintToggle();
  const FRAME = {
    day: { line: '1-minute line', candles: '5-minute candles' },
    year: { line: 'daily close line', candles: 'weekly candles' },
  };
  const CANDLE_NOTE = {
    day: '5-minute candles built from NSE 1-minute values.',
    year: 'Weekly candles built from daily closes: open = previous week\'s close, high/low = highest/lowest close.',
  };

  // ---------- range bar: where the current value sits between low and high ----------
  function rangeBar(label, lo, hi, cur, note) {
    if (lo == null || hi == null || cur == null || hi <= lo) return null;
    const pos = Math.min(100, Math.max(0, (cur - lo) / (hi - lo) * 100));
    return h('div', { class: 'rb', title: `${label}: low ${fmt(lo)}, high ${fmt(hi)}, now ${fmt(cur)}` },
      h('div', { class: 'h' }, h('b', {}, label), note ? h('span', {}, note) : null),
      h('div', { class: 't' }, h('i', { style: `left:${pos}%` })),
      h('div', { class: 'l num' }, h('span', {}, fmt(lo)), h('span', {}, fmt(hi))));
  }
  const offHigh = (cur, hi) => cur != null && hi ? (cur >= hi ? 'at the high' : `${Math.abs((cur / hi - 1) * 100).toFixed(1)}% below high`) : '';

  // ---------- charts ----------
  // Charts are drawn after the page is in the DOM so they use the real width (crisp text at any size).
  let mounts = [];
  const mount = (el, draw) => { mounts.push([el, draw]); return el; };
  function drawCharts() { for (const [el, draw] of mounts) if (el.isConnected) { el.replaceChildren(); draw(el, el.clientWidth || 300); } }
  let rz; addEventListener('resize', () => { clearTimeout(rz); rz = setTimeout(drawCharts, 150); });

  const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const istParts = (t) => { const d = new Date((t + 19800) * 1000); return { y: d.getUTCFullYear(), m: d.getUTCMonth(), d: d.getUTCDate(), hh: d.getUTCHours(), mm: d.getUTCMinutes() }; };
  const hhmm = (t) => { const p = istParts(t); return String(p.hh).padStart(2, '0') + ':' + String(p.mm).padStart(2, '0'); };
  const dayLabel = (t) => { const p = istParts(t); return `${p.d} ${MON[p.m]} ${p.y}`; };
  function niceTicks(lo, hi, n) {
    const raw = (hi - lo) / n, mag = Math.pow(10, Math.floor(Math.log10(raw))), step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((x) => x >= raw);
    const out = []; for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(+v.toFixed(6)); return out;
  }
  const UP = '22,121,74', DOWN = '191,58,48', INK = '86,86,79';

  /* mode 'day': x = 09:15–15:30 IST, fill green above / red below previous close.
     mode 'year': x = first..last date, one colour (trend, or neutral). */
  // Candles from a value series. day: 5-minute buckets. year: weeks (IST, Monday start),
  // opening at the previous week's close.
  function toCandles(points, mode, x0) {
    const out = [];
    let cur = null, prevClose = null;
    for (const [t, v] of points) {
      const key = mode === 'day' ? Math.floor((t - x0) / 300) : Math.floor(((t + 19800) / 86400 + 3) / 7);
      if (!cur || cur.key !== key) {
        if (cur) { prevClose = cur.c; out.push(cur); }
        const o = mode === 'year' && prevClose != null ? prevClose : v;
        cur = { key, t0: t, t1: t, o, h: Math.max(o, v), l: Math.min(o, v), c: v };
      } else { cur.t1 = t; cur.h = Math.max(cur.h, v); cur.l = Math.min(cur.l, v); cur.c = v; }
    }
    if (cur) out.push(cur);
    return out;
  }

  function lineChart(el, W, points, { mode, base = null, height = 220, neutral = false, compact = false }) {
    const H = height, padL = 4, padR = compact ? 4 : 58, padT = 10, padB = compact ? 20 : 26;
    let x0, x1;
    if (mode === 'day') { const t = points[0][0], mid = t - ((t + 19800) % 86400); x0 = mid + 33300; x1 = mid + 55800; }
    else { x0 = points[0][0]; x1 = points[points.length - 1][0]; }
    const candles = chartStyle === 'candles' ? toCandles(points, mode, x0) : null;
    if (candles && mode === 'year') { x0 -= 3.5 * 86400; x1 += 3.5 * 86400; }
    const vals = points.map((p) => p[1]).concat(base != null ? [base] : []).concat(candles ? candles.flatMap((c) => [c.h, c.l]) : []);
    let lo = Math.min(...vals), hi = Math.max(...vals); const pad = (hi - lo) * 0.08 || hi * 0.002; lo -= pad; hi += pad;
    const X = (t) => padL + (Math.min(Math.max(t, x0), x1) - x0) / (x1 - x0 || 1) * (W - padL - padR);
    const Y = (v) => padT + (hi - v) / (hi - lo) * (H - padT - padB);
    const first = points[0][1], last = points[points.length - 1][1];
    const trendUp = last >= (base ?? first);
    const one = neutral ? INK : trendUp ? UP : DOWN;
    const line = points.map((p, i) => (i ? 'L' : 'M') + X(p[0]).toFixed(1) + ',' + Y(p[1]).toFixed(1)).join('');
    const yb = base != null ? Y(base) : H - padB;
    const area = line + `L${X(points[points.length - 1][0]).toFixed(1)},${yb.toFixed(1)}L${X(points[0][0]).toFixed(1)},${yb.toFixed(1)}Z`;
    const uid = Math.random().toString(36).slice(2);
    const kids = [];
    // grid + axis labels
    if (!compact) for (const v of niceTicks(lo + pad, hi - pad, 3)) {
      kids.push(sv('line', { x1: padL, x2: W - padR, y1: Y(v), y2: Y(v), stroke: '#efefea' }));
      kids.push(sv('text', { x: W - padR + 8, y: Y(v) + 4, 'font-size': 11, fill: '#9a9a92' }, nf0.format(v)));
    }
    const xt = [];
    if (mode === 'day') for (const [h_, m_] of (W < 520 ? [[9, 15], [11, 0], [13, 0], [15, 30]] : [[9, 15], [10, 0], [11, 0], [12, 0], [13, 0], [14, 0], [15, 30]])) xt.push([x0 + ((h_ * 60 + m_) - 555) * 60, h_ === 9 || (h_ === 15 && m_ === 30) ? `${String(h_).padStart(2, '0')}:${String(m_).padStart(2, '0')}` : (compact ? '' : `${h_}:00`)]);
    else { const a = istParts(x0), b = istParts(x1); xt.push([x0, `${MON[a.m]} '${String(a.y).slice(2)}`], [x0 + (x1 - x0) / 2, (() => { const p = istParts(x0 + (x1 - x0) / 2); return `${MON[p.m]} '${String(p.y).slice(2)}`; })()], [x1, `${MON[b.m]} '${String(b.y).slice(2)}`]); }
    xt.forEach(([t, label], i) => {
      if (!compact && mode === 'day') kids.push(sv('line', { x1: X(t), x2: X(t), y1: padT, y2: H - padB, stroke: '#f3f3ef' }));
      if (label) kids.push(sv('text', { x: X(t), y: H - 7, 'font-size': 11, fill: '#9a9a92', 'text-anchor': i === 0 ? 'start' : i === xt.length - 1 ? 'end' : 'middle' }, label));
    });
    // fills + line (split at base for day charts)
    const defs = sv('defs', {});
    kids.unshift(defs);
    const grad = (id, rgb, flip) => defs.append(sv('linearGradient', { id, x1: 0, y1: flip ? 1 : 0, x2: 0, y2: flip ? 0 : 1 },
      sv('stop', { offset: '0%', 'stop-color': `rgb(${rgb})`, 'stop-opacity': .22 }), sv('stop', { offset: '100%', 'stop-color': `rgb(${rgb})`, 'stop-opacity': .02 })));
    if (candles) {
      const slot = (mode === 'day' ? 300 : 7 * 86400) / (x1 - x0) * (W - padL - padR);
      const bw = Math.max(1.5, Math.min(14, slot * 0.66));
      if (base != null) kids.push(sv('line', { x1: padL, x2: W - padR, y1: Y(base), y2: Y(base), stroke: '#8c8c84', 'stroke-dasharray': '4 4' }));
      if (base != null && !compact) kids.push(sv('text', { x: W - padR + 8, y: Y(base) + 4, 'font-size': 11, 'font-weight': 600, fill: '#56564f' }, 'Prev'));
      for (const c of candles) {
        const cx = mode === 'day' ? X(x0 + c.key * 300 + 150) : X((c.t0 + c.t1) / 2);
        const col = `rgb(${c.c >= c.o ? UP : DOWN})`;
        kids.push(sv('line', { x1: cx, x2: cx, y1: Y(c.h), y2: Y(c.l), stroke: col, 'stroke-width': 1 }));
        const y = Math.min(Y(c.o), Y(c.c)), hgt = Math.max(1, Math.abs(Y(c.o) - Y(c.c)));
        kids.push(sv('rect', { x: cx - bw / 2, y, width: bw, height: hgt, fill: col, rx: bw > 4 ? 1 : 0 }));
        c.cx = cx;
      }
    } else if (base != null && !neutral) {
      defs.append(sv('clipPath', { id: 'a' + uid }, sv('rect', { x: 0, y: 0, width: W, height: yb })));
      defs.append(sv('clipPath', { id: 'b' + uid }, sv('rect', { x: 0, y: yb, width: W, height: H })));
      grad('ga' + uid, UP, false); grad('gb' + uid, DOWN, true);
      kids.push(sv('path', { d: area, fill: `url(#ga${uid})`, 'clip-path': `url(#a${uid})` }), sv('path', { d: area, fill: `url(#gb${uid})`, 'clip-path': `url(#b${uid})` }));
      kids.push(sv('line', { x1: padL, x2: W - padR, y1: yb, y2: yb, stroke: '#8c8c84', 'stroke-dasharray': '4 4' }));
      if (!compact) kids.push(sv('text', { x: W - padR + 8, y: yb + 4, 'font-size': 11, 'font-weight': 600, fill: '#56564f' }, 'Prev'));
      kids.push(sv('path', { d: line, fill: 'none', stroke: `rgb(${UP})`, 'stroke-width': 2, 'clip-path': `url(#a${uid})`, 'stroke-linejoin': 'round' }),
                sv('path', { d: line, fill: 'none', stroke: `rgb(${DOWN})`, 'stroke-width': 2, 'clip-path': `url(#b${uid})`, 'stroke-linejoin': 'round' }));
    } else {
      grad('g' + uid, one, false);
      const a2 = line + `L${X(points[points.length - 1][0]).toFixed(1)},${H - padB}L${X(points[0][0]).toFixed(1)},${H - padB}Z`;
      kids.push(sv('path', { d: a2, fill: `url(#g${uid})` }), sv('path', { d: line, fill: 'none', stroke: `rgb(${one})`, 'stroke-width': compact ? 1.7 : 2, 'stroke-linejoin': 'round' }));
    }
    const endCol = base != null && !neutral ? (last >= base ? UP : DOWN) : one;
    if (!candles) kids.push(sv('circle', { cx: X(points[points.length - 1][0]), cy: Y(last), r: compact ? 3 : 4, fill: `rgb(${endCol})` }));
    // hover / touch
    const cross = sv('line', { y1: padT, y2: H - padB, stroke: '#1b1b19', 'stroke-width': 1, opacity: 0 });
    const dot = sv('circle', { r: 4.5, fill: '#fff', 'stroke-width': 2, opacity: 0 });
    kids.push(cross, dot);
    const svg = sv('svg', { width: W, height: H, viewBox: `0 0 ${W} ${H}` }, kids);
    const tip = h('div', { class: 'tip', hidden: '' });
    el.append(svg, tip);
    const ref = base ?? first;
    const move = (clientX) => {
      const r = svg.getBoundingClientRect(), mx = clientX - r.left;
      if (candles) {
        let c = candles[0];
        for (const k of candles) if (Math.abs(k.cx - mx) < Math.abs(c.cx - mx)) c = k;
        cross.setAttribute('x1', c.cx); cross.setAttribute('x2', c.cx); cross.setAttribute('opacity', .2);
        dot.setAttribute('opacity', 0);
        const when = mode === 'day' ? `${hhmm(x0 + c.key * 300)}–${hhmm(x0 + c.key * 300 + 300)} IST` : `Week of ${dayLabel(c.t0)}`;
        tip.hidden = false;
        tip.replaceChildren(h('b', {}, when), `  O ${fmt(c.o)}  H ${fmt(c.h)}  L ${fmt(c.l)}  C ${fmt(c.c)}  `,
          h('span', { style: 'opacity:.75' }, pct((c.c / c.o - 1) * 100)));
        tip.style.left = Math.min(Math.max(c.cx, tip.offsetWidth / 2), W - tip.offsetWidth / 2) + 'px';
        tip.style.top = Math.max(-34, Y(c.h) - 44) + 'px';
        return;
      }
      let best = points[0];
      for (const p of points) if (Math.abs(X(p[0]) - mx) < Math.abs(X(best[0]) - mx)) best = p;
      const x = X(best[0]), y = Y(best[1]), ch = (best[1] / ref - 1) * 100;
      cross.setAttribute('x1', x); cross.setAttribute('x2', x); cross.setAttribute('opacity', .2);
      dot.setAttribute('cx', x); dot.setAttribute('cy', y); dot.setAttribute('opacity', 1);
      dot.setAttribute('stroke', `rgb(${neutral ? INK : best[1] >= ref ? UP : DOWN})`);
      tip.hidden = false;
      tip.replaceChildren(h('b', {}, mode === 'day' ? hhmm(best[0]) + ' IST' : dayLabel(best[0])), '  ' + fmt(best[1]) + '  ',
        h('span', { style: 'opacity:.75' }, pct(ch) + (mode === 'day' ? ' vs prev close' : ' vs ' + dayLabel(points[0][0]))));
      tip.style.left = Math.min(Math.max(x, tip.offsetWidth / 2), W - tip.offsetWidth / 2) + 'px';
      tip.style.top = Math.max(-34, y - 44) + 'px';
    };
    svg.addEventListener('pointermove', (e) => move(e.clientX));
    svg.addEventListener('pointerdown', (e) => move(e.clientX));
    svg.addEventListener('pointerleave', () => { cross.setAttribute('opacity', 0); dot.setAttribute('opacity', 0); tip.hidden = true; });
    svg.addEventListener('click', (e) => e.stopPropagation());
  }

  // ---------- live ticks ----------
  let prev = new Map(), next = new Map();
  function live(el, key, value) {
    next.set(key, value);
    const old = prev.get(key);
    if (old != null && value != null && old !== value) el.classList.add(value > old ? 'tick-up' : 'tick-down');
    return el;
  }

  // ================= load =================
  let data = null;
  async function load() {
    try {
      const r = await fetch('/api/market/overview');
      const j = await r.json();
      if (!r.ok) throw new Error(j.detail || r.statusText);
      data = j.data;
      render();
    } catch (e) {
      if (!data) {
        $('#app').replaceChildren(h('div', { class: 'card err' }, 'NSE is not responding right now. Retrying automatically.'));
        $('#status').replaceChildren(h('span', { class: 'dot' }), h('span', {}, 'Offline'));
      }
    }
    schedule();
  }
  const isOpen = () => !!data && !data.sample && (data.market_status.status || '').toLowerCase() === 'open';
  function sessionLabel(o) { // NSE "16-Nov-2026 15:30" -> "16 Nov 2026, 15:30"
    const m = /^(\d+)-(\w+)-(\d+)\s+(\d+:\d+)/.exec(o.as_of || '');
    return m ? `${+m[1]} ${m[2]} ${m[3]}, ${m[4]}` : (o.as_of || '');
  }

  // ================= render =================
  function render() {
    const o = data;
    next = new Map();
    const open = isOpen();
    const when = sessionLabel(o), day = when.split(',')[0];
    const updated = new Date(o.fetched_at).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    $('#status').replaceChildren(h('span', { class: 'dot' + (open ? ' open' : '') }),
      h('span', {}, open ? `Market open · updated ${updated}` : `Market ${(o.market_status.status || 'closed').toLowerCase()} · showing ${day} session`));
    $('#banner').hidden = !o.sample;
    if (o.sample) $('#banner-text').textContent = `Offline mode — saved sample data captured ${new Date(o.captured_at).toLocaleString('en-IN')}. Not live.`;
    const n = o.indices.find((i) => i.name === 'NIFTY 50');
    mounts = [];
    $('#app').replaceChildren(hero(o, n, open, day), others(o, open), breadth(o, open), sectors(o, open), lists(o, open));
    drawCharts();
    prev = next;
  }
  const today = (open, day) => open ? 'today' : `on ${day}`;

  // section header: title, description, and the matching NSE page
  const NSE_PAGE = {
    indices: ['https://www.nseindia.com/market-data/live-market-indices', 'All indices on NSE'],
    breadth: ['https://www.nseindia.com/market-data/advance', 'Advances / declines on NSE'],
    movers: ['https://www.nseindia.com/market-data/top-gainers-losers', 'Gainers & losers on NSE'],
    active: ['https://www.nseindia.com/market-data/most-active-equities', 'Most active on NSE'],
    extremes: ['https://www.nseindia.com/market-data/52-week-high-equity-market', '52-week high/low on NSE'],
  };
  const head = (title, desc, key) => h('div', { class: 'sh' }, h('h2', {}, title), desc ? h('p', {}, desc) : null,
    key ? h('a', { class: 'nse', href: NSE_PAGE[key][0], target: '_blank', rel: 'noopener' }, NSE_PAGE[key][1] + ' ↗') : null);

  // ---- 1. NIFTY 50 day chart
  function hero(o, n, open, day) {
    const pts = n.day_chart;
    const card = h('div', { class: 'card hero' },
      h('div', { class: 'head' },
        menuable(h('div', { class: 'name-btn' },
          h('div', { class: 'label' }, 'NIFTY 50 · 50 of India\'s largest listed companies'),
          h('div', { class: 'top', style: 'margin-top:6px' },
            live(h('span', { class: 'big num' }, fmt(n.last)), 'n50', n.last),
            h('span', { class: 'chip num chg ' + dir(n.change_pct) }, `${arrow(n.change_pct)} ${n.change > 0 ? '+' : ''}${fmt(n.change)} (${pct(n.change_pct)})`)),
          h('div', { class: 'sub' }, `Change ${today(open, day)} vs previous close of ${fmt(n.previous_close)}`)),
          () => indexMenu(n, 'Index', '50 of India\'s largest listed companies'), n.links.chart, true),
        h('span', { class: 'frame' }, `${open ? 'Today' : day} · ${FRAME.day[chartStyle]} · 09:15–15:30 IST`)),
      pts ? mount(h('div', { class: 'chart' }), (el, w) => lineChart(el, w, pts, { mode: 'day', base: n.previous_close, height: innerWidth < 680 ? 220 : 300 }))
          : h('div', { class: 'muted', style: 'padding:40px 0' }, 'Day chart unavailable right now.'),
      pts ? h('div', { class: 'chart-note' }, chartStyle === 'candles' ? CANDLE_NOTE.day + ' Dashed line = previous close. Hover for open/high/low/close.'
        : 'Green above / red below the dashed previous close. Hover or touch for the price at any minute.') : null,
      h('div', { class: 'facts num' },
        rangeBar('Day range', n.low, n.high, n.last),
        rangeBar('52-week range', n.year_low, n.year_high, n.last, offHigh(n.last, n.year_high)),
        h('div', { class: 'f' }, h('span', {}, '1-week return'), h('b', { class: dir(n.return_7d_pct) }, pct(n.return_7d_pct))),
        h('div', { class: 'f' }, h('span', {}, '1-month return'), h('b', { class: dir(n.return_30d_pct) }, pct(n.return_30d_pct))),
        h('div', { class: 'f' }, h('span', {}, '1-year return'), h('b', { class: dir(n.return_365d_pct) }, pct(n.return_365d_pct)))));
    return h('section', {}, head(open ? 'Market today' : `Market on ${day}`, 'Tap NIFTY 50 for its full chart and stock list', 'indices'), card);
  }

  // ---- 2. Other indices (1-year charts, 2 per row)
  const DESC = {
    'NIFTY BANK': 'Large, heavily traded bank stocks',
    'NIFTY MIDCAP 100': '100 mid-sized companies',
    'NIFTY SMALLCAP 100': '100 smaller companies',
    'INDIA VIX': 'Fear gauge: NIFTY volatility priced into options for the next 30 days',
  };
  function others(o, open) {
    const cards = o.indices.filter((i) => i.name !== 'NIFTY 50').map((i) => {
      const pts = i.year_chart, vix = i.name === 'INDIA VIX';
      const yr = pts && pts.length > 1 ? (pts[pts.length - 1][1] / pts[0][1] - 1) * 100 : null;
      const since = pts && pts.length > 1 ? (() => { const p = istParts(pts[0][0]); return `${p.d} ${MON[p.m]} '${String(p.y).slice(2)}`; })() : '';
      return h('div', { class: 'card ic' },
        h('div', { class: 'head' },
          menuable(h('div', { class: 'name-btn' },
            h('div', { class: 'n' }, i.name + '  ↗'),
            h('div', { class: 'd' }, DESC[i.name] || ''),
            h('div', { class: 'v' }, live(h('b', { class: 'num' }, fmt(i.last)), 'i:' + i.name, i.last),
              h('span', { class: 'chip num ' + dir(i.change_pct) }, arrow(i.change_pct) + ' ' + pct(i.change_pct) + ' ' + (open ? 'today' : 'last session')))),
            () => indexMenu(i, 'Index', DESC[i.name]), i.links.chart, true),
          h('div', { style: 'text-align:right' }, h('span', { class: 'frame' }, '1 year · ' + FRAME.year[chartStyle]),
            yr == null ? null : h('div', { class: 'num ' + (vix ? 'muted' : dir(yr)), style: 'font-size:12.5px;margin-top:6px;font-weight:600', title: `Change in this chart, from the ${since} close to the latest close` }, `${pct(yr)} since ${since}`))),
        pts ? mount(h('div', { class: 'chart' }), (el, w) => lineChart(el, w, pts, { mode: 'year', height: 150, compact: true, neutral: vix }))
            : h('div', { class: 'muted', style: 'height:150px;display:grid;place-items:center;font-size:12px' }, '1-year chart unavailable'),
        h('div', { class: 'ranges num' },
          rangeBar('Day range', i.low, i.high, i.last),
          rangeBar('52-week range', i.year_low, i.year_high, i.last, offHigh(i.last, i.year_high))));
    });
    return h('section', {}, head('Other indices', chartStyle === 'candles' ? '1-year charts. ' + CANDLE_NOTE.year : 'Charts show the last 1 year of daily closes. Hover for any day.', 'indices'), h('div', { class: 'idx' }, cards));
  }

  // ---- 3. Did most stocks rise?
  function breadth(o, open) {
    const b = o.breadth, tot = (b.advances + b.declines + b.unchanged) || 1, share = b.advances / tot * 100;
    const [verdict, cls] = share >= 55 ? ['Yes — most stocks rose', 'up'] : share <= 45 ? ['No — most stocks fell', 'down'] : ['Mixed — about as many rose as fell', ''];
    const left = h('div', {},
      h('div', { class: 'verdict ' + cls }, verdict),
      h('div', { class: 'vsub num' }, `${b.advances} of ${tot} NIFTY 500 stocks rose ${open ? 'today' : 'in the session'}, ${b.declines} fell` + (b.unchanged ? `, ${b.unchanged} unchanged.` : '.')),
      h('div', { class: 'split num' },
        b.advances ? h('div', { class: 'r', style: `width:${b.advances / tot * 100}%` }, '▲ ' + b.advances) : null,
        b.unchanged ? h('div', { class: 'u', style: `width:${b.unchanged / tot * 100}%` }) : null,
        b.declines ? h('div', { class: 'f', style: `width:${b.declines / tot * 100}%` }, b.declines + ' ▼') : null),
      h('div', { class: 'split-l num' }, h('span', {}, `${Math.round(share)}% rose`), h('span', {}, `${Math.round(b.declines / tot * 100)}% fell`)),
      menuable(h('span', { class: 'lnk' }, 'See all NIFTY 500 stocks ↗'),
        () => ({ kind: 'Index', title: o.universe, sub: '500 largest NSE-listed companies', chg: null, last: null, items: indexItems(o.universe_links) }), o.universe_links.chart, true));
    const max = Math.max(1, ...b.buckets.map((x) => x.count));
    const shade = ['1', '.7', '.42', '.42', '.7', '1'];
    const rows = b.buckets.map((x, i) => [i === 3 ? h('div', { class: 'gap' }) : null,
      h('div', { class: 'row num' }, h('span', { class: 'l' }, x.label),
        h('span', { class: 'b' }, h('i', { style: `width:${x.count / max * 100}%;background:rgba(${i < 3 ? UP : DOWN},${shade[i]})` })),
        h('span', { class: 'c ' + (i < 3 ? 'up' : 'down') }, x.count))]);
    return h('section', {}, head('Did most stocks rise?', 'NIFTY 500 = the 500 largest NSE-listed companies.', 'breadth'),
      h('div', { class: 'card breadth' }, left, h('div', { class: 'bk' }, h('h4', {}, 'How big were the moves? (number of stocks)'), rows.flat())));
  }

  // ---- 4. Sectors
  function sectors(o, open) {
    const tiles = o.sectors.map((x) => {
      const strong = x.change_pct != null && Math.abs(x.change_pct) >= 1.4;
      return menuable(h('div', { class: 'ht' + (strong ? ' dark' : ''), style: `background:${tint(x.change_pct, 2.5)}` },
        h('div', { class: 'n' }, short(x.name)),
        h('div', {}, live(h('div', { class: 'p num' }, pct(x.change_pct)), 's:' + x.name, x.change_pct),
          x.advances != null ? h('div', { class: 'a num' }, `${x.advances} rose · ${x.declines} fell`) : null)),
        () => indexMenu(x, 'Sector index', x.advances != null ? `${x.advances} member stocks rose, ${x.declines} fell` : ''), x.links.chart, true);
    });
    const up = o.sectors.filter((x) => x.change_pct > 0).length;
    return h('section', {}, head('Sectors', `${up} of ${o.sectors.length} NSE sector indices rose ${open ? 'today' : 'in the session'}. Darker = bigger move.`, 'indices'), h('div', { class: 'heat' }, tiles));
  }

  // ---- 5. Stock lists: two half-width cards, tabs switch what each card lists
  const tabs = { movers: 'gainers', ext: 'highs' };
  try { Object.assign(tabs, JSON.parse(localStorage.getItem('stockly.tabs') || '{}')); } catch (e) { /* private mode */ }
  const saveTabs = () => { try { localStorage.setItem('stockly.tabs', JSON.stringify(tabs)); } catch (e) { /* ignore */ } };

  // compact low→high track with a dot at the current price
  function miniRange(lo, hi, cur, what) {
    if (lo == null || hi == null || cur == null || hi <= lo) return h('div', { class: 'mr' }, h('div', { class: 't' }));
    const pos = Math.min(100, Math.max(0, (cur - lo) / (hi - lo) * 100));
    return h('div', { class: 'mr', title: `${what}: low ₹${fmt(lo)} · high ₹${fmt(hi)} · now ₹${fmt(cur)}` },
      h('div', { class: 't' }, h('b', { style: `width:${pos}%` }), h('i', { style: `left:${pos}%` })),
      h('div', { class: 'l num' }, h('span', {}, fmt(lo)), h('span', {}, fmt(hi))));
  }
  function valueBar(v, max) {
    return h('div', { class: 'mr', title: `Value traded ${cr(v)}: ${Math.round((v || 0) / max * 100)}% of the top stock` },
      h('div', { class: 't v' }, h('b', { style: `width:${(v || 0) / max * 100}%` })));
  }
  const fromLow = (r) => r.year_low ? `+${((r.price / r.year_low - 1) * 100).toFixed(0)}% from 52-wk low` : '';
  const fromHigh = (r) => r.year_high ? `${((1 - r.price / r.year_high) * 100).toFixed(0)}% below 52-wk high` : '';

  // one tabbed card: views = { key: {tab, count, url, nse, sum, cols, rows, row, empty} }
  function tabbed(id, title, views) {
    const build = () => {
      const key = views[tabs[id]] ? tabs[id] : Object.keys(views)[0], v = views[key];
      const tabBtns = Object.entries(views).map(([k, x]) => h('button', {
        type: 'button', role: 'tab', 'aria-selected': String(k === key), 'data-k': k, class: x.kind || '',
        onclick: () => { tabs[id] = k; saveTabs(); const nc = build(); card.replaceWith(nc); card = nc; nc.querySelector(`[data-k="${k}"]`).focus(); },
      }, x.tab, x.count != null ? h('span', { class: 'cnt num' }, x.count) : null));
      const list = v.rows.length
        ? v.rows.map((r, i) => menuable(h('div', { class: 'sr' },
            h('span', { class: 'rk num' }, i + 1),
            h('div', { class: 's' }, h('b', {}, r.symbol), h('small', {}, titleCase(r.company_name))),
            v.bar(r), v.val(r)),
          () => stockMenu(r.symbol, r.company_name, r.price, r.change_pct), DEST.chart(r.symbol)))
        : [h('div', { class: 'none' }, v.empty)];
      return h('div', { class: 'card tl' },
        h('div', { class: 'ct' }, h('h3', {}, title),
          h('a', { class: 'nse', href: v.url, target: '_blank', rel: 'noopener' }, v.nse + ' ↗')),
        h('div', { class: 'tabs', role: 'tablist', 'aria-label': title }, tabBtns),
        h('div', { class: 'sum' }, v.sum),
        h('div', { class: 'cols' }, h('span', {}), h('span', {}, 'Stock'), h('span', {}, v.cols[0]), h('span', {}, v.cols[1])),
        h('div', { class: 'rows' }, list));
    };
    let card = build();
    return card;
  }

  function lists(o, open) {
    const when = open ? 'today' : 'in the session';
    const pctVal = (r) => live(h('div', { class: 'p num ' + dir(r.change_pct) }, pct(r.change_pct), h('small', {}, '₹' + fmt(r.price))), 'p:' + r.symbol, r.price);
    const dayBar = (r) => miniRange(r.day_low, r.day_high, r.price, 'Day range');
    const offDay = (r, up) => r.price == null || r[up ? 'day_high' : 'day_low'] == null ? '' : up
      ? (r.price >= r.day_high ? 'at day high' : `${((1 - r.price / r.day_high) * 100).toFixed(1)}% below day high`)
      : (r.price <= r.day_low ? 'at day low' : `${((r.price / r.day_low - 1) * 100).toFixed(1)}% above day low`);
    const withNote = (bar, text, cls) => h('div', {}, bar, h('div', { class: 'note ' + (cls || 'muted') }, text));
    const maxV = Math.max(1, ...o.most_active.map((r) => r.traded_value || 0));
    const movers = tabbed('movers', 'Biggest movers', {
      gainers: { tab: 'Gainers', kind: 'up', rows: o.gainers, url: NSE_PAGE.movers[0], nse: 'NSE',
        sum: `Top ${o.gainers.length} by % rise ${when}`, cols: ['Day low → high', 'Change'],
        bar: (r) => withNote(dayBar(r), offDay(r, true)), val: pctVal, empty: 'No NIFTY 500 stock rose.' },
      losers: { tab: 'Losers', kind: 'down', rows: o.losers, url: NSE_PAGE.movers[0], nse: 'NSE',
        sum: `Top ${o.losers.length} by % fall ${when}`, cols: ['Day low → high', 'Change'],
        bar: (r) => withNote(dayBar(r), offDay(r, false)), val: pctVal, empty: 'No NIFTY 500 stock fell.' },
      value: { tab: 'Most traded', rows: o.most_active, url: NSE_PAGE.active[0], nse: 'NSE',
        sum: `Top ${o.most_active.length} by value traded ${when} · 1 Cr = ₹10 million`, cols: ['Value traded', 'Change'],
        bar: (r) => h('div', {}, h('div', { class: 'vt num' }, cr(r.traded_value)), valueBar(r.traded_value, maxV)), val: pctVal, empty: 'No data.' },
    });
    const yh = o.year_highs, yl = o.year_lows;
    const extSum = (d, what, order) => [h('b', { class: 'num' }, d.count), ` ${d.count === 1 ? 'stock' : 'stocks'} hit a new 52-week ${what}`,
      d.count > d.stocks.length ? ` · top ${d.stocks.length} by % ${order}` : ''];
    const ext = tabbed('ext', '52-week highs & lows', {
      highs: { tab: 'New highs', kind: 'up', count: yh.count, rows: yh.stocks, url: NSE_PAGE.extremes[0], nse: 'NSE',
        sum: extSum(yh, 'high', 'gain'), cols: ['52-week low → high', 'Change'],
        bar: (r) => withNote(miniRange(r.year_low, r.year_high, r.price, '52-week range'), fromLow(r), 'up'),
        val: pctVal, empty: 'No stock hit a new 52-week high.' },
      lows: { tab: 'New lows', kind: 'down', count: yl.count, rows: yl.stocks, url: 'https://www.nseindia.com/market-data/52-week-low-equity-market', nse: 'NSE',
        sum: extSum(yl, 'low', 'fall'), cols: ['52-week low → high', 'Change'],
        bar: (r) => withNote(miniRange(r.year_low, r.year_high, r.price, '52-week range'), fromHigh(r), 'down'),
        val: pctVal, empty: 'No stock hit a new 52-week low.' },
    });
    return h('section', {}, head('Stocks that stood out', `NIFTY 500 stocks ${open ? 'today' : 'in the session'}. Bars run from low to high; the dot is the latest price. Tap a stock for its chart, fundamentals or NSE quote.`),
      h('div', { class: 'grid2 lists' }, movers, ext));
  }

  // refresh: 30 s while open, 5 min otherwise; pause in background tabs
  let timer = null;
  function schedule() {
    clearTimeout(timer);
    timer = setTimeout(() => { if (document.hidden) schedule(); else load(); }, isOpen() ? 30000 : 300000);
  }
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden && isOpen() && Date.now() - new Date(data.fetched_at).getTime() > 30000) load();
  });

  // ================= search =================
  const q = $('#q'), out = $('#results');
  let universe = null, loading = null, sel = 0, hits = [];
  function ensureSymbols() {
    if (universe || loading) return loading;
    loading = fetch('/api/market/symbols').then((r) => r.json()).then((j) => {
      universe = (j.data?.symbols || []).map(([sym, n]) => ({ s: sym, n, k: (sym + ' ' + n).toLowerCase() }));
    }).catch(() => { universe = []; }).finally(() => { loading = null; search(); });
    return loading;
  }
  function search() {
    const term = q.value.trim().toLowerCase();
    if (!term) { out.hidden = true; return; }
    if (!universe) { out.hidden = false; out.replaceChildren(h('div', { class: 'res-empty' }, 'Loading NSE symbols…')); ensureSymbols(); return; }
    const exact = [], starts = [], name = [];
    for (const u of universe) {
      const sl = u.s.toLowerCase();
      if (sl === term) exact.push(u); else if (sl.startsWith(term)) starts.push(u); else if (u.k.includes(term)) name.push(u);
      if (exact.length + starts.length + name.length > 60) break;
    }
    hits = [...exact, ...starts.sort((a, b) => a.s.length - b.s.length), ...name].slice(0, 8);
    sel = 0; out.hidden = false;
    if (!hits.length) {
      const raw = q.value.trim().toUpperCase();
      out.replaceChildren(h('div', { class: 'res-empty' }, 'No listed NSE match. ', h('a', { href: DEST.chart(raw), target: '_blank', rel: 'noopener', style: 'text-decoration:underline' }, 'Try ' + raw + ' on TradingView ↗')));
      return;
    }
    paint();
  }
  function paint() {
    out.replaceChildren(...hits.map((u, i) => h('div', { class: 'res' + (i === sel ? ' on' : ''), onmouseenter: () => hl(i), onmousedown: (e) => { if (!e.target.closest('a')) e.preventDefault(); }, onclick: (e) => { if (!e.target.closest('a')) go(u); } },
      h('span', { class: 's' }, u.s), h('span', { class: 'n' }, titleCase(u.n)),
      h('span', { class: 'go' }, h('a', { href: DEST.chart(u.s), target: '_blank', rel: 'noopener' }, 'Chart'), h('a', { href: DEST.fundamentals(u.s), target: '_blank', rel: 'noopener' }, 'Fundamentals'), h('a', { href: DEST.nse(u.s), target: '_blank', rel: 'noopener' }, 'NSE')))));
  }
  function hl(i) { sel = i; out.querySelectorAll('.res').forEach((r, k) => r.classList.toggle('on', k === i)); }
  // a result opens the same destination sheet as everything else on the page
  const go = (u) => { out.hidden = true; openMenu(q, stockMenu(u.s, u.n, null, null)); };
  q.addEventListener('focus', () => { ensureSymbols(); if (q.value.trim()) search(); });
  q.addEventListener('input', search);
  q.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowDown' && hits.length) { hl((sel + 1) % hits.length); e.preventDefault(); }
    else if (e.key === 'ArrowUp' && hits.length) { hl((sel - 1 + hits.length) % hits.length); e.preventDefault(); }
    else if (e.key === 'Enter' && hits[sel]) { e.preventDefault(); go(hits[sel]); }
    else if (e.key === 'Escape') { q.value = ''; out.hidden = true; q.blur(); }
  });
  document.addEventListener('click', (e) => { if (!e.target.closest('.search')) out.hidden = true; });
  document.addEventListener('keydown', (e) => {
    if (e.key === '/' && document.activeElement !== q && !/input|textarea/i.test(document.activeElement.tagName)) { e.preventDefault(); q.focus(); }
  });

  // Shared with the per-stock page (/stocks/<SYMBOL>, stock.js).
  window.Stockly = {
    h, fmt, pct, dir, arrow, cr, titleCase, tint, rangeBar, offHigh, lineChart, menuable, openMenu, stockMenu, indexMenu, DEST,
    FRAME, CANDLE_NOTE, MON, istParts,
    get style() { return chartStyle; }, onStyle: (f) => styleHooks.push(f),
    mount, resetMounts: () => { mounts = []; }, drawCharts,
  };
  if (document.body.dataset.page !== 'stock') load();
})();
