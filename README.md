# MINTRO

A floating desktop card that mines a **basket** of small CPU coins from one laptop, so you hold a little of
several early-stage coins in case one takes off. Total earnings are set by your laptop's speed: the basket
spreads that speed across several bets, it doesn't multiply it.

Free and open source (GPL-3.0), every feature included. **MINTRO takes no fee**: every share goes to your own
address. MINTRO is paid for by coin projects that list their coins, and listed coins are always labelled.

## Install (Windows 10/11)

1. Run **`MINTRO-Setup-0.4.1.exe`** (from `dist\`, or the GitHub release). It installs in a few seconds and
   opens MINTRO. No admin rights, no Python needed. If the build isn't code-signed, Windows SmartScreen warns:
   choose *More info > Run anyway*.
2. MINTRO is now in the Start menu and on the desktop. It installs to `%LOCALAPPDATA%\Programs\MINTRO`;
   your settings, wallets and miners live in `%LOCALAPPDATA%\MINTRO`.
3. To remove it: *Settings > Apps > MINTRO > Uninstall* (or `MINTRO.exe --uninstall`). Your data and
   wallets are kept.

Needs the Microsoft Edge WebView2 runtime, which Windows 11 and up-to-date Windows 10 already have.

## Use it

1. Open MINTRO. The card appears in the bottom-right corner, always on top. The first time, it explains what
   to expect in a few lines.
2. Press **Create N wallets** in the basket header (Monero-family coins), or open a coin and paste a wallet
   address for it.
3. Press the big **Start** button. Press it again to pause. Closing the card stops mining.

Everything else is automatic: picking coins, sharing time between them, choosing the nearest pool server,
falling back to another pool, pausing on battery. The `–` button shrinks the card to a strip; drag the top bar
to move it. Everything on the card is clickable: the status pill jumps to what needs attention, **Mined** shows
what each coin has earned, **Basket** jumps to the coins, and **Power** (or the gear) opens settings. Esc closes
any panel.

## Tuned to each PC automatically

On first launch MINTRO reads the processor, memory, graphics, battery and screen scaling, then sizes everything
to that machine. The default power mode, **Auto**:

- picks a thread count from the CPU's cache and class (thin ultrabook, gaming laptop, desktop);
- drops the miner to idle priority the moment you touch the keyboard or mouse, and uses fewer threads while
  you work; back to full speed when the PC is idle (no restart, no lag);
- switches RandomX coins to their 256 MB *light* mode when free memory is under ~2.6 GB, so the PC never swaps;
- pauses on battery;
- calibrates: after a few minutes of mining it replaces the speed estimates with speeds measured on this PC
  and re-plans the basket.

The line under the status ("Auto · Standard laptop · 3 of 12 threads · tuned") shows what it's doing; tap it
for details. Eco, Balanced and Max are there to override it. The card sizes itself for Windows display scaling
*and* the Accessibility text size.

## How the basket works

- **Coins**: CPU coins on the rplant pool that one of MINTRO's engines can mine, around 15 today, from Monero,
  Zephyr and Salvium to new coins with no market yet.
- **Engines**: each downloaded from its project's official GitHub release and checksum-verified on first use.

  | Engine | Algorithms | Its own dev fee |
  |---|---|---|
  | XMRig | RandomX, RandomARQ, RandomWOW, GhostRider | 1% (donation level) |
  | cpuminer-opt | yespower, yespowerR16, yescryptR32, power2b, minotaurx | none |
  | SRBMiner-Multi (GPU) | firopow, meowpow | about 0.85% |

- **Size adapts**: a coin is only included if it gets enough mining time to reach the pool's minimum payout
  within a week; otherwise its coins would sit on the pool. Settings > Basket size caps it (Auto = up to 500).
- **Score** (0-100) favours coins where you'd mine a bigger slice of new supply, with active miners, and
  either no market yet (earliest stage) or real trading. Each coin shows a one-line reason.
- **Turns**: one coin at a time for 20 minutes (a laptop has one CPU cache and ~2.5 GB RAM per RandomX
  miner), rotating so each coin gets its planned share of time.
- **Learns**: real speeds per algorithm replace the estimates after a few minutes of mining.
- **Listed coins**: coin projects can apply to be listed (see "For publishers" below). A listed coin carries a
  "Listed" label and is scored like any other; a "Featured" coin also gets a guaranteed share of mining time
  (10% at most), shown on the coin. Settings > Featured listings turns those guarantees off on your PC.
- **Where to sell / store safely**: each coin lists the exchanges the pool knows it trades on, and hardware
  wallets that can hold it.
- **Safety nets**: addresses the pool rejects are flagged; if a pool server can't be reached MINTRO tries the
  next one (Monero also falls back to SupportXMR and HashVault), then skips the coin for 30 minutes; antivirus
  blocks are explained on the card.

**Run a check** (settings) tests the coin list, pool connection, engines, Windows Security, wallets, memory,
and payouts in one go, with a plain-language result for each.

## Getting a wallet address

**One click** (Monero, Zephyr, Salvium, MYT): open the coin and press **Create a wallet for me**, or press
**Create N wallets** in the basket header to do all of them. MINTRO then:

1. downloads that coin's official Windows command-line release (Zephyr 44 MB, Salvium 31 MB, Monero ~70 MB,
   MYT 97 MB) and checks it against the SHA-256 its developers publish (Monero, Salvium, MYT; Zephyr
   publishes none, so it relies on the HTTPS download from Zephyr's own GitHub);
2. runs the coin's own `wallet-rpc` offline on 127.0.0.1 behind a random password, creates a wallet, and
   re-creates it from its seed so it starts scanning at today's block height;
3. puts the address into your basket and writes `wallets\<COIN>\BACKUP-<COIN>-KEEP-SECRET.txt` with the
   address, seed words, restore height and how to open it.

**Back up the seed words** (coin row > Seed words): write them on paper. Anyone with them, or with the
`wallets` folder, can spend those coins. The wallet file has no password; you can set one in the wallet app.
To see your balance or send coins, open the wallet file (or restore from the seed) in the coin's official
wallet. MINTRO never overwrites a wallet it made.

**Paste an address** (any other coin): each coin row has **Wallet download**, **Official site** and
**Explorer** links. Install the wallet, create a wallet, write down its seed words, and copy its *receive*
address into MINTRO.

## Extras (all free)

Settings > Extras:

- **GPU mining**: a second lane that mines GPU coins with SRBMiner-Multi alongside the CPU basket, on PCs with
  a discrete NVIDIA, AMD or Intel Arc GPU. On by default on desktops; on laptops you turn it on (heat, fans).
- **Tax report**: a CSV of everything mined per day and coin, with its dollar value at the time
  (`Documents\MINTRO`).
- **Alerts**: Windows notifications when MINTRO stops, a coin reaches a payout, a coin's price jumps, or a new
  coin arrives.
- **My PCs**: pick a folder every PC can see (OneDrive works) and each PC running MINTRO shows up there.

## Updates

MINTRO updates itself and **mining doesn't stop while it does**. It checks for a new release a few minutes after
starting and every 6 hours, downloads it, checks it was signed by MINTRO's publisher (anything else is refused),
and installs it once you've been away from the PC for two minutes (or when you press **Install now** in
Settings). The running miner is handed to the new version, which carries on with the same coin, the same pool
connection and the same counters. If the new version doesn't start properly, the previous one comes back.

## What MINTRO connects to

- The rplant pool (coin list, mining) and any listed coin's own pool; GitHub (engine downloads, updates, the
  coin listings feed); WhatToMine and CoinGecko (prices); the coins' official wallet releases when you create a
  wallet.
- The public miner counter, if the publisher runs one: every 10 minutes an anonymous heartbeat with a random
  install ID, the app version and whether it's mining. No wallet, no name, no hardware. Turn it off in
  Settings ("Count me in the public miner counter").

## Antivirus

Windows Security (Microsoft Defender) flags every crypto miner engine; it calls XMRig
*Trojan:Win64/HashvaultMiner*. "Allow" in Protection history usually doesn't stick for miners: the file has
already been removed, and the next download is a new detection. So when Windows Security stops an engine, the
card offers **Allow MINTRO's miner**: Windows shows its admin prompt, and if you approve, Windows Security skips
only MINTRO's miner folder (`%LOCALAPPDATA%\MINTRO\miners`). Nothing changes unless you approve the prompt, and
you can undo it under *Windows Security > Virus & threat protection > Manage settings > Exclusions*. While
blocked, MINTRO doesn't keep re-downloading the engine.

## For publishers

| Guide | |
|---|---|
| [docs/LISTINGS.md](docs/LISTINGS.md) | coin listings, the revenue model: the request form, the admin tool, signed publishing |
| [docs/UPDATES.md](docs/UPDATES.md) | releasing an update that installed copies pick up by themselves |
| [docs/STATS.md](docs/STATS.md) | the stats service: public counters (downloads, miners) and listing requests |
| [docs/ANTIVIRUS.md](docs/ANTIVIRUS.md) | code signing and false-positive submissions |
| [docs/LAUNCH-POSTS.md](docs/LAUNCH-POSTS.md) | launch post drafts |

Fill in `mintro/config.py` (`GITHUB_REPO`, `STATS_URL`, referral codes) and `docs/assets/ui.js` (`SITE`) before
releasing. The website is `docs/` (GitHub Pages).

## Run from source

Double-click **`MINTRO.bat`** (needs Python 3.9+, and `pywebview` for the floating card:
`py -3.12 -m pip install pywebview`; without it the same card opens in your browser).

Build the installer and the update package with `py -3.12 setup\build.py` (needs `pywebview` and
`pyinstaller`). Set `MINTRO_SIGN_THUMBPRINT` (or `MINTRO_SIGN_PFX` and `MINTRO_SIGN_PASSWORD`) to code-sign the
.exe files; see the script's docstring.

If something looks wrong, `data\mintro.log` (or `%LOCALAPPDATA%\MINTRO\data\mintro.log` when installed)
records the card's layout and any errors.

## Files

| Path | What |
|---|---|
| `mintro/app.py` | the floating window |
| `mintro/web/card.html` | the card UI |
| `mintro/server.py` | local API between the card and the engines |
| `mintro/engine.py` | runs a lane (CPU or GPU): rotates coins, keeps the ledger, calibrates, hands miners over on update |
| `mintro/miners.py` | engine drivers: XMRig, cpuminer-opt, SRBMiner-Multi (download, arguments, stats) |
| `mintro/pools.py` | pool choices per coin, with fallbacks |
| `mintro/basket.py` | scoring and adaptive basket |
| `mintro/coins.py` | coin list, ports and links from the rplant pool, with listed coins merged in |
| `mintro/listings.py` | the signed coin listings feed |
| `mintro/updater.py` | signed self-updates with miner handoff and rollback |
| `mintro/telemetry.py` | the anonymous heartbeat for the public miner counter |
| `mintro/signing.py` | Ed25519 checks for updates and listings |
| `mintro/wallets.py` | one-click wallets with each coin's official wallet tool |
| `mintro/tuning.py` | Auto mode: per-PC thread counts, activity-based priority, memory-safe RandomX |
| `mintro/gpu.py` | discrete GPU detection and speed estimate |
| `mintro/extras.py` | tax report, alerts, My PCs |
| `mintro/partners.py`, `config.py` | sponsored (promo) coins and affiliate links; publisher settings |
| `mintro/selftest.py` | Run a check |
| `mintro/defender.py` | the Windows Security exclusion, behind Windows' admin prompt |
| `mintro/installer.py` | per-user install / uninstall (shortcuts, Apps entry) |
| `mintro/hardware.py`, `calc.py`, `market.py`, `bench.py` | hardware, estimates, prices, profit report |
| `setup/` | `build.py` (setup file, signed update package), entry points, icon |
| `publisher/admin.py`, `MINTRO Admin.bat` | the admin dashboard (sign-in required): listing requests, checks, preview, signed publishing. Publisher only, never shipped to users |
| `publisher/mintro_keys.py` | the publisher signing key: signs updates and listings (publisher only) |
| `server/stats/` | the stats service (Cloudflare Worker): public counters and listing requests |
| `listings/` | the published coin listings feed and its signature |
| `docs/` | website (`index.html`, `assets/`) and publisher guides |
| `data/`, `miners/`, `tools/`, `wallets/` | created at run time, not in git; **keep `wallets/` private** |

## License

GPL-3.0. See [LICENSE](LICENSE).

*"Mined" amounts are estimates; the pool's payouts are what count. Coins with no market may never be worth
anything. Not financial advice.*
