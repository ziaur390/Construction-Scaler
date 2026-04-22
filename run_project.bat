@echo off
setlocal

where py >nul 2>nul
if %errorlevel%==0 (
  start "Construction Scaler Server" cmd /k py server.py
  timeout /t 2 >nul
  start "" http://127.0.0.1:8001
  goto :eof
)

where python >nul 2>nul
if %errorlevel%==0 (
  start "Construction Scaler Server" cmd /k python server.py
  timeout /t 2 >nul
  start "" http://127.0.0.1:8001
  goto :eof
)

echo Python was not found on PATH.
echo Install Python or run the project from an environment where Python is available.
exit /b 1
