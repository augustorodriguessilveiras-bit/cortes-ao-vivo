@echo off
chcp 65001 >nul
title Cortes ao Vivo
cd /d "%~dp0.."

rem usa o Python 3.14 se ele estiver instalado (mais garantido); senao, o "python" padrao
set PY=python
py -3.14 --version >nul 2>nul
if not errorlevel 1 set PY=py -3.14
py -V:3.14 --version >nul 2>nul
if not errorlevel 1 set PY=py -V:3.14

%PY% --version >nul 2>nul
if errorlevel 1 (
  echo.
  echo  [ERRO] Python nao encontrado.
  echo  Instale em https://www.python.org/downloads/
  echo  IMPORTANTE: marque a caixinha "Add python.exe to PATH" na instalacao.
  echo  Depois abra este INICIAR.bat de novo.
  start "" https://www.python.org/downloads/
  pause
  exit /b
)
for /f "tokens=2" %%v in ('%PY% --version 2^>^&1') do set PYV=%%v
echo  Python %PYV% encontrado.

where ffmpeg >nul 2>nul
if errorlevel 1 (
  echo.
  echo  Instalando o ffmpeg ^(so na primeira vez^)...
  winget install -e --id Gyan.FFmpeg --accept-source-agreements --accept-package-agreements
  echo.
  echo  Pronto! FECHE esta janela e abra o INICIAR.bat de novo.
  pause
  exit /b
)

echo  Instalando/atualizando componentes ^(na 1a vez demora alguns minutos^)...
%PY% -m pip install --disable-pip-version-check -q --upgrade -r requirements.txt
if errorlevel 1 (
  echo.
  echo  [ERRO] Nao deu pra instalar os componentes.
  echo  Tire um print desta janela e mande pro Claude.
  pause
  exit /b
)

echo  Instalando o reconhecimento de fala ^(opcional, na 1a vez demora^)...
%PY% -m pip install --disable-pip-version-check -q --upgrade faster-whisper >nul 2>nul
if errorlevel 1 echo  ^(nao deu pra instalar o reconhecimento de fala; o programa funciona normal sem ele^)

echo.
echo  ==========================================
echo   Iniciando o Cortes ao Vivo...
echo   O painel abre sozinho no navegador quando estiver pronto.
echo   Endereco: http://localhost:8000
echo   Para desligar: feche esta janela.
echo  ==========================================
echo.
rem abre o navegador so quando o programa responder (espera ate 2 minutos)
start "" /min powershell -NoProfile -WindowStyle Hidden -Command "for($i=0;$i -lt 120;$i++){try{Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:8000/api/state' -TimeoutSec 2 | Out-Null; Start-Process 'http://localhost:8000'; break}catch{Start-Sleep 1}}"
%PY% -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --no-access-log --log-level warning
echo.
echo  [ERRO] O programa parou. Tire um print desta janela e mande pro Claude.
pause
