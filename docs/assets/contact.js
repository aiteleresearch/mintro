/* MINTRO website: the contact form (contact.html).
   It posts to MINTRO's mail endpoint (data-api on the form; server.js in the Aitele deployment), which emails the
   team with Reply-To set to you and sends you a confirmation. If the endpoint can't be reached, your email app opens
   with the message filled in instead. */
(() => {
  'use strict';
  const form = document.getElementById('contactForm');
  if (!form) return;
  const api = (form.dataset.api || '').replace(/\/+$/, '');
  const inbox = form.dataset.email;
  const msg = document.getElementById('contactMsg');
  const button = form.querySelector('button[type=submit]');
  const say = (text, kind) => { msg.textContent = text; msg.className = `apply-msg ${kind || ''}`; };
  const openMail = (d) => {
    location.href = `mailto:${inbox}?subject=${encodeURIComponent(`MINTRO: ${d.topic}`)}`
      + `&body=${encodeURIComponent(`${d.message}\n\n${d.name}`)}`;
  };
  document.getElementById('year').textContent = new Date().getFullYear();

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const d = Object.fromEntries(new FormData(form));
    const missing = ['name', 'email', 'message'].find((k) => !String(d[k] || '').trim());
    if (missing) { say(`Please fill in your ${missing}.`, 'err'); form[missing].focus(); return; }
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(d.email.trim())) { say('Please check your email address.', 'err'); form.email.focus(); return; }
    button.disabled = true;
    say('Sending…');
    let r = null, body = {};
    try {
      r = await fetch(`${api}/api/contact`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(d) });
      body = await r.json().catch(() => ({}));
    } catch { r = null; }
    button.disabled = false;
    if (r && r.ok && body.ok) {
      form.reset();
      say(`Thanks, ${d.name.trim().split(/\s+/)[0]}! Your message is in, and a confirmation is on its way to ${d.email.trim()}.`, 'ok');
    } else if (r && r.status >= 400 && r.status < 500 && r.status !== 404 && body.error) {
      say(body.error, 'err');               // something to fix: a field, or too many messages
    } else {
      say(`We couldn't reach our server, so your email app will open with your message — just press send.`, 'err');
      openMail(d);
    }
  });
})();
