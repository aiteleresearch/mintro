/* MINTRO website: the download counter, its statistics overlay, and anonymous visitor counting.
   The numbers come from the site server's /api/stats (server/website/server.js, at API below), counted since the day
   the site went live. Visitors are counted without cookies: this browser keeps two small notes in localStorage —
   that it has been here before, and the last day it was — and each page view sends only those two yes/no flags,
   so the server never sees an ID. Only the site's own copy (where API is this page's origin) counts visits. */
(() => {
  'use strict';
  const API = 'https://mintra.aiteleresearch.com';
  const base = API.replace(/\/+$/, '');
  const ownSite = (() => { try { return new URL(base, location.href).origin === location.origin; } catch { return false; } })();
  const utcDay = () => new Date().toISOString().slice(0, 10);
  const fmt = (n) => Number(n || 0).toLocaleString();
  const fmtDate = (iso, opts = { day: 'numeric', month: 'short', year: 'numeric' }) =>
    new Date(`${iso}T00:00:00Z`).toLocaleDateString(undefined, { timeZone: 'UTC', ...opts });
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];

  /* ---------- count this visit ---------- */

  if (ownSite) {
    let flags = { new: false, today: false };
    try {
      flags = { new: !localStorage.getItem('mintro-seen'), today: localStorage.getItem('mintro-day') !== utcDay() };
      localStorage.setItem('mintro-seen', '1');
      localStorage.setItem('mintro-day', utcDay());
    } catch { /* storage off: count the page view only, never a visitor we can't tell apart */ }
    const body = JSON.stringify(flags);
    const url = `${base}/api/visit`;
    const sent = navigator.sendBeacon && navigator.sendBeacon(url, new Blob([body], { type: 'application/json' }));
    if (!sent) fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body, keepalive: true }).catch(() => {});
  }

  /* ---------- the counter ---------- */

  const spots = $$('[data-dlstat]');
  const openers = $$('[data-stats-open]');
  if (!spots.length && !openers.length) return;
  let data = null;

  async function load() {
    try {
      const r = await fetch(`${base}/api/stats`, { cache: 'no-store' });
      if (!r.ok) throw new Error(r.status);
      data = await r.json();
    } catch {
      return; // offline or not deployed yet: the counter stays hidden
    }
    spots.forEach((el) => { $('[data-dl-total]', el).textContent = fmt(data.totals.downloads); el.hidden = false; });
    if (dlg && dlg.open) render();
  }
  load();
  setInterval(() => { if (!document.hidden) load(); }, 120e3);

  /* ---------- the statistics overlay ---------- */

  let dlg = null, metric = 'downloads', range = 30;
  const METRICS = {
    downloads: { label: 'Downloads', day: (d) => d.downloads, added: (d) => d.downloads, unit: ['download', 'downloads'] },
    visitors: { label: 'Unique visitors', day: (d) => d.visitors, added: (d) => d.newVisitors, unit: ['visitor', 'visitors'] },
  };

  function build() {
    dlg = document.createElement('dialog');
    dlg.className = 'stats-dlg';
    dlg.setAttribute('aria-labelledby', 'statsTitle');
    dlg.innerHTML = `
      <div class="sd-head">
        <div>
          <p class="eyebrow">Open numbers</p>
          <h2 id="statsTitle">Downloads &amp; visitors</h2>
          <p class="sd-since"></p>
        </div>
        <button class="sd-x" type="button" aria-label="Close"><svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3.5 3.5l9 9m0-9-9 9"/></svg></button>
      </div>
      <div class="sd-tiles">
        <button class="sd-tile" type="button" data-metric="downloads"><span>Downloads</span><b data-total="downloads">—</b><small>Windows installer</small></button>
        <button class="sd-tile" type="button" data-metric="visitors"><span>Unique visitors</span><b data-total="visitors">—</b><small>browsers, counted without cookies</small></button>
        <div class="sd-tile still"><span>Updates delivered</span><b data-total="updates">—</b><small>to installed copies</small></div>
      </div>
      <div class="sd-chart-head">
        <p class="sd-chart-title"></p>
        <div class="sd-range" role="group" aria-label="Period">
          <button type="button" data-range="7">7 days</button><button type="button" data-range="30">30 days</button><button type="button" data-range="0">All</button>
        </div>
      </div>
      <div class="sd-chart">
        <span class="sd-ymax"></span><span class="sd-ctotal"></span>
        <svg viewBox="0 0 640 200" preserveAspectRatio="none" role="img"></svg>
        <div class="sd-tip" hidden></div>
        <div class="sd-axis"><span></span><span></span></div>
      </div>
      <div class="sd-legend"><span><i class="k-bar"></i>Each day</span><span><i class="k-line"></i>Total so far</span></div>
      <p class="sd-note">Counted on this site since day one. A download is counted when it starts (a repeat from the same
        connection within 10 minutes counts once). Unique visitors are browsers: each one tells the server only whether it
        has been here before and whether it's its first visit today — no cookies, no IDs, no IP addresses kept. Updates
        are installed copies of MINTRO that fetched a new version.</p>`;
    document.body.append(dlg);
    $('.sd-x', dlg).addEventListener('click', () => dlg.close());
    dlg.addEventListener('click', (e) => { if (e.target === dlg) dlg.close(); }); // the backdrop
    $$('[data-metric]', dlg).forEach((b) => b.addEventListener('click', () => { metric = b.dataset.metric; render(); }));
    $$('[data-range]', dlg).forEach((b) => b.addEventListener('click', () => { range = Number(b.dataset.range); render(); }));
    const chart = $('.sd-chart', dlg);
    chart.addEventListener('pointermove', (e) => hover(e));
    chart.addEventListener('pointerleave', () => { $('.sd-tip', dlg).hidden = true; $$('.hl', dlg).forEach((n) => n.classList.remove('hl')); });
  }

  let shown = [];
  function render() {
    if (!data) { $('.sd-since', dlg).textContent = 'Loading…'; return; }
    $('.sd-tip', dlg).hidden = true; // a redraw (new metric, period or numbers) drops the old hover
    const m = METRICS[metric];
    $('.sd-since', dlg).textContent = `Since ${fmtDate(data.since)}, when this site went live`;
    ['downloads', 'visitors', 'updates'].forEach((k) => { $(`[data-total="${k}"]`, dlg).textContent = fmt(data.totals[k]); });
    $$('[data-metric]', dlg).forEach((b) => b.classList.toggle('on', b.dataset.metric === metric));
    $$('[data-range]', dlg).forEach((b) => b.classList.toggle('on', Number(b.dataset.range) === range));

    // Running total over the whole history, then the chosen period's slice of it.
    let run = 0;
    const all = data.days.map((d) => ({ date: d.date, value: m.day(d), total: (run += m.added(d)) }));
    shown = range ? all.slice(-range) : all;
    const n = shown.length, W = 640, H = 200, top = 14, bottom = 188;
    const maxV = Math.max(1, ...shown.map((d) => d.value));
    const maxT = Math.max(1, ...shown.map((d) => d.total));
    const slot = W / n, bw = Math.max(1.5, Math.min(28, slot * 0.62));
    const y = (v, max) => bottom - (v / max) * (bottom - top);
    const bars = shown.map((d, i) => {
      const x = i * slot + (slot - bw) / 2, h = bottom - y(d.value, maxV);
      return `<rect class="bar" data-i="${i}" x="${x.toFixed(1)}" y="${(bottom - h).toFixed(1)}" width="${bw.toFixed(1)}" height="${Math.max(h, d.value ? 1.5 : 0).toFixed(1)}" rx="${Math.min(4, bw / 3).toFixed(1)}"/>`;
    }).join('');
    const pts = shown.map((d, i) => `${(i * slot + slot / 2).toFixed(1)},${y(d.total, maxT).toFixed(1)}`);
    const line = n > 1 ? `<polyline class="cum" points="${pts.join(' ')}"/>` : '';
    const dots = shown.map((d, i) => `<circle class="dot" data-i="${i}" cx="${(i * slot + slot / 2).toFixed(1)}" cy="${y(d.total, maxT).toFixed(1)}" r="3.2"/>`).join('');
    $('.sd-chart svg', dlg).innerHTML = `<line class="base" x1="0" y1="${bottom}" x2="${W}" y2="${bottom}"/>${bars}${line}${dots}`;
    $('.sd-chart svg', dlg).setAttribute('aria-label', `${m.label} per day, ${shown.length} days`);
    $('.sd-chart-title', dlg).textContent = `${m.label} — ${range ? `last ${Math.min(range, n)} days` : `all ${n} day${n === 1 ? '' : 's'}`}`;
    $('.sd-ymax', dlg).textContent = `${fmt(maxV)} / day`;
    $('.sd-ctotal', dlg).textContent = `${fmt(shown[n - 1].total)} total`;
    const [a, b] = $$('.sd-axis span', dlg);
    a.textContent = fmtDate(shown[0].date, { day: 'numeric', month: 'short' });
    b.textContent = n > 1 ? fmtDate(shown[n - 1].date, { day: 'numeric', month: 'short' }) : '';
  }

  function hover(e) {
    if (!shown.length) return;
    const svg = $('.sd-chart svg', dlg), r = svg.getBoundingClientRect();
    const i = Math.max(0, Math.min(shown.length - 1, Math.floor(((e.clientX - r.left) / r.width) * shown.length)));
    const d = shown[i], m = METRICS[metric];
    $$('.hl', dlg).forEach((n) => n.classList.remove('hl'));
    $$(`[data-i="${i}"]`, dlg).forEach((n) => n.classList.add('hl'));
    const tip = $('.sd-tip', dlg);
    tip.innerHTML = `<b>${fmtDate(d.date)}</b><span>${fmt(d.value)} ${m.unit[d.value === 1 ? 0 : 1]} that day</span><span>${fmt(d.total)} in total</span>`;
    tip.hidden = false;
    const x = ((i + 0.5) / shown.length) * r.width;
    tip.style.left = `${Math.max(70, Math.min(r.width - 70, x))}px`;
  }

  function open() {
    if (!dlg) build();
    render();
    if (typeof dlg.showModal === 'function') dlg.showModal(); else dlg.setAttribute('open', '');
    if (!data) load();
  }
  openers.forEach((b) => b.addEventListener('click', open));
})();
