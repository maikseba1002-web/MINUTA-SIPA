@echo off
:: Ejecutar siempre desde la carpeta del proyecto, incluso al abrir con doble clic
cd /d "%~dp0"
:: Forzar codificacion UTF-8 para que los acentos y la Ñ se vean bien
chcp 65001 >nul
color 0B
title SIPA - Sistema de Escuadron GNA

echo ==========================================================
echo    SISTEMA DE PLANILLAS DEL SERVICIO DE AULA - GENDARMERIA
echo ==========================================================
echo.
echo [1/3] Verificando e instalando dependencias...
python -m pip install -r requirements.txt --quiet --disable-pip-version-check --no-warn-script-location

echo.
echo [2/3] Interfaz lista. Abra el navegador cuando el servidor indique que esta en linea.

echo [3/3] Motor Backend en ejecucion.
echo.
echo ==========================================================
echo   URL: http://127.0.0.1:5000
echo   No cierre esta ventana mientras utiliza SIPA.
echo ==========================================================
echo.

:: Iniciar el servidor Flask (sin modo debug en produccion)
python main.py

pause
