@echo off
rem Maicol en el lateral de la pantalla: una pestaña en el borde que abre y esconde el panel.
rem (JARVIS.bat sigue abriendo la ventana grande de siempre.)
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" call JARVIS.bat
start "" ".venv\Scripts\pythonw.exe" scripts\maicol_lateral.pyw %*
