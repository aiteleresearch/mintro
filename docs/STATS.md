# The stats service: public counters and listing requests

`server/stats` is a small Cloudflare Worker with a D1 (SQLite) database. It does three things:

1. counts MINTRO PCs that are mining, from anonymous heartbeats;
2. serves those numbers (plus GitHub's download count) to the website's **Open numbers** section;
3. receives listing requests from the website's form, for the admin tool (docs/LISTINGS.md).

It runs on Cloudflare's free tier for a long while: each mining PC sends one heartbeat every 10 minutes.

## What is counted, exactly

| Number | Meaning | Source |
|---|---|---|
| Mining right now | installs whose latest heartbeat (every 10 min) said "mining", in the last 20 min | heartbeats |
| Mined in the last 24 h | installs that reported mining at any point in the last 24 hours | heartbeats |
| Active in 30 days | installs heard from in the last 30 days | heartbeats |
| Installs | every install that has ever checked in, each counted once (an update keeps the same ID) | heartbeats |
| Downloads | GitHub's own `download_count` for the `MINTRO-Setup-*.exe` installers across all releases; update packages fetched by installed copies are not counted | GitHub API |

A heartbeat is exactly `{"id": "<random 32-hex install ID>", "v": "<version>", "mining": true|false, "lanes": [...]}`.
No wallet, no name, no hardware. The IP address is only used, as a salted hash that changes daily, to stop
one machine adding more than 5 new installs a day; it is never stored as-is. People switch heartbeats off in
the app (Settings > "Count me in the public miner counter").

**How anyone can verify it**
- Downloads: the website links to `api.github.com/repos/aiteleresearch/mintro/releases`, GitHub's raw data.
- Live numbers: the website links to `/v1/stats` and `/v1/history`, the service's raw JSON.
- History: `.github/workflows/stats-snapshot.yml` records the numbers once a day into `stats/history.csv`
  in the repository. Each row is a commit by GitHub Actions, so the history can't be quietly rewritten.
- Method: this page and the worker's source (`server/stats/worker.js`) are public.

Be honest about the limits too: heartbeats come from the app, so they show how many copies are running, not
proof of hashrate. The pool's own pages (rplant shows miners per coin) are an independent cross-check.

## Deploy (about 15 minutes, once)

You need a free Cloudflare account and Node.js.

```
npm install -g wrangler
wrangler login
cd server\stats
wrangler d1 create mintro-stats
```

Paste the `database_id` it prints into `wrangler.toml`, and set `GITHUB_REPO` there to your repository. Then:

```
wrangler d1 execute mintro-stats --remote --file schema.sql
wrangler secret put SALT          # any long random string
wrangler secret put ADMIN_TOKEN   # another long random string; the admin tool uses it
wrangler deploy
```

`wrangler deploy` prints the service URL (e.g. `https://mintro-stats.you.workers.dev`). Put it in:

1. `mintro/config.py`: `STATS_URL` (the app's heartbeats), then build a release;
2. `docs/assets/ui.js`: `SITE.stats` (the website's numbers and form);
3. GitHub: Settings > Secrets and variables > Actions > Variables > `STATS_URL` (the daily snapshot);
4. the admin tool's Settings, with the admin token.

Optional: `wrangler secret put GITHUB_TOKEN` (a read-only token) raises GitHub's API limit for the download count.

## Endpoints

| | |
|---|---|
| `POST /v1/ping` | heartbeat from the app |
| `GET /v1/stats` | the live numbers (public, cached 60 s) |
| `GET /v1/history` | one row per day: peak miners, mined in 24 h, installs, downloads (public) |
| `POST /v1/listing-request` | the website's listing form (public, rate-limited) |
| `GET /v1/admin/requests` | listing requests (needs `Authorization: Bearer ADMIN_TOKEN`) |
| `POST /v1/admin/requests/:id` | `{status, note}` (admin) |
