#!/usr/bin/env bash
# FILE: packaging/linux/build_linux.sh
# Builds installers/INTVAL-Setup-<version>-linux-x86_64 (a graphical installer
# with the app inside) and installers/INTVAL-Update-<version>-linux-x86_64 (the
# same program under the name that makes it update an existing install in place,
# keeping all data). Run from the repository root on Linux with Python 3.10+:
#
#   bash packaging/linux/build_linux.sh
#
# or from Windows through Docker:  powershell -File packaging\build_linux.ps1
# Build on the OLDEST distribution you want to support: the program runs on
# that glibc and anything newer (the Docker build uses Debian 11).
set -euo pipefail
cd "$(dirname "$0")/../.."

PY=${PYTHON:-python3}
if [ "${INTVAL_SKIP_DEPS:-0}" != "1" ]; then
  echo "== 0/5 installing build dependencies"
  "$PY" -m pip install --quiet --upgrade pip
  "$PY" -m pip install --quiet -r requirements.txt pyinstaller pillow
  # Linux xgboost wheels bring NVIDIA's NCCL (~200 MB) for multi-GPU training;
  # INTVAL trains on the CPU, so ship the CPU-only build of the same package
  "$PY" -m pip uninstall --quiet -y xgboost || true
  "$PY" -m pip install --quiet xgboost-cpu
  # removing xgboost leaves its NCCL dependency behind (nvidia-nccl-cu12, -cu13, ...)
  NVIDIA=$("$PY" -m pip list --format=freeze | grep -iE '^nvidia[-_]' | cut -d= -f1 || true)
  [ -n "$NVIDIA" ] && "$PY" -m pip uninstall --quiet -y $NVIDIA
  # pip leaves part of the folder behind, and PyInstaller would still bundle it
  "$PY" -c "import shutil, site; [shutil.rmtree(p + '/nvidia', ignore_errors=True) for p in site.getsitepackages()]"
  if "$PY" -c "import nvidia.nccl" 2>/dev/null; then echo "NVIDIA NCCL is still installed" >&2; exit 1; fi
fi
VERSION=$("$PY" packaging/stage.py --version)
echo "== INTVAL $VERSION for Linux"

echo "== 1/5 freezing the app with PyInstaller"
"$PY" -m PyInstaller packaging/intval.spec --noconfirm --clean --distpath build/pyi-dist-linux --workpath build/pyi-work-linux

echo "== 2/5 staging data, settings and the web app"
"$PY" packaging/stage.py build/pyi-dist-linux/INTVAL build/stage-linux

echo "== 3/5 packing the payload"
rm -rf build/linux && mkdir -p build/linux
"$PY" - <<'EOF'
import tarfile
from pathlib import Path
src = Path("build/stage-linux")
with tarfile.open("build/linux/payload.tar.gz", "w:gz", compresslevel=6) as tar:
    for p in sorted(src.rglob("*")):
        tar.add(p, arcname=p.relative_to(src).as_posix(), recursive=False)
EOF
"$PY" packaging/wizard_art.py build/linux >/dev/null
cp assets/intval.png build/linux/icon.png
cp build/stage-linux/VERSION build/linux/VERSION

echo "== 4/5 building the installer"
NAME="INTVAL-Setup-$VERSION-linux-x86_64"
"$PY" -m PyInstaller packaging/linux/installer.py --onefile --noconfirm --clean --name "$NAME" \
  --distpath build/linux/dist --workpath build/linux/work --specpath build/linux \
  --add-data "$PWD/build/linux/payload.tar.gz:." --add-data "$PWD/build/linux/banner.png:." \
  --add-data "$PWD/build/linux/icon.png:." --add-data "$PWD/build/linux/VERSION:."

echo "== 5/5 done"
mkdir -p installers
cp "build/linux/dist/$NAME" "installers/$NAME"
# the updater is the same program: its name puts it in update mode (installer.py)
cp "build/linux/dist/$NAME" "installers/INTVAL-Update-$VERSION-linux-x86_64"
chmod +x "installers/$NAME" "installers/INTVAL-Update-$VERSION-linux-x86_64"
ls -lh "installers/$NAME" "installers/INTVAL-Update-$VERSION-linux-x86_64"
