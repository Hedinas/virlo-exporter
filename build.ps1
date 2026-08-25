[CmdletBinding()]
param(
    [switch]$SkipTests
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonExe = Join-Path $ProjectRoot '.venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $PythonExe)) {
    throw 'Virtual environment not found. Run setup_windows.ps1 first.'
}

if (-not $SkipTests) {
    & $PythonExe -m pytest
    if ($LASTEXITCODE -ne 0) { throw 'Tests failed.' }
}

& $PythonExe -m PyInstaller `
    --noconfirm `
    --clean `
    --onedir `
    --windowed `
    --name 'Virlo Exporter' `
    --paths (Join-Path $ProjectRoot 'src') `
    --add-data "$(Join-Path $ProjectRoot 'assets');assets" `
    (Join-Path $ProjectRoot 'src\virlo_exporter\main.py')

if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed.' }
Write-Host "Built: $(Join-Path $ProjectRoot 'dist\Virlo Exporter\Virlo Exporter.exe')"

