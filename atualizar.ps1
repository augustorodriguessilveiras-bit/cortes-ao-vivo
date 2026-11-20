# Atualiza o Cortes ao Vivo a partir do GitHub (os cortes, canais e ajustes em "dados" nao sao mexidos)
$ErrorActionPreference = 'Stop'
$repo = 'augustorodriguessilveiras-bit/cortes-ao-vivo'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
try {
    $sha = (Invoke-RestMethod "https://api.github.com/repos/$repo/commits/main" -TimeoutSec 15 -Headers @{ 'User-Agent' = 'cortes-ao-vivo' }).sha
} catch {
    Write-Host '  Nao deu pra verificar atualizacao agora (sem internet?). Abrindo a versao atual.'
    exit 0
}
$verFile = Join-Path $root '.versao'
$local = ''
if (Test-Path $verFile) { $local = (Get-Content $verFile -Raw).Trim() }
if ($local -eq $sha) {
    Write-Host '  Voce ja esta com a versao mais nova.'
    exit 0
}
try {
    Write-Host '  Baixando a versao nova...'
    $tmp = Join-Path $env:TEMP ('cortes_atualizacao_' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory $tmp | Out-Null
    $zip = Join-Path $tmp 'novo.zip'
    Invoke-WebRequest "https://github.com/$repo/archive/$sha.zip" -OutFile $zip -UseBasicParsing -TimeoutSec 120
    Expand-Archive $zip -DestinationPath $tmp
    $src = Get-ChildItem $tmp -Directory | Select-Object -First 1
    # copia tudo por cima, menos os dados do usuario e o proprio INICIAR.bat (que esta rodando agora)
    robocopy $src.FullName $root /E /XD dados .git /XF .env INICIAR.bat /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy falhou ($LASTEXITCODE)" }
    Set-Content -Path $verFile -Value $sha
    Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host '  Atualizado para a versao mais nova!'
} catch {
    Write-Host "  Nao deu pra atualizar agora ($($_.Exception.Message)). Abrindo a versao atual."
}
exit 0
