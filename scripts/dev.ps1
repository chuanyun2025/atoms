param([ValidateSet("up","down","logs","restart","status")][string]$Action="up")
$ErrorActionPreference="Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
python scripts/init_env.py
if ($Action -eq "up") {
    docker compose --env-file .env.local up -d --build
    if ($LASTEXITCODE -ne 0) { throw "本地服务启动失败" }
    docker compose --env-file .env.local exec -T gateway nginx -s reload
} elseif ($Action -eq "status") {
    docker compose --env-file .env.local ps
} elseif ($Action -eq "logs") {
    docker compose --env-file .env.local logs --tail 60 -f api worker gateway
} else {
    docker compose --env-file .env.local $Action
}
