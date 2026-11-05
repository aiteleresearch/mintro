@echo off
rem MINTRO - double-click to open the floating card. Closing the card stops mining.
cd /d "%~dp0"
for %%V in (3.12 3.13 3.11 3) do (
  py -%%V -c "import webview" >nul 2>nul && (start "" pyw -%%V -m mintro.app & exit /b)
)
rem No pywebview installed: show the card in the browser instead
where py >nul 2>nul && (start "MINTRO" /min cmd /c "py -3 -m mintro --page card || pause" & exit /b)
where python >nul 2>nul && (start "MINTRO" /min cmd /c "python -m mintro --page card || pause" & exit /b)
echo MINTRO needs Python 3.9 or newer: https://www.python.org/downloads/
pause
