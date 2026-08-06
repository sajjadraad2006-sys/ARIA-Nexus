# ARIA NEXUS v2 - Windows development setup
# Safe and idempotent: creates the venv, installs core packages, and runs tests.
# It does NOT install CUDA, download models, or change system-wide settings.

[CmdletBinding()]
param(
    [switch]$InstallFullRequirements,
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$VenvDir = Join-Path $ProjectRoot ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"

function Step([string]$Message) {
    Write-Host ""
    Write-Host ("==> " + $Message) -ForegroundColor Cyan
}

function Fail([string]$Message) {
    Write-Host ("ERROR: " + $Message) -ForegroundColor Red
    exit 1
}

Step "Validating repository"
if (-not (Test-Path (Join-Path $ProjectRoot "backend\server.py"))) {
    Fail "Run this script from the ARIA repository under scripts\setup_windows.ps1."
}

$PyLauncher = Get-Command "py.exe" -ErrorAction SilentlyContinue
if ($null -eq $PyLauncher) {
    Fail "Python launcher py.exe was not found. Install Python 3.12 first."
}

& py -3.12 --version
if ($LASTEXITCODE -ne 0) {
    Fail "Python 3.12 is required."
}

Step "Creating Python 3.12 virtual environment"
if (-not (Test-Path $VenvPython)) {
    & py -3.12 -m venv $VenvDir
    if ($LASTEXITCODE -ne 0) { Fail "Could not create .venv." }
} else {
    Write-Host ".venv already exists; reusing it." -ForegroundColor DarkGray
}

Step "Updating packaging tools"
& $VenvPython -m pip install --upgrade pip setuptools wheel
if ($LASTEXITCODE -ne 0) { Fail "Could not update pip tooling." }

Step "Installing ARIA core packages"
$CorePackages = @(
    "flask>=2.0.0",
    "flask-cors>=3.0.0",
    "flask-socketio>=5.3.0",
    "requests>=2.28.0",
    "pyopenssl>=23.0.0",
    "numpy>=1.24.0",
    "psutil>=5.9.0",
    "pyyaml>=6.0"
)
& $VenvPython -m pip install @CorePackages
if ($LASTEXITCODE -ne 0) { Fail "Core package installation failed." }

if ($InstallFullRequirements) {
    Step "Installing optional AI requirements"
    Write-Host "This can take a long time and may expose Windows-specific dependency issues." -ForegroundColor Yellow
    & $VenvPython -m pip install -r (Join-Path $ProjectRoot "backend\requirements.txt")
    if ($LASTEXITCODE -ne 0) {
        Fail "Full requirements failed. Core setup remains usable; review the pip error before retrying."
    }
}

Step "Creating local runtime directories"
foreach ($RelativePath in @("models", "vendor", "logs", ".aria\reports", ".aria\run")) {
    New-Item -ItemType Directory -Force -Path (Join-Path $ProjectRoot $RelativePath) | Out-Null
}

Step "Running ARIA project doctor"
$ReportPath = Join-Path $ProjectRoot ".aria\reports\windows-doctor.txt"
& $VenvPython (Join-Path $ProjectRoot "scripts\doctor.py") --save $ReportPath
$DoctorExit = $LASTEXITCODE

if (-not $SkipTests) {
    Step "Running smoke tests"
    & $VenvPython (Join-Path $ProjectRoot "backend\test_smoke.py")
    if ($LASTEXITCODE -ne 0) { Fail "Smoke tests failed." }

    Step "Compiling Python sources"
    & $VenvPython -m compileall -q (Join-Path $ProjectRoot "backend") (Join-Path $ProjectRoot "aarya_wakeword")
    if ($LASTEXITCODE -ne 0) { Fail "Python compilation checks failed." }
}

Write-Host ""
Write-Host "ARIA Windows core setup completed." -ForegroundColor Green
Write-Host ("Doctor report: " + $ReportPath)
if ($DoctorExit -ne 0) {
    Write-Host "The doctor reported a critical failure. Review the report above." -ForegroundColor Yellow
    exit $DoctorExit
}
Write-Host "Models and native inference binaries are intentionally not installed yet." -ForegroundColor Yellow
