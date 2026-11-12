/* Anti-spam check for a website form: a self-hosted proof-of-work captcha in the ALTCHA format (altcha.org, MIT).
   On the page:  <form data-captcha …>  and  <script defer src="…/captcha.js"></script>
   data-captcha is where to get a challenge; empty means /api/captcha on this site. A [data-captcha-slot] element
   inside the form says where the status line goes (otherwise it goes just above the send button).

   It fetches a signed challenge, solves it in a background worker (about a second, while the visitor types), and
   when the form is sent adds the answer as the hidden field `captcha`, so the form's own script sends it along
   (FormData picks it up). Each answer is good for one message, so a fresh one is solved after every send, and
   before one would expire. A send made before the answer is ready waits for it and then goes by itself. If the
   check can't be loaded at all, the send goes ahead and the server decides, so a page's own fallback (opening the
   email app, say) still works. Nothing about the visitor leaves the page.
   The same file is in MINTRO, Sandhi, Laghu and Pramaan; the Aitele Next.js sites have components/captcha.tsx. */
(() => {
  'use strict';
  if (window.__captcha) return;
  window.__captcha = true;

  const WORKER = `
self.onmessage = async (e) => {
  const { salt, challenge, max } = e.data;
  const enc = new TextEncoder();
  const want = new Uint8Array(challenge.match(/../g).map((h) => parseInt(h, 16)));
  for (let n = 0; n <= max; n++) {
    const got = new Uint8Array(await crypto.subtle.digest("SHA-256", enc.encode(salt + n)));
    let i = 0;
    while (i < 32 && got[i] === want[i]) i++;
    if (i === 32) return self.postMessage(n);
  }
  self.postMessage(null);
};`;

  async function solveHere(c) {
    const enc = new TextEncoder();
    const want = new Uint8Array((c.challenge.match(/../g) || []).map((h) => parseInt(h, 16)));
    for (let n = 0; n <= c.maxnumber; n++) {
      const got = new Uint8Array(await crypto.subtle.digest('SHA-256', enc.encode(c.salt + n)));
      let i = 0;
      while (i < 32 && got[i] === want[i]) i++;
      if (i === 32) return n;
      if (n % 2000 === 1999) await new Promise((r) => setTimeout(r, 0)); // keep the page responsive
    }
    return null;
  }

  function solve(c) {
    let url = '';
    try {
      url = URL.createObjectURL(new Blob([WORKER], { type: 'text/javascript' }));
      const worker = new Worker(url);
      return new Promise((resolve) => {
        const done = () => { worker.terminate(); URL.revokeObjectURL(url); };
        worker.onmessage = (e) => { done(); resolve(e.data); };
        worker.onerror = (e) => { e.preventDefault(); done(); solveHere(c).then(resolve, () => resolve(null)); };
        worker.postMessage({ salt: c.salt, challenge: c.challenge, max: c.maxnumber });
      });
    } catch {
      if (url) URL.revokeObjectURL(url);
      return solveHere(c);
    }
  }

  const TEXT = {
    working: 'Checking you’re not a bot…',
    ready: 'Anti-spam check passed.',
    held: 'Finishing the anti-spam check — sending in a moment…',
    failed: 'The anti-spam check couldn’t load.',
  };
  const css = document.createElement('style');
  css.textContent = '.captcha-status{display:flex;align-items:center;gap:.55em;margin:.6em 0;font-size:.8rem;line-height:1.4;opacity:.8}'
    + '.captcha-status>i{width:.6em;height:.6em;flex:none;border-radius:50%;border:1.5px solid currentColor;opacity:.6}'
    + '.captcha-status[data-state=ready]>i{background:currentColor;opacity:1}'
    + '.captcha-status[data-state=working]>i,.captcha-status[data-state=held]>i{animation:captcha-pulse 1.1s ease-in-out infinite}'
    + '.captcha-status button{font:inherit;color:inherit;text-decoration:underline;background:none;border:0;padding:0;margin-left:.3em;cursor:pointer}'
    + '@keyframes captcha-pulse{0%,100%{transform:scale(.7)}50%{transform:scale(1.05)}}';
  document.head.appendChild(css);

  const guards = new Map(); // form -> its submit handler

  function guard(form) {
    const url = form.getAttribute('data-captcha') || '/api/captcha';
    const field = Object.assign(document.createElement('input'), { type: 'hidden', name: 'captcha' });
    form.appendChild(field);
    const box = document.createElement('p');
    box.className = 'captcha-status';
    box.setAttribute('role', 'status');
    box.setAttribute('aria-live', 'polite');
    box.innerHTML = '<i aria-hidden="true"></i><span></span>';
    const slot = form.querySelector('[data-captcha-slot]');
    const button = form.querySelector('[type=submit]');
    if (slot) slot.appendChild(box);
    else if (button) {
      let at = button; // the button, or the row holding it: whichever sits directly in the form
      while (at.parentElement && at.parentElement !== form) at = at.parentElement;
      form.insertBefore(box, at.parentElement === form ? at : null);
    } else form.appendChild(box);

    let token = '', expires = 0, run = 0, busy = false, timer = 0, holdTimer = 0, state = '';
    let held = null;
    const show = (s) => {
      state = s;
      box.dataset.state = s;
      box.lastChild.textContent = TEXT[s];
      if (s === 'failed') {
        const again = Object.assign(document.createElement('button'), { type: 'button', textContent: 'Try again' });
        again.onclick = () => fresh();
        box.lastChild.appendChild(again);
      }
    };
    const send = () => {
      const s = held && held.submitter;
      held = null;
      clearTimeout(holdTimer);
      if (form.requestSubmit) {
        if (s && s.isConnected && form.contains(s)) form.requestSubmit(s); else form.requestSubmit();
      } else if (s) s.click();
      else form.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
    };
    const fresh = async () => {
      const id = ++run;
      busy = true;
      token = '';
      clearTimeout(timer);
      show(held ? 'held' : 'working');
      try {
        const r = await fetch(url, { cache: 'no-store', credentials: 'omit' });
        if (!r.ok) throw new Error(`challenge ${r.status}`);
        const c = await r.json();
        const n = await solve(c);
        if (id !== run) return;
        if (n === null || n === undefined) throw new Error('unsolved');
        token = btoa(JSON.stringify({ algorithm: c.algorithm, challenge: c.challenge, number: n, salt: c.salt, signature: c.signature }));
        expires = Number((/[?&]expires=(\d+)/.exec(c.salt) || [])[1]) * 1000 || Date.now() + 10 * 60000;
        busy = false;
        timer = setTimeout(fresh, Math.max(10000, expires - Date.now() - 60000)); // renew before it lapses
        show('ready');
      } catch {
        if (id !== run) return;
        busy = false;
        show('failed');
      }
      if (held) send();
    };
    guards.set(form, (e) => {
      if (token && expires - Date.now() > 15000) {
        field.value = token;
        token = '';
        setTimeout(fresh, 0); // that answer is spent: solve the next one
        return;
      }
      if (state === 'failed' && !busy) { // can't check from here: let it go, the server decides
        field.value = '';
        setTimeout(fresh, 0);
        return;
      }
      // Not ready yet: hold the send (the page's own handlers too) and send it once the answer is in.
      e.preventDefault();
      e.stopImmediatePropagation();
      held = { submitter: e.submitter || null };
      show('held');
      clearTimeout(holdTimer);
      holdTimer = setTimeout(() => { if (held) { state = 'failed'; busy = false; send(); } }, 25000);
      if (!busy) fresh();
    });
    fresh();
  }

  // Capture, on the document: runs before the form's own submit handlers, whatever order the scripts loaded in.
  document.addEventListener('submit', (e) => {
    const g = guards.get(e.target);
    if (g) g(e);
  }, true);

  const start = () => document.querySelectorAll('form[data-captcha]').forEach((f) => { if (!guards.has(f)) guard(f); });
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
