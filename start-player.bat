@echo off
rem 双击这个文件就能打开播放器。关掉黑窗口即停止。
start "" http://localhost:8765/web/
"C:\Users\wzzpk\.conda\envs\pywork\python.exe" "%~dp0pipeline\serve.py" 8765
