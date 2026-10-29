# FILE: packaging/build_windows.ps1
# Builds installers\INTVAL-Setup-<version>-windows-x64.exe (first install) and
# installers\INTVAL-Update-<version>-windows-x64.exe (updates an existing install
# in place and keeps every bit of the user's data - see windows\intval-update.iss).
#
#   powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1
#
# Needs: the project's .venv with requirements.txt installed, PyInstaller
# (pip install pyinstaller) and Inno Setup 6 (winget install JRSoftware.InnoSetup).
# web\dist must be built (npm run build in web\) - it is committed, so usually is.

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$Py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) { $Py = "python" }

$Iscc = @(
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $Iscc) { throw "Inno Setup 6 not found - winget install JRSoftware.InnoSetup" }

$Version = & $Py packaging\stage.py --version
Write-Host "== INTVAL $Version for Windows"

Write-Host "== 1/4 freezing the app with PyInstaller"
& $Py -m PyInstaller packaging\intval.spec --noconfirm --clean --distpath build\pyi-dist --workpath build\pyi-work
if ($LASTEXITCODE) { throw "PyInstaller failed" }

Write-Host "== 2/4 staging data, settings and the web app"
& $Py packaging\stage.py build\pyi-dist\INTVAL build\stage-windows
if ($LASTEXITCODE) { throw "staging failed" }

Write-Host "== 3/4 drawing the installer artwork"
& $Py packaging\wizard_art.py build\art
if ($LASTEXITCODE) { throw "artwork failed" }

Write-Host "== 4/4 compiling the installer and the updater with Inno Setup"
New-Item -ItemType Directory -Force installers | Out-Null
foreach ($Script in "intval.iss", "intval-update.iss") {
    & $Iscc /Q "/DAppVersion=$Version" "/DStageDir=$Root\build\stage-windows" "/DArtDir=$Root\build\art" "/DOutDir=$Root\installers" "packaging\windows\$Script"
    if ($LASTEXITCODE) { throw "Inno Setup failed on $Script" }
}

foreach ($Name in "Setup", "Update") {
    $Out = Get-Item "installers\INTVAL-$Name-$Version-windows-x64.exe"
    Write-Host ("== done: {0} ({1:N0} MB)" -f $Out.FullName, ($Out.Length / 1MB))
}
