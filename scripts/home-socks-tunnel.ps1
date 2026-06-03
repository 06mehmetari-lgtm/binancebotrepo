# Ev Windows PC — VPS'e ücretsiz SOCKS tüneli (Groq/Cerebras bypass)
# Yönetici PowerShell:
#   .\scripts\home-socks-tunnel.ps1 -VpsHost 194.163.181.39 -VpsUser root
#
# VPS .env: ALL_PROXY=socks5://127.0.0.1:1080
# Sonra: bash scripts/enable-groq-cerebras.sh

param(
    [string]$VpsHost = "194.163.181.39",
    [string]$VpsUser = "root",
    [int]$RemotePort = 1080
)

Write-Host "Ev PC -> VPS SOCKS tüneli (port $RemotePort on VPS)"
Write-Host "Bu pencereyi KAPATMAYIN. Kopunca Groq durur."
Write-Host ""
ssh -N -R "${RemotePort}:127.0.0.1:${RemotePort}" "${VpsUser}@${VpsHost}"
