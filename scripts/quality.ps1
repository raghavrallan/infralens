"""Run the same quality gates locally that CI enforces."""
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not $env:RUN_INFRA_TESTS -and (Test-Path ".env.test")) {
    Get-Content ".env.test" | ForEach-Object {
        if ($_ -match '^\s*RUN_INFRA_TESTS=(.+)\s*$') {
            $env:RUN_INFRA_TESTS = $Matches[1].Trim().Trim('"').Trim("'")
        }
    }
}

$failUnder = 0
if ($env:RUN_INFRA_TESTS -match '^(?i:1|true|yes|on)$') {
    $failUnder = 90
}

Write-Host "==> Pylint (fail under 9.0)"
pylint app executors
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "==> Tests + coverage (fail under $failUnder%; RUN_INFRA_TESTS=$($env:RUN_INFRA_TESTS))"
pytest --cov=app --cov=executors --cov-branch --cov-report=term-missing --cov-report=html --cov-report=xml --cov-fail-under=$failUnder --junitxml=junit.xml
exit $LASTEXITCODE
