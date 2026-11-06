/* MINTRO website: page interactions. Everything here works with or without the 3D scene. */
(() => {
  'use strict';

  // Your GitHub repository ("owner/name"), stats service (server/stats, docs/STATS.md) and a contact email.
  // Every Download and GitHub link, the live numbers and the listing form use these.
  // api: MINTRO's mail endpoint (server.js in the Aitele deployment): listing requests are emailed to the team.
  const SITE = { repo: 'aiteleresearch/mintro', stats: '', email: 'hello@aiteleresearch.com', api: 'https://mintra.aiteleresearch.com' };
  const hasRepo = !SITE.repo.includes('OWNER'), statsBase = SITE.stats.replace(/\/+$/, '');
  const apiBase = SITE.api.replace(/\/+$/, '');

  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const root = document.documentElement;
  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const fine = matchMedia('(hover: hover) and (pointer: fine)').matches;
  const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));

  /* ---------- links ---------- */

  const LINKS = {
    download: `https://github.com/${SITE.repo}/releases/latest`,
    repo: `https://github.com/${SITE.repo}`,
    license: `https://github.com/${SITE.repo}/blob/main/LICENSE`,
    statsRaw: statsBase ? `${statsBase}/v1/stats` : '#numbers',
    downloadsRaw: hasRepo ? `https://api.github.com/repos/${SITE.repo}/releases` : '#numbers',
    historyCsv: hasRepo ? `https://github.com/${SITE.repo}/blob/main/stats/history.csv` : '#numbers',
    method: hasRepo ? `https://github.com/${SITE.repo}/blob/main/docs/STATS.md` : '#numbers',
  };
  $$('[data-href]').forEach((a) => {
    a.href = LINKS[a.dataset.href];
    if (a.href.startsWith('https:')) { a.target = '_blank'; a.rel = 'noopener'; }
  });
  $('#year').textContent = new Date().getFullYear();

  /* ---------- split headings into words that rise into place ---------- */

  function split(el) {
    let i = 0;
    const walk = (node) => [...node.childNodes].forEach((ch) => {
      if (ch.nodeType === 3) {
        const frag = document.createDocumentFragment();
        ch.textContent.split(/(\s+)/).forEach((part) => {
          if (!part) return;
          if (/^\s+$/.test(part)) { frag.append(' '); return; }
          const w = document.createElement('span');
          const wi = document.createElement('span');
          w.className = 'w'; wi.className = 'wi';
          wi.textContent = part;
          wi.style.setProperty('--i', i++);
          w.append(wi);
          frag.append(w);
        });
        ch.replaceWith(frag);
      } else if (ch.nodeType === 1 && ch.tagName !== 'BR') {
        walk(ch);
      }
    });
    walk(el);
  }
  $$('[data-split]').forEach(split);
  $$('.score').forEach((s, i) => s.style.setProperty('--n', i));
  $$('.seed-words li').forEach((s, i) => s.style.setProperty('--k', i));

  /* ---------- loader ---------- */

  const loader = $('#loader'), bar = $('#ldBar'), pct = $('#ldPct');
  const t0 = performance.now();
  let shown = 0, goal = 20, finished = false, sceneOk = root.classList.contains('gl-ready');
  if (sceneOk || root.classList.contains('no-gl')) goal = 100;
  function tick() {
    if (finished) return;
    shown += (goal - shown) * 0.16;
    bar.style.transform = `scaleX(${(shown / 100).toFixed(3)})`;
    pct.textContent = String(Math.round(shown)).padStart(3, '0');
    if (goal >= 100 && shown > 98 && performance.now() - t0 > 450) { finish(); return; }
    requestAnimationFrame(tick);
  }
  function finish() {
    finished = true;
    loader.classList.add('out');
    root.classList.add('loaded');
    $$('[data-hero]').forEach((el) => el.classList.add('in'));
    setTimeout(() => loader.remove(), 1300);
  }
  requestAnimationFrame(tick);
  document.fonts.ready.then(() => { goal = Math.max(goal, 60); });
  addEventListener('mintro:scene-ready', () => { sceneOk = true; root.classList.remove('no-gl'); goal = 100; });
  addEventListener('mintro:scene-failed', () => { goal = 100; });
  setTimeout(() => { goal = 100; }, 1800);                                  // never hold the page for a slow CDN
  setTimeout(() => { if (!sceneOk) root.classList.add('no-gl'); }, 9000);   // no 3D after 9 s: show the CSS crystal

  /* ---------- reveal on scroll ---------- */

  const io = new IntersectionObserver((entries) => entries.forEach((e) => {
    if (e.isIntersecting) { e.target.classList.add('in'); io.unobserve(e.target); }
  }), { rootMargin: '0px 0px -10% 0px', threshold: 0.12 });
  $$('[data-reveal], [data-split]:not([data-hero]), .stage').forEach((el) => io.observe(el));

  const countIO = new IntersectionObserver((entries) => entries.forEach((e) => {
    if (!e.isIntersecting) return;
    countIO.unobserve(e.target);
    const el = e.target, to = +el.dataset.count, from = +(el.dataset.from || 0), start = performance.now();
    if (reduced) { el.textContent = to; return; }
    const step = (now) => {
      const t = clamp((now - start) / 1800, 0, 1);
      el.textContent = Math.round(from + (to - from) * (1 - Math.pow(1 - t, 4)));
      if (t < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }), { threshold: 0.6 });
  $$('[data-count]').forEach((el) => { el.textContent = el.dataset.from || '0'; countIO.observe(el); });

  /* ---------- scroll-linked pieces ---------- */

  const nav = $('#nav'), prog = $('#progress');
  const navLinks = $$('.nav-links a'), navTargets = navLinks.map((a) => $(a.getAttribute('href')));
  const path = $('#stepsPath'), steps = $('#steps');
  const plen = path ? path.getTotalLength() : 0;
  if (path) { path.style.strokeDasharray = plen; path.style.strokeDashoffset = plen; }

  // Straight talk: words light up as you scroll through the section
  const honestSec = $('#honest'), words = [];
  (function wrapWords(node, key) {
    [...node.childNodes].forEach((ch) => {
      if (ch.nodeType === 3) {
        const frag = document.createDocumentFragment();
        ch.textContent.split(/(\s+)/).forEach((part) => {
          if (!part) return;
          if (/^\s+$/.test(part)) { frag.append(' '); return; }
          const s = document.createElement('span');
          s.className = key ? 'hw key' : 'hw';
          s.textContent = part;
          words.push(s);
          frag.append(s);
        });
        ch.replaceWith(frag);
      } else if (ch.nodeType === 1) {
        wrapWords(ch, key || ch.tagName === 'EM');
      }
    });
  })($('#honestText'), false);

  const stage = $('#stage'), device = $('#device');
  let scrollRX = 0, deviceVisible = false, lastY = scrollY, queued = false;

  function onScroll() {
    queued = false;
    const y = scrollY, max = root.scrollHeight - innerHeight;
    prog.style.transform = `scaleX(${max > 0 ? (y / max).toFixed(4) : 0})`;
    nav.classList.toggle('solid', y > 30);
    if (Math.abs(y - lastY) > 4) nav.classList.toggle('hide', y > lastY && y > 600);
    lastY = y;

    let active = -1;
    navTargets.forEach((t, i) => { if (t && t.getBoundingClientRect().top < innerHeight * 0.45) active = i; });
    navLinks.forEach((a, i) => a.classList.toggle('active', i === active));

    if (path) {
      const r = steps.getBoundingClientRect();
      path.style.strokeDashoffset = (plen * (1 - clamp((innerHeight * 0.9 - r.top) / (r.height + innerHeight * 0.25), 0, 1))).toFixed(1);
    }
    if (words.length) {
      const r = honestSec.getBoundingClientRect();
      const p = reduced ? 1 : clamp((innerHeight * 0.55 - r.top) / (r.height - innerHeight * 0.75), 0, 1);
      const lit = Math.floor(p * 1.1 * words.length);
      words.forEach((w, i) => w.classList.toggle('on', i < lit));
    }
    if (stage) {
      const r = stage.getBoundingClientRect();
      const p = clamp((innerHeight - r.top) / ((innerHeight + r.height) / 2), 0, 1);
      scrollRX = Math.pow(1 - p, 3) * 38; // leans back as it arrives, flat when centred
      deviceVisible = r.bottom > 0 && r.top < innerHeight;
    }
  }
  addEventListener('scroll', () => { if (!queued) { queued = true; requestAnimationFrame(onScroll); } }, { passive: true });
  addEventListener('resize', onScroll);
  onScroll();

  /* ---------- the card in the showcase ---------- */

  if (device) {
    let tRX = 0, tRY = 0, cRX = 38, cRY = 0;
    addEventListener('pointermove', (e) => {
      if (!fine) return;
      tRY = (e.clientX / innerWidth - 0.5) * 24;
      tRX = -(e.clientY / innerHeight - 0.5) * 14;
    }, { passive: true });
    (function loop() {
      requestAnimationFrame(loop);
      if (!deviceVisible) return;
      const k = reduced ? 1 : 0.075;
      cRX += (tRX + scrollRX - cRX) * k;
      cRY += (tRY - cRY) * k;
      device.style.setProperty('--rx', `${cRX.toFixed(2)}deg`);
      device.style.setProperty('--ry', `${cRY.toFixed(2)}deg`);
      device.style.setProperty('--gx', `${(55 + cRY * 3.2).toFixed(1)}%`);
    })();

    // Live numbers: the turn counts down, the speed wobbles, coins accumulate
    const arc = $('#dArc'), CIRC = 339.3;
    let turn = 11 * 60 + 42, hash = 2.41, mined = 0.4213, zeph = 0.01412;
    const update = () => {
      turn = turn > 0 ? turn - 1 : 1199;
      $('#dTurn').textContent = `Turn ends in ${Math.floor(turn / 60)}:${String(turn % 60).padStart(2, '0')}`;
      arc.style.strokeDashoffset = (CIRC * turn / 1200).toFixed(1);
      hash = clamp(hash + (Math.random() - 0.5) * 0.07, 2.28, 2.54);
      $('#dHash').textContent = `${hash.toFixed(2)} kH/s`;
      zeph += 0.0000041 * hash;
      mined += 0.0000524 * hash;
      $('#dZeph').textContent = zeph.toFixed(5);
      $('#dMined').textContent = `$${mined.toFixed(4)}`;
    };
    update();
    setInterval(update, 1000);
  }

  /* ---------- pointer effects ---------- */

  $$('.spot').forEach((el) => el.addEventListener('pointermove', (e) => {
    const r = el.getBoundingClientRect();
    el.style.setProperty('--mx', `${e.clientX - r.left}px`);
    el.style.setProperty('--my', `${e.clientY - r.top}px`);
  }));
  if (fine && !reduced) {
    $$('[data-tilt]').forEach((el) => {
      const max = +el.dataset.tilt || 4;
      el.addEventListener('pointerenter', () => { el.style.transition = 'transform .3s cubic-bezier(.16,1,.3,1)'; });
      el.addEventListener('pointermove', (e) => {
        const r = el.getBoundingClientRect();
        const x = (e.clientX - r.left) / r.width - 0.5, y = (e.clientY - r.top) / r.height - 0.5;
        el.style.transform = `perspective(1100px) rotateX(${(-y * max).toFixed(2)}deg) rotateY(${(x * max).toFixed(2)}deg) translateZ(0)`;
      });
      el.addEventListener('pointerleave', () => { el.style.transition = 'transform .9s cubic-bezier(.16,1,.3,1)'; el.style.transform = ''; });
    });
    $$('[data-magnetic]').forEach((b) => {
      const inner = b.querySelector('span');
      b.addEventListener('pointermove', (e) => {
        const r = b.getBoundingClientRect();
        const x = e.clientX - r.left - r.width / 2, y = e.clientY - r.top - r.height / 2;
        b.style.transform = `translate(${(x * 0.2).toFixed(1)}px, ${(y * 0.3).toFixed(1)}px)`;
        if (inner) inner.style.transform = `translate(${(x * 0.08).toFixed(1)}px, ${(y * 0.12).toFixed(1)}px)`;
      });
      b.addEventListener('pointerleave', () => { b.style.transform = ''; if (inner) inner.style.transform = ''; });
    });
  }

  /* ---------- Auto mode terminal types itself out ---------- */

  const typer = $('[data-typer]');
  if (typer) {
    const lines = $$('p', typer).map((p) => ({ p, text: p.textContent, ok: p.hasAttribute('data-ok') }));
    if (!reduced) lines.forEach((l) => { l.p.textContent = ''; });
    const run = async () => {
      for (const l of lines) {
        if (!reduced) {
          l.p.classList.add('typing');
          for (let i = 1; i <= l.text.length; i++) { l.p.textContent = l.text.slice(0, i); await wait(10 + Math.random() * 16); }
          l.p.classList.remove('typing');
        }
        if (l.ok) { const s = document.createElement('span'); s.className = 'ok'; s.textContent = '✓'; l.p.append(s); }
        if (!reduced) await wait(240);
      }
    };
    const tio = new IntersectionObserver((es) => { if (es[0].isIntersecting) { tio.disconnect(); setTimeout(run, reduced ? 0 : 450); } }, { threshold: 0.5 });
    tio.observe(typer);
  }

  /* ---------- pool fallback demo ---------- */

  const pools = $$('#pools li');
  if (pools.length) {
    const LABEL = { try: 'connecting…', down: 'no answer', up: 'shares accepted', '': 'standby' };
    const SEQ = [[['try', '', ''], 1600], [['down', 'try', ''], 1500], [['down', 'up', ''], 3400], [['', '', ''], 900]];
    let k = 0;
    const next = () => {
      const [states, ms] = SEQ[k];
      states.forEach((st, i) => { pools[i].className = st; pools[i].querySelector('span').textContent = LABEL[st]; });
      k = (k + 1) % SEQ.length;
      setTimeout(next, ms);
    };
    next();
  }

  /* ---------- open numbers: live, each from a public source ---------- */

  const numsSec = $('#numbers');
  if (numsSec) {
    const shown = {};
    const getJSON = async (url) => { const r = await fetch(url, { cache: 'no-store' }); if (!r.ok) throw new Error(r.status); return r.json(); };

    // Installer downloads straight from GitHub (60 API calls an hour per visitor, so cache for 10 minutes)
    async function githubDownloads() {
      try {
        const cached = JSON.parse(sessionStorage.getItem('mintro-dl') || 'null');
        if (cached && Date.now() - cached.at < 600e3) return cached.n;
      } catch { /* storage unavailable */ }
      let n = 0;
      for (let page = 1; page <= 5; page++) {
        const releases = await getJSON(`https://api.github.com/repos/${SITE.repo}/releases?per_page=100&page=${page}`);
        for (const rel of releases) for (const a of rel.assets || []) if (/^MINTRO-Setup-.*\.exe$/.test(a.name)) n += a.download_count;
        if (releases.length < 100) break;
      }
      try { sessionStorage.setItem('mintro-dl', JSON.stringify({ at: Date.now(), n })); } catch { /* fine */ }
      return n;
    }

    function show(key, value) {
      const el = $(`[data-stat="${key}"]`, numsSec);
      if (!el || value == null) return;
      const from = shown[key] ?? 0;
      shown[key] = value;
      if (reduced || from === value) { el.textContent = value.toLocaleString(); return; }
      const start = performance.now();
      const step = (now) => {
        const t = clamp((now - start) / 1400, 0, 1);
        el.textContent = Math.round(from + (value - from) * (1 - Math.pow(1 - t, 4))).toLocaleString();
        if (t < 1) requestAnimationFrame(step);
      };
      requestAnimationFrame(step);
    }

    function chart(days) {
      const svg = $('#trendChart');
      const pts = (days || []).slice(-30).map((d) => d.peak_mining || 0);
      let empty = $('.trend-empty', numsSec);
      if (pts.length < 2) {
        svg.innerHTML = '<line class="base" x1="0" y1="110" x2="600" y2="110"/>';
        if (!empty) { empty = document.createElement('p'); empty.className = 'trend-empty'; svg.after(empty); }
        empty.textContent = statsBase ? 'Collecting the first days…' : 'Goes live with the stats service';
        return;
      }
      if (empty) empty.remove();
      const max = Math.max(...pts, 1), x = (i) => (i / (pts.length - 1)) * 600, y = (v) => 110 - (v / max) * 96;
      const line = pts.map((v, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join('');
      svg.innerHTML = `<defs><linearGradient id="trendFill" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="#3ddc97" stop-opacity=".28"/><stop offset="1" stop-color="#3ddc97" stop-opacity="0"/></linearGradient></defs>`
        + `<line class="base" x1="0" y1="110" x2="600" y2="110"/><path class="area" d="${line}L600,110L0,110Z"/><path class="line" d="${line}"/>`;
      $('#trendRange').textContent = `last ${pts.length} days · peak ${max.toLocaleString()}`;
    }

    async function refresh() {
      let stats = {};
      if (statsBase) {
        try { stats = await getJSON(`${statsBase}/v1/stats`); } catch { /* offline: keep what's shown */ }
        try { chart((await getJSON(`${statsBase}/v1/history`)).days); } catch { chart([]); }
      } else {
        chart([]);
      }
      if (stats.downloads == null && hasRepo) { try { stats.downloads = await githubDownloads(); } catch { /* rate-limited */ } }
      ['mining_now', 'downloads', 'mined_24h', 'installs'].forEach((k) => show(k, stats[k]));
      if (stats.updated) {
        const foot = $('#numsFoot');
        let stamp = $('.stamp', foot);
        if (!stamp) { stamp = document.createElement('span'); stamp.className = 'stamp'; foot.append(' ', stamp); }
        stamp.textContent = `Updated ${new Date(stats.updated).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}.`;
      }
    }

    let timer = null;
    new IntersectionObserver((es) => {
      if (es[0].isIntersecting && !timer) { refresh(); timer = setInterval(() => { if (!document.hidden) refresh(); }, 60e3); }
    }, { rootMargin: '600px 0px' }).observe(numsSec);
  }

  /* ---------- listing request form ---------- */

  const form = $('#applyForm');
  if (form) {
    const msg = $('#applyMsg'), poolFields = $$('.pool-f', form);
    const syncPool = () => poolFields.forEach((f) => { f.hidden = form.source.value !== 'custom'; });
    form.source.addEventListener('change', syncPool);
    syncPool();
    const say = (text, kind) => { msg.textContent = text; msg.className = `apply-msg ${kind || ''}`; };
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const data = Object.fromEntries(new FormData(form));
      const missing = ['project', 'symbol', 'site', 'email'].find((k) => !String(data[k] || '').trim());
      if (missing) { say(`Please fill in ${missing === 'symbol' ? 'the ticker' : missing}.`, 'err'); form[missing].focus(); return; }
      if (data.source === 'custom' && !(data.pool_host && data.pool_port)) { say('Add your pool host and port.', 'err'); return; }
      const mailRequest = () => {
        location.href = `mailto:${SITE.email}?subject=${encodeURIComponent(`Listing request: ${data.project} (${data.symbol})`)}`
          + `&body=${encodeURIComponent(Object.entries(data).filter(([k, v]) => v && k !== 'website_url').map(([k, v]) => `${k}: ${v}`).join('\n'))}`;
      };
      const endpoint = apiBase ? `${apiBase}/api/listing` : statsBase ? `${statsBase}/v1/listing-request` : '';
      if (!endpoint) {
        if (SITE.email) mailRequest(); else say('Listing requests open soon.', 'err');
        return;
      }
      const button = $('button[type=submit]', form);
      button.disabled = true;
      say('Sending…');
      try {
        const r = await fetch(endpoint, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) })
          .catch(() => null);
        const body = r ? await r.json().catch(() => ({})) : {};
        if ((!r || r.status >= 500 || r.status === 404) && SITE.email) {
          say("We couldn't reach our server, so your email app will open with the request filled in — just press send.", 'err');
          mailRequest();
          return;
        }
        if (!r.ok || body.error) throw new Error(body.error || `The request didn't go through (${r.status}).`);
        form.reset();
        syncPool();
        say(`Thanks! Request #${body.id || ''} is in. We'll email you within two business days.`, 'ok');
      } catch (err) {
        say(err.message, 'err');
      } finally {
        button.disabled = false;
      }
    });
  }

  /* ---------- FAQ opens and closes smoothly ---------- */

  $$('.qa details').forEach((d) => {
    const ans = $('.ans', d);
    $('summary', d).addEventListener('click', (e) => {
      if (reduced) return;
      e.preventDefault();
      const ease = 'cubic-bezier(.16,1,.3,1)';
      if (d.open) {
        const h = ans.offsetHeight;
        ans.animate([{ height: `${h}px`, opacity: 1 }, { height: '0px', opacity: 0 }], { duration: 420, easing: ease, fill: 'forwards' })
          .onfinish = (ev) => { d.open = false; ev.target.cancel(); };
      } else {
        d.open = true;
        const h = ans.offsetHeight;
        ans.animate([{ height: '0px', opacity: 0 }, { height: `${h}px`, opacity: 1 }], { duration: 620, easing: ease });
      }
    });
  });
})();
