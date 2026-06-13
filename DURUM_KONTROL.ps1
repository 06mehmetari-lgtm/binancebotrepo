# Prometheus VPS tam durum kontrolu
# Kullanim:  .\DURUM_KONTROL.ps1

Set-Location $PSScriptRoot

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  PROMETHEUS — VPS DURUM KONTROLU" -ForegroundColor Cyan
Write-Host "  http://194.163.181.39:3000/system" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# Python bul (py -3 ayri arguman olmali — "& py -3" string olarak calismaz)
$PyExe = $null
$PyPrefix = @()
if (Get-Command python -ErrorAction SilentlyContinue) {
    $PyExe = "python"
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $PyExe = "py"
    $PyPrefix = @("-3")
} else {
    Write-Host "[HATA] Python yuklu degil" -ForegroundColor Red
    exit 1
}

# secrets kontrol
if (-not (Test-Path "scripts\.deploy.secrets")) {
    Write-Host "[HATA] scripts\.deploy.secrets yok" -ForegroundColor Red
    Write-Host "  copy scripts\.deploy.secrets.example scripts\.deploy.secrets"
    Write-Host "  VPS_PASS=... ekle"
    exit 1
}

# paramiko — pip uyarilari hata sayilmasin
$prevErr = $ErrorActionPreference
$ErrorActionPreference = "SilentlyContinue"
& $PyExe @PyPrefix -m pip install paramiko -q *> $null
$ErrorActionPreference = $prevErr

# Ana rapor (vps_full_status.py paramiko yoksa kendisi de kurar)
& $PyExe @PyPrefix scripts\vps_full_status.py
$code = $LASTEXITCODE
if ($null -eq $code) { $code = 0 }

Write-Host ""
if ($code -eq 0) {
    Write-Host "Durum: OK" -ForegroundColor Green
} else {
    Write-Host "Durum: SORUN VAR — yukaridaki OZET'e bakin" -ForegroundColor Yellow
}

exit $code
