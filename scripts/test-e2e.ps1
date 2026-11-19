param([switch]$KeepRunning)
$ErrorActionPreference="Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
python scripts/e2e-env.py
npx playwright install chromium
if ($LASTEXITCODE -ne 0) { throw "测试浏览器安装失败" }
docker compose --env-file .env.test -p atoms-e2e up -d --build
if ($LASTEXITCODE -ne 0) { throw "测试服务启动失败" }
$previousVideoPasscode = $env:ATOMS_E2E_VIDEO_PASSCODE
try {
    docker compose --env-file .env.test -p atoms-e2e exec -T gateway nginx -s reload
    python scripts/wait-http.py http://localhost:8082/health/ready
    if ($LASTEXITCODE -ne 0) { throw "测试服务未就绪" }
    $passcode = docker compose --env-file .env.test -p atoms-e2e exec -T api python -m atoms.ops passcode-create --label "E2E video" --credits 500 --max-visitors 0
    if ($LASTEXITCODE -ne 0) { throw "测试视频口令创建失败" }
    $env:ATOMS_E2E_VIDEO_PASSCODE = ($passcode | ConvertFrom-Json).code
    npm run test:e2e
    $testExit=$LASTEXITCODE
} finally {
    $env:ATOMS_E2E_VIDEO_PASSCODE = $previousVideoPasscode
    if (-not $KeepRunning) { docker compose --env-file .env.test -p atoms-e2e down }
}
exit $testExit
