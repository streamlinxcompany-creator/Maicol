@echo off
rem Arranca el núcleo de JARVIS (si no está corriendo) y abre la interfaz como app.
cd /d "%~dp0"
title JARVIS

if not exist ".venv\Scripts\python.exe" (
  echo Preparando entorno por primera vez...
  python -m venv .venv || (echo Instala Python desde https://python.org & pause & exit /b 1)
  ".venv\Scripts\python.exe" -m pip install -q --upgrade pip
  ".venv\Scripts\python.exe" -m pip install -q -r requirements.txt
)
if not exist ".env" copy ".env.example" ".env" >nul

curl -s -o nul -m 2 http://127.0.0.1:8765/api/ping
if errorlevel 1 (
  rem como administrador si está instalada la tarea (scripts\instalar_admin.ps1); si no, como siempre
  schtasks /run /tn "Maicol Nucleo" >nul 2>nul || start "" /b ".venv\Scripts\pythonw.exe" -m jarvis
  for /l %%i in (1,1,60) do (
    timeout /t 1 /nobreak >nul
    curl -s -o nul -m 1 http://127.0.0.1:8765/api/ping && goto listo
  )
)
:listo
rem Ventana de app sin barras (Edge o Chrome). Ambos traen reconocimiento de voz.
where msedge >nul 2>nul && (start "" msedge --app=http://127.0.0.1:8765 --window-size=1500,920 --autoplay-policy=no-user-gesture-required & exit /b)
if exist "%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe" (start "" "%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe" --app=http://127.0.0.1:8765 --window-size=1500,920 --autoplay-policy=no-user-gesture-required & exit /b)
if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" (start "" "%ProgramFiles%\Google\Chrome\Application\chrome.exe" --app=http://127.0.0.1:8765 --window-size=1500,920 --autoplay-policy=no-user-gesture-required & exit /b)
start "" http://127.0.0.1:8765
