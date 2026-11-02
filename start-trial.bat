@echo off
rem Double-click to open the trial copy of the listening website: http://localhost:8790/
rem The owner tries new versions here; the family and other users use the online site.
rem Close this window to stop it. Keep this file ASCII-only: cmd reads .bat bytes in the
rem console code page.
rem
rem Two copies of this repo live side by side (specs/SPEC-008-stable-and-dev.md).
rem The trial copy sits next to this folder as "<this folder name>-stable" and has the
rem marker file .lm-stable-copy. This folder is the dev copy claude edits. Double-clicking
rem the dev copy hands over to the trial copy. The suffix and the marker name are also
rem written in pipeline/stable_copy.py (SUFFIX, MARKER); tests/test_stable_copy.py pins both.
rem
rem Every line that runs something ends with "& exit /b". Switching versions rewrites
rem this very file, and cmd would otherwise go on reading it at a stale byte offset
rem and run garbage (SPEC-008, experiment 1). The start / update / restart loop
rem lives in Python for the same reason.
rem Usage: start-trial.bat [--port N] [--no-browser]
setlocal
for %%I in ("%~dp0.") do set "NAME=%%~nxI"
if not exist "%~dp0.lm-stable-copy" if exist "%~dp0..\%NAME%-stable\.lm-stable-copy" (
  call "%~dp0..\%NAME%-stable\start-trial.bat" %* & exit /b
)
"C:\Users\wzzpk\.conda\envs\pywork\python.exe" "%~dp0pipeline\stable_copy.py" run %* & exit /b
