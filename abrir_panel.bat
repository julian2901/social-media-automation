@echo off
REM Levanta el panel local de clips en http://127.0.0.1:8765
REM Este archivo vive en la raiz del repositorio y arranca la carpeta panel\.
chcp 65001 > nul

set "RAIZ=%~dp0"
cd /d "%RAIZ%panel"

set "PY=%RAIZ%panel\.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

set "URL=http://127.0.0.1:8765/"

REM Si el panel ya esta corriendo, solo abrimos la pagina.
powershell -NoProfile -Command "try { (Invoke-WebRequest -Uri '%URL%' -TimeoutSec 2 -UseBasicParsing).StatusCode } catch { 'down' }" > "%TEMP%\panel_check.txt" 2>&1
set /p PANEL_UP=<"%TEMP%\panel_check.txt"
if "%PANEL_UP%"=="200" (
  echo El panel ya esta abierto. Abriendo la pagina...
  start "" "%URL%"
  exit /b 0
)

echo Levantando el panel de clips...
echo No cierres esta ventana mientras trabajas. (Ctrl+C para detener)

REM Espera a que el servidor escuche y solo entonces abre el navegador.
start "" /b powershell -NoProfile -WindowStyle Hidden -Command "$u='%URL%'; for($i=0;$i -lt 60;$i++){ try { if((Invoke-WebRequest -Uri $u -TimeoutSec 2 -UseBasicParsing).StatusCode -eq 200){ Start-Process $u; break } } catch {}; Start-Sleep -Milliseconds 700 }"

"%PY%" app.py

echo.
echo El panel se detuvo. Puedes cerrar esta ventana.
pause
