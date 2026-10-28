@echo off
rem THE one script for the visitor-facing site (local acceptance, SPEC-009 v7).
rem Double-click it: if the site is already up it just opens the page again;
rem if not, it starts the server first (keep this window open while listening,
rem closing it stops the site). Keep this file ASCII + CRLF.
setlocal
netstat -ano | findstr /C:":8790 " | findstr /C:"LISTENING" >nul
if %errorlevel%==0 goto open
"C:\Users\wzzpk\.conda\envs\pywork\python.exe" "%~dp0pipeline\serve.py" --hosted --open & exit /b
:open
start "" "http://localhost:8790/"
exit /b
