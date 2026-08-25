[CmdletBinding()]
param(
    [switch]$NoLaunch
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvPath = Join-Path $ProjectRoot '.venv'
$PythonExe = Join-Path $VenvPath 'Scripts\python.exe'

$PythonCommand = Get-Command py -ErrorAction SilentlyContinue
if (-not $PythonCommand) { throw 'Python 3.12 or newer is required. Install it from python.org.' }

# Qt does not publish wheels for free-threaded CPython builds. Pick the newest
# regular (GIL-enabled) Python 3.12+ registered with the Windows launcher.
$PythonTag = $null
foreach ($Candidate in @('3.14', '3.13', '3.12')) {
    $GilDisabled = & py "-$Candidate" -c "import sysconfig; print(int(bool(sysconfig.get_config_var('Py_GIL_DISABLED'))))" 2>$null
    if (($LASTEXITCODE -eq 0) -and ($GilDisabled -eq '0')) {
        $PythonTag = $Candidate
        break
    }
}
if (-not $PythonTag) { throw 'A regular (non-free-threaded) Python 3.12+ installation is required.' }

if (Test-Path -LiteralPath $PythonExe) {
    $VenvGilDisabled = & $PythonExe -c "import sysconfig; print(int(bool(sysconfig.get_config_var('Py_GIL_DISABLED'))))"
    if ($VenvGilDisabled -ne '0') {
        $ResolvedVenv = (Resolve-Path -LiteralPath $VenvPath).Path
        if ((Split-Path -Parent $ResolvedVenv) -ne $ProjectRoot) { throw "Refusing to replace unexpected venv path: $ResolvedVenv" }
        Remove-Item -LiteralPath $ResolvedVenv -Recurse -Force
    }
}

if (-not (Test-Path -LiteralPath $VenvPath)) {
    & py "-$PythonTag" -m venv $VenvPath
}

& $PythonExe -m pip install --upgrade pip
& $PythonExe -m pip install -r (Join-Path $ProjectRoot 'requirements-dev.txt')
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
& $PythonExe -m pip install -e $ProjectRoot
if ($LASTEXITCODE -ne 0) { throw 'Project installation failed.' }

New-Item -ItemType Directory -Force -Path (Join-Path $ProjectRoot 'exports') | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $ProjectRoot 'logs') | Out-Null

& (Join-Path $ProjectRoot 'build.ps1')

$ExePath = Join-Path $ProjectRoot 'dist\Virlo Exporter\Virlo Exporter.exe'
if (-not (Test-Path -LiteralPath $ExePath)) { throw "Built executable was not found at $ExePath" }

$Desktop = [Environment]::GetFolderPath('Desktop')
$ShortcutPath = Join-Path $Desktop 'Virlo Exporter.lnk'
$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $ExePath
$Shortcut.WorkingDirectory = Split-Path -Parent $ExePath
$Shortcut.IconLocation = "$ExePath,0"
$Shortcut.Description = 'Virlo Content Research Agent manager and AI dataset exporter'
$Shortcut.Save()

Write-Host "Shortcut: $ShortcutPath"
if (-not $NoLaunch) {
    Start-Process -FilePath $ExePath -WorkingDirectory (Split-Path -Parent $ExePath)
}
