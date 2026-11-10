/* MINTRO website: the download guide.

   MINTRO's installer isn't code-signed yet, so browsers and Windows warn before it runs. Every Download button
   starts the download and opens this guide: what the warnings look like and the clicks that get past them
   (Keep, then More info > Run anyway). On a phone or a Mac it explains that MINTRO is for Windows PCs instead
   of handing over an .exe. Buttons marked data-dl-guide open the guide without downloading. */
(() => {
  'use strict';

  const URL_DL = 'https://mintro.aiteleresearch.com/download/latest';
  const FEED = '/download/release.json';
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const ua = navigator.userAgent;
  const platform = (navigator.userAgentData && navigator.userAgentData.platform) || '';
  const isWindows = /Windows/i.test(platform || ua) && !/Windows Phone|Xbox/i.test(ua);
  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
  let dlg = null, file = 'MINTRO-Setup.exe', feedAsked = false, timer = null;

  const X = '<svg viewBox="0 0 14 14" aria-hidden="true"><path d="M3 3l8 8M11 3l-8 8" fill="none"/></svg>';

  function startDownload(url) {
    const a = document.createElement('a');
    a.href = url; a.download = ''; a.hidden = true;
    document.body.append(a); a.click(); a.remove();
  }

  // The exact file name, as the browser and Windows will show it
  function askFeed() {
    if (feedAsked) return;
    feedAsked = true;
    fetch(FEED, { cache: 'no-store' }).then((r) => (r.ok ? r.json() : null)).then((rel) => {
      const asset = rel && (rel.assets || []).find((a) => /^MINTRO-Setup-[\w.-]+\.exe$/.test(a.name));
      if (asset) { file = asset.name; $$('[data-file]', dlg).forEach((el) => (el.textContent = file)); }
    }).catch(() => { /* keep the generic name */ });
  }

  function build() {
    dlg = document.createElement('dialog');
    dlg.className = 'dl-dlg';
    dlg.setAttribute('aria-labelledby', 'dgTitle');
    dlg.innerHTML = `
      <div class="dg-head">
        <div>
          <p class="eyebrow dg-status"><i aria-hidden="true"></i><span data-status></span></p>
          <h2 id="dgTitle" data-title></h2>
          <p class="dg-lede" data-lede></p>
          <div class="dg-elsewhere" data-elsewhere>
            <button class="btn small primary" type="button" data-send><span>Send the link to my PC</span></button>
            <span class="dg-sent" data-sent role="status"></span>
          </div>
        </div>
        <button class="sd-x" type="button" data-close aria-label="Close">${X}</button>
      </div>
      <ol class="dg-steps">
        <li>
          <b>Keep the file</b>
          <p>If your browser says <q><span data-file>${file}</span> isn't commonly downloaded</q>, choose <em>Keep</em>.
            In Edge that's <em>…</em> &rsaquo; <em>Keep</em>, then <em>Show more</em> &rsaquo; <em>Keep anyway</em>.</p>
        </li>
        <li>
          <b>Open it: <em>More info</em>, then <em>Run anyway</em></b>
          <p>Windows shows <q>Windows protected your PC</q>. Click <em>More info</em>, check that the app is
            <span class="dg-file" data-file>${file}</span>, then click <em>Run anyway</em>.</p>
          <figure class="ss" data-stage="0" aria-hidden="true">
            <div class="ss-win">
              <p class="ss-title">Windows protected your PC</p>
              <p class="ss-text">Microsoft Defender SmartScreen prevented an unrecognized app from starting.</p>
              <p class="ss-more"><span data-target="0">More info</span></p>
              <dl class="ss-app"><dt>App:</dt><dd data-file>${file}</dd><dt>Publisher:</dt><dd>Unknown publisher</dd></dl>
              <div class="ss-btns"><span class="ss-run" data-target="1">Run anyway</span><span>Don't run</span></div>
              <svg class="ss-cursor" viewBox="0 0 16 22"><path d="M1 1v17l4.6-4.4 3.1 7 3-1.3-3-6.9H15z"/></svg>
            </div>
            <figcaption><span data-cap="0">Click <b>More info</b></span><span data-cap="1">then <b>Run anyway</b></span></figcaption>
          </figure>
        </li>
        <li>
          <b>Click <em>Install</em></b>
          <p>MINTRO Setup opens. One click installs it in a few seconds, just for you and without admin rights,
            then MINTRO opens.</p>
        </li>
      </ol>
      <details class="dg-why">
        <summary>Why does Windows warn about MINTRO?</summary>
        <p>MINTRO is new and isn't code-signed yet, so Windows can't name its publisher, and it warns about any app
          it hasn't seen many people install. The source code is public on
          <a href="https://github.com/aiteleresearch/mintro" target="_blank" rel="noopener">GitHub</a>, the
          installer writes only to your own user folder, and <em>Settings &rsaquo; Apps</em> removes it.</p>
        <p>On PCs with <em>Smart App Control</em> on, Windows blocks unsigned apps without a Run anyway button, so
          MINTRO can't be installed there yet.</p>
      </details>
      <div class="dg-foot">
        <a class="dg-alt" data-alt href="${URL_DL}"></a>
        <button class="btn primary" type="button" data-primary><span></span></button>
      </div>`;
    document.body.append(dlg);

    dlg.addEventListener('click', (e) => {
      if (e.target === dlg || e.target.closest('[data-close]')) dlg.close();  // the backdrop, or a close button
    });
    dlg.addEventListener('close', stopAnimation);
    $('[data-alt]', dlg).addEventListener('click', (e) => {
      e.preventDefault();
      startDownload(URL_DL);
      setMode('started');
    });
    $('[data-primary]', dlg).addEventListener('click', () => {
      if (dlg.dataset.mode === 'guide') { startDownload(URL_DL); setMode('started'); } else dlg.close();
    });
    $('[data-send]', dlg).addEventListener('click', sendLink);
    $('.ss', dlg).addEventListener('click', () => !timer && stage(1 - +$('.ss', dlg).dataset.stage));
  }

  const TEXT = {
    started: {
      status: 'Your download has started',
      title: 'Windows will ask before it runs MINTRO',
      lede: "MINTRO isn't code-signed yet, so your browser and Windows show a warning the first time. Here's what you'll see, and the clicks that get you past it.",
      alt: "Download didn't start? Try again", primary: 'Got it',
    },
    guide: {
      status: 'Before you install',
      title: 'Windows will ask before it runs MINTRO',
      lede: "MINTRO isn't code-signed yet, so your browser and Windows show a warning the first time. Here's what you'll see, and the clicks that get you past it.",
      alt: '', primary: 'Download MINTRO',
    },
    elsewhere: {
      status: 'MINTRO is for Windows',
      title: 'Open this page on your Windows PC',
      lede: 'MINTRO runs on Windows 10 and 11. On your PC, open mintro.aiteleresearch.com and press Download. Windows will ask before it runs the installer; these are the steps.',
      alt: 'Download anyway', primary: 'Got it',
    },
  };

  function setMode(mode) {
    const t = TEXT[mode];
    dlg.dataset.mode = mode;
    $('[data-status]', dlg).textContent = t.status;
    $('[data-title]', dlg).textContent = t.title;
    $('[data-lede]', dlg).textContent = t.lede;
    $('[data-alt]', dlg).textContent = t.alt;
    $('[data-alt]', dlg).hidden = !t.alt;
    $('[data-primary] span', dlg).textContent = t.primary;
    $('[data-elsewhere]', dlg).hidden = mode !== 'elsewhere';
  }

  async function sendLink() {
    const url = `${location.origin}/`, sent = $('[data-sent]', dlg);
    try {
      if (navigator.share) { await navigator.share({ title: 'MINTRO', text: 'MINTRO for Windows', url }); return; }
      await navigator.clipboard.writeText(url);
      sent.textContent = 'Link copied. Paste it into a message to yourself.';
    } catch (e) {
      if (e && e.name === 'AbortError') return;  // the share sheet was dismissed
      sent.textContent = url;
    }
  }

  // The SmartScreen picture: More info, then Run anyway, on a loop while the guide is open
  function stage(n) {
    const ss = $('.ss', dlg), win = $('.ss-win', ss), cursor = $('.ss-cursor', ss);
    ss.dataset.stage = String(n);
    requestAnimationFrame(() => {
      const target = $(`[data-target="${n}"]`, ss), w = win.getBoundingClientRect(), r = target.getBoundingClientRect();
      cursor.style.transform = `translate(${r.left - w.left + r.width * 0.55}px, ${r.top - w.top + r.height * 0.45}px)`;
    });
  }
  function startAnimation() {
    stopAnimation();
    stage(0);
    if (reduced) return;  // still: tap the picture to see the next step
    let n = 0;
    timer = setInterval(() => stage((n = 1 - n)), 2800);
  }
  function stopAnimation() { clearInterval(timer); timer = null; }

  function open(mode) {
    if (!dlg) build();
    askFeed();
    setMode(mode);
    $('[data-sent]', dlg).textContent = '';
    $('.dg-why', dlg).open = false;
    if (typeof dlg.showModal === 'function') dlg.showModal(); else dlg.setAttribute('open', '');
    dlg.scrollTop = 0;
    startAnimation();
  }

  $$('[data-href="download"]').forEach((a) => {
    a.removeAttribute('target');  // the download starts here; there's no page to open in a new tab
    a.addEventListener('click', (e) => {
      if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;  // let new-tab clicks be
      e.preventDefault();
      if (isWindows) { startDownload(a.href || URL_DL); open('started'); } else open('elsewhere');
    });
  });
  $$('[data-dl-guide]').forEach((b) => b.addEventListener('click', (e) => { e.preventDefault(); open(isWindows ? 'guide' : 'elsewhere'); }));
})();
