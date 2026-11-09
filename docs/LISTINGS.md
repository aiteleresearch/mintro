# Coin listings: MINTRO's revenue

MINTRO is free for everyone who mines: every feature, no fee. It's paid for by coin projects that list their
coins. A listed coin reaches every MINTRO PC without the project shipping anything, and without you shipping
an app update.

## What a project buys

| Plan | What it gets | Label in the app |
|---|---|---|
| **Listed** | In every MINTRO's coin catalog, with its pitch and links, on the rplant pool or its own pool. Scored like every other coin: a listing buys a place, not a better score. | "Listed" |
| **Featured** | Everything in Listed, plus a guaranteed share of each basket's mining time (you set it, 10% at most). Featured coins are placed in the basket first. | "Featured", with the share |
| **Promo** | For coins MINTRO can't mine yet: a spot in the Sponsored box at the end of the coin list. | "Sponsored" |

Rules you can point projects to (and the app enforces):
- Labels are always shown. People can switch off featured guarantees on their PC (Settings > Featured listings).
- A featured coin still has to be able to reach a pool payout within a week on that PC; a guarantee can't
  strand someone's coins on a pool.
- No promises of returns in pitches; you can pause or delist at any time (scams, dead chains, broken pools).
- Algorithms MINTRO mines: RandomX, RandomARQ, RandomWOW, GhostRider (XMRig); yespower, yespowerR16,
  yescryptR32, power2b, minotaurx (cpuminer-opt); firopow, meowpow (SRBMiner-Multi, GPU).

Pricing is yours to set; a flat fee per 30 days per plan, paid up front, is the simplest. Payment happens
outside MINTRO (invoice, Stripe payment link, crypto); the admin tool tracks where each request stands.

## The flow

```
website form  ──>  stats service inbox  ──>  admin tool: review, check, preview  ──>  publish (signed)  ──>  every MINTRO
"List your coin"     (server/stats)          publisher/admin.py                      listings/listings.json     within ~15 min
```

1. **A project applies** with the form on the website (section "For coin projects"). It lands in the stats
   service's inbox. Spam is held back by a hidden honeypot field and a per-IP daily limit.
2. **Open the admin dashboard**: double-click `publisher\MINTRO Admin.bat` (or `py -3.12 publisher\admin.py`).
   It's a separate program on your PC, never part of the app people install, and only you can sign in: the
   first time it asks you to create the admin password (12+ characters, stored only as a salted hash), and
   every time after that you sign in with it. Sessions end after 8 idle hours or on Sign out; five wrong
   passwords lock sign-in for a minute. Then, once, in Settings: stats service URL `https://mintro.aiteleresearch.com`
   (the website's own server, which collects the requests), and the admin token, which the Aitele VM generated:
   `grep MINTRO_ADMIN_TOKEN ~/.aitele-install.conf` there. The dashboard runs only on your PC because publishing
   signs the coin list with your publisher key (`%USERPROFILE%\MINTRO-publisher`), which must never sit on a server.
3. **Requests** tab: every request with its plan, algorithm, pool and contact. Change a request's status as you
   go (new, reviewing, awaiting payment, listed, rejected) and keep private notes on it.
4. **Review**: opens the listing editor pre-filled from the request (ticker, name, plan, algorithm, pool, links,
   30 days). Fill in the pitch and, for coins on their own pool, the network numbers (hashrate, block time,
   reward, payout minimum, fee) or a network API URL that returns them.
5. **Run checks**: the tool checks the ticker, plan and dates, that the algorithm is one MINTRO mines, that the
   coin is really on rplant (for rplant coins), and connects to each pool and speaks stratum to it. It also
   estimates what a typical laptop would mine. Publishing is blocked while a listed coin fails a check.
6. **Preview on my PC**: your own MINTRO switches to the new list at once (a signed staging feed served by the
   admin tool), so you see the coin in the basket exactly as users will. Stop preview to go back.
7. **Publish**: bumps the serial number, writes `listings/listings.json`, signs it, commits it and pushes it to
   GitHub. Every running MINTRO checks the feed every 10 minutes (an unchanged feed costs one tiny reply),
   verifies the signature, and replans its basket the moment the serial goes up, so a new listing reaches
   everyone within about 15 minutes (GitHub's own cache adds up to 5). People get a "New coin in MINTRO"
   notification for it. Copies that were off pick it up when they start.
8. **Keep it current**: in the Listings tab, **+30 days** extends a listing, **Pause** takes it out without
   deleting it, Edit changes anything, then Publish again. Expired listings drop out by themselves on the
   date in "Listed until".

## The feed

`listings/listings.json` in your repository, served from `raw.githubusercontent.com` (or `config.LISTINGS_URL`):

```json
{
  "serial": 7,
  "issued": "2026-11-05T10:00:00Z",
  "coins": [
    {"symbol": "ZEPH", "name": "Zephyr", "status": "listed", "tier": "standard", "source": "rplant",
     "until": "2026-12-31", "pitch": "Private stablecoin protocol on RandomX.", "links": {"site": "https://..."}},
    {"symbol": "NOVA", "name": "NovaCoin", "status": "listed", "tier": "featured", "min_share": 0.05,
     "source": "custom", "algo": "yespower",
     "pools": [{"name": "Nova pool", "host": "pool.nova.example", "port": 6234, "tls": true, "user": "{address}.{worker}"}],
     "network": {"hashrate": 200000, "block_time": 120, "reward": 50, "min_payout": 1, "fee": 0.01, "miners": 40},
     "network_api": "https://explorer.nova.example/api/mintro",
     "links": {"site": "https://nova.example", "wallet": "https://...", "be": "https://..."},
     "markets": [{"name": "Xeggex", "url": "https://..."}]}
  ]
}
```

`listings.json.sig` next to it holds the publisher's signature over the serial and the file's SHA-256.
The app rejects a feed whose signature doesn't verify against the key in `mintro/signing.py`, and any feed
with a lower serial than the one it already has, so an old feed can't be replayed and nobody without your
signing key can add a coin or point miners at a pool. Edit listings with the admin tool, not by hand: a
hand edit breaks the signature (which is the point).

`network_api`, if a project offers one, must return JSON with any of `hashrate`, `block_time`, `reward`,
`min_payout`, `fee`, `price_usd`, `miners`; the app reads it every 15 minutes and falls back to the numbers
in the listing.

## Affiliate links (a smaller, second income)

- **Exchanges**: each coin's **Where to sell** links come from the pool's market list (and a listing's
  `markets`). Add your referral code per exchange in `config.EXCHANGE_REFERRALS`, keyed by the name the app
  shows: `{"nonkyc.io": "ref=YOURCODE"}`. Links with a code are labelled "(affiliate links)".
- **Hardware wallets**: `config.HARDWARE_WALLETS` lists Ledger and Trezor for coins they can hold; put your
  affiliate URL in `ref`.
