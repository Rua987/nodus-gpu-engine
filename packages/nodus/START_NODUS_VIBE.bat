@echo off
cd /d "%~dp0"
python nodus_vibe.py --cwd "%CD%" %*
