# FILE: packaging/intval.spec
# PyInstaller recipe: freezes run.py and everything it imports into one folder
# (dist/INTVAL/) that runs without Python installed. Used by
# packaging/build_windows.ps1 and packaging/linux/build_linux.sh; run it from
# the repository root:  pyinstaller packaging/intval.spec
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(SPECPATH).parent
FLAT = ["src", "src/sources", "src/models", "src/io_layer", "tools"]  # run.py's sys.path, imported flat
paths = [str(ROOT)] + [str(ROOT / p) for p in FLAT]

# every project module by its import name, so a late import is never missed
hidden = [f.stem for d in FLAT for f in (ROOT / d).glob("*.py") if f.stem != "__init__"]
hidden += ["tools." + f.stem for f in (ROOT / "tools").glob("*.py")]
hidden += ["server." + f.stem for f in (ROOT / "server").glob("*.py") if f.stem != "__init__"] + ["server"]
hidden += ["agents." + f.stem for f in (ROOT / "src" / "agents").glob("*.py") if f.stem != "__init__"] + ["agents"]
hidden += collect_submodules("uvicorn") + ["matplotlib.backends.backend_agg"]

datas, binaries = [], []
for pkg in ("curl_cffi", "yfinance", "lightgbm", "xgboost"):  # native libraries and data files
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hidden += h

a = Analysis(
    [str(ROOT / "run.py")],
    pathex=paths,
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden,
    excludes=["tkinter", "IPython", "pytest", "PyInstaller", "notebook", "PyQt5", "PySide6"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="INTVAL",
    icon=str(ROOT / "assets" / "intval.ico") if sys.platform == "win32" else None,
    console=True,  # the window shows the server log; closing it stops INTVAL
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="INTVAL")
