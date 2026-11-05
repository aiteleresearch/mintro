# Launch post drafts

Drafts to adapt and post yourself. Read each community's rules first: most forbid unannounced self-promotion,
and some ban mining software outright. Say you're the developer, every time. Replace the version
and the screenshot links.

Before posting: the release is signed (or you say clearly that it isn't yet), the Microsoft false-positive
submission is in (see ANTIVIRUS.md), and the website and GitHub release are live.

---

## Bitcointalk: [ANN] thread

Board: *Mining software (miners)*.

**Title:** `[ANN] MINTRO: basket mining for laptops (free, open source, no fee)`

```
MINTRO is a small desktop card for Windows that mines a basket of early-stage CPU coins on an ordinary laptop.

I built it for people who'd like to try mining but won't touch a command line. It's three clicks: install,
create or paste wallets, press Start.

WHAT IT DOES
- Picks CPU coins from the rplant pool where your PC would mine the biggest share of new supply, and shares
  its time between them. A coin only joins the basket if it can reach the pool's payout within a week.
- Tunes itself to the PC: threads from the CPU cache size, idle priority while you use the PC, RandomX light
  mode when RAM is short, pauses on battery, learns real speeds per algorithm.
- Engines: XMRig (RandomX, GhostRider), cpuminer-opt (yespower, yescrypt, power2b, minotaurx) and
  SRBMiner-Multi (GPU). Downloaded from each project's official GitHub release and checksum-verified.
- One-click wallets for Monero-family coins using each coin's official wallet-rpc, offline, with a seed backup.
- Pool fallbacks, a self-check, and plain-language antivirus handling.

FEES
MINTRO takes no fee and every feature is free. Every share goes to your address. MINTRO is paid for by coin
projects that list their coins (always labelled in the app). The engines keep their own dev fees (XMRig 1%,
SRBMiner-Multi ~0.85%, cpuminer-opt none); the app lists them.

HONEST EXPECTATIONS
A laptop earns cents to a few dollars a month, and power can cost more. The point is holding a little of
several young coins in case one takes off. Most won't.

LINKS
Download: https://github.com/aiteleresearch/mintro/releases/latest
Source (GPL-3.0): https://github.com/aiteleresearch/mintro
Website: https://aiteleresearch.github.io/mintro

Antivirus will flag the mining engines (it flags every miner). The app explains this and can exclude its
own miner folder after Windows asks you. Please report anything else that gets flagged.

Feedback and coin suggestions welcome. If you run a CPU coin and want it supported, post here.
```

---

## Reddit

Pick subreddits whose rules allow it (check the sidebar; message the mods first if unsure). Candidates:
r/CryptoMining, r/MoneroMining (RandomX angle only; they dislike altcoin hype), r/cpumining,
r/gpumining (GPU lane), and the subreddits of coins MINTRO supports.

**Title:** `I made a free, open-source app that mines a basket of small CPU coins on a normal laptop (no fee)`

```
Hi all, developer here. MINTRO is a floating card for Windows: install, add wallets (it can create them with
the coins' official wallet tools), press Start. It picks the coins where a laptop gets the biggest share of
new supply, rotates between them and tunes itself to your PC (backs off when you use it, pauses on battery).

- Free, GPL-3.0, MINTRO takes no fee (the engines' own dev fees are listed in the app)
- XMRig + cpuminer-opt for CPU coins, official releases, checksum-verified
- Realistic numbers: on a laptop this is a lottery ticket on young coins, not income

Source: https://github.com/aiteleresearch/mintro
Download: https://github.com/aiteleresearch/mintro/releases/latest

Antivirus flags every miner engine; the app explains why and what to do. I'd love feedback, especially on
which coins it picks and how it behaves on your hardware.
```

---

## Discord / Telegram (coin and pool communities)

Ask an admin before posting. Short version:

```
Hi! I'm the developer of MINTRO, a free open-source Windows app that lets non-technical people mine CPU coins
in three clicks. It already supports <COIN> on rplant: it picks the pool port, region and threads itself, and
can create a <COIN> wallet in one click (for Monero-family coins).

It could bring your coin new small miners. Happy to hear what you'd want from it.
https://github.com/aiteleresearch/mintro
```

---

## Pool operators (rplant and others)

```
Hi, I maintain MINTRO (GPL-3.0), a Windows app that points casual laptop miners at CPU coins on your pool.
It reads /api/dash and /api/currencies to pick ports and coins, connects over TLS to the nearest region,
and sets the worker name to "mintro" so you can see its traffic. It caches the coin list and refreshes it
at most every 15 minutes per PC, so it adds little load.

Is that use of your API OK with you, and is there anything you'd like it to do differently (rate limits,
user agent, ports)? Source: https://github.com/aiteleresearch/mintro
```
