@echo off
curl.exe -s -m 10 http://127.0.0.1:5050/health | findstr /c:"\"ok\":true" >nul
if %errorlevel%==0 exit /b 0
echo %date% %time% BRIDGE DOWN - restarting >> C:\Temp\watchdog.log
taskkill /f /im pythonw.exe >> C:\Temp\watchdog.log 2>&1
timeout /t 3 /nobreak >nul
start "" "C:\Program Files\Python311\pythonw.exe" C:\Temp\bridge.py
echo %date% %time% RESTART ISSUED >> C:\Temp\watchdog.log
