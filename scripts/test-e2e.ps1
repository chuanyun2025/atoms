param([switch]$KeepRunning)
$ErrorActionPreference="Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
python scripts/e2e-env.py
npx playwright install chromium
if ($LASTEXITCODE -ne 0) { throw "测试浏览器安装失败" }
docker compose --env-file .env.test -p atoms-e2e up -d --build
if ($LASTEXITCODE -ne 0) { throw "测试服务启动失败" }
try {
    docker compose --env-file .env.test -p atoms-e2e exec -T gateway nginx -s reload
    python scripts/wait-http.py http://localhost:8082/health/ready
    if ($LASTEXITCODE -ne 0) { throw "测试服务未就绪" }
    npm run test:e2e
    $testExit=$LASTEXITCODE
} finally {
    if (-not $KeepRunning) { docker compose --env-file .env.test -p atoms-e2e down }
}
exit $testExit
