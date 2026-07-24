# DevSecOps Skills Suite - local run helper (Windows PowerShell)
#
# Setup always uses Python 3.12 for .venv. If the PC only has 3.13/3.14,
# the script installs Python 3.12 automatically (winget, then official installer).
#
# `start` runs live reload:
#   - API (uvicorn --reload) in a CMD window
#   - RQ worker in a CMD window
#   - Next.js `next dev` (HMR) in a CMD window  -> open FRONTEND_PORT (3000)
#
# Usage:
#   .\start-local.ps1 setup     # one-time: Python 3.12 venv, pip, frontend deps/build
#   .\start-local.ps1 start     # Postgres+Redis + live API/worker/frontend (CMD windows)
#   .\start-local.ps1 stop      # stop CMD windows + Docker infra
#   .\start-local.ps1 status    # show what is running
#   .\start-local.ps1 restart   # stop then start
#
# Optional:
#   .\start-local.ps1 start -SkipDocker
#   .\start-local.ps1 start -WithExecutors
#   .\start-local.ps1 setup -SkipFrontendBuild
#   .\start-local.ps1 start -ResetWinNat

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
$FrontendDir = Join-Path $Root "frontend"
$FrontendOut = Join-Path $Root "frontend\out"
$PidDir = Join-Path $Root ".local-run"
$ApiPidFile = Join-Path $PidDir "api.pid"
$WorkerPidFile = Join-Path $PidDir "worker.pid"
$FrontendPidFile = Join-Path $PidDir "frontend.pid"
$ApiScriptFile = Join-Path $PidDir "run-api.cmd"
$WorkerScriptFile = Join-Path $PidDir "run-worker.cmd"
$FrontendScriptFile = Join-Path $PidDir "run-frontend.cmd"

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
    if (-not $env:FRONTEND_HOST) { $env:FRONTEND_HOST = "127.0.0.1" }
    if (-not $env:FRONTEND_PORT) { $env:FRONTEND_PORT = "3000" }
    if (-not $env:DEV_API_ORIGIN) {
        $env:DEV_API_ORIGIN = ("http://" + $env:APP_HOST + ":" + $env:APP_PORT)
    }
}

function Assert-Venv {
    if (-not (Test-Path $VenvPython)) {
        throw "Virtualenv missing. Run: .\start-local.ps1 setup"
    }
}

function Invoke-Native {
    # Run a native exe with args via cmd.exe so PowerShell cannot mangle
    # values like -3.12 into numbers / split options.
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string[]]$ArgumentList = @()
    )

    $argLine = ($ArgumentList | ForEach-Object {
        $a = [string]$_
        if ($a -match '[\s"]') { '"' + ($a -replace '"', '\"') + '"' } else { $a }
    }) -join " "

    $cmd = '"' + $FilePath + '"'
    if ($argLine) { $cmd = $cmd + " " + $argLine }

    $oldEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $output = & cmd.exe /c $cmd 2>&1
    $code = $LASTEXITCODE
    $ErrorActionPreference = $oldEap

    return @{
        ExitCode = $code
        Output = (($output | Out-String).Trim())
    }
}

function Get-PythonByMinor {
    param([Parameter(Mandatory = $true)][int]$Minor)

    # Always return a real python.exe path. Never return "py -3.12" because
    # PowerShell parses -3.12 as a number and ends up calling the wrong Python.
    $pathCandidates = @(
        "$env:LocalAppData\Programs\Python\Python3$Minor\python.exe",
        "$env:LocalAppData\Python\pythoncore-3.$Minor-64\python.exe",
        "$env:LocalAppData\Python\pythoncore-3.$Minor-32\python.exe",
        "${env:ProgramFiles}\Python3$Minor\python.exe",
        "${env:ProgramFiles}\Python\Python3$Minor\python.exe",
        "C:\Python3$Minor\python.exe"
    )

    foreach ($path in $pathCandidates) {
        if (-not (Test-Path $path)) { continue }
        $result = Invoke-Native -FilePath $path -ArgumentList @(
            "-c",
            ("import sys; assert sys.version_info[:2]==(3,{0}); print('%s.%s.%s' % sys.version_info[:3])" -f $Minor)
        )
        if ($result.ExitCode -eq 0 -and $result.Output) {
            return @{
                Exe = $path
                Args = @()
                Minor = $Minor
                Version = ($result.Output -split "`r?`n" | Select-Object -Last 1).Trim()
                Display = $path
            }
        }
    }

    # Ask the py launcher for the absolute interpreter path (via cmd, not PS splat)
    $pyCmd = Get-Command py.exe -ErrorAction SilentlyContinue
    if (-not $pyCmd) { $pyCmd = Get-Command py -ErrorAction SilentlyContinue }
    if ($pyCmd) {
        $launcher = $pyCmd.Source
        $result = Invoke-Native -FilePath $launcher -ArgumentList @(
            "-3.$Minor",
            "-c",
            "import sys; print(sys.executable); print('%s.%s.%s' % sys.version_info[:3])"
        )
        if ($result.ExitCode -eq 0 -and $result.Output) {
            $lines = @($result.Output -split "`r?`n" | Where-Object { $_.Trim() })
            if ($lines.Count -ge 2) {
                $exePath = $lines[0].Trim()
                $ver = $lines[1].Trim()
                if ((Test-Path $exePath) -and $ver.StartsWith("3.$Minor")) {
                    return @{
                        Exe = $exePath
                        Args = @()
                        Minor = $Minor
                        Version = $ver
                        Display = $exePath
                    }
                }
            }
        }
    }

    return $null
}

function Refresh-ProcessPath {
    $machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $user = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = ($machine + ";" + $user)
}

function Install-Python312 {
    Write-Host "==> Python 3.12 not found - installing it automatically"

    # 1) winget (preferred on modern Windows)
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Write-Host "    Installing Python.Python.3.12 via winget..."
        $oldEap = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        & winget install -e --id Python.Python.3.12 `
            --accept-package-agreements `
            --accept-source-agreements `
            --disable-interactivity
        $wingetCode = $LASTEXITCODE
        $ErrorActionPreference = $oldEap
        Write-Host ("    winget exit code: " + $wingetCode)
        Refresh-ProcessPath
        Start-Sleep -Seconds 3
        $py = Get-PythonByMinor -Minor 12
        if ($py) { return $py }
    }
    else {
        Write-Host "    winget not available - trying official installer download"
    }

    # 2) Official silent installer fallback
    $installerUrl = "https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe"
    $installerPath = Join-Path $env:TEMP "python-3.12.10-amd64.exe"
    Write-Host ("    Downloading " + $installerUrl)
    try {
        Invoke-WebRequest -Uri $installerUrl -OutFile $installerPath -UseBasicParsing
        Write-Host "    Running silent Python 3.12 installer..."
        $proc = Start-Process -FilePath $installerPath -ArgumentList @(
            "/quiet",
            "InstallAllUsers=0",
            "PrependPath=1",
            "Include_launcher=1",
            "Include_pip=1",
            "Include_test=0"
        ) -Wait -PassThru
        Refresh-ProcessPath
        Start-Sleep -Seconds 3
        $py = Get-PythonByMinor -Minor 12
        if ($py) { return $py }
        Write-Host ("    Installer exited with code " + $proc.ExitCode)
    }
    catch {
        Write-Host ("    Official installer failed: " + $_.Exception.Message)
    }

    return $null
}

function Ensure-Python312 {
    $py = Get-PythonByMinor -Minor 12
    if ($py) {
        Write-Host ("    Found Python " + $py.Version + " at " + $py.Exe)
        return $py
    }

    $py = Install-Python312
    if ($py) {
        Write-Host ("    Python " + $py.Version + " is ready at " + $py.Exe)
        return $py
    }

    # Last resort only if install failed hard
    $fallback = Get-PythonByMinor -Minor 11
    if ($fallback) {
        Write-Host "    WARNING: could not install Python 3.12; falling back to 3.11"
        return $fallback
    }

    throw @"
Could not find or install Python 3.12 automatically.
Install winget / allow the installer, or install Python 3.12 manually, then re-run:
  .\start-local.ps1 setup
"@
}

function Get-VenvPythonMinor {
    if (-not (Test-Path $VenvPython)) { return $null }
    try {
        $result = Invoke-Native -FilePath $VenvPython -ArgumentList @(
            "-c",
            "import sys; print('%s.%s' % sys.version_info[:2])"
        )
        if ($result.ExitCode -ne 0 -or -not $result.Output) { return $null }
        return ($result.Output -split "`r?`n" | Select-Object -Last 1).Trim()
    }
    catch {
        return $null
    }
}

function Invoke-Setup {
    Write-Host "==> Ensuring Python 3.12 for .venv (auto-installs if system has 3.13/3.14 only)"
    $py = Ensure-Python312

    $existingMinor = Get-VenvPythonMinor
    $allowed = @("3.11", "3.12")
    if ($existingMinor -and ($allowed -notcontains $existingMinor)) {
        Write-Host ("    Existing .venv is Python " + $existingMinor + " - recreating with " + $py.Version)
        Remove-Item -Recurse -Force (Join-Path $Root ".venv")
    }
    elseif ($existingMinor -and $py.Minor -eq 12 -and $existingMinor -ne "3.12") {
        Write-Host ("    Existing .venv is Python " + $existingMinor + " - upgrading to 3.12")
        Remove-Item -Recurse -Force (Join-Path $Root ".venv")
    }

    if (-not (Test-Path $VenvPython)) {
        Write-Host ("    Creating .venv with Python " + $py.Version)
        Write-Host ("    Interpreter: " + $py.Exe)
        $create = Invoke-Native -FilePath $py.Exe -ArgumentList @("-m", "venv", ".venv")
        if ($create.ExitCode -ne 0 -or -not (Test-Path $VenvPython)) {
            if ($create.Output) { Write-Host $create.Output }
            throw ("Failed to create .venv with Python " + $py.Version + " (" + $py.Exe + ")")
        }
    }
    else {
        $verResult = Invoke-Native -FilePath $VenvPython -ArgumentList @(
            "-c",
            "import sys; print('%s.%s.%s' % sys.version_info[:3])"
        )
        Write-Host ("    Using existing Python " + $verResult.Output + " venv")
    }

    $confirm = Get-VenvPythonMinor
    if ($allowed -notcontains $confirm) {
        throw ("Expected .venv Python 3.11/3.12 but found " + $confirm + ". Delete .venv and re-run setup.")
    }

    Write-Host "==> Installing Python dependencies"
    $pipUpgrade = Invoke-Native -FilePath $VenvPython -ArgumentList @("-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel")
    if ($pipUpgrade.ExitCode -ne 0) {
        if ($pipUpgrade.Output) { Write-Host $pipUpgrade.Output }
        throw "Failed to upgrade pip/setuptools/wheel"
    }

    # Prefer wheels so psycopg2-binary does not try to compile (needs pg_config).
    $reqFile = Join-Path $Root "requirements.txt"
    $pipInstall = Invoke-Native -FilePath $VenvPython -ArgumentList @(
        "-m", "pip", "install", "--prefer-binary", "-r", $reqFile
    )
    if ($pipInstall.ExitCode -ne 0) {
        if ($pipInstall.Output) { Write-Host $pipInstall.Output }
        throw @"
Failed to install Python dependencies.
If you see 'pg_config executable not found', delete .venv and re-run setup with Python 3.12:
  Remove-Item -Recurse -Force .venv
  .\start-local.ps1 setup
"@
    }

    if (-not $SkipFrontendBuild) {
        Write-Host "==> Building Next.js frontend"
        Push-Location (Join-Path $Root "frontend")
        try {
            if (-not (Test-Path "node_modules")) {
                npm install
            }
            npm run build
            if ($LASTEXITCODE -ne 0) {
                throw "Frontend build failed"
            }
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
    Write-Host ("Setup complete (Python " + $confirm + "). Next: .\start-local.ps1 start")
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
    # Only stop API/worker runtimes. Never match start-local.ps1 itself or the
    # helper scripts, or we kill the current setup/start process mid-run.
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            $_.CommandLine -and (
                ($_.CommandLine -like "*uvicorn*app.main:app*") -or
                ($_.CommandLine -like "*uvicorn.exe*app.main:app*") -or
                ($_.CommandLine -like "*rq.exe*worker*intelligence*") -or
                ($_.CommandLine -like "*rq worker intelligence*")
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

function Write-Utf8NoBomFile {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string[]]$Lines
    )
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllLines($Path, $Lines, $utf8NoBom)
}

function Escape-CmdSetValue {
    param([string]$Value)
    if ($null -eq $Value) { return "" }
    # cmd set values: escape special chars that break the line
    return ($Value -replace '([&|<>^])', '^$1')
}

function Get-NodeExe {
    $candidates = @(
        (Get-Command node.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source),
        "$env:ProgramFiles\nodejs\node.exe",
        "${env:ProgramFiles(x86)}\nodejs\node.exe",
        "$env:LOCALAPPDATA\Programs\node\node.exe"
    ) | Where-Object { $_ }
    foreach ($path in $candidates) {
        if (Test-Path $path) { return $path }
    }
    throw "node.exe not found. Install Node.js 20+ from https://nodejs.org/ and re-run setup."
}

function Wait-HttpReady {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [string]$Label = "service",
        [int]$TimeoutSec = 60
    )
    Write-Host ("==> Waiting for " + $Label + " at " + $Url)
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        try {
            $resp = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2
            if ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 500) {
                Write-Host ("    " + $Label + " is up")
                return $true
            }
        }
        catch {
            Start-Sleep -Milliseconds 800
        }
    }
    Write-Host ("    WARNING: " + $Label + " did not become ready within " + $TimeoutSec + "s")
    return $false
}

function Write-ChildScripts {
    param(
        [string]$HostName,
        [string]$Port,
        [string]$FrontendHost,
        [string]$FrontendPort,
        [string]$DbUrl,
        [string]$RedisUrl,
        [string]$ExecutorKey,
        [string]$ControlPlane,
        [string]$DevApiOrigin
    )

    $db = Escape-CmdSetValue $DbUrl
    $redis = Escape-CmdSetValue $RedisUrl
    $execKey = Escape-CmdSetValue $ExecutorKey
    $cp = Escape-CmdSetValue $ControlPlane
    $devApi = Escape-CmdSetValue $DevApiOrigin

    $nodeExe = Get-NodeExe
    $nextCli = Join-Path $FrontendDir "node_modules\next\dist\bin\next"
    if (-not (Test-Path $nextCli)) {
        throw "Next.js is not installed in frontend\node_modules. Run: .\start-local.ps1 setup"
    }

    $apiLines = @(
        "@echo off"
        "title DevSecOps API"
        "cd /d `"$Root`""
        "set `"DATABASE_URL=$db`""
        "set `"REDIS_URL=$redis`""
        "set `"EXECUTOR_SERVICE_KEY=$execKey`""
        "set `"CONTROL_PLANE_URL=$cp`""
        "set `"APP_HOST=$HostName`""
        "set `"APP_PORT=$Port`""
        "echo DevSecOps API - leave this CMD window open"
        "echo API (hot reload) on http://${HostName}:${Port}"
        "echo."
        "`"$UvicornExe`" app.main:app --reload --host $HostName --port $Port"
        "echo."
        "echo API exited. Press any key to close this window."
        "pause >nul"
    )
    Write-Utf8NoBomFile -Path $ApiScriptFile -Lines $apiLines

    $workerLines = @(
        "@echo off"
        "title DevSecOps Worker"
        "cd /d `"$Root`""
        "set `"DATABASE_URL=$db`""
        "set `"REDIS_URL=$redis`""
        "echo DevSecOps Worker - leave this CMD window open"
        "echo RQ worker listening on queue: intelligence"
        "echo."
        "`"$RqExe`" worker intelligence --worker-class app.intelligence.worker.Worker --url $redis"
        "echo."
        "echo Worker exited. Press any key to close this window."
        "pause >nul"
    )
    Write-Utf8NoBomFile -Path $WorkerScriptFile -Lines $workerLines

    # Use absolute node.exe + next CLI so detached CMD works even when npm is not on PATH.
    $frontendLines = @(
        "@echo off"
        "title DevSecOps Frontend"
        "cd /d `"$FrontendDir`""
        "set `"DEV_API_ORIGIN=$devApi`""
        "set `"NEXT_PUBLIC_API_BASE=$devApi`""
        "set `"NODE_ENV=development`""
        "echo DevSecOps Frontend (Next.js live reload) - leave this CMD window open"
        "echo UI with hot reload: http://${FrontendHost}:${FrontendPort}"
        "echo API calls go directly to: $devApi"
        "echo Node: $nodeExe"
        "echo."
        "if not exist `"node_modules\next\dist\bin\next`" ("
        "  echo ERROR: frontend dependencies missing. Run: .\start-local.ps1 setup"
        "  pause"
        "  exit /b 1"
        ")"
        "`"$nodeExe`" `"$nextCli`" dev --hostname $FrontendHost --port $FrontendPort"
        "echo."
        "echo Frontend exited. If this failed, check Node/Next install and re-run setup."
        "echo Press any key to close this window."
        "pause >nul"
    )
    Write-Utf8NoBomFile -Path $FrontendScriptFile -Lines $frontendLines
}

function Start-DetachedCmdWindow {
    param(
        [Parameter(Mandatory = $true)][string]$Title,
        [Parameter(Mandatory = $true)][string]$ScriptPath
    )

    # Fully detach a CMD window from Cursor/VS Code/Windows Terminal job objects.
    $cmdline = 'start "' + $Title + '" cmd.exe /k call "' + $ScriptPath + '"'
    $oldEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & cmd.exe /c $cmdline
    $ErrorActionPreference = $oldEap
}

function Start-AppProcesses {
    Assert-Venv
    Load-DotEnv
    Ensure-EnvDefaults
    Ensure-PidDir

    $nodeModules = Join-Path $FrontendDir "node_modules"
    if (-not (Test-Path $nodeModules)) {
        throw "frontend\node_modules is missing. Run: .\start-local.ps1 setup"
    }

    $hostName = $env:APP_HOST
    $preferredPort = [int]$env:APP_PORT
    $frontendHost = $env:FRONTEND_HOST
    $frontendPort = [int]$env:FRONTEND_PORT
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
        Write-Host ("==> Using fallback API port " + $port + " because " + $preferredPort + " is stuck")
    }

    if (-not (Test-PortFree -Port $frontendPort)) {
        Write-Host ("==> Frontend port " + $frontendPort + " is busy - freeing it")
        Clear-ListenPort -Port $frontendPort | Out-Null
        if (-not (Test-PortFree -Port $frontendPort)) {
            $frontendPort = Find-FreePort -PreferredPort $frontendPort -Candidates @(3000, 3001, 3002, 3010, 3030)
            Write-Host ("==> Using fallback frontend port " + $frontendPort)
        }
    }

    $env:APP_PORT = [string]$port
    $env:FRONTEND_PORT = [string]$frontendPort
    $controlPlane = "http://" + $hostName + ":" + $port
    $env:CONTROL_PLANE_URL = $controlPlane
    $devApiOrigin = "http://" + $hostName + ":" + $port
    $env:DEV_API_ORIGIN = $devApiOrigin

    Write-ChildScripts `
        -HostName $hostName `
        -Port ([string]$port) `
        -FrontendHost $frontendHost `
        -FrontendPort ([string]$frontendPort) `
        -DbUrl $dbUrl `
        -RedisUrl $redisUrl `
        -ExecutorKey $executorKey `
        -ControlPlane $controlPlane `
        -DevApiOrigin $devApiOrigin

    Write-Host "==> Starting detached CMD windows (API + worker + live frontend)"
    Start-DetachedCmdWindow -Title "DevSecOps API" -ScriptPath $ApiScriptFile
    Start-DetachedCmdWindow -Title "DevSecOps Worker" -ScriptPath $WorkerScriptFile
    Start-DetachedCmdWindow -Title "DevSecOps Frontend" -ScriptPath $FrontendScriptFile

    Start-Sleep -Seconds 2
    $apiReady = Wait-HttpReady -Url ("http://" + $hostName + ":" + $port + "/api/health") -Label "API" -TimeoutSec 45
    $uiReady = Wait-HttpReady -Url ("http://" + $frontendHost + ":" + $frontendPort + "/") -Label "Frontend" -TimeoutSec 90

    if ($WithExecutors) {
        Write-Host "==> Starting provider executors (Docker)"
        docker compose -f docker-compose.local-executors.yml up --build -d
    }

    Write-Host ""
    if ($uiReady) {
        Write-Host "Local stack is up in separate CMD windows."
    }
    else {
        Write-Host "API/worker may be up, but the Frontend window failed to become ready."
        Write-Host "Open the 'DevSecOps Frontend' CMD window and read the error."
        Write-Host "Common fix: .\start-local.ps1 setup   then   .\start-local.ps1 start"
    }
    Write-Host ("  UI (live):  http://" + $frontendHost + ":" + $frontendPort)
    Write-Host ("  API:        http://" + $hostName + ":" + $port)
    Write-Host ("  Dashboard:  http://" + $frontendHost + ":" + $frontendPort + "/dashboard")
    if (-not $apiReady) {
        Write-Host "  WARNING: API health check did not succeed yet - check the API CMD window."
    }
    Write-Host ""
    Write-Host "Edit frontend or Python code - changes reload automatically."
    Write-Host "Keep the three CMD windows open. Closing them stops the app."
    if ($port -ne $preferredPort) {
        Write-Host ""
        Write-Host ("Note: preferred API port " + $preferredPort + " is a Windows/Docker ghost binding.")
        Write-Host "To reclaim it later (Admin PowerShell): net stop winnat & net start winnat"
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
            Stop-PortProcessTree -ProcId ([int]$procId)
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
    Stop-ProcessFromPidFile -Path $FrontendPidFile -Label "frontend" -Quiet:$Quiet

    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            $_.CommandLine -and (
                ($_.CommandLine -like "*uvicorn*app.main:app*") -or
                ($_.CommandLine -like "*rq.exe*worker*intelligence*") -or
                ($_.CommandLine -like "*rq worker intelligence*") -or
                ($_.CommandLine -like "*run-api.cmd*") -or
                ($_.CommandLine -like "*run-worker.cmd*") -or
                ($_.CommandLine -like "*run-frontend.cmd*") -or
                (
                    ($_.CommandLine -like "*next*dev*") -and
                    ($_.CommandLine -like "*frontend*")
                )
            )
        } |
        ForEach-Object {
            Stop-PortProcessTree -ProcId ([int]$_.ProcessId)
            if (-not $Quiet) { Write-Host ("Stopped leftover process " + $_.ProcessId) }
        }

    # Also close titled CMD windows if still around
    Get-Process -Name cmd -ErrorAction SilentlyContinue | ForEach-Object {
        try {
            if ($_.MainWindowTitle -match '^DevSecOps (API|Worker|Frontend)') {
                Stop-PortProcessTree -ProcId $_.Id
                if (-not $Quiet) { Write-Host ("Stopped CMD window: " + $_.MainWindowTitle) }
            }
        }
        catch { }
    }
}

function Invoke-Stop {
    Write-Host "==> Stopping local API / worker / frontend"
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

    if (Test-Path $VenvPython) { Write-Host "venv:              ok" } else { Write-Host "venv:              missing (run setup)" }
    if (Test-Path (Join-Path $FrontendDir "node_modules")) { Write-Host "frontend deps:     ok" } else { Write-Host "frontend deps:     missing (run setup)" }
    if (Test-Path $FrontendOut) { Write-Host "frontend/out:      ok (static build)" } else { Write-Host "frontend/out:      not built (optional for live start)" }

    $titles = @{}
    Get-Process -Name cmd -ErrorAction SilentlyContinue | ForEach-Object {
        if ($_.MainWindowTitle -match '^DevSecOps (API|Worker|Frontend)') {
            $titles[$_.MainWindowTitle] = $_.Id
        }
    }
    foreach ($name in @("DevSecOps API", "DevSecOps Worker", "DevSecOps Frontend")) {
        if ($titles.ContainsKey($name)) {
            Write-Host ("{0,-18} running (pid {1})" -f ($name + ":"), $titles[$name])
        }
        else {
            Write-Host ("{0,-18} not running" -f ($name + ":"))
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
