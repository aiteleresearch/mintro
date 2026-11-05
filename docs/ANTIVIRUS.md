# Antivirus and SmartScreen

Every antivirus flags crypto miners. Expect this to be the biggest support issue, and work on it before launch.
There are two separate problems:

| What gets flagged | Why | What you can do |
|---|---|---|
| **The mining engines** (XMRig, cpuminer-opt, SRBMiner-Multi) | Malware bundles the same engines to mine on stolen PCs, so vendors detect them by design (Microsoft calls XMRig `Trojan:Win64/HashvaultMiner`). | Little. Vendors rarely un-flag miners. MINTRO handles it in the app: it explains the block and offers to exclude only its miner folder, with Windows' own admin prompt. |
| **MINTRO itself** (`MINTRO.exe`, `MINTRO-Setup-x.y.z.exe`) | Unsigned PyInstaller apps are often false positives, and an app that downloads miners looks suspicious to heuristics. | A lot: sign the files, submit them as false positives, build reputation. |

## 1. Sign every release

Unsigned files get the "Windows protected your PC" SmartScreen screen and more heuristic detections.
`setup/build.py` signs both files when a certificate is configured (see its docstring for the environment
variables).

- **OV code-signing certificate**: roughly $200-400/year from a CA (DigiCert, Sectigo, GlobalSign, SSL.com...).
  Since 2023 the private key must live on a hardware token or a cloud HSM, so you get a USB token or a cloud
  signing account rather than a `.pfx` file. With a token, set `MINTRO_SIGN_THUMBPRINT`.
- **Open-source certificate**: Certum sells a cheaper code-signing certificate for open-source developers.
  MINTRO is GPL-3.0, so it qualifies.
- **Microsoft's Azure signing service** (Trusted Signing): a low monthly price and SmartScreen-friendly, but
  only available to some regions and organisation types; check the current eligibility.

SmartScreen reputation builds per certificate as people download and run your signed files; the warning
fades after enough clean installs. Keep using the same certificate.

## 2. Submit MINTRO's own files as false positives

Do this for every release, right after you build it and before you announce it.

1. Upload `MINTRO-Setup-x.y.z.exe` to VirusTotal (https://www.virustotal.com) and note which engines flag it.
2. **Microsoft** (most important: Windows Security is on every PC): https://www.microsoft.com/en-us/wdsi/filesubmission
   - Sign in, choose **Software developer**, product **Microsoft Defender Antivirus**.
   - Upload the setup file, and separately `MINTRO.exe` from `build\app\MINTRO`.
   - Select **Incorrectly detected as malware/malicious** and paste the text below.
3. For each other vendor VirusTotal showed, use its false-positive form (they move; search the vendor's name
   plus "false positive submission"). Common ones: Kaspersky OpenTIP (https://opentip.kaspersky.com),
   Avast/AVG, Bitdefender, ESET (samples@eset.com, subject "False positive"), Norton, McAfee, Trend Micro.

Submission text (edit the version and links):

```
MINTRO x.y.z is an open-source (GPL-3.0) desktop app for mining small cryptocurrencies on the user's own PC,
with the user's consent: nothing runs until the user presses Start, mining stops when the window closes,
and the app is listed in Settings > Apps with a normal uninstaller.

Source code: https://github.com/aiteleresearch/mintro
Release: https://github.com/aiteleresearch/mintro/releases/tag/vx.y.z
SHA-256 of the submitted file: <hash>

The installer and MINTRO.exe contain no mining code. When the user starts mining, MINTRO downloads an
official mining engine (XMRig, cpuminer-opt or SRBMiner-Multi) from that project's GitHub release and
verifies its published checksum. We understand those engines are detected by policy and are not asking for
them to be allowed; we are asking that MINTRO's own installer and executable not be detected as malware.
```

Get the hash with `Get-FileHash .\MINTRO-Setup-x.y.z.exe`.

Microsoft usually answers within a few days. If it's reclassified, the fix reaches PCs with the next
definition update (`Update-MpSignature`).

## 3. What not to do

- Don't pack, obfuscate or hide the miners, and don't silently add Defender exclusions. That is what
  malware does, it gets the app permanently flagged, and it's not what MINTRO is.
- Don't tell people to turn off their antivirus. The in-app button excludes one folder only, after Windows
  asks the person.

## 4. In the app

When Windows Security removes an engine, MINTRO stops re-downloading it and shows **Allow MINTRO's miner**,
which runs `Add-MpPreference -ExclusionPath %LOCALAPPDATA%\MINTRO\miners` behind Windows' admin prompt.
**Run a check** in settings shows whether the folder is allowed. Other antivirus products need their own
exclusion; point people at their vendor's help page.
