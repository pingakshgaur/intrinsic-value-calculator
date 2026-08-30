# FILE: gui.py
"""
Desktop front end for the intrinsic value engine.

    python run.py --gui        (preferred)
    python gui.py              (also works)

Design notes worth knowing before you edit this file:

1. THE PIPELINE RUNS ON A WORKER THREAD. A full run is several minutes of
   network I/O. On the main thread the window would stop repainting and
   Windows would grey it out as "Not Responding". Only the worker touches
   pipeline code; only the main thread touches widgets. They communicate
   through a queue, drained by a timer. Never call a widget method from
   inside _worker().

2. stdout IS REDIRECTED, NOT REPLACED. pipeline.py prints its whole
   diagnostic narrative - fetch results, gate verdicts, coverage tables, fold
   metrics. Rather than rewrite all of that to emit events, sys.stdout is
   pointed at a queue for the duration of the run. You keep every line you
   see in the terminal today, in the console pane, live.

3. CANCELLATION RIDES ON THAT REDIRECT. QueueWriter.write() raises
   RunCancelled when the cancel flag is set, so the run stops at the next
   print - once per company during the fetch. RunCancelled inherits from
   BaseException deliberately: pipeline.py is full of 'except Exception'
   guards that would otherwise swallow it and carry on.

4. matplotlib IS PINNED TO Agg before anything imports pyplot. csv_analyzer
   renders charts on the worker thread; a GUI backend there would try to
   touch Tk from the wrong thread and take the process down.

Settings written here are pushed onto the config module in place, exactly as
the CLI flags do. The two front ends stay in sync because they mutate the same
object - there is no second copy of the defaults to drift.
"""

import logging
import os
import queue
import subprocess
import sys
import threading
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
for _sub in ("src", "src/sources", "src/models", "src/io_layer", "tools"):
    _p = str(ROOT / _sub)
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Must precede any pyplot import anywhere in the process. See note 4.
import matplotlib

matplotlib.use("Agg")

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

try:
    import ttkbootstrap as tb
except ImportError as exc:  # surfaced by run.py with an install hint
    raise ImportError(
        "ttkbootstrap is not installed - run: pip install ttkbootstrap"
    ) from exc

try:
    from PIL import Image, ImageTk

    HAVE_PIL = True
except ImportError:
    HAVE_PIL = False

import pandas as pd

import config
import inputs
import pipeline
import ticker_resolver

log = logging.getLogger("valuation")

MONO = ("Consolas", 9) if sys.platform.startswith("win") else ("Menlo", 10)
TICK, CROSS = "\u2713", ""


class RunCancelled(BaseException):
    """Raised inside the worker when the user presses Cancel. See note 3."""


class QueueWriter:
    """
    File-like stand-in for sys.stdout that forwards to the GUI queue.

    Chunks are passed through verbatim rather than split into lines, so
    print(..., end=' ', flush=True) still renders as a single growing line -
    that is how the fetch progress reads in the terminal and there is no
    reason to lose it here.
    """

    def __init__(self, q, cancel_event):
        self._q = q
        self._cancel = cancel_event

    def write(self, text):
        if self._cancel.is_set():
            raise RunCancelled()
        if text:
            self._q.put(("out", text))
        return len(text)

    def flush(self):
        pass

    def isatty(self):
        return False


def setup_logging():
    """Idempotent - run.py may already have configured the root logger."""
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = config.OUTPUT_DIR / config.LOG_FILE
    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=logging.DEBUG,
            format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
            handlers=[logging.FileHandler(path, mode="w", encoding="utf-8")],
        )
        for noisy in ("yfinance", "urllib3", "peewee"):
            logging.getLogger(noisy).setLevel(logging.ERROR)
    return path


def open_in_explorer(path):
    path = Path(path)
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(path))  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except Exception as e:
        messagebox.showerror("Could not open", f"{type(e).__name__}: {e}")


class App(tb.Window):
    def __init__(self):
        super().__init__(themename=getattr(config, "GUI_THEME", "flatly"))
        self.title("Intrinsic Value Calculator  -  FY2021-FY2025")
        self.geometry(getattr(config, "GUI_WINDOW_SIZE", "1280x820"))
        self.minsize(*getattr(config, "GUI_MIN_SIZE", (1060, 700)))

        self.companies = []
        self.include = {}
        self.queue = queue.Queue()
        self.cancel = threading.Event()
        self.worker = None
        self.expected = 0
        self.fetched = 0
        self._chart_ref = None

        self._build_vars()
        self._build_header()
        self._build_tabs()
        self._build_statusbar()

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(150, self._drain)

        if config.DEFAULT_INPUT.exists():
            self._load_companies(config.DEFAULT_INPUT)

    # ------------------------------------------------------------------ vars
    def _build_vars(self):
        g = getattr
        self.v_input = tk.StringVar(value=str(config.DEFAULT_INPUT))

        self.v_screening = tk.StringVar(
            value=(
                "off"
                if not g(config, "SUFFICIENCY_ENABLED", True)
                else g(config, "SUFFICIENCY_MODE", "enforce")
            )
        )
        self.v_min_fy = tk.IntVar(value=g(config, "MIN_COMPLETE_FY", 4))
        self.v_min_bench = tk.IntVar(value=g(config, "MIN_BENCHMARK_FY", 4))
        self.v_need_price = tk.BooleanVar(
            value=g(config, "SUFFICIENCY_REQUIRE_ANCHOR_PRICE", True)
        )
        self.v_keep_peers = tk.BooleanVar(
            value=g(config, "SUFFICIENCY_KEEP_IN_PEERS", True)
        )
        self.v_keep_ml = tk.BooleanVar(value=g(config, "SUFFICIENCY_KEEP_IN_ML", True))
        self.v_sheet_all = tk.BooleanVar(
            value=g(config, "EXCLUSION_SHEET_INCLUDE_PASSED", False)
        )

        self.v_bench = tk.StringVar(value=g(config, "BENCHMARK_BASIS", "may1"))
        self.v_offset = tk.IntVar(value=g(config, "BENCHMARK_MAX_OFFSET_DAYS", 10))
        self.v_meanbasis = tk.StringVar(value=g(config, "FY_MEAN_BASIS", "trading"))
        self.v_exchange = tk.StringVar(value=g(config, "EXCHANGE_SUFFIX", ".NS"))

        self.v_ml = tk.BooleanVar(value=g(config, "ML_ENABLED", True))
        self.v_mlsplit = tk.StringVar(value=g(config, "ML_SPLIT", "hybrid"))
        self.v_analyze = tk.BooleanVar(value=g(config, "ANALYSIS_ENABLED", True))
        self.v_dpi = tk.IntVar(value=g(config, "CHART_DPI", 200))

        self.v_fylabel = tk.StringVar(value=g(config, "FY_LABEL_STYLE", "range"))
        self.v_reasons = tk.StringVar(
            value=(
                "off"
                if not g(config, "SHOW_REASONS", True)
                else g(config, "REASON_STYLE", "code")
            )
        )
        self.v_estimation = tk.StringVar(value=g(config, "ESTIMATION_MODE", "balanced"))
        self.v_overrides = tk.BooleanVar(value=g(config, "USE_OVERRIDES", True))
        self.v_offline = tk.BooleanVar(value=g(config, "OFFLINE", False))
        self.v_dark = tk.BooleanVar(value=False)

        self.v_status = tk.StringVar(value="idle")
        self.v_count = tk.StringVar(value="no companies loaded")

    # ---------------------------------------------------------------- header
    def _build_header(self):
        bar = tb.Frame(self, padding=(14, 10))
        bar.pack(fill="x")
        tb.Label(
            bar,
            text="Intrinsic Value Calculator",
            font=("Segoe UI Semibold", 15),
        ).pack(side="left")
        tb.Label(
            bar,
            text="Traditional  \u00b7  AI  \u00b7  Hybrid   |   Indian equity market",
            bootstyle="secondary",
        ).pack(side="left", padx=12)
        tb.Checkbutton(
            bar,
            text="Dark",
            variable=self.v_dark,
            bootstyle="round-toggle",
            command=self._toggle_theme,
        ).pack(side="right")
        tb.Separator(self).pack(fill="x")

    def _toggle_theme(self):
        name = (
            getattr(config, "GUI_THEME_DARK", "darkly")
            if self.v_dark.get()
            else getattr(config, "GUI_THEME", "flatly")
        )
        try:
            self.style.theme_use(name)
        except Exception:
            pass

    # ------------------------------------------------------------------ tabs
    def _build_tabs(self):
        nb = tb.Notebook(self, padding=8)
        nb.pack(fill="both", expand=True)
        self.nb = nb
        self.tab_companies = tb.Frame(nb, padding=10)
        self.tab_settings = tb.Frame(nb, padding=10)
        self.tab_run = tb.Frame(nb, padding=10)
        self.tab_results = tb.Frame(nb, padding=10)
        self.tab_charts = tb.Frame(nb, padding=10)
        nb.add(self.tab_companies, text="  Companies  ")
        nb.add(self.tab_settings, text="  Settings  ")
        nb.add(self.tab_run, text="  Run  ")
        nb.add(self.tab_results, text="  Results  ")
        nb.add(self.tab_charts, text="  Charts  ")

        self._build_companies(self.tab_companies)
        self._build_settings(self.tab_settings)
        self._build_run(self.tab_run)
        self._build_results(self.tab_results)
        self._build_charts(self.tab_charts)

    # ------------------------------------------------------------- companies
    def _build_companies(self, parent):
        top = tb.Frame(parent)
        top.pack(fill="x", pady=(0, 8))
        tb.Label(top, text="Input CSV").pack(side="left")
        tb.Entry(top, textvariable=self.v_input).pack(
            side="left", fill="x", expand=True, padx=8
        )
        tb.Button(top, text="Browse", bootstyle="secondary", command=self._browse).pack(
            side="left"
        )
        tb.Button(
            top, text="Reload", bootstyle="secondary-outline", command=self._reload
        ).pack(side="left", padx=(6, 0))

        mid = tb.Frame(parent)
        mid.pack(fill="both", expand=True)

        cols = ("inc", "name", "sector", "cap", "ticker")
        self.tree_c = ttk.Treeview(
            mid, columns=cols, show="headings", selectmode="none"
        )
        for key, label, w, anchor in (
            ("inc", "Include", 70, "center"),
            ("name", "Company name", 330, "w"),
            ("sector", "Sector", 240, "w"),
            ("cap", "Market cap", 110, "w"),
            ("ticker", "Ticker", 120, "w"),
        ):
            self.tree_c.heading(key, text=label)
            self.tree_c.column(key, width=w, anchor=anchor)
        sb = ttk.Scrollbar(mid, orient="vertical", command=self.tree_c.yview)
        self.tree_c.configure(yscrollcommand=sb.set)
        self.tree_c.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree_c.bind("<Button-1>", self._toggle_row)
        self.tree_c.tag_configure("off", foreground="#9aa0a6")

        bot = tb.Frame(parent)
        bot.pack(fill="x", pady=(8, 0))
        for text, fn in (
            ("Select all", lambda: self._set_all(True)),
            ("Select none", lambda: self._set_all(False)),
            ("Invert", self._invert),
        ):
            tb.Button(bot, text=text, bootstyle="secondary-outline", command=fn).pack(
                side="left", padx=(0, 6)
            )
        tb.Label(bot, textvariable=self.v_count, bootstyle="secondary").pack(
            side="right"
        )

    def _browse(self):
        p = filedialog.askopenfilename(
            title="Select companies CSV",
            initialdir=str(config.DATA_DIR),
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if p:
            self.v_input.set(p)
            self._load_companies(p)

    def _reload(self):
        self._load_companies(self.v_input.get())

    def _load_companies(self, path):
        try:
            self.companies = inputs.read_csv_input(path)
        except Exception as e:
            messagebox.showerror("Could not read input", f"{type(e).__name__}: {e}")
            return
        self.include = {c["name"]: True for c in self.companies}
        self._refresh_company_tree()

    def _refresh_company_tree(self):
        self.tree_c.delete(*self.tree_c.get_children())
        for c in self.companies:
            on = self.include.get(c["name"], True)
            self.tree_c.insert(
                "",
                "end",
                iid=c["name"],
                values=(
                    TICK if on else CROSS,
                    c["name"],
                    c.get("sector", ""),
                    c.get("cap", ""),
                    c.get("ticker") or "",
                ),
                tags=() if on else ("off",),
            )
        self._update_count()

    def _update_count(self):
        n = sum(1 for v in self.include.values() if v)
        self.v_count.set(f"{n} of {len(self.companies)} companies selected")

    def _toggle_row(self, event):
        if self.tree_c.identify_region(event.x, event.y) != "cell":
            return
        if self.tree_c.identify_column(event.x) != "#1":
            return
        iid = self.tree_c.identify_row(event.y)
        if not iid:
            return
        self.include[iid] = not self.include.get(iid, True)
        on = self.include[iid]
        self.tree_c.set(iid, "inc", TICK if on else CROSS)
        self.tree_c.item(iid, tags=() if on else ("off",))
        self._update_count()

    def _set_all(self, state):
        for k in self.include:
            self.include[k] = state
        self._refresh_company_tree()

    def _invert(self):
        for k in self.include:
            self.include[k] = not self.include[k]
        self._refresh_company_tree()

    # -------------------------------------------------------------- settings
    def _build_settings(self, parent):
        wrap = tb.Frame(parent)
        wrap.pack(fill="both", expand=True)
        left = tb.Frame(wrap)
        right = tb.Frame(wrap)
        left.pack(side="left", fill="both", expand=True, padx=(0, 8))
        right.pack(side="left", fill="both", expand=True, padx=(8, 0))

        # ---- data sufficiency ----
        g = tb.Labelframe(left, text="  Data sufficiency gate  ", padding=12)
        g.pack(fill="x", pady=(0, 10))
        tb.Label(
            g,
            text=(
                "Checked on reported data, before the estimation layer.\n"
                "yfinance publishes ~4 annual periods, so FY2021 is usually\n"
                "absent and 4 is the observable ceiling, not a middling bar."
            ),
            bootstyle="secondary",
            justify="left",
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))

        tb.Label(g, text="Mode").grid(row=1, column=0, sticky="w", pady=3)
        modes = tb.Frame(g)
        modes.grid(row=1, column=1, sticky="w")
        for val, label in (
            ("enforce", "Drop failures"),
            ("report_only", "Flag only"),
            ("off", "Disabled"),
        ):
            tb.Radiobutton(
                modes, text=label, value=val, variable=self.v_screening
            ).pack(side="left", padx=(0, 12))

        self._spin(g, 2, "Complete FYs required", self.v_min_fy, 1, 5)
        self._spin(g, 3, "Benchmark FYs required", self.v_min_bench, 0, 5)
        self._check(
            g, 4, "A complete FY must also carry an in-FY price", self.v_need_price
        )
        self._check(
            g, 5, "Keep excluded firms in the sector medians", self.v_keep_peers
        )
        self._check(g, 6, "Keep excluded firms in ML training", self.v_keep_ml)
        self._check(
            g, 7, "List passing firms in the sheet too (full audit)", self.v_sheet_all
        )

        # ---- prices ----
        p = tb.Labelframe(left, text="  Prices  ", padding=12)
        p.pack(fill="x")
        self._combo(p, 0, "Benchmark basis", self.v_bench, ["may1", "mean", "close"])
        self._spin(p, 1, "Max offset from 1 May (days)", self.v_offset, 1, 45)
        self._combo(p, 2, "In-FY mean basis", self.v_meanbasis, ["trading", "calendar"])
        self._combo(p, 3, "Exchange suffix", self.v_exchange, [".NS", ".BO"])

        # ---- models ----
        m = tb.Labelframe(right, text="  Models  ", padding=12)
        m.pack(fill="x", pady=(0, 10))
        self._check(m, 0, "Run the ML models (XGBoost, RF, LightGBM)", self.v_ml)
        self._combo(m, 1, "ML split", self.v_mlsplit, ["hybrid", "expanding", "loyo"])
        self._combo(
            m,
            2,
            "Estimation layer",
            self.v_estimation,
            ["balanced", "aggressive", "off"],
        )
        self._check(m, 3, "Run the statistics / chart stage", self.v_analyze)
        self._spin(m, 4, "Chart DPI", self.v_dpi, 72, 600, 4)

        # ---- output ----
        o = tb.Labelframe(right, text="  Output  ", padding=12)
        o.pack(fill="x", pady=(0, 10))
        self._combo(o, 0, "Financial year labels", self.v_fylabel, ["range", "int"])
        self._combo(
            o, 1, "Blank-cell reasons", self.v_reasons, ["code", "detailed", "off"]
        )
        self._check(o, 2, "Use data/fundamentals_override.csv", self.v_overrides)
        self._check(o, 3, "Offline mode (mock data, no network)", self.v_offline)

        tb.Button(
            right,
            text="Open output folder",
            bootstyle="secondary-outline",
            command=lambda: open_in_explorer(config.OUTPUT_DIR),
        ).pack(anchor="w")

    def _spin(self, parent, row, label, var, lo, hi, step=1):
        tb.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=3)
        tb.Spinbox(
            parent, from_=lo, to=hi, increment=step, textvariable=var, width=10
        ).grid(row=row, column=1, sticky="w", padx=(12, 0))

    def _combo(self, parent, row, label, var, values):
        tb.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=3)
        tb.Combobox(
            parent, textvariable=var, values=values, state="readonly", width=14
        ).grid(row=row, column=1, sticky="w", padx=(12, 0))

    def _check(self, parent, row, label, var):
        tb.Checkbutton(parent, text=label, variable=var).grid(
            row=row, column=0, columnspan=2, sticky="w", pady=3
        )

    # ------------------------------------------------------------------- run
    def _build_run(self, parent):
        top = tb.Frame(parent)
        top.pack(fill="x", pady=(0, 8))
        self.btn_run = tb.Button(
            top, text="Run full valuation", bootstyle="success", command=self._run_full
        )
        self.btn_run.pack(side="left")
        self.btn_screen = tb.Button(
            top,
            text="Screen only (dry run)",
            bootstyle="info-outline",
            command=self._run_screen,
        )
        self.btn_screen.pack(side="left", padx=8)
        self.btn_cancel = tb.Button(
            top,
            text="Cancel",
            bootstyle="danger-outline",
            command=self._request_cancel,
            state="disabled",
        )
        self.btn_cancel.pack(side="left")
        tb.Button(
            top,
            text="Clear console",
            bootstyle="secondary-outline",
            command=self._clear,
        ).pack(side="right")
        tb.Button(
            top,
            text="Save console",
            bootstyle="secondary-outline",
            command=self._save_console,
        ).pack(side="right", padx=6)

        self.pbar = tb.Progressbar(
            parent, mode="determinate", bootstyle="success-striped"
        )
        self.pbar.pack(fill="x", pady=(0, 8))

        box = tb.Frame(parent)
        box.pack(fill="both", expand=True)
        self.console = tk.Text(box, wrap="none", font=MONO, height=24, undo=False)
        ysb = ttk.Scrollbar(box, orient="vertical", command=self.console.yview)
        xsb = ttk.Scrollbar(box, orient="horizontal", command=self.console.xview)
        self.console.configure(yscrollcommand=ysb.set, xscrollcommand=xsb.set)
        self.console.grid(row=0, column=0, sticky="nsew")
        ysb.grid(row=0, column=1, sticky="ns")
        xsb.grid(row=1, column=0, sticky="ew")
        box.rowconfigure(0, weight=1)
        box.columnconfigure(0, weight=1)
        self.console.configure(state="disabled")

    def _clear(self):
        self.console.configure(state="normal")
        self.console.delete("1.0", "end")
        self.console.configure(state="disabled")

    def _save_console(self):
        p = filedialog.asksaveasfilename(
            defaultextension=".txt",
            initialdir=str(config.OUTPUT_DIR),
            initialfile="gui_console.txt",
        )
        if not p:
            return
        Path(p).write_text(self.console.get("1.0", "end"), encoding="utf-8")
        self._echo(f"\n[gui] console saved to {p}\n")

    def _echo(self, text):
        self.console.configure(state="normal")
        self.console.insert("end", text)
        self.console.see("end")
        self.console.configure(state="disabled")

    # --------------------------------------------------------------- results
    def _build_results(self, parent):
        bar = tb.Frame(parent)
        bar.pack(fill="x", pady=(0, 8))
        tb.Button(
            bar, text="Refresh", bootstyle="secondary", command=self._load_results
        ).pack(side="left")
        tb.Button(
            bar,
            text="Open workbook",
            bootstyle="secondary-outline",
            command=lambda: open_in_explorer(
                config.OUTPUT_DIR / f"{config.OUTPUT_BASENAME}.xlsx"
            ),
        ).pack(side="left", padx=6)
        tb.Button(
            bar,
            text="Open output folder",
            bootstyle="secondary-outline",
            command=lambda: open_in_explorer(config.OUTPUT_DIR),
        ).pack(side="left")

        sub = tb.Notebook(parent)
        sub.pack(fill="both", expand=True)
        f1 = tb.Frame(sub, padding=6)
        f2 = tb.Frame(sub, padding=6)
        sub.add(f1, text="  Intrinsic values  ")
        sub.add(f2, text="  Excluded companies  ")
        self.tree_r = self._scrolled_tree(f1)
        self.tree_x = self._scrolled_tree(f2)

    def _scrolled_tree(self, parent):
        tree = ttk.Treeview(parent, show="headings")
        ysb = ttk.Scrollbar(parent, orient="vertical", command=tree.yview)
        xsb = ttk.Scrollbar(parent, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=ysb.set, xscrollcommand=xsb.set)
        tree.grid(row=0, column=0, sticky="nsew")
        ysb.grid(row=0, column=1, sticky="ns")
        xsb.grid(row=1, column=0, sticky="ew")
        parent.rowconfigure(0, weight=1)
        parent.columnconfigure(0, weight=1)
        return tree

    def _fill_tree(self, tree, path, max_rows=3000):
        tree.delete(*tree.get_children())
        tree["columns"] = ()
        if not Path(path).exists():
            return False
        try:
            df = pd.read_csv(path, dtype=str, keep_default_na=False)
        except Exception as e:
            self._echo(f"[gui] could not read {Path(path).name}: {e}\n")
            return False
        cols = list(df.columns)
        tree["columns"] = cols
        for c in cols:
            tree.heading(c, text=c)
            tree.column(c, width=min(max(90, len(str(c)) * 8), 280), anchor="w")
        for _, row in df.head(max_rows).iterrows():
            tree.insert("", "end", values=list(row))
        return True

    def _load_results(self):
        out = config.OUTPUT_DIR
        self._fill_tree(self.tree_r, out / f"{config.OUTPUT_BASENAME}.csv")
        self._fill_tree(
            self.tree_x,
            out
            / f"{getattr(config, 'EXCLUSIONS_BASENAME', 'Intrinsic_Value_Excluded')}.csv",
        )
        self._load_charts()

    # ---------------------------------------------------------------- charts
    def _build_charts(self, parent):
        left = tb.Frame(parent)
        left.pack(side="left", fill="y", padx=(0, 10))
        tb.Label(left, text="Generated charts").pack(anchor="w", pady=(0, 6))
        self.lst_charts = tk.Listbox(left, width=38, height=26, font=MONO)
        self.lst_charts.pack(fill="y", expand=True)
        self.lst_charts.bind("<<ListboxSelect>>", self._show_chart)
        tb.Button(
            left,
            text="Refresh",
            bootstyle="secondary-outline",
            command=self._load_charts,
        ).pack(fill="x", pady=(6, 0))

        self.chart_panel = tb.Label(
            parent,
            text="Run the pipeline, then pick a chart.",
            anchor="center",
            bootstyle="secondary",
        )
        self.chart_panel.pack(side="left", fill="both", expand=True)

    def _chart_dir(self):
        return config.OUTPUT_DIR / getattr(config, "CHART_DIR_NAME", "charts")

    def _load_charts(self):
        self.lst_charts.delete(0, "end")
        d = self._chart_dir()
        if not d.exists():
            return
        for p in sorted(d.glob("*.png")):
            self.lst_charts.insert("end", p.name)

    def _show_chart(self, _event=None):
        sel = self.lst_charts.curselection()
        if not sel:
            return
        path = self._chart_dir() / self.lst_charts.get(sel[0])
        try:
            if HAVE_PIL:
                img = Image.open(path)
                w = max(self.chart_panel.winfo_width(), 640) - 20
                h = max(self.chart_panel.winfo_height(), 480) - 20
                img.thumbnail((w, h))
                self._chart_ref = ImageTk.PhotoImage(img)
            else:
                # Tk 8.6 reads PNG natively; without Pillow it cannot be scaled,
                # so a 200-dpi chart will simply be shown at full size.
                self._chart_ref = tk.PhotoImage(file=str(path))
            self.chart_panel.configure(image=self._chart_ref, text="")
        except Exception as e:
            self.chart_panel.configure(
                image="", text=f"Could not display {path.name}\n{type(e).__name__}: {e}"
            )

    # ------------------------------------------------------------- statusbar
    def _build_statusbar(self):
        tb.Separator(self).pack(fill="x")
        bar = tb.Frame(self, padding=(14, 6))
        bar.pack(fill="x")
        tb.Label(bar, textvariable=self.v_status, bootstyle="secondary").pack(
            side="left"
        )
        tb.Label(
            bar,
            text=f"output: {config.OUTPUT_DIR}",
            bootstyle="secondary",
        ).pack(side="right")

    # ----------------------------------------------------------- run control
    def _apply_settings(self):
        """Push widget state onto config, exactly as run.apply_args does."""
        mode = self.v_screening.get()
        config.SUFFICIENCY_ENABLED = mode != "off"
        if mode != "off":
            config.SUFFICIENCY_MODE = mode
        config.MIN_COMPLETE_FY = int(self.v_min_fy.get())
        config.MIN_BENCHMARK_FY = int(self.v_min_bench.get())
        config.SUFFICIENCY_REQUIRE_ANCHOR_PRICE = bool(self.v_need_price.get())
        config.SUFFICIENCY_KEEP_IN_PEERS = bool(self.v_keep_peers.get())
        config.SUFFICIENCY_KEEP_IN_ML = bool(self.v_keep_ml.get())
        config.EXCLUSION_SHEET_INCLUDE_PASSED = bool(self.v_sheet_all.get())

        config.BENCHMARK_BASIS = self.v_bench.get()
        config.BENCHMARK_MAX_OFFSET_DAYS = int(self.v_offset.get())
        config.FY_MEAN_BASIS = self.v_meanbasis.get()
        config.EXCHANGE_SUFFIX = self.v_exchange.get()

        config.ML_ENABLED = bool(self.v_ml.get())
        config.ML_SPLIT = self.v_mlsplit.get()
        config.ESTIMATION_MODE = self.v_estimation.get()
        config.ANALYSIS_ENABLED = bool(self.v_analyze.get())
        config.CHART_DPI = int(self.v_dpi.get())

        config.FY_LABEL_STYLE = self.v_fylabel.get()
        reasons = self.v_reasons.get()
        config.SHOW_REASONS = reasons != "off"
        if reasons != "off":
            config.REASON_STYLE = reasons
        config.USE_OVERRIDES = bool(self.v_overrides.get())
        config.OFFLINE = bool(self.v_offline.get())

    def _selected(self):
        return [c for c in self.companies if self.include.get(c["name"], True)]

    def _run_full(self):
        self._start("run")

    def _run_screen(self):
        self._start("screen")

    def _start(self, mode):
        if self.worker and self.worker.is_alive():
            return
        self._apply_settings()

        if config.OFFLINE:
            import mock_source

            selected = mock_source.COMPANIES
            ticker_resolver.resolve = mock_source.resolve
        else:
            selected = self._selected()

        if not selected:
            messagebox.showwarning(
                "Nothing to run", "No companies are selected on the Companies tab."
            )
            return

        self.cancel.clear()
        self.expected = len(selected)
        self.fetched = 0
        self.pbar.configure(maximum=max(self.expected, 1), value=0)
        self.btn_run.configure(state="disabled")
        self.btn_screen.configure(state="disabled")
        self.btn_cancel.configure(state="normal")
        self.v_status.set(
            f"running {'sufficiency screen' if mode == 'screen' else 'full valuation'} "
            f"on {self.expected} companies ..."
        )
        self.nb.select(self.tab_run)
        self._echo(
            f"\n{'=' * 78}\n[gui] {mode} starting - {self.expected} companies, "
            f"gate {'off' if not config.SUFFICIENCY_ENABLED else config.SUFFICIENCY_MODE}, "
            f"MIN_COMPLETE_FY={config.MIN_COMPLETE_FY}\n{'=' * 78}\n"
        )

        self.worker = threading.Thread(
            target=self._work, args=(mode, selected), daemon=True
        )
        self.worker.start()

    def _work(self, mode, selected):
        """Worker thread. Touches no widgets - everything goes via the queue."""
        writer = QueueWriter(self.queue, self.cancel)
        old_out, old_err = sys.stdout, sys.stderr
        sys.stdout = sys.stderr = writer
        try:
            if mode == "screen":
                pipeline.screen_only(selected)
            else:
                pipeline.run(selected)
            self.queue.put(("done", "finished"))
        except RunCancelled:
            self.queue.put(("done", "cancelled"))
        except BaseException as e:  # noqa: BLE001 - the worker must never die silently
            log.exception("gui run failed")
            self.queue.put(
                ("out", f"\nFATAL: {type(e).__name__}: {e}\n{traceback.format_exc()}\n")
            )
            self.queue.put(("done", "failed"))
        finally:
            sys.stdout, sys.stderr = old_out, old_err

    def _request_cancel(self):
        if self.worker and self.worker.is_alive():
            self.cancel.set()
            self.v_status.set("cancelling - will stop at the next company ...")
            self._echo("\n[gui] cancel requested\n")

    def _drain(self):
        """Main thread. Empties the queue into the console and progress bar."""
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                if kind == "out":
                    self._echo(payload)
                    hits = payload.count("[fetch] ")
                    if hits:
                        self.fetched = min(self.fetched + hits, self.expected)
                        self.pbar.configure(value=self.fetched)
                        self.v_status.set(
                            f"fetching {self.fetched}/{self.expected} ..."
                        )
                    for marker, label in (
                        ("[gate]", "screening data sufficiency"),
                        ("[ml]", "training ML models"),
                        ("[export]", "writing output files"),
                        ("[analyzer]", "generating charts"),
                    ):
                        if marker in payload:
                            self.v_status.set(label)
                elif kind == "done":
                    self._finish(payload)
        except queue.Empty:
            pass
        self.after(120, self._drain)

    def _finish(self, outcome):
        self.btn_run.configure(state="normal")
        self.btn_screen.configure(state="normal")
        self.btn_cancel.configure(state="disabled")
        self.pbar.configure(value=self.expected if outcome == "finished" else 0)
        self.v_status.set(f"{outcome}  -  log: {config.OUTPUT_DIR / config.LOG_FILE}")
        self._echo(f"\n[gui] {outcome}\n")
        if outcome == "finished":
            self._load_results()
            self.nb.select(self.tab_results)

    def _on_close(self):
        if self.worker and self.worker.is_alive():
            if not messagebox.askokcancel(
                "Run in progress",
                "A run is still going. Close anyway?\n\n"
                "Partial output files may be left behind.",
            ):
                return
            self.cancel.set()
        self.destroy()


def launch():
    setup_logging()
    App().mainloop()


if __name__ == "__main__":
    launch()
