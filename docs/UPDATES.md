# Releasing an update

Installed copies of MINTRO update themselves, and mining doesn't stop while they do.

## Release steps

1. Bump `__version__` in `mintro/__init__.py` (e.g. 0.4.1 to 0.4.2).
2. Build: `py -3.12 setup\build.py`. `dist\` then holds:
   - `MINTRO-Setup-0.4.2.exe`: the installer, for new users (and the website's download counter);
   - `MINTRO-Update-0.4.2.zip`: the same app, for installed copies;
   - `MINTRO-Update-0.4.2.zip.sig`: its signature, made with your publisher key.
3. Publish them on MINTRO's website: in the Aitele repo run
   `bash "Ventures websites/Mintro/sync-from-mintro.sh"` (it copies the three files and writes
   `download/release.json`), then `bash deploy/build-zip.sh`, upload the zip to the VM and re-run `install.sh`.
4. Optional: also create a GitHub release tagged `v0.4.2` with the same three files. Copies from 0.4.1 and
   earlier only look on GitHub, so one GitHub release moves them onto the website's feed for good.

That's all. Each installed MINTRO checks https://mintro.aiteleresearch.com/download/release.json (GitHub's latest
release if the website doesn't answer) a few minutes after it starts and then every 6 hours.

## What happens on each PC

1. MINTRO sees `v0.4.2` is newer, downloads the `.sig` and the `.zip`, and checks that the signature was made
   by your key (`mintro/signing.py`) over this exact file. Anything else is refused and nothing is installed.
2. It unpacks the new version next to the installed one (`%LOCALAPPDATA%\Programs\MINTRO-update-0.4.2`).
3. Settings shows "0.4.2 is ready: it installs when you step away, and mining keeps going" (with an
   **Install now** button). After 2 minutes without keyboard or mouse input it installs:
   - each mining engine records its running miner in a handoff file and lets go of it without stopping it;
   - MINTRO closes; a small helper swaps the program folder and starts the new version;
   - the new version adopts the running miners (same process, same pool connection), and its counters carry on
     from where they were: earnings, shares, the current coin's turn, and the seconds it mined during the swap;
   - the card says "MINTRO updated to 0.4.2. Mining didn't stop."
4. If the new version doesn't report healthy within 90 seconds, the helper puts the previous version back and
   starts it; it adopts the miners again, and that PC skips the failed version until a newer one is released.
   MINTRO only closes once the helper has confirmed it's running, so a helper that can't start never leaves
   anyone without MINTRO. The helper's log is `%LOCALAPPDATA%\MINTRO\data\updates\update.log`.

Earnings, speeds, settings, wallets and the anonymous install ID live in `%LOCALAPPDATA%\MINTRO`, which updates
never touch. A manual reinstall with a new setup file over a running MINTRO also keeps the miners going.

## Testing an update before everyone gets it

Point one PC at a test feed instead of the normal one: add `"update_feed": "https://.../latest.json"` to
`%LOCALAPPDATA%\MINTRO\data\app-prefs.json`, where `latest.json` has the same shape as GitHub's
`/releases/latest` response (`tag_name` and `assets` with `name` and `browser_download_url`). The signature
check still applies. Remove the line to go back to normal releases.

## Keys

The same publisher key signs updates and the coin listings feed. Lose it and you can't ship updates that
installed copies accept; leak it and someone else could. Keep a backup offline. See `publisher/mintro_keys.py`.
