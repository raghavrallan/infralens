# Local n8n parity with server fixes (PowerShell).
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Ensure-EnvDefault([string]$Key, [string]$Value) {
  if (-not (Test-Path .env)) { throw ".env missing - copy from .env.example first" }
  $lines = Get-Content .env
  if ($lines | Where-Object { $_ -match "^$([regex]::Escape($Key))=" }) { return }
  Add-Content .env "`n$Key=$Value"
  Write-Host "appended $Key"
}

if (-not (Test-Path .env)) { throw ".env missing" }

$hasKey = Select-String -Path .env -Pattern '^N8N_ENCRYPTION_KEY=' -Quiet
if (-not $hasKey) {
  $bytes = New-Object byte[] 24
  [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
  $key = ($bytes | ForEach-Object { $_.ToString("x2") }) -join ""
  Add-Content .env "`nN8N_ENCRYPTION_KEY=$key"
  Write-Host "set N8N_ENCRYPTION_KEY"
}

Ensure-EnvDefault "N8N_WEBHOOKS_ENABLED" "true"
Ensure-EnvDefault "N8N_HOST_PORT" "5678"
Ensure-EnvDefault "N8N_SECURE_COOKIE" "false"
Ensure-EnvDefault "N8N_PUBLIC_WEBHOOK_URL" "http://127.0.0.1:5678/"
Ensure-EnvDefault "N8N_EDITOR_BASE_URL" "http://127.0.0.1:5678/"
Ensure-EnvDefault "N8N_WEBHOOK_URL" "http://n8n:5678/webhook/infralens"

Write-Host "==> Starting n8n"
docker compose --profile container-app up -d n8n

Write-Host "==> Waiting for health"
$ok = $false
for ($i = 0; $i -lt 30; $i++) {
  try {
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:5678/healthz" -UseBasicParsing -TimeoutSec 2
    if ($r.StatusCode -eq 200) { $ok = $true; break }
  } catch { Start-Sleep -Seconds 2 }
}
if (-not $ok) { throw "n8n did not become healthy" }
Write-Host "n8n healthy"

$email = if ($env:N8N_OWNER_EMAIL) { $env:N8N_OWNER_EMAIL } else { "raghavrallan@mooglelabs.com" }
$pass = if ($env:N8N_OWNER_PASSWORD) { $env:N8N_OWNER_PASSWORD } else { "Infralens@n8n1" }
$body = @{
  email = $email
  firstName = "Raghav"
  lastName = "Rallan"
  password = $pass
} | ConvertTo-Json

try {
  $setup = Invoke-WebRequest -Uri "http://127.0.0.1:5678/rest/owner/setup" -Method POST -Body $body -ContentType "application/json" -UseBasicParsing
  Write-Host "owner setup HTTP $($setup.StatusCode)"
} catch {
  Write-Host "owner setup skipped/failed (may already exist): $($_.Exception.Message)"
}

Write-Host ""
Write-Host "Open: http://127.0.0.1:5678"
Write-Host "Email: $email"
Write-Host "Password: $pass"
