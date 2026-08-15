"""Run the same quality gates locally that CI enforces."""
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Write-Host "==> Pylint (fail under 9.0)"
pylint app executors
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "==> Tests + coverage (fail under 90%)"
pytest --cov=app --cov=executors --cov-branch --cov-report=term-missing --cov-report=html --cov-report=xml --cov-fail-under=90 --junitxml=junit.xml
exit $LASTEXITCODE
