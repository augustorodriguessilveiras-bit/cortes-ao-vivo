@echo off
chcp 65001 >nul
title Cortes ao Vivo
cd /d "%~dp0"
echo.
echo  Verificando se tem versao nova...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0atualizar.ps1"
call "%~dp0scripts\rodar.bat"
