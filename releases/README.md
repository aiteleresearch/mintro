# MINTRO installer

`MINTRO-Setup-<version>.exe` here is the latest MINTRO installer for Windows 10 and 11: the same file the website's
Download button serves. `SHA256SUMS.txt` holds its SHA-256, so you can check a download:

```powershell
Get-FileHash .\MINTRO-Setup-<version>.exe
```

Run it to install MINTRO for your Windows account (no admin rights). Install steps, requirements and what Windows
shows the first time: https://mintro.aiteleresearch.com/download.html

`setup\build.py` replaces this file with each new build, so the folder always holds exactly one installer, the
latest; older versions stay in the git history.
