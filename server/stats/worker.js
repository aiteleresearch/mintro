/* MINTRO's small backend: a Cloudflare Worker with a D1 (SQLite) database. See docs/STATS.md and docs/LISTINGS.md.

   POST /v1/ping                 from the app: {id, v, mining, lanes}. id is a random install ID, nothing personal.
   GET  /v1/stats                public: miners mining now, mined in the last 24 h, active in 30 days, installs, downloads
   GET  /v1/history              public: one row per day (peak miners, installs, downloads), last 365 days
   POST /v1/listing-request      public: a coin project asks to be listed (the website's form)
   GET  /v1/admin/requests       admin (Bearer ADMIN_TOKEN): the listing requests
   POST /v1/admin/requests/:id   admin: {status, note} to move a request along

   Counting rules, so the numbers mean something:
   - "Mining now" = installs whose latest heartbeat (sent every 10 min) said they're mining, within 20 min.
   - Downloads = GitHub's own download counts for the MINTRO-Setup-*.exe installers, all releases (update
     packages that installed copies fetch are not counted).
   - One IP address can add at most NEW_IDS_PER_IP_PER_DAY new installs a day, so a script can't pad the count.
     The IP is only used as a salted hash that changes every day, and never stored as-is. */

const ACTIVE_S = 20 * 60;
const NEW_IDS_PER_IP_PER_DAY = 5;
const REQUESTS_PER_IP_PER_DAY = 5;
const REQUEST_STATUSES = ['new', 'reviewing', 'awaiting_payment', 'listed', 'rejected'];

export default {
  async fetch(req, env, ctx) {
    const url = new URL(req.url);
    if (req.method === 'OPTIONS') return cors(new Response(null, { status: 204 }));
    try {
      if (req.method === 'POST' && url.pathname === '/v1/ping') return cors(await ping(req, env));
      if (req.method === 'GET' && url.pathname === '/v1/stats') return cors(json(await stats(env, ctx), 200, 60));
      if (req.method === 'GET' && url.pathname === '/v1/history') return cors(json(await history(env), 200, 300));
      if (req.method === 'POST' && url.pathname === '/v1/listing-request') return cors(await listingRequest(req, env));
      if (url.pathname.startsWith('/v1/admin/')) {
        if (!(await isAdmin(req, env))) return json({ error: 'not allowed' }, 401);
        if (req.method === 'GET' && url.pathname === '/v1/admin/requests') return json(await listRequests(env));
        const m = url.pathname.match(/^\/v1\/admin\/requests\/(\d+)$/);
        if (req.method === 'POST' && m) return json(await updateRequest(req, env, Number(m[1])));
      }
      return cors(json({ error: 'not found' }, 404));
    } catch (err) {
      console.error(err);
      return cors(json({ error: 'server error' }, 500));
    }
  },

  // Hourly: keep each day's peak and tidy the per-IP limits
  async scheduled(_event, env, ctx) {
    const s = await stats(env, ctx);
    const day = new Date().toISOString().slice(0, 10);
    await env.DB.batch([
      env.DB.prepare(`INSERT INTO daily (day, peak_mining, mined_24h, installs, downloads) VALUES (?1, ?2, ?3, ?4, ?5)
                      ON CONFLICT(day) DO UPDATE SET peak_mining = MAX(peak_mining, ?2), mined_24h = MAX(mined_24h, ?3),
                      installs = ?4, downloads = COALESCE(?5, downloads)`)
        .bind(day, s.mining_now, s.mined_24h, s.installs, s.downloads),
      env.DB.prepare(`DELETE FROM new_ids WHERE day < ?1`).bind(new Date(Date.now() - 2 * 86400e3).toISOString().slice(0, 10)),
      env.DB.prepare(`DELETE FROM request_limits WHERE day < ?1`).bind(new Date(Date.now() - 2 * 86400e3).toISOString().slice(0, 10)),
    ]);
  },
};

async function ping(req, env) {
  const body = await req.json().catch(() => null);
  if (!body || typeof body.id !== 'string' || !/^[0-9a-f]{32}$/.test(body.id)) return json({ error: 'bad ping' }, 400);
  const now = Math.floor(Date.now() / 1000);
  const mining = body.mining === true ? 1 : 0;
  const version = String(body.v || '').slice(0, 16);
  const known = await env.DB.prepare('SELECT id FROM installs WHERE id = ?1').bind(body.id).first();
  if (!known) {
    const day = new Date().toISOString().slice(0, 10);
    const iph = await sha256(`${env.SALT || ''}|${day}|${req.headers.get('CF-Connecting-IP') || ''}`);
    const seen = await env.DB.prepare('SELECT n FROM new_ids WHERE iph = ?1 AND day = ?2').bind(iph, day).first();
    if (seen && seen.n >= NEW_IDS_PER_IP_PER_DAY) return json({ ok: true, counted: false }, 202);
    await env.DB.batch([
      env.DB.prepare(`INSERT INTO new_ids (iph, day, n) VALUES (?1, ?2, 1) ON CONFLICT(iph, day) DO UPDATE SET n = n + 1`)
        .bind(iph, day),
      env.DB.prepare(`INSERT INTO installs (id, first_seen, last_seen, mining, last_mining, version) VALUES (?1, ?2, ?2, ?3, ?4, ?5)`)
        .bind(body.id, now, mining, mining ? now : 0, version),
    ]);
  } else {
    await env.DB.prepare(`UPDATE installs SET last_seen = ?2, mining = ?3, version = ?4,
                          last_mining = CASE WHEN ?3 = 1 THEN ?2 ELSE last_mining END WHERE id = ?1`)
      .bind(body.id, now, mining, version).run();
  }
  return json({ ok: true, counted: true });
}

// ---- coin listing requests ----------------------------------------------------------------------------

const FIELDS = {  // field: [max length, required]
  project: [80, true], symbol: [10, true], algorithm: [30, true], source: [10, true], plan: [10, true],
  pool_host: [120, false], pool_port: [6, false], pool_tls: [5, false], site: [200, true], explorer: [200, false],
  wallet: [200, false], email: [120, true], telegram: [60, false], message: [1500, false],
};

async function listingRequest(req, env) {
  const body = await req.json().catch(() => null);
  if (!body || typeof body !== 'object') return json({ error: 'Send the form as JSON.' }, 400);
  if (body.website_url) return json({ ok: true });  // honeypot field: bots fill it, people never see it
  const data = {};
  for (const [field, [max, required]] of Object.entries(FIELDS)) {
    const value = String(body[field] ?? '').trim();
    if (required && !value) return json({ error: `Please fill in ${field.replace('_', ' ')}.` }, 400);
    if (value.length > max) return json({ error: `${field.replace('_', ' ')} is too long.` }, 400);
    data[field] = value;
  }
  data.symbol = data.symbol.toUpperCase();
  if (!/^[A-Z0-9]{2,10}$/.test(data.symbol)) return json({ error: 'The ticker should be 2-10 letters or digits.' }, 400);
  if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(data.email)) return json({ error: 'That email address doesn\'t look right.' }, 400);
  for (const link of ['site', 'explorer', 'wallet']) {
    if (data[link] && !data[link].startsWith('https://')) return json({ error: `The ${link} link must start with https://` }, 400);
  }
  if (!['standard', 'featured', 'promo'].includes(data.plan)) return json({ error: 'Pick a listing plan.' }, 400);
  if (!['rplant', 'custom'].includes(data.source)) return json({ error: 'Say where the coin is mined.' }, 400);

  const day = new Date().toISOString().slice(0, 10);
  const iph = await sha256(`${env.SALT || ''}|req|${day}|${req.headers.get('CF-Connecting-IP') || ''}`);
  const seen = await env.DB.prepare('SELECT n FROM request_limits WHERE iph = ?1 AND day = ?2').bind(iph, day).first();
  if (seen && seen.n >= REQUESTS_PER_IP_PER_DAY) return json({ error: 'Too many requests today. Email us instead.' }, 429);
  const now = Math.floor(Date.now() / 1000);
  const [, inserted] = await env.DB.batch([
    env.DB.prepare(`INSERT INTO request_limits (iph, day, n) VALUES (?1, ?2, 1) ON CONFLICT(iph, day) DO UPDATE SET n = n + 1`)
      .bind(iph, day),
    env.DB.prepare(`INSERT INTO listing_requests (created, updated, status, data, note) VALUES (?1, ?1, 'new', ?2, '') RETURNING id`)
      .bind(now, JSON.stringify(data)),
  ]);
  return json({ ok: true, id: inserted.results[0].id });
}

async function listRequests(env) {
  const { results } = await env.DB.prepare(
    'SELECT id, created, updated, status, data, note FROM listing_requests ORDER BY id DESC LIMIT 500').all();
  return { requests: results.map((r) => ({ ...r, data: JSON.parse(r.data) })) };
}

async function updateRequest(req, env, id) {
  const body = await req.json().catch(() => ({}));
  if (!REQUEST_STATUSES.includes(body.status)) return { error: `status must be one of ${REQUEST_STATUSES.join(', ')}` };
  await env.DB.prepare('UPDATE listing_requests SET status = ?2, note = ?3, updated = ?4 WHERE id = ?1')
    .bind(id, body.status, String(body.note || '').slice(0, 2000), Math.floor(Date.now() / 1000)).run();
  return { ok: true };
}

async function isAdmin(req, env) {
  const given = (req.headers.get('Authorization') || '').replace(/^Bearer\s+/i, '');
  if (!env.ADMIN_TOKEN || !given) return false;
  const [a, b] = await Promise.all([sha256(given), sha256(env.ADMIN_TOKEN)]);  // equal-length, so a fair comparison
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

// ---- counters --------------------------------------------------------------------------------------------

async function stats(env, ctx) {
  const now = Math.floor(Date.now() / 1000);
  const r = await env.DB.prepare(`SELECT
      COALESCE(SUM(CASE WHEN mining = 1 AND last_seen > ?1 THEN 1 ELSE 0 END), 0) AS mining_now,
      COALESCE(SUM(CASE WHEN last_mining > ?2 THEN 1 ELSE 0 END), 0) AS mined_24h,
      COALESCE(SUM(CASE WHEN last_seen > ?3 THEN 1 ELSE 0 END), 0) AS active_30d,
      COUNT(*) AS installs
    FROM installs`).bind(now - ACTIVE_S, now - 86400, now - 30 * 86400).first();
  return {
    mining_now: r.mining_now, mined_24h: r.mined_24h, active_30d: r.active_30d, installs: r.installs,
    downloads: await downloads(env, ctx), repo: env.GITHUB_REPO || null,
    rules: { mining_now_window_minutes: ACTIVE_S / 60, new_installs_per_ip_per_day: NEW_IDS_PER_IP_PER_DAY,
             downloads: 'GitHub download_count of MINTRO-Setup-*.exe assets, all releases' },
    updated: new Date().toISOString(),
  };
}

async function history(env) {
  const { results } = await env.DB.prepare(
    'SELECT day, peak_mining, mined_24h, installs, downloads FROM daily ORDER BY day DESC LIMIT 365').all();
  return { days: results.reverse() };
}

// GitHub's own count of installer downloads, cached for 10 minutes
async function downloads(env, ctx) {
  if (!env.GITHUB_REPO) return null;
  const key = new Request(`https://cache.mintro.invalid/downloads/${env.GITHUB_REPO}`);
  const hit = await caches.default.match(key);
  if (hit) return (await hit.json()).downloads;
  const headers = { 'User-Agent': 'mintro-stats', Accept: 'application/vnd.github+json' };
  if (env.GITHUB_TOKEN) headers.Authorization = `Bearer ${env.GITHUB_TOKEN}`;
  let total = 0;
  for (let page = 1; page <= 10; page++) {
    const r = await fetch(`https://api.github.com/repos/${env.GITHUB_REPO}/releases?per_page=100&page=${page}`, { headers });
    if (!r.ok) return null;
    const releases = await r.json();
    for (const rel of releases) {
      for (const a of rel.assets || []) if (/^MINTRO-Setup-.*\.exe$/.test(a.name)) total += a.download_count;
    }
    if (releases.length < 100) break;
  }
  ctx.waitUntil(caches.default.put(key, new Response(JSON.stringify({ downloads: total }),
    { headers: { 'Cache-Control': 'max-age=600' } })));
  return total;
}

function json(body, status = 200, maxAge = 0) {
  return new Response(JSON.stringify(body), {
    status, headers: { 'Content-Type': 'application/json', 'Cache-Control': maxAge ? `public, max-age=${maxAge}` : 'no-store' },
  });
}

function cors(res) {
  res.headers.set('Access-Control-Allow-Origin', '*');  // public endpoints only: admin ones aren't wrapped
  res.headers.set('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.headers.set('Access-Control-Allow-Headers', 'Content-Type');
  return res;
}

async function sha256(text) {
  const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, '0')).join('');
}
