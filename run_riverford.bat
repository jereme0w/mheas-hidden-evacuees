@echo off
cd /d "%~dp0"
python backend\app.py --seed-demo --port 5001
pause
