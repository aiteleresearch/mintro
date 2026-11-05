@echo off
rem MINTRO admin dashboard: listing requests, coin listings, signed publishing.
rem Publisher only: this is never part of the MINTRO app people install. Keep this window open while you use it.
title MINTRO admin
py -3.12 "%~dp0admin.py"
if errorlevel 1 pause
