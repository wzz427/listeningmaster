@echo off
rem Double-click to open the listening player. Close this window to stop it.
rem Keep this file ASCII-only: cmd reads .bat bytes in the console code page.
rem
rem Two copies of this repo live side by side (specs/SPEC-008-stable-and-dev.md).
rem The stable copy is the one the family uses: it sits next to this folder as
rem "<this folder name>-stable" and has the marker file .lm-stable-copy. This
rem folder is the dev copy claude edits. Double-clicking the dev copy hands over
rem to the stable copy. The suffix and the marker name are also written in
rem pipeline/stable_copy.py (SUFFIX, MARKER); tests/test_stable_copy.py pins both.
rem
rem Every line that runs something ends with "& exit /b". Switching versions rewrites
rem this very file, and cmd would otherwise go on reading it at a stale byte offset
rem and run garbage (SPEC-008, experiment 1). The start / update / restart loop
rem lives in Python for the same reason.
rem Usage: start-player.bat [--port N] [--no-browser]
setlocal
for %%I in ("%~dp0.") do set "NAME=%%~nxI"
if not exist "%~dp0.lm-stable-copy" if exist "%~dp0..\%NAME%-stable\.lm-stable-copy" (
  call "%~dp0..\%NAME%-stable\start-player.bat" %* & exit /b
)
"C:\Users\wzzpk\.conda\envs\pywork\python.exe" "%~dp0pipeline\stable_copy.py" run %* & exit /b
