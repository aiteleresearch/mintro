#!/usr/bin/env node
// MINTRO website server, for the copy of the site on the Aitele VM (mintra.aiteleresearch.com). Caddy serves the
// pages and passes /api/* and /download/* here. No dependencies.
//
//   POST /api/contact     the contact form  } emailed the way every Aitele venture's sendInquiry does: the team
//   POST /api/listing     the listing form  } inbox gets it with Reply-To set to the sender, who gets a confirmation
//   POST /api/visit       a page view; counts unique visitors without cookies (the page sends two flags)
//   GET  /api/stats       downloads, unique visitors, page views and updates delivered, per day since day one
//   GET  /download/<file> the installer, the update package and its release feed — counted, resumable
//   GET  /download/latest redirects to the newest installer
//   GET  /api/health
//   GET  /v1/admin/requests        } the listing requests, for the publisher's admin dashboard (publisher/admin.py),
//   POST /v1/admin/requests/:id    } same API as server/stats: Bearer MINTRO_ADMIN_TOKEN
//
// Counts and listing requests are kept in MINTRO_DATA_DIR (default: ../mintro-data, beside the app folder), which
// a redeploy never touches: stats.json and requests.json, written atomically, each with a .bak; stats also get a
// daily snapshot, and pending counts are flushed on shutdown.
//
// Env (deploy/install.sh writes .env.local next to this file): RESEND_API_KEY, EMAIL_FROM, CONTACT_INBOX, PORT,
// MINTRO_SITE_URL, MINTRO_DATA_DIR, MINTRO_ADMIN_TOKEN, MINTRO_ALLOWED_ORIGINS (more origins allowed to post).
// Local preview: `node server.js --static` also serves the pages, on http://localhost:5100.
'use strict';
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');

// .env.local, read the way the Next apps read it: values already in the environment win.
try {
  for (const line of fs.readFileSync(path.join(__dirname, '.env.local'), 'utf8').split(/\r?\n/)) {
    const m = line.match(/^\s*([A-Za-z0-9_]+)\s*=\s*(.*?)\s*$/);
    if (m && process.env[m[1]] === undefined) process.env[m[1]] = m[2].replace(/^["']|["']$/g, '');
  }
} catch { /* no .env.local */ }

const PORT = Number(process.env.PORT) || 5100;
const SITE_URL = (process.env.MINTRO_SITE_URL || 'https://mintra.aiteleresearch.com').replace(/\/+$/, '');
const SITE_DIR = path.resolve(process.env.MINTRO_SITE_DIR || path.join(__dirname, 'site'));
const DATA_DIR = path.resolve(process.env.MINTRO_DATA_DIR || path.join(__dirname, '..', 'mintro-data'));
const INBOX = process.env.CONTACT_INBOX || 'hello@aiteleresearch.com';
const FROM = process.env.EMAIL_FROM || 'Aitele Research <notify@aiteleresearch.com>';
const RESEND = process.env.RESEND_ENDPOINT || 'https://api.resend.com/emails';
const ORIGINS = new Set([
  new URL(SITE_URL).origin,
  'https://aiteleresearch.github.io',
  ...(process.env.MINTRO_ALLOWED_ORIGINS || '').split(',').map((s) => s.trim()).filter(Boolean),
]);
const SERVE_PAGES = process.argv.includes('--static');
const BRAND = { name: 'MINTRO', accent: '#3ddc97', accentDeep: '#0b9a69' };
const WRITE_US = 'Please write to hello@aiteleresearch.com directly.';
const TOPICS = ['General question', 'Problem with MINTRO', 'Listing a coin', 'Partnership', 'Press'];
const PLANS = { standard: 'Listed', featured: 'Featured', promo: 'Promo' };
const BOTS = /bot|crawl|spider|slurp|preview|facebookexternalhit|embedly|headless|lighthouse/i;

/* ---------- helpers ---------- */

const esc = (s) => String(s).replace(/[<>&"]/g, (c) => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;' })[c]);
const oneLine = (s) => String(s).replace(/[\r\n]+/g, ' ').trim();
const str = (v, max) => String(v ?? '').trim().slice(0, max);
const isEmail = (s) => /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(s) && s.length <= 120;
const isUrl = (s) => /^https?:\/\/[^\s]+$/i.test(s) && s.length <= 200;
const today = () => new Date().toISOString().slice(0, 10);
// Only Caddy reaches this port, and Caddy sets X-Forwarded-For from the real client: its last entry is the visitor.
const clientIp = (req) => String(req.headers['x-forwarded-for'] || '').split(',').pop().trim() || req.socket.remoteAddress || '';

// Sliding-window limits per connection, in memory only.
function limiter(perWindow, windowMs) {
  const hits = new Map();
  setInterval(() => {
    const now = Date.now();
    for (const [k, ts] of hits) if (!ts.some((t) => now - t < windowMs)) hits.delete(k);
  }, 60e3).unref();
  return (key) => {
    const now = Date.now();
    const recent = (hits.get(key) || []).filter((t) => now - t < windowMs);
    if (recent.length >= perWindow) { hits.set(key, recent); return Math.ceil((recent[0] + windowMs - now) / 60e3); }
    recent.push(now);
    hits.set(key, recent);
    return 0;
  };
}
const formLimit = limiter(5, 10 * 60e3);     // 5 messages per 10 minutes
const visitLimit = limiter(120, 10 * 60e3);  // page views counted per connection per 10 minutes

/* ---------- counters (persist across restarts and redeploys) ---------- */

const STATS_FILE = path.join(DATA_DIR, 'stats.json');
const SNAPSHOT_DAYS = 30;
const blankDay = () => ({ downloads: 0, visitors: 0, newVisitors: 0, views: 0, updates: 0 });
const valid = (s) => s && typeof s.since === 'string' && s.totals && typeof s.days === 'object';

function loadStats() {
  fs.mkdirSync(DATA_DIR, { recursive: true });
  try {
    const s = JSON.parse(fs.readFileSync(STATS_FILE, 'utf8'));
    if (valid(s)) return s;
    throw new Error('not a stats file');
  } catch (e) {
    if (e.code !== 'ENOENT') {
      // Never write over a file we can't read: keep it aside, then fall back to the last good copy.
      const aside = `${STATS_FILE}.unreadable-${Date.now()}`;
      try { fs.renameSync(STATS_FILE, aside); } catch { /* gone already */ }
      console.error(`stats.json unreadable (${e.message}); kept as ${path.basename(aside)}`);
    }
  }
  try {
    const s = JSON.parse(fs.readFileSync(`${STATS_FILE}.bak`, 'utf8'));
    if (valid(s)) { console.error('stats restored from stats.json.bak'); return s; }
  } catch { /* no backup */ }
  return { since: today(), totals: { downloads: 0, visitors: 0, views: 0, updates: 0 }, days: {} };
}

function writeStats() {
  try {
    const tmp = `${STATS_FILE}.tmp`;
    fs.writeFileSync(tmp, JSON.stringify(stats));
    if (fs.existsSync(STATS_FILE)) fs.copyFileSync(STATS_FILE, `${STATS_FILE}.bak`);
    fs.renameSync(tmp, STATS_FILE);
    const snap = path.join(DATA_DIR, `stats-${today()}.json`);
    if (!fs.existsSync(snap)) {
      fs.copyFileSync(STATS_FILE, snap);
      const cutoff = new Date(Date.now() - SNAPSHOT_DAYS * 864e5).toISOString().slice(0, 10);
      for (const f of fs.readdirSync(DATA_DIR)) {
        const m = /^stats-(\d{4}-\d{2}-\d{2})\.json$/.exec(f);
        if (m && m[1] < cutoff) fs.unlinkSync(path.join(DATA_DIR, f));
      }
    }
  } catch (e) {
    console.error('could not save stats:', e.message);
  }
}

const stats = loadStats();
writeStats(); // records day one on a fresh install, and the day's snapshot
let saveTimer = null;
function save() { if (!saveTimer) saveTimer = setTimeout(() => { saveTimer = null; writeStats(); }, 2000); }
function flush() { if (saveTimer) { clearTimeout(saveTimer); saveTimer = null; writeStats(); } }
for (const sig of ['SIGTERM', 'SIGINT']) process.on(sig, () => { flush(); process.exit(0); });

// views / downloads / updates add to the day and the total; "visitors" is a day's unique visitors, and
// "newVisitors" (first visit ever from that browser) is what adds to the all-time unique-visitor total.
function count(fields) {
  const day = (stats.days[today()] ||= blankDay());
  for (const [k, n] of Object.entries(fields)) {
    if (!n) continue;
    day[k] = (day[k] || 0) + n;
    if (k === 'newVisitors') stats.totals.visitors += n;
    else if (k !== 'visitors') stats.totals[k] = (stats.totals[k] || 0) + n;
  }
  save();
}

function statsView() {
  const days = [];
  for (let d = new Date(`${stats.since}T00:00:00Z`), end = today(); ; d.setUTCDate(d.getUTCDate() + 1)) {
    const date = d.toISOString().slice(0, 10);
    days.push({ date, ...blankDay(), ...(stats.days[date] || {}) });
    if (date >= end || days.length > 3660) break;
  }
  return { since: stats.since, today: today(), totals: stats.totals, days };
}

/* ---------- listing requests, for the publisher's admin dashboard ---------- */

const REQUESTS_FILE = path.join(DATA_DIR, 'requests.json');
const REQUEST_STATUSES = ['new', 'reviewing', 'awaiting_payment', 'listed', 'rejected'];
const REQUEST_FIELDS = ['project', 'symbol', 'algorithm', 'plan', 'source', 'pool_host', 'pool_port', 'pool_tls', 'site',
  'explorer', 'wallet', 'email', 'telegram', 'message'];

function loadRequests() {
  for (const f of [REQUESTS_FILE, `${REQUESTS_FILE}.bak`]) {
    try {
      const r = JSON.parse(fs.readFileSync(f, 'utf8'));
      if (Array.isArray(r.requests)) return r;
    } catch (e) {
      if (e.code !== 'ENOENT' && f === REQUESTS_FILE) {
        const aside = `${REQUESTS_FILE}.unreadable-${Date.now()}`;
        try { fs.renameSync(REQUESTS_FILE, aside); } catch { /* gone already */ }
        console.error(`requests.json unreadable (${e.message}); kept as ${path.basename(aside)}`);
      }
    }
  }
  return { next: 1, requests: [] };
}
const requests = loadRequests();
function saveRequests() {
  try {
    const tmp = `${REQUESTS_FILE}.tmp`;
    fs.writeFileSync(tmp, JSON.stringify(requests));
    if (fs.existsSync(REQUESTS_FILE)) fs.copyFileSync(REQUESTS_FILE, `${REQUESTS_FILE}.bak`);
    fs.renameSync(tmp, REQUESTS_FILE);
  } catch (e) {
    console.error('could not save listing requests:', e.message);
  }
}
function addRequest(form) {
  const now = Math.floor(Date.now() / 1000);
  const data = Object.fromEntries(REQUEST_FIELDS.map((k) => [k, str(form[k], 2000)]));
  data.symbol = data.symbol.toUpperCase();
  const r = { id: requests.next++, created: now, updated: now, status: 'new', data, note: '' };
  requests.requests.unshift(r);
  saveRequests();
  return r.id;
}
function isAdmin(req) {
  const want = process.env.MINTRO_ADMIN_TOKEN || '';
  const given = String(req.headers.authorization || '').replace(/^Bearer\s+/i, '');
  if (!want || !given) return false;
  const a = crypto.createHash('sha256').update(given).digest(), b = crypto.createHash('sha256').update(want).digest();
  return crypto.timingSafeEqual(a, b);
}

/* ---------- downloads: served here so they can be counted ---------- */

const DL_DIR = path.join(SITE_DIR, 'download');
const TYPES = { '.html': 'text/html; charset=utf-8', '.css': 'text/css', '.js': 'text/javascript', '.svg': 'image/svg+xml',
  '.png': 'image/png', '.webmanifest': 'application/manifest+json', '.xml': 'application/xml', '.txt': 'text/plain',
  '.json': 'application/json', '.sig': 'application/json', '.exe': 'application/octet-stream', '.zip': 'application/zip' };
const recentDownloads = new Map(); // "<ip>|<file>" -> time: a repeat within 10 minutes counts once
setInterval(() => { const now = Date.now(); for (const [k, t] of recentDownloads) if (now - t > 10 * 60e3) recentDownloads.delete(k); }, 60e3).unref();

const version = (f) => (/-(\d+(?:\.\d+)*)\.\w+$/.exec(f) || [, '0'])[1].split('.').map(Number);
const newer = (a, b) => { const x = version(a), y = version(b); for (let i = 0; i < Math.max(x.length, y.length); i++) if ((x[i] || 0) !== (y[i] || 0)) return (x[i] || 0) > (y[i] || 0); return false; };
function newestInstaller() {
  try { return fs.readdirSync(DL_DIR).filter((f) => /^MINTRO-Setup-[\d.]+\.exe$/.test(f)).reduce((a, f) => (!a || newer(f, a) ? f : a), ''); }
  catch { return ''; }
}

function serveDownload(req, res, pathname) {
  const name = decodeURIComponent(pathname.slice('/download/'.length)).replace(/\/$/, '');
  if (name === 'latest') {
    const file = newestInstaller();
    if (!file) return plain(res, 404, 'No installer here yet.');
    res.writeHead(302, { Location: `/download/${file}`, 'Cache-Control': 'no-store' });
    return res.end();
  }
  if (!/^[\w.-]+$/.test(name)) return plain(res, 404, 'Not found');
  const file = path.join(DL_DIR, name);
  fs.stat(file, (err, st) => {
    if (err || !st.isFile()) return plain(res, 404, 'Not found');
    let start = 0, end = st.size - 1, status = 200;
    const m = /^bytes=(\d*)-(\d*)$/.exec(req.headers.range || '');
    if (m && (m[1] || m[2])) {
      if (m[1]) { start = Number(m[1]); if (m[2]) end = Math.min(Number(m[2]), end); }
      else start = Math.max(0, st.size - Number(m[2]));
      if (start > end) { res.writeHead(416, { 'Content-Range': `bytes */${st.size}` }); return res.end(); }
      status = 206;
    }
    const ext = path.extname(name);
    res.writeHead(status, {
      'Content-Type': TYPES[ext] || 'application/octet-stream',
      'Content-Length': end - start + 1,
      'Accept-Ranges': 'bytes',
      'Last-Modified': st.mtime.toUTCString(),
      'Cache-Control': ext === '.json' || ext === '.sig' ? 'no-cache' : 'public, max-age=3600',
      ...(ext === '.exe' || ext === '.zip' ? { 'Content-Disposition': `attachment; filename="${name}"` } : {}),
      ...(status === 206 ? { 'Content-Range': `bytes ${start}-${end}/${st.size}` } : {}),
    });
    if (req.method === 'HEAD') return res.end();
    // Count a download when it starts (not each resumed piece), once per connection per file per 10 minutes.
    const kind = /^MINTRO-Setup-.*\.exe$/.test(name) ? 'downloads' : /^MINTRO-Update-.*\.zip$/.test(name) ? 'updates' : '';
    if (kind && start === 0 && !BOTS.test(req.headers['user-agent'] || '')) {
      const key = `${clientIp(req)}|${name}`;
      if (!recentDownloads.has(key)) { recentDownloads.set(key, Date.now()); count({ [kind]: 1 }); }
    }
    fs.createReadStream(file, { start, end }).pipe(res);
  });
}

function servePage(req, res, pathname) {
  const rel = decodeURIComponent(pathname).replace(/\/$/, '/index.html');
  const file = path.join(SITE_DIR, path.normalize(rel).replace(/^([/\\])+/, ''));
  const inside = file.startsWith(SITE_DIR + path.sep);
  fs.readFile(inside ? file : '', (err, data) => {
    if (err) return fs.readFile(path.join(SITE_DIR, '404.html'), (_, page) => { res.writeHead(404, { 'Content-Type': TYPES['.html'] }); res.end(page || 'Not found'); });
    res.writeHead(200, { 'Content-Type': TYPES[path.extname(file)] || 'application/octet-stream' });
    res.end(data);
  });
}

/* ---------- email ---------- */

async function sendRaw({ to, subject, html, text, replyTo }) {
  const key = process.env.RESEND_API_KEY;
  if (!key) return { ok: false, status: 503, error: `Email isn't configured on the server yet. ${WRITE_US}` };
  try {
    const res = await fetch(RESEND, {
      method: 'POST',
      headers: { Authorization: `Bearer ${key}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ from: FROM, to, subject: oneLine(subject), html, text, ...(replyTo ? { reply_to: replyTo } : {}) }),
    });
    if (!res.ok) return { ok: false, status: 502, error: `Sending failed (${res.status}). ${WRITE_US}` };
    return { ok: true };
  } catch {
    return { ok: false, status: 502, error: `A network error stopped the message. Please try again, or write to hello@aiteleresearch.com.` };
  }
}

// The team's copy: every field, and Reply-To set to the sender so a reply goes straight to them.
function teamMail({ heading, rows, message, replyName }) {
  const text = `${heading}\n\n${rows.map(([k, v]) => `${k}: ${v}`).join('\n')}${message ? `\n\nMessage:\n${message}` : ''}\n\n— sent from ${SITE_URL}`;
  const html = `<h2 style="font-family:system-ui,sans-serif;margin:0 0 12px">${esc(heading)}</h2>`
    + `<table style="font-family:system-ui,sans-serif;font-size:14px;border-collapse:collapse">`
    + rows.map(([k, v]) => `<tr><td style="padding:4px 14px 4px 0;color:#667;vertical-align:top"><strong>${esc(k)}</strong></td><td style="padding:4px 0">${esc(v)}</td></tr>`).join('')
    + `</table>${message ? `<p style="font-family:system-ui,sans-serif;font-size:14px;white-space:pre-wrap"><strong>Message</strong><br>${esc(message)}</p>` : ''}`
    + `<p style="font-family:system-ui,sans-serif;font-size:12px;color:#889">Sent from ${esc(SITE_URL)}. Reply to this email to reach ${esc(replyName)} directly.</p>`;
  return { html, text };
}

const FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif";
const SOCIAL = [
  ['LinkedIn', 'https://www.linkedin.com/company/aitele'], ['X', 'https://x.com/aiteleresearch'],
  ['Instagram', 'https://www.instagram.com/aiteleresearch/'], ['YouTube', 'https://www.youtube.com/@aiteleresearch'],
  ['WhatsApp', 'https://whatsapp.com/channel/0029VbCJPIf545uoE8NYVb2C'],
];

// The sender's acknowledgement: the same branded, responsive email the other ventures send, in MINTRO's mint.
function ackMail({ kicker, title, body, echo }) {
  const echoHtml = echo
    ? `<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:20px 0 4px"><tr><td style="background:#f6f6f7;border:1px solid #ececef;border-radius:12px;padding:15px 17px;font:14px/1.7 ${FONT};color:#52525b;white-space:pre-wrap">${esc(echo)}</td></tr></table>`
    : '';
  const social = SOCIAL.map(([n, u]) => `<a href="${u}" style="color:${BRAND.accentDeep};text-decoration:none;font:600 11px/1 ${FONT};letter-spacing:.04em">${n}</a>`)
    .join(`<span style="color:#d4d4d8">&nbsp;·&nbsp;</span>`);
  const html = `<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light">
<title>${esc(title)}</title>
<style>@media only screen and (max-width:540px){.card{width:100%!important}.px{padding-left:22px!important;padding-right:22px!important}}</style>
</head>
<body style="margin:0;padding:0;background:#eef0f2">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;color:transparent">${esc(body)}&#8203;&zwnj;&nbsp;&zwnj;&nbsp;</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#eef0f2"><tr><td align="center" style="padding:30px 16px">
  <table role="presentation" class="card" width="520" cellpadding="0" cellspacing="0" style="width:520px;max-width:520px;background:#ffffff;border-radius:18px;overflow:hidden;box-shadow:0 2px 10px rgba(15,16,21,0.07)">
    <tr><td style="background:#050607;padding:22px 30px">
      <span style="font:700 18px ${FONT};letter-spacing:.24em;color:${BRAND.accent};vertical-align:middle">${BRAND.name}</span>
      <span style="font:600 11px ${FONT};letter-spacing:.12em;text-transform:uppercase;color:rgba(255,255,255,0.6);margin-left:10px;vertical-align:middle">a venture of Aitele Research</span>
    </td></tr>
    <tr><td class="px" style="padding:32px 30px 6px">
      <div style="font:700 11px ${FONT};letter-spacing:.16em;text-transform:uppercase;color:${BRAND.accentDeep};margin:0 0 12px">${esc(kicker)}</div>
      <h1 style="margin:0;font:600 23px/1.3 ${FONT};color:#18181b">${esc(title)}</h1>
      <p style="margin:15px 0 0;font:15px/1.75 ${FONT};color:#52525b">${esc(body)}</p>
      ${echoHtml}
      <p style="margin:18px 0 0;font:15px/1.75 ${FONT};color:#52525b">If you have anything to add, just reply to this email.</p>
    </td></tr>
    <tr><td class="px" style="padding:24px 30px 30px">
      <div style="border-top:1px solid #ececef;margin-top:8px;padding-top:16px;font:12px/1.7 ${FONT};color:#a1a1aa">
        ${BRAND.name} &mdash; a venture of <a href="https://aiteleresearch.com" style="color:${BRAND.accentDeep};text-decoration:none">Aitele Research</a>.<br>
        This is an automated confirmation; a human will follow up personally.
      </div>
      <div style="margin:16px 0 0">${social}</div>
    </td></tr>
  </table>
</td></tr></table>
</body></html>`;
  const text = `${title}\n\n${body}${echo ? `\n\n${echo}` : ''}\n\nIf you have anything to add, just reply to this email.\n\n${BRAND.name} — a venture of Aitele Research`;
  return { html, text };
}

async function contact(d) {
  const name = str(d.name, 80), email = str(d.email, 120), message = str(d.message, 4000);
  const topic = TOPICS.includes(str(d.topic, 60)) ? str(d.topic, 60) : TOPICS[0];
  if (!name) return { status: 400, error: 'Please fill in your name.' };
  if (!isEmail(email)) return { status: 400, error: 'Please check your email address.' };
  if (!message) return { status: 400, error: 'Please write a message.' };

  const team = teamMail({ heading: 'New message from the MINTRO website', rows: [['Topic', topic], ['Name', name], ['Email', email]], message, replyName: name });
  const sent = await sendRaw({ to: INBOX, subject: `MINTRO · ${topic} — ${name}`, replyTo: email, ...team });
  if (!sent.ok) return sent;
  const first = name.split(/\s+/)[0];
  await sendRaw({ to: email, subject: `We received your message — ${BRAND.name}`, ...ackMail({
    kicker: 'Message received', title: `Thanks, ${first} — we've got it.`, echo: message,
    body: `Your message has reached the ${BRAND.name} team at Aitele Research, and a person will get back to you at this address soon.`,
  }) }).catch(() => undefined); // the acknowledgement is best-effort
  return { status: 200, ok: true };
}

async function listing(d) {
  const f = {
    project: str(d.project, 80), symbol: str(d.symbol, 10).toUpperCase(), algorithm: str(d.algorithm, 30),
    plan: PLANS[str(d.plan, 20)] || PLANS.standard, source: str(d.source, 20) === 'custom' ? 'Their own pool' : 'The rplant pool',
    pool: str(d.source, 20) === 'custom' ? `${str(d.pool_host, 120)}:${str(d.pool_port, 6)}${str(d.pool_tls, 5) === 'false' ? '' : ' (TLS)'}` : '',
    site: str(d.site, 200), explorer: str(d.explorer, 200), wallet: str(d.wallet, 200),
    email: str(d.email, 120), telegram: str(d.telegram, 60), message: str(d.message, 1500),
  };
  if (!f.project || !f.symbol) return { status: 400, error: 'Please fill in the project and its ticker.' };
  if (!isUrl(f.site)) return { status: 400, error: 'Please give the project website as a full https:// address.' };
  if (!isEmail(f.email)) return { status: 400, error: 'Please check the email address.' };
  for (const k of ['explorer', 'wallet']) if (f[k] && !isUrl(f[k])) return { status: 400, error: `Please give the ${k === 'wallet' ? 'wallet download' : 'explorer'} as a full https:// address.` };

  const id = addRequest(d); // kept for the admin dashboard even if the email can't go out
  const rows = [['Request', `#${id}`], ['Project', `${f.project} (${f.symbol})`], ['Plan', f.plan], ['Algorithm', f.algorithm || '—'],
    ['Mined on', f.source + (f.pool ? ` — ${f.pool}` : '')], ['Website', f.site], ['Explorer', f.explorer || '—'],
    ['Wallet download', f.wallet || '—'], ['Email', f.email], ['Telegram', f.telegram || '—']];
  const team = teamMail({ heading: 'New listing request from the MINTRO website', rows, message: f.message, replyName: f.project });
  const sent = await sendRaw({ to: INBOX, subject: `MINTRO listing request · ${f.project} (${f.symbol}) · ${f.plan}`, replyTo: f.email, ...team });
  if (!sent.ok) return sent;
  await sendRaw({ to: f.email, subject: `We received your listing request — ${BRAND.name}`, ...ackMail({
    kicker: `Listing request #${id}`, title: `Thanks — ${f.project} is in the queue.`,
    body: `We check every coin and pool before listing, and reply within two business days. A listed coin is always labelled in MINTRO, and is scored like any other.`,
  }) }).catch(() => undefined);
  return { status: 200, ok: true, id };
}

/* ---------- server ---------- */

function send(res, status, body, origin, extra = {}) {
  res.writeHead(status, {
    'Content-Type': 'application/json',
    'Cache-Control': 'no-store',
    ...(origin ? { 'Access-Control-Allow-Origin': origin, Vary: 'Origin' } : {}),
    ...extra,
  });
  res.end(JSON.stringify(body));
}
const plain = (res, status, text) => { res.writeHead(status, { 'Content-Type': 'text/plain; charset=utf-8' }); res.end(text); };

function readJson(req, cb) {
  let size = 0;
  const chunks = [];
  req.on('data', (c) => { size += c.length; if (size > 32e3) req.destroy(); else chunks.push(c); });
  req.on('end', () => {
    let d;
    try { d = JSON.parse(Buffer.concat(chunks).toString('utf8') || '{}'); } catch { d = null; }
    cb(d && typeof d === 'object' ? d : null);
  });
}

const server = http.createServer((req, res) => {
  const url = new URL(req.url, 'http://x');
  const origin = req.headers.origin;
  // The site's own pages (whatever host serves them: mintra, or localhost in a preview), plus the allowed origins.
  const sameHost = (() => { try { return !!origin && new URL(origin).host === req.headers.host; } catch { return false; } })();
  const allowed = origin && (ORIGINS.has(origin) || sameHost) ? origin : '';

  if ((req.method === 'GET' || req.method === 'HEAD') && url.pathname.startsWith('/download/')) return serveDownload(req, res, url.pathname);
  if (url.pathname.startsWith('/v1/admin/')) {
    if (!isAdmin(req)) return send(res, 401, { error: 'unauthorized' });
    if (req.method === 'GET' && url.pathname === '/v1/admin/requests') return send(res, 200, { requests: requests.requests.slice(0, 500) });
    const m = /^\/v1\/admin\/requests\/(\d+)$/.exec(url.pathname);
    if (req.method === 'POST' && m) {
      return readJson(req, (d) => {
        if (!d || !REQUEST_STATUSES.includes(d.status)) return send(res, 400, { error: `status must be one of ${REQUEST_STATUSES.join(', ')}` });
        const r = requests.requests.find((x) => x.id === Number(m[1]));
        if (!r) return send(res, 404, { error: 'No such request' });
        Object.assign(r, { status: d.status, note: str(d.note, 2000), updated: Math.floor(Date.now() / 1000) });
        saveRequests();
        send(res, 200, { ok: true });
      });
    }
    return send(res, 404, { error: 'Not found' });
  }
  if (!url.pathname.startsWith('/api/')) {
    if (SERVE_PAGES && req.method === 'GET') return servePage(req, res, url.pathname);
    return send(res, req.method === 'GET' ? 200 : 404, req.method === 'GET' ? { ok: true, service: 'mintro-site' } : { error: 'Not found' });
  }
  if (req.method === 'OPTIONS') {
    if (!allowed) return send(res, 403, { error: 'Origin not allowed' });
    res.writeHead(204, { 'Access-Control-Allow-Origin': allowed, 'Access-Control-Allow-Methods': 'GET, POST', 'Access-Control-Allow-Headers': 'Content-Type', 'Access-Control-Max-Age': '86400', Vary: 'Origin' });
    return res.end();
  }
  if (req.method === 'GET' && url.pathname === '/api/health') return send(res, 200, { ok: true, email: !!process.env.RESEND_API_KEY }, allowed);
  if (req.method === 'GET' && url.pathname === '/api/stats') return send(res, 200, statsView(), allowed, { 'Cache-Control': 'public, max-age=30' });

  if (req.method === 'POST' && url.pathname === '/api/visit') {
    if (origin && !allowed) return send(res, 403, { error: 'Origin not allowed' });
    return readJson(req, (d) => {
      const ip = clientIp(req);
      if (d && !BOTS.test(req.headers['user-agent'] || '') && !visitLimit(ip)) {
        count({ views: 1, visitors: d.today === true ? 1 : 0, newVisitors: d.new === true ? 1 : 0 });
      }
      res.writeHead(204, allowed ? { 'Access-Control-Allow-Origin': allowed, Vary: 'Origin' } : {});
      res.end();
    });
  }

  const handler = { '/api/contact': contact, '/api/listing': listing }[url.pathname];
  if (req.method !== 'POST' || !handler) return send(res, 404, { error: 'Not found' }, allowed);
  if (origin && !allowed) return send(res, 403, { error: 'This form can only be sent from the MINTRO website.' });
  readJson(req, async (d) => {
    if (!d) return send(res, 400, { error: 'The form data was unreadable.' }, allowed);
    if (str(d.website_url, 200)) return send(res, 200, { ok: true }, allowed); // the hidden honeypot field: a bot
    const wait = formLimit(clientIp(req));
    if (wait) return send(res, 429, { error: `Too many messages from your connection — please wait about ${wait} minute${wait === 1 ? '' : 's'} and try again.` }, allowed);
    try {
      const { status, ...body } = await handler(d);
      console.log(`${new Date().toISOString()} ${url.pathname} ${status}`);
      send(res, status, body, allowed);
    } catch (e) {
      console.error(`${url.pathname} failed:`, e && e.message);
      send(res, 500, { error: `Something went wrong on our side. ${WRITE_US}` }, allowed);
    }
  });
});

server.listen(PORT, SERVE_PAGES ? undefined : '127.0.0.1', () => {
  console.log(`MINTRO site server on :${PORT}${SERVE_PAGES ? ' (serving the pages too)' : ''} — email ${process.env.RESEND_API_KEY ? 'on' : 'OFF (no RESEND_API_KEY)'}; counting since ${stats.since} in ${DATA_DIR}`);
});
