-- MINTRO backend (Cloudflare D1): miner counter and coin listing requests. Apply with:
--   wrangler d1 execute mintro-stats --remote --file server/stats/schema.sql

-- One row per install: a random ID from the app, when it was last heard from, and whether it was mining
CREATE TABLE IF NOT EXISTS installs (
  id          TEXT PRIMARY KEY,
  first_seen  INTEGER NOT NULL,
  last_seen   INTEGER NOT NULL,
  mining      INTEGER NOT NULL DEFAULT 0,
  last_mining INTEGER NOT NULL DEFAULT 0,
  version     TEXT
);
CREATE INDEX IF NOT EXISTS installs_last_seen ON installs (last_seen);

-- New installs per (salted, daily-changing) IP hash: caps how fast one machine can add installs
CREATE TABLE IF NOT EXISTS new_ids (
  iph TEXT NOT NULL,
  day TEXT NOT NULL,
  n   INTEGER NOT NULL,
  PRIMARY KEY (iph, day)
);

-- Daily public record (also snapshotted into the GitHub repo by .github/workflows/stats-snapshot.yml)
CREATE TABLE IF NOT EXISTS daily (
  day         TEXT PRIMARY KEY,
  peak_mining INTEGER,
  mined_24h   INTEGER,
  installs    INTEGER,
  downloads   INTEGER
);

-- Coin listing requests from the website's "List your coin" form
CREATE TABLE IF NOT EXISTS listing_requests (
  id      INTEGER PRIMARY KEY AUTOINCREMENT,
  created INTEGER NOT NULL,
  updated INTEGER NOT NULL,
  status  TEXT NOT NULL DEFAULT 'new',   -- new, reviewing, awaiting_payment, listed, rejected
  data    TEXT NOT NULL,                 -- the form, as JSON
  note    TEXT NOT NULL DEFAULT ''       -- the admin's notes
);

CREATE TABLE IF NOT EXISTS request_limits (
  iph TEXT NOT NULL,
  day TEXT NOT NULL,
  n   INTEGER NOT NULL,
  PRIMARY KEY (iph, day)
);
