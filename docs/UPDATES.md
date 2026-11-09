# Releasing an update

Installed copies of MINTRO update themselves, and mining doesn't stop while they do.

## Release steps

1. Bump `__version__` in `mintro/__init__.py` (e.g. 0.4.1 to 0.4.2).
2. Build: `py -3.12 setup\build.py`. `dist\` then holds:
   - `MINTRO-Setup-0.4.2.exe`: the installer, for new users (and the website's download counter);
   - `MINTRO-Update-0.4.2.zip`: the same app, for installed copies;
   - `MINTRO-Update-0.4.2.zip.sig`: its signature, made with your publisher key.
3. Publish them on MINTRO's website: commit and push this repo (the website ships exactly as it is on GitHub),
   keep the three files in `dist\`, then in the Aitele repo run `bash deploy/build-zip.sh`. It takes the website
   from GitHub and the three files from `dist\` (`MINTRO_SRC` if this repo isn't at `C:\MINTRO`), writes
   `download/release.json`, and builds the deploy zip; upload it to the VM and re-run `install.sh`.
4. Optional: also create a GitHub release tagged with the version and the same three files. Only copies of
   0.4.1 and earlier look on GitHub alone; 0.4.1 was never published (no GitHub release, no live website),
   so from 0.4.2 every copy anyone downloads already follows the website's feed.

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

## Website counters across deploys

Downloads, unique visitors, page views and updates delivered are kept by the website's server in
`/opt/aitele/mintro-data/` on the VM (`stats.json`, a `.bak`, and a dated snapshot each day), outside the folder a
deploy replaces. Every redeploy — a new version, a page change — carries on counting from the same totals. Copy
that folder if you ever move to a new VM.

## Service notices — and if MINTRO ever closes

The update feed can also carry a notice, signed with the same publisher key, that every installed MINTRO picks up
at its next check (within 6 hours) and keeps even when it's offline:

    py publisher\mintro_keys.py sign-notice --kind message --text "Planned maintenance on Sunday."
    py publisher\mintro_keys.py sign-notice --kind end-of-service --text "MINTRO has closed. Thank you." --url https://...
    py publisher\mintro_keys.py sign-notice --clear

Each writes (or removes) `dist/service-notice.json`; the next website deploy (the Aitele repo's
`deploy/build-zip.sh`, then `install.sh` on the VM) puts it into `download/release.json`.

- **message**: a note at the top of every card.
- **end-of-service**: mining stops at once, Start stays off, and the card offers **Uninstall MINTRO**. Settings,
  earnings history and any wallets MINTRO made stay in `%LOCALAPPDATA%\MINTRO`, so people keep their funds.

A notice that isn't signed by your key is ignored. Only the website's own feed can clear a notice (GitHub's
release data never carries one), so a notice stays in force if the website is later switched off. Deploy with
`--clear` to take a notice down, for example if the service resumes. Notices reach installed copies only while
the website (or GitHub) answers: send the end-of-service notice before switching the website off, and leave it up
for a few weeks so PCs that are rarely online still see it.

## Testing an update before everyone gets it

Point one PC at a test feed instead of the normal one: add `"update_feed": "https://.../latest.json"` to
`%LOCALAPPDATA%\MINTRO\data\app-prefs.json`, where `latest.json` has the same shape as GitHub's
`/releases/latest` response (`tag_name` and `assets` with `name` and `browser_download_url`). The signature
check still applies. Remove the line to go back to normal releases.

## Keys

The same publisher key signs updates and the coin listings feed. Lose it and you can't ship updates that
installed copies accept; leak it and someone else could. Keep a backup offline. See `publisher/mintro_keys.py`.
