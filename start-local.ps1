# DevSecOps Skills Suite - local run helper (Windows PowerShell)
#
# Usage:
#   .\start-local.ps1 setup     # one-time: venv, pip, frontend build
#   .\start-local.ps1 start     # Postgres+Redis (Docker) + API + worker
#   .\start-local.ps1 stop      # stop API/worker windows + Docker infra
#   .\start-local.ps1 status    # show what is running
#   .\start-local.ps1 restart   # stop then start
#
# Optional:
#   .\start-local.ps1 start -SkipDocker
#   .\start-local.ps1 start -WithExecutors
#   .\start-local.ps1 setup -SkipFrontendBuild

param(
    [Parameter(Position = 0)]
    [ValidateSet("setup", "start", "stop", "restart", "status")]
    [string]$Command = "start",

    [switch]$SkipDocker,
    [switch]$SkipFrontendBuild,
    [switch]$WithExecutors,
    [switch]$ResetWinNat
)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
Set-Location $Root

$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
$RqExe = Join-Path $Root ".venv\Scripts\rq.exe"
$UvicornExe = Join-Path $Root ".venv\Scripts\uvicorn.exe"
$FrontendOut = Join-Path $Root "frontend\out"
$PidDir = Join-Path $Root ".local-run"
$ApiPidFile = Join-Path $PidDir "api.pid"
$WorkerPidFile = Join-Path $PidDir "worker.pid"
$ApiScriptFile = Join-Path $PidDir "run-api.ps1"
$WorkerScriptFile = Join-Path $PidDir "run-worker.ps1"

$DefaultDatabaseUrl = "postgresql+psycopg2://devsecops:devsecops@localhost:5544/devsecops"
$DefaultRedisUrl = "redis://localhost:6399/0"

function Ensure-PidDir {
    if (-not (Test-Path $PidDir)) {
        New-Item -ItemType Directory -Path $PidDir | Out-Null
    }
}

function Load-DotEnv {
    $envFile = Join-Path $Root ".env"
    if (-not (Test-Path $envFile)) {
        $example = Join-Path $Root ".env.example"
        if (Test-Path $example) {
            Copy-Item $example $envFile
            Write-Host "Created .env from .env.example"
        }
    }
    if (-not (Test-Path $envFile)) { return }

    Get-Content $envFile | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#")) { return }
        $parts = $line -split "=", 2
        if ($parts.Count -ne 2) { return }
        $name = $parts[0].Trim()
        $value = $parts[1].Trim().Trim('"').Trim("'")
        if (-not [string]::IsNullOrWhiteSpace($name)) {
            Set-Item -Path "Env:$name" -Value $value
        }
    }
}

function Ensure-EnvDefaults {
    if (-not $env:DATABASE_URL) { $env:DATABASE_URL = $DefaultDatabaseUrl }
    if (-not $env:REDIS_URL) { $env:REDIS_URL = $DefaultRedisUrl }
    if (-not $env:EXECUTOR_SERVICE_KEY) { $env:EXECUTOR_SERVICE_KEY = "dev-executor-key" }
    if (-not $env:CONTROL_PLANE_URL) { $env:CONTROL_PLANE_URL = "http://127.0.0.1:8000" }
    if (-not $env:APP_HOST) { $env:APP_HOST = "127.0.0.1" }
    if (-not $env:APP_PORT) { $env:APP_PORT = "8000" }
}

function Assert-Venv {
    if (-not (Test-Path $VenvPython)) {
        throw "Virtualenv missing. Run: .\start-local.ps1 setup"
    }
}

function Invoke-Setup {
    Write-Host "==> Creating / updating virtualenv"
    if (-not (Test-Path $VenvPython)) {
        python -m venv .venv
    }

    Write-Host "==> Installing Python dependencies"
    & $VenvPython -m pip install --upgrade pip
    & $VenvPython -m pip install -r (Join-Path $Root "requirements.txt")

    if (-not $SkipFrontendBuild) {
        Write-Host "==> Building Next.js frontend"
        Push-Location (Join-Path $Root "frontend")
        try {
            if (-not (Test-Path "node_modules")) {
                npm install
            }
            npm run build
        }
        finally {
            Pop-Location
        }
    }
    else {
        Write-Host "==> Skipping frontend build (-SkipFrontendBuild)"
    }

    Load-DotEnv
    Write-Host ""
    Write-Host "Setup complete. Next: .\start-local.ps1 start"
}

function Start-Infra {
    if ($SkipDocker) {
        Write-Host "==> Skipping Docker infra (-SkipDocker). Expecting local Postgres/Redis."
        return
    }

    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw "Docker not found. Install Docker Desktop, or use: .\start-local.ps1 start -SkipDocker"
    }

    Write-Host "==> Starting Postgres + Redis (Docker)"
    docker compose up -d postgres redis

    Write-Host "==> Waiting for Postgres..."
    $ready = $false
    for ($i = 0; $i -lt 30; $i++) {
        docker exec devsecops-postgres pg_isready -U devsecops -d devsecops 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) { $ready = $true; break }
        Start-Sleep -Seconds 1
    }
    if (-not $ready) {
        throw "Postgres did not become ready in time."
    }

    Write-Host "==> Waiting for Redis..."
    $ready = $false
    for ($i = 0; $i -lt 30; $i++) {
        docker exec devsecops-redis redis-cli ping 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) { $ready = $true; break }
        Start-Sleep -Seconds 1
    }
    if (-not $ready) {
        throw "Redis did not become ready in time."
    }
}

function Get-ListenPids {
    param([int]$Port)

    $result = @()
    try {
        $result = @(
            Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
                Select-Object -ExpandProperty OwningProcess -Unique
        )
    }
    catch { }

    if ($result.Count -eq 0) {
        $lines = netstat -ano | Select-String (":" + $Port + "\s+.*LISTENING")
        foreach ($line in $lines) {
            $parts = @(($line.ToString() -split "\s+") | Where-Object { $_ })
            if ($parts.Count -ge 5) {
                $result += [int]$parts[-1]
            }
        }
        $result = @($result | Select-Object -Unique)
    }
    return @($result | Where-Object { $_ -and $_ -gt 0 })
}

function Stop-DockerPortPublishers {
    param([int]$Port)

    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { return }

    # Named API container from this project
    $apiContainer = docker ps -a --filter "name=devsecops-api" --format "{{.Names}} {{.Status}}" 2>$null
    if ($apiContainer -match "devsecops-api") {
        Write-Host ("    Stopping Docker container devsecops-api")
        docker rm -f devsecops-api 2>$null | Out-Null
    }

    # Any running container that publishes this host port
    $rows = docker ps --format "{{.ID}}|{{.Names}}|{{.Ports}}" 2>$null
    foreach ($row in $rows) {
        if (-not $row) { continue }
        if ($row -match (":" + $Port + "->") -or $row -match ("0\.0\.0\.0:" + $Port) -or $row -match ("\[::\]:" + $Port)) {
            $parts = $row -split "\|"
            $name = if ($parts.Count -ge 2) { $parts[1] } else { $parts[0] }
            Write-Host ("    Stopping Docker container publishing port " + $Port + ": " + $name)
            docker rm -f $parts[0] 2>$null | Out-Null
        }
    }
}

function Stop-PortProcessTree {
    param([int]$ProcId)

    if (-not $ProcId -or $ProcId -le 0) { return }

    # Prefer taskkill (tree + force); falls back to Stop-Process
    $null = & taskkill.exe /F /T /PID $ProcId 2>$null
    Get-CimInstance Win32_Process -Filter ("ParentProcessId = " + $ProcId) -ErrorAction SilentlyContinue |
        ForEach-Object {
            $null = & taskkill.exe /F /T /PID $_.ProcessId 2>$null
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        }
    Stop-Process -Id $ProcId -Force -ErrorAction SilentlyContinue
}

function Stop-MatchingAppProcesses {
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            $_.CommandLine -and (
                ($_.CommandLine -like "*uvicorn*app.main:app*") -or
                ($_.CommandLine -like "*uvicorn.exe*app.main:app*") -or
                ($_.CommandLine -like "*\start-local.ps1*") -or
                ($_.CommandLine -like "*run-api.ps1*")
            )
        } |
        ForEach-Object {
            Write-Host ("    Stopping related process " + $_.Name + " (pid " + $_.ProcessId + ")")
            Stop-PortProcessTree -ProcId ([int]$_.ProcessId)
        }
}

function Reset-WinNatIfNeeded {
    # Ghost LISTENING sockets (PID gone, port still held) are common with Docker Desktop.
    # Restarting WinNAT can clear them, but needs elevation. Only runs when -ResetWinNat is passed.
    if (-not $ResetWinNat) {
        return $false
    }

    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    $isAdmin = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

    $resetCmd = "net stop winnat & net start winnat"
    if (-not $isAdmin) {
        Write-Host "    Requesting Administrator approval to restart WinNAT (UAC prompt)..."
        try {
            $p = Start-Process -FilePath "cmd.exe" -ArgumentList "/c", $resetCmd -Verb RunAs -Wait -PassThru
            Start-Sleep -Seconds 2
            return ($p.ExitCode -eq 0)
        }
        catch {
            Write-Host "    UAC was cancelled or elevation failed."
            return $false
        }
    }

    Write-Host "    Restarting WinNAT to clear ghost Docker port binding..."
    try {
        $null = & net.exe stop winnat 2>$null
        Start-Sleep -Seconds 1
        $null = & net.exe start winnat 2>$null
        Start-Sleep -Seconds 2
        return $true
    }
    catch {
        Write-Host ("    WinNAT restart failed: " + $_.Exception.Message)
        return $false
    }
}

function Test-PortFree {
    param([int]$Port)
    return (@(Get-ListenPids -Port $Port).Count -eq 0)
}

function Find-FreePort {
    param(
        [int]$PreferredPort,
        [int[]]$Candidates = @(8000, 8001, 8002, 8010, 8080, 8800)
    )

    $ordered = @($PreferredPort) + @($Candidates | Where-Object { $_ -ne $PreferredPort })
    foreach ($candidate in $ordered) {
        if (Test-PortFree -Port $candidate) {
            return $candidate
        }
    }
    throw "No free TCP port found among: $($ordered -join ', ')"
}

function Clear-ListenPort {
    param(
        [Parameter(Mandatory = $true)]
        [int]$Port
    )

    Write-Host ("==> Checking port " + $Port)

    Stop-DockerPortPublishers -Port $Port
    Stop-MatchingAppProcesses

    for ($attempt = 1; $attempt -le 3; $attempt++) {
        if (Test-PortFree -Port $Port) {
            Write-Host ("    Port " + $Port + " is free")
            return $true
        }

        $pids = @(Get-ListenPids -Port $Port)
        $hadLiveProcess = $false
        foreach ($procId in $pids) {
            $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
            if ($proc) {
                $hadLiveProcess = $true
                Write-Host ("    Port " + $Port + " in use by " + $proc.ProcessName + " (pid " + $procId + ") - stopping it (attempt " + $attempt + ")")
                Stop-PortProcessTree -ProcId $procId
            }
            else {
                Write-Host ("    Port " + $Port + " shows ghost pid " + $procId + " (process already gone)")
            }
        }

        Start-Sleep -Seconds 1
        if (Test-PortFree -Port $Port) {
            Write-Host ("    Port " + $Port + " cleared")
            return $true
        }

        # Only ghost PIDs left - try WinNAT reset once
        if (-not $hadLiveProcess -and $attempt -eq 1) {
            $reset = Reset-WinNatIfNeeded
            if ($reset) {
                Start-Sleep -Seconds 2
                if (Test-PortFree -Port $Port) {
                    Write-Host ("    Port " + $Port + " cleared after WinNAT reset")
                    return $true
                }
            }
        }
    }

    Write-Host ("    Could not free port " + $Port + " (ghost Docker/Windows binding). Will use another port.")
    return $false
}

function Write-ChildScripts {
    param(
        [string]$HostName,
        [string]$Port,
        [string]$DbUrl,
        [string]$RedisUrl,
        [string]$ExecutorKey,
        [string]$ControlPlane
    )

    $apiLines = @(
        '$ErrorActionPreference = "Stop"'
        ('Set-Location "' + $Root + '"')
        ('$env:DATABASE_URL = "' + $DbUrl + '"')
        ('$env:REDIS_URL = "' + $RedisUrl + '"')
        ('$env:EXECUTOR_SERVICE_KEY = "' + $ExecutorKey + '"')
        ('$env:CONTROL_PLANE_URL = "' + $ControlPlane + '"')
        ('$env:APP_HOST = "' + $HostName + '"')
        ('$env:APP_PORT = "' + $Port + '"')
        ('Write-Host "API listening on http://' + $HostName + ':' + $Port + '"')
        ('& "' + $UvicornExe + '" app.main:app --reload --host ' + $HostName + ' --port ' + $Port)
    )
    Set-Content -Path $ApiScriptFile -Value $apiLines -Encoding UTF8

    $workerLines = @(
        '$ErrorActionPreference = "Stop"'
        ('Set-Location "' + $Root + '"')
        ('$env:DATABASE_URL = "' + $DbUrl + '"')
        ('$env:REDIS_URL = "' + $RedisUrl + '"')
        'Write-Host "RQ worker listening on queue: intelligence"'
        ('& "' + $RqExe + '" worker intelligence --worker-class app.intelligence.worker.Worker --url ' + $RedisUrl)
    )
    Set-Content -Path $WorkerScriptFile -Value $workerLines -Encoding UTF8
}

function Start-AppProcesses {
    Assert-Venv
    Load-DotEnv
    Ensure-EnvDefaults
    Ensure-PidDir

    if (-not (Test-Path $FrontendOut)) {
        throw "frontend\out is missing. Run: .\start-local.ps1 setup"
    }

    $hostName = $env:APP_HOST
    $preferredPort = [int]$env:APP_PORT
    $dbUrl = $env:DATABASE_URL
    $redisUrl = $env:REDIS_URL
    $executorKey = $env:EXECUTOR_SERVICE_KEY

    Stop-AppProcesses -Quiet

    $cleared = Clear-ListenPort -Port $preferredPort
    if ($cleared) {
        $port = $preferredPort
    }
    else {
        $port = Find-FreePort -PreferredPort $preferredPort
        Write-Host ("==> Using fallback port " + $port + " because " + $preferredPort + " is stuck")
    }

    $env:APP_PORT = [string]$port
    $controlPlane = "http://" + $hostName + ":" + $port
    $env:CONTROL_PLANE_URL = $controlPlane

    Write-ChildScripts -HostName $hostName -Port ([string]$port) -DbUrl $dbUrl -RedisUrl $redisUrl -ExecutorKey $executorKey -ControlPlane $controlPlane

    Write-Host "==> Starting API window"
    $apiProc = Start-Process powershell -PassThru -ArgumentList @(
        "-NoExit",
        "-ExecutionPolicy", "Bypass",
        "-File", $ApiScriptFile
    )
    Set-Content -Path $ApiPidFile -Value $apiProc.Id

    Write-Host "==> Starting worker window"
    $workerProc = Start-Process powershell -PassThru -ArgumentList @(
        "-NoExit",
        "-ExecutionPolicy", "Bypass",
        "-File", $WorkerScriptFile
    )
    Set-Content -Path $WorkerPidFile -Value $workerProc.Id

    if ($WithExecutors) {
        Write-Host "==> Starting provider executors (Docker)"
        docker compose -f docker-compose.local-executors.yml up --build -d
    }

    Write-Host ""
    Write-Host "Local stack is up."
    Write-Host ("  Chat:      http://" + $hostName + ":" + $port)
    Write-Host ("  Dashboard: http://" + $hostName + ":" + $port + "/dashboard")
    Write-Host ("  Settings:  http://" + $hostName + ":" + $port + "/settings")
    if ($port -ne $preferredPort) {
        Write-Host ""
        Write-Host ("Note: preferred port " + $preferredPort + " is a Windows/Docker ghost binding.")
        Write-Host "To reclaim it later (Admin PowerShell): net stop winnat & net start winnat"
        Write-Host "Or restart Docker Desktop / reboot."
    }
    Write-Host ""
    Write-Host "Stop with: .\start-local.ps1 stop"
}

function Stop-ProcessFromPidFile {
    param([string]$Path, [string]$Label, [switch]$Quiet)

    if (-not (Test-Path $Path)) {
        if (-not $Quiet) { Write-Host ("No saved " + $Label + " pid.") }
        return
    }

    $procId = (Get-Content $Path -ErrorAction SilentlyContinue | Select-Object -First 1).Trim()
    if ($procId -and ($procId -as [int])) {
        $proc = Get-Process -Id ([int]$procId) -ErrorAction SilentlyContinue
        if ($proc) {
            Get-CimInstance Win32_Process -Filter ("ParentProcessId = " + $procId) -ErrorAction SilentlyContinue |
                ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
            Stop-Process -Id ([int]$procId) -Force -ErrorAction SilentlyContinue
            if (-not $Quiet) { Write-Host ("Stopped " + $Label + " (pid " + $procId + ")") }
        }
        elseif (-not $Quiet) {
            Write-Host ($Label + " process already exited (pid " + $procId + ")")
        }
    }
    Remove-Item $Path -Force -ErrorAction SilentlyContinue
}

function Stop-AppProcesses {
    param([switch]$Quiet)

    Stop-ProcessFromPidFile -Path $ApiPidFile -Label "API" -Quiet:$Quiet
    Stop-ProcessFromPidFile -Path $WorkerPidFile -Label "worker" -Quiet:$Quiet

    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            $_.CommandLine -and (
                ($_.CommandLine -like "*uvicorn*app.main:app*") -or
                ($_.CommandLine -like "*rq.exe*worker*intelligence*")
            )
        } |
        ForEach-Object {
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
            if (-not $Quiet) { Write-Host ("Stopped leftover process " + $_.ProcessId) }
        }
}

function Invoke-Stop {
    Write-Host "==> Stopping local API / worker"
    Stop-AppProcesses

    if (-not $SkipDocker) {
        if (Get-Command docker -ErrorAction SilentlyContinue) {
            Write-Host "==> Stopping Docker infra (postgres/redis)"
            docker compose stop postgres redis 2>$null
            if ($WithExecutors -or (Test-Path (Join-Path $Root "docker-compose.local-executors.yml"))) {
                docker compose -f docker-compose.local-executors.yml down 2>$null
            }
        }
    }

    Write-Host "Stopped."
}

function Invoke-Status {
    Write-Host ("Project: " + $Root)
    Write-Host ""

    if (Test-Path $VenvPython) { Write-Host "venv:          ok" } else { Write-Host "venv:          missing (run setup)" }
    if (Test-Path $FrontendOut) { Write-Host "frontend/out:  ok" } else { Write-Host "frontend/out:  missing (run setup)" }

    foreach ($pair in @(
        @{ Name = "API"; File = $ApiPidFile },
        @{ Name = "worker"; File = $WorkerPidFile }
    )) {
        if (Test-Path $pair.File) {
            $procId = (Get-Content $pair.File | Select-Object -First 1).Trim()
            $alive = Get-Process -Id ([int]$procId) -ErrorAction SilentlyContinue
            if ($alive) {
                Write-Host ((" {0,-13} running (pid {1})" -f ($pair.Name + ":"), $procId).TrimStart())
            }
            else {
                Write-Host ((" {0,-13} stale pid file ({1})" -f ($pair.Name + ":"), $procId).TrimStart())
            }
        }
        else {
            Write-Host ((" {0,-13} not managed" -f ($pair.Name + ":")).TrimStart())
        }
    }

    if (Get-Command docker -ErrorAction SilentlyContinue) {
        Write-Host ""
        Write-Host "Docker containers:"
        docker ps --filter "name=devsecops-" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
    }
}

switch ($Command) {
    "setup" { Invoke-Setup }
    "start" {
        Start-Infra
        Start-AppProcesses
    }
    "stop" { Invoke-Stop }
    "restart" {
        Invoke-Stop
        Start-Sleep -Seconds 1
        Start-Infra
        Start-AppProcesses
    }
    "status" { Invoke-Status }
}
