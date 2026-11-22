@echo off
chcp 65001 >nul
title Cortes ao Vivo
cd /d "%~dp0.."

rem acha um Python que funcione DE VERDADE (o "py" novo pode existir sem o Python estar instalado)
set PY=
call :tenta "py -V:3.14"
if not defined PY call :tenta "py -3.14"
if not defined PY call :tenta "python"
if not defined PY call :tenta "py"
if not defined PY (
  where py >nul 2>nul
  if not errorlevel 1 (
    echo.
    echo  Instalando o Python 3.14 ^(so na primeira vez, alguns minutos^)...
    py install 3.14
    call :tenta "py -V:3.14"
    if not defined PY call :tenta "py -3.14"
  )
)

if not defined PY (
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
if not exist dados mkdir dados
%PY% -m pip install --disable-pip-version-check -q --upgrade faster-whisper > "dados\fala_instalacao.log" 2>&1
if errorlevel 1 (
  echo.
  echo  [AVISO] Nao deu pra instalar o reconhecimento de fala.
  echo  O programa funciona sem ele, mas acha menos momentos e os titulos ficam menos ligados ao que o streamer fala.
  echo  O motivo aparece no painel, em Ajustes. Mande um print pro Claude.
  echo.
)

echo.
echo  ==========================================
echo   Iniciando o Cortes ao Vivo...
echo   O painel abre sozinho no navegador quando estiver pronto.
echo   Endereco: http://localhost:8000
echo   Para desligar: feche esta janela.
echo  ==========================================
echo.
rem se uma versao antiga do programa ainda estiver aberta (usando a porta 8000), fecha ela antes
powershell -NoProfile -Command "$p = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique; if ($p) { Write-Host '  Fechando uma versao antiga do programa que ainda estava aberta...'; $p | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }; Start-Sleep 2 }"

rem gravadores que ficaram rodando escondidos de vezes anteriores (travam arquivos e pesam no PC): fecha
powershell -NoProfile -Command "$n = 0; Get-CimInstance Win32_Process -Filter \"Name='ffmpeg.exe' OR Name='python.exe' OR Name='pythonw.exe' OR Name='streamlink.exe'\" -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -and ($_.CommandLine -like '*gravacoes*' -or $_.CommandLine -like '*streamlink*--stdout*') } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; $n++ }; if ($n) { Write-Host \"  Fechei $n gravador(es) que tinham ficado abertos escondidos.\" }"

rem abre o navegador so quando o programa responder (espera ate 2 minutos)
start "" /min powershell -NoProfile -WindowStyle Hidden -Command "for($i=0;$i -lt 120;$i++){try{Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:8000/api/state' -TimeoutSec 2 | Out-Null; Start-Process 'http://localhost:8000'; break}catch{Start-Sleep 1}}"
%PY% -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --no-access-log --log-level warning
echo.
echo  [ERRO] O programa parou. Tire um print desta janela e mande pro Claude.
pause
exit /b

rem testa se esse comando roda o Python de verdade (precisa responder "Python 3.x")
:tenta
%~1 --version 2>nul | findstr /b /c:"Python 3." >nul
if not errorlevel 1 set "PY=%~1"
exit /b
