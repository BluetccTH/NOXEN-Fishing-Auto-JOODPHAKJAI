@echo off
setlocal
cd /d "%~dp0"
title [ NOXEN ] - Fishing Auto JOODPHAKJAI
where py >nul 2>nul
if %errorlevel%==0 (set "PY=py -3") else (set "PY=python")
if not exist ".venv\Scripts\python.exe" (
  echo Creating an isolated Python environment...
  %PY% -m venv .venv
  if errorlevel 1 (
    echo Could not create the virtual environment. Install Python 3.10+ with the venv feature.
    pause
    exit /b 1
  )
)
.venv\Scripts\python.exe -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
  echo Package installation failed. Check your internet connection and try again.
  pause
  exit /b 1
)
echo.
echo Starting [ NOXEN ] - Fishing Auto JOODPHAKJAI...
.venv\Scripts\python.exe app.py
if errorlevel 1 pause
endlocal
