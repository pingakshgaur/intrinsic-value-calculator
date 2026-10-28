# FILE: packaging/stage.py
"""
Lay out the installed app: the frozen program (PyInstaller's dist/INTVAL)
plus everything it reads from disk at run time.

    python packaging/stage.py <frozen dir> <stage dir>

The stage dir is what the installers copy to the user's chosen folder:

    INTVAL(.exe), _internal/      the frozen program
    web/dist/                     the built browser app
    data/*.csv                    starter company lists and training universes
    agent_settings.yaml           settings, from the factory defaults
    agent_settings.defaults.yaml  the factory defaults ("reset" in the web app)
    assets/, docs/, README.md, .env.example, VERSION

Personal state never ships: .env, llm_providers.json, output/, .cache/, data/live/.
"""

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_FILES = ["companies.csv", "training_universe.csv", "auto_training_universe.csv", "fundamentals_override.csv"]


def version():
    return json.loads((ROOT / "web" / "package.json").read_text(encoding="utf-8"))["version"]


def stage(frozen, out):
    frozen, out = Path(frozen), Path(out)
    if not (frozen / "_internal").is_dir():
        sys.exit(f"{frozen} is not a PyInstaller build (no _internal folder)")
    if not (ROOT / "web" / "dist" / "index.html").exists():
        sys.exit("web/dist is missing - run 'npm run build' in web/ first")
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(frozen, out)
    shutil.copytree(ROOT / "web" / "dist", out / "web" / "dist")
    (out / "data").mkdir()
    for name in DATA_FILES:
        shutil.copy2(ROOT / "data" / name, out / "data" / name)
    defaults = (ROOT / "agent_settings.defaults.yaml").read_text(encoding="utf-8")
    shutil.copy2(ROOT / "agent_settings.defaults.yaml", out / "agent_settings.defaults.yaml")
    # the working copy starts as the defaults, without the "do not edit" banner
    body = defaults.split("\n", 3)[3] if defaults.startswith("# Factory copy") else defaults
    (out / "agent_settings.yaml").write_text(body, encoding="utf-8")
    shutil.copytree(ROOT / "assets", out / "assets")
    shutil.copytree(ROOT / "docs", out / "docs")
    for name in ("README.md", ".env.example"):
        shutil.copy2(ROOT / name, out / name)
    (out / "VERSION").write_text(version() + "\n", encoding="utf-8")
    size = sum(f.stat().st_size for f in out.rglob("*") if f.is_file())
    print(f"staged INTVAL {version()} in {out} ({size / 1024**2:.0f} MB)")


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--version":
        print(version())
    elif len(sys.argv) == 3:
        stage(sys.argv[1], sys.argv[2])
    else:
        sys.exit(__doc__)
