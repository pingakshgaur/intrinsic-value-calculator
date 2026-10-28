# FILE: packaging/build_linux.ps1
# Builds the Linux installer from Windows, inside Docker (Debian 11, so the
# result runs on Ubuntu 20.04+, Debian 11+, Fedora 34+ and similar):
#
#   powershell -ExecutionPolicy Bypass -File packaging\build_linux.ps1
#
# Needs Docker Desktop running. The work itself is packaging/linux/build_linux.sh.

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
docker info --format "{{.ServerVersion}}" | Out-Null
if ($LASTEXITCODE) { throw "Docker is not running - start Docker Desktop first" }

# copy the repository (minus the bulky local folders) into a volume-free build:
# the Windows .venv and node_modules must not leak into the Linux build
docker run --rm -v "${Root}:/host:ro" -v "${Root}\installers:/out" python:3.12-bullseye bash -c @'
set -e
mkdir /src && cd /host
tar --exclude=./.venv --exclude=./web/node_modules --exclude=./build --exclude=./installers --exclude=./output \
    --exclude=./.cache --exclude=./.git --exclude=./data/live -cf - . | tar -xf - -C /src
cd /src
bash packaging/linux/build_linux.sh
cp installers/INTVAL-Setup-* /out/
'@
if ($LASTEXITCODE) { throw "the Linux build failed" }
Get-ChildItem "$Root\installers\INTVAL-Setup-*-linux-*" | Format-Table Name, @{ n = "MB"; e = { [math]::Round($_.Length / 1MB) } }
