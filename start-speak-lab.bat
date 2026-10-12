@echo off
rem Double-click to open the speaking experiment page (docs/handoff.md 2026-10-12, D52).
rem Close this window to stop it. ASCII only: cmd reads .bat bytes in the console code page.
rem This is an experiment page: it never touches the player or the hosted trial copy,
rem and it uses its own ports 8770/8771 (docs/environment.md).
rem --open lets the server itself launch the browser once it is actually up.
"C:\Users\wzzpk\.conda\envs\pywork\python.exe" "%~dp0pipeline\speak_lab.py" --open & exit /b
