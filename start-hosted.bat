@echo off
rem Double-click to start the hosted (visitor-facing) trial server on this PC, for
rem owner acceptance before anything goes to the real server (SPEC-009 v7).
rem Visitors go straight in without an account; the login link sits at the sidebar
rem bottom. Port and invite code come from server-config.json (gitignored) in the
rem repo root. Close this window to stop the server.
rem Keep this file ASCII-only: cmd reads .bat bytes in the console code page.
setlocal
"C:\Users\wzzpk\.conda\envs\pywork\python.exe" "%~dp0pipeline\serve.py" --hosted --open & exit /b
