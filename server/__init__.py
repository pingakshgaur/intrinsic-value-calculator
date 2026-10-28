# FILE: server/__init__.py
"""
Local web API for the browser UI.

    python run.py --web            # serves web/dist and opens the browser

Binds to 127.0.0.1 only. Long work (valuation runs, agent runs, key checks)
runs as a child `python run.py ...` process, so a crash or a stuck download
can never take the web server down, and the pipeline's module-level config
changes stay inside that child. Quick, pure calculations - the Hybrid Model
Lab's what-if evaluations - run in-process.
"""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
for _sub in ("src", "src/sources", "src/models", "src/io_layer", "tools", ""):
    _p = str(_ROOT / _sub) if _sub else str(_ROOT)
    if _p not in sys.path:
        sys.path.insert(0, _p)
