#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Security Client — Windows Installer
.DESCRIPTION
    Installs the Security Client and registers it as a Windows Scheduled Task
    that starts automatically with the system and runs as SYSTEM.
    Requires PowerShell 5.1+, Windows 10/Server 2016+, internet access.
.EXAMPLE
    # From an elevated PowerShell prompt:
    Set-ExecutionPolicy Bypass -Scope Process -Force
    .\install_windows.ps1
.PARAMETER InstallDir
    Target installation directory (default: C:\SecurityClient)
.PARAMETER TaskName
    Windows Scheduled Task name (default: SecurityClient)
#>
[CmdletBinding()]
param(
    [string]$InstallDir = 'C:\SecurityClient',
    [string]$TaskName   = 'SecurityClient'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Write-Info { param($m) Write-Host "[INFO]  $m" -ForegroundColor Green  }
function Write-Warn { param($m) Write-Host "[WARN]  $m" -ForegroundColor Yellow }
function Write-Step { param($m) Write-Host "`n--- $m ---" -ForegroundColor Cyan   }

# ---------------------------------------------------------------------------
# 1. Python 3.10+ detection / installation
# ---------------------------------------------------------------------------
Write-Step 'Checking Python'

function Find-Python {
    foreach ($cmd in @('python', 'python3', 'py')) {
        $exe = Get-Command $cmd -ErrorAction SilentlyContinue
        if (-not $exe) { continue }
        $verStr = & $exe --version 2>&1
        if ($verStr -match '(\d+)\.(\d+)') {
            $major = [int]$Matches[1]; $minor = [int]$Matches[2]
            if ($major -ge 3 -and $minor -ge 10) { return $exe.Source }
        }
    }
    return $null
}

$PythonExe = Find-Python

if (-not $PythonExe) {
    Write-Info 'Python 3.10+ not found — trying winget ...'
    try {
        winget install --id Python.Python.3.12 --silent `
            --accept-source-agreements --accept-package-agreements 2>&1 | Out-Null
        # Refresh PATH for this session
        $env:PATH = [System.Environment]::GetEnvironmentVariable('PATH','Machine') + ';' +
                    [System.Environment]::GetEnvironmentVariable('PATH','User')
        $PythonExe = Find-Python
    } catch { Write-Warn "winget failed: $_" }
}

if (-not $PythonExe) {
    Write-Info 'Downloading Python 3.12 from python.org ...'
    $Installer = Join-Path $env:TEMP 'python-setup.exe'
    Invoke-WebRequest 'https://www.python.org/ftp/python/3.12.0/python-3.12.0-amd64.exe' `
        -OutFile $Installer -UseBasicParsing
    Start-Process $Installer -ArgumentList '/quiet InstallAllUsers=1 PrependPath=1' -Wait
    Remove-Item $Installer -Force -ErrorAction SilentlyContinue
    $env:PATH = [System.Environment]::GetEnvironmentVariable('PATH','Machine') + ';' +
                [System.Environment]::GetEnvironmentVariable('PATH','User')
    $PythonExe = Find-Python
}

if (-not $PythonExe) {
    throw 'Python 3.10+ installation failed. Install manually from https://python.org then re-run.'
}
Write-Info "Python: $PythonExe  ($(& $PythonExe --version 2>&1))"

# ---------------------------------------------------------------------------
# 2. Download / update client
# ---------------------------------------------------------------------------
Write-Step 'Downloading Security Client'

$RepoUrl = 'https://github.com/linuxxunil1/security-client'

if (-not (Test-Path $InstallDir)) {
    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
}

$GitExe = Get-Command git -ErrorAction SilentlyContinue
if ($GitExe) {
    if (Test-Path (Join-Path $InstallDir '.git')) {
        Write-Info 'Updating existing installation via git pull ...'
        & git -C $InstallDir pull --ff-only
    } else {
        Write-Info 'Cloning repository ...'
        & git clone --depth=1 $RepoUrl $InstallDir
    }
} else {
    Write-Info 'git not found — downloading ZIP archive ...'
    $ZipPath = Join-Path $env:TEMP 'security-client.zip'
    Invoke-WebRequest "$RepoUrl/archive/refs/heads/main.zip" `
        -OutFile $ZipPath -UseBasicParsing
    $ExtractTemp = Join-Path $env:TEMP 'sc-extract'
    Expand-Archive -Path $ZipPath -DestinationPath $ExtractTemp -Force
    $Inner = Get-ChildItem $ExtractTemp | Select-Object -First 1
    Copy-Item "$($Inner.FullName)\*" -Destination $InstallDir -Recurse -Force
    Remove-Item $ExtractTemp -Recurse -Force
    Remove-Item $ZipPath    -Force
}

# ---------------------------------------------------------------------------
# 3. Virtual environment + dependencies
# ---------------------------------------------------------------------------
Write-Step 'Setting up Python environment'

$VenvDir = Join-Path $InstallDir '.venv'
$VenvPy  = Join-Path $VenvDir 'Scripts\python.exe'
$VenvPip = Join-Path $VenvDir 'Scripts\pip.exe'

if (-not (Test-Path $VenvDir)) {
    Write-Info 'Creating virtual environment ...'
    & $PythonExe -m venv $VenvDir
}
Write-Info 'Installing Python dependencies ...'
& $VenvPip install --quiet --upgrade pip
& $VenvPip install --quiet -r (Join-Path $InstallDir 'requirements.txt')

# ---------------------------------------------------------------------------
# 4. Configuration
# ---------------------------------------------------------------------------
Write-Step 'Configuration'

Write-Host ''
Write-Host '================================================================' -ForegroundColor Cyan
Write-Host '  Security Client Configuration' -ForegroundColor Cyan
Write-Host '================================================================' -ForegroundColor Cyan
$ServerUrl  = Read-Host '  Security Server URL  [http://localhost:8000]'
if ([string]::IsNullOrWhiteSpace($ServerUrl)) { $ServerUrl = 'http://localhost:8000' }
$ClientName = Read-Host "  Client display name  [$env:COMPUTERNAME]"
if ([string]::IsNullOrWhiteSpace($ClientName)) { $ClientName = $env:COMPUTERNAME }
Write-Host '================================================================' -ForegroundColor Cyan

$EnvContent = @"
SERVER_URL=$ServerUrl
CLIENT_NAME=$ClientName
CLIENT_ID=
API_KEY=
SCAN_INTERVAL=300
POLL_INTERVAL=30
LOG_LEVEL=INFO
"@
$EnvContent | Set-Content -Path (Join-Path $InstallDir '.env') -Encoding UTF8

# ---------------------------------------------------------------------------
# 5. Wrapper script (auto-restart on crash)
# ---------------------------------------------------------------------------
$WrapperPath = Join-Path $InstallDir 'start_client.bat'
@"
@echo off
:loop
"$VenvPy" "$InstallDir\client.py"
if %errorlevel% neq 0 (
    timeout /t 30 /nobreak >nul
    goto loop
)
"@ | Set-Content -Path $WrapperPath -Encoding ASCII

# ---------------------------------------------------------------------------
# 6. Register Windows Scheduled Task
# ---------------------------------------------------------------------------
Write-Step "Registering Scheduled Task '$TaskName'"

$Existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($Existing) {
    Write-Warn "Task '$TaskName' already exists — replacing."
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

$LogPath = Join-Path $InstallDir 'client.log'
$Action  = New-ScheduledTaskAction `
    -Execute  'cmd.exe' `
    -Argument "/c `"$WrapperPath`" >> `"$LogPath`" 2>&1"

$Trigger  = New-ScheduledTaskTrigger -AtStartup

$Settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit  ([TimeSpan]::Zero) `
    -RestartCount        5 `
    -RestartInterval     (New-TimeSpan -Minutes 1) `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable

$Principal = New-ScheduledTaskPrincipal `
    -UserId    'SYSTEM' `
    -LogonType ServiceAccount `
    -RunLevel  Highest

Register-ScheduledTask `
    -TaskName   $TaskName `
    -Action     $Action `
    -Trigger    $Trigger `
    -Settings   $Settings `
    -Principal  $Principal `
    -Description 'Security Client — security scan agent' | Out-Null

Write-Info 'Starting task ...'
Start-ScheduledTask -TaskName $TaskName

# ---------------------------------------------------------------------------
# 7. Done
# ---------------------------------------------------------------------------
$State = (Get-ScheduledTask -TaskName $TaskName).State
Write-Host ''
Write-Info 'Installation complete!'
Write-Info "Task state  : $State"
Write-Info "Config file : $(Join-Path $InstallDir '.env')"
Write-Info "Log file    : $LogPath"
Write-Host ''
Write-Info 'Useful commands:'
Write-Info "  Start  : Start-ScheduledTask -TaskName '$TaskName'"
Write-Info "  Stop   : Stop-ScheduledTask  -TaskName '$TaskName'"
Write-Info "  Remove : Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:`$false"
