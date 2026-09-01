# FILE: gui.py
"""
Desktop front end for the intrinsic value engine.

    python run.py --gui        (preferred)
    python gui.py              (also works)

WRITTEN FOR TWO AUDIENCES

The engine is a research instrument, but the window in front of it should be
usable by someone who has never valued a company. So the interface runs in two
modes. SIMPLE mode shows four decisions in plain words and hides everything
else behind sensible defaults. ADVANCED mode exposes every knob the CLI has,
each one captioned with what it does and what changes in the output when you
move it. The mode switch is in the header; Simple is the default.

Nothing is hidden that changes a number silently. Anything altered in Advanced
mode that could affect a published figure prints into the technical log.

ARCHITECTURE NOTES

1. The pipeline runs on a WORKER THREAD. A real run is minutes of network I/O;
   on the main thread the window would stop repainting. Only the worker calls
   pipeline code, only the main thread touches widgets, and they communicate
   through a queue drained by a timer.

2. stdout IS REDIRECTED into that queue, so every diagnostic the pipeline
   prints appears live. The GUI additionally TRANSLATES those lines into plain
   English for the progress panel - the raw text stays available under
   "Technical log" for anyone who wants it.

3. CANCELLATION rides on the redirect: QueueWriter.write() raises RunCancelled
   when the flag is set, so the run stops at the next print. RunCancelled
   inherits from BaseException because pipeline.py is full of 'except
   Exception' guards that would otherwise swallow it.

4. EVERY SETTINGS READ IS GUARDED. A spinbox holding "" or "abc" used to raise
   inside the settings reader, the exception vanished into Tk's silent error
   handler, and the Run button appeared to do nothing whatsoever.

5. matplotlib is pinned to Agg before any pyplot import, because charts render
   on the worker thread and a GUI backend there would touch Tk from the wrong
   thread and take the process down.
"""

import logging
import os
import queue
import re
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

import matplotlib

matplotlib.use("Agg")

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

try:
    import ttkbootstrap as tb
except ImportError as exc:
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
H1 = ("Segoe UI Semibold", 15)
H2 = ("Segoe UI Semibold", 11)
BODY = ("Segoe UI", 9)
TICK, CROSS = "\u2713", ""

# Raw pipeline output -> what a human should read. Order matters: the first
# pattern that matches a line wins.
STEPS = [
    ("input", "Reading your company list"),
    ("fetch", "Downloading published accounts and share prices"),
    ("gate", "Checking each company has enough data to be valued fairly"),
    ("estimate", "Filling small gaps in the accounts"),
    ("ml", "Teaching the AI models from historical patterns"),
    ("export", "Writing your spreadsheet and CSV files"),
    ("analyzer", "Drawing the charts"),
]

TRANSLATIONS = [
    (r"^\[input\]", "Reading your company list"),
    (r"^\[fetch\] (.+?) \.\.\.", "Downloading data for {0}"),
    (r"^\[gate\] data sufficiency", "Checking data quality"),
    (r"^\[gate\] AUTO-ADJUSTED", "Data was thinner than expected - adjusting"),
    (r"^\[gate\] (\d+)/(\d+) companies pass", "{0} of {1} companies have enough data"),
    (r"^\[estimate\]", "Filling small gaps in the accounts"),
    (r"^\[ml\] building", "Preparing the AI training data"),
    (r"^\[ml\] (\d+) rows", "Training the AI models on {0} company-years"),
    (r"^\[export\]", "Writing your report files"),
    (r"^\[analyzer\]", "Drawing the charts"),
]


class RunCancelled(BaseException):
    """Raised inside the worker when the user presses Stop."""


class QueueWriter:
    """
    Stand-in for sys.stdout that forwards to the GUI queue.

    Chunks pass through verbatim rather than being split into lines, so
    print(..., end=' ', flush=True) still renders as one growing line - that
    is how the fetch progress reads in a terminal and there is no reason to
    lose it here.
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
    if not path.exists():
        messagebox.showinfo(
            "Not there yet",
            f"{path.name} has not been created yet.\n\n"
            f"Run a calculation first - the file appears when it finishes.",
        )
        return
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(path))  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except Exception as e:
        messagebox.showerror("Could not open", f"{type(e).__name__}: {e}")


def translate(line):
    """Raw pipeline line -> plain sentence, or None if it isn't worth showing."""
    for pattern, template in TRANSLATIONS:
        m = re.search(pattern, line)
        if m:
            try:
                return template.format(*m.groups())
            except (IndexError, KeyError):
                return template
    return None


class App(tb.Window):
    def __init__(self):
        super().__init__(themename=getattr(config, "GUI_THEME", "flatly"))
        self.title("Intrinsic Value Calculator")
        self.geometry(getattr(config, "GUI_WINDOW_SIZE", "1280x820"))
        self.minsize(*getattr(config, "GUI_MIN_SIZE", (1060, 700)))

        self.companies = []
        self.include = {}
        self.queue = queue.Queue()
        self.cancel = threading.Event()
        self.worker = None
        self.expected = 0
        self.fetched = 0
        self.last_records = None
        self._chart_ref = None
        self._advanced_frames = []

        self._build_vars()
        self._build_header()
        self._build_tabs()
        self._build_statusbar()

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(150, self._drain)

        if config.DEFAULT_INPUT.exists():
            self._load_companies(config.DEFAULT_INPUT)
        self._apply_mode()

    # ------------------------------------------------------------------ vars
    def _build_vars(self):
        g = getattr
        self.v_input = tk.StringVar(value=str(config.DEFAULT_INPUT))
        self.v_advanced = tk.BooleanVar(value=False)
        self.v_dark = tk.BooleanVar(value=False)

        self.v_screening = tk.StringVar(
            value=(
                "off"
                if not g(config, "SUFFICIENCY_ENABLED", True)
                else g(config, "SUFFICIENCY_MODE", "enforce")
            )
        )
        self.v_min_fy = tk.IntVar(value=g(config, "MIN_COMPLETE_FY", 3))
        self.v_min_bench = tk.IntVar(value=g(config, "MIN_BENCHMARK_FY", 3))
        self.v_autorelax = tk.BooleanVar(
            value=g(config, "SUFFICIENCY_AUTO_RELAX", True)
        )
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
        self.v_estimation = tk.StringVar(value=g(config, "ESTIMATION_MODE", "balanced"))
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
        self.v_overrides = tk.BooleanVar(value=g(config, "USE_OVERRIDES", True))
        self.v_offline = tk.BooleanVar(value=g(config, "OFFLINE", False))

        self.v_status = tk.StringVar(value="Ready")
        self.v_headline = tk.StringVar(value="Nothing running yet")
        self.v_count = tk.StringVar(value="No companies loaded")
        self.v_gatehint = tk.StringVar(value="")
        self.v_shownlog = tk.BooleanVar(value=False)

        # Live feedback: moving the strictness dial re-estimates survivors
        # against the last screening, so the effect is visible before running.
        for var in (self.v_min_fy, self.v_min_bench):
            var.trace_add("write", lambda *_: self._update_gate_hint())

    def _iget(self, var, fallback):
        """IntVar.get() raises on empty or non-numeric spinbox text. See note 4."""
        try:
            return int(var.get())
        except Exception:
            return fallback

    # ---------------------------------------------------------------- header
    def _build_header(self):
        bar = tb.Frame(self, padding=(16, 12))
        bar.pack(fill="x")
        box = tb.Frame(bar)
        box.pack(side="left")
        tb.Label(box, text="Intrinsic Value Calculator", font=H1).pack(anchor="w")
        tb.Label(
            box,
            text="Works out what Indian listed companies appear to be worth, "
            "then compares that with what their shares actually traded at.",
            bootstyle="secondary",
            font=BODY,
        ).pack(anchor="w")

        right = tb.Frame(bar)
        right.pack(side="right")
        tb.Checkbutton(
            right,
            text="Dark",
            variable=self.v_dark,
            bootstyle="round-toggle",
            command=self._toggle_theme,
        ).pack(side="right", padx=(12, 0))
        tb.Checkbutton(
            right,
            text="Advanced settings",
            variable=self.v_advanced,
            bootstyle="round-toggle",
            command=self._apply_mode,
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

    def _apply_mode(self):
        show = self.v_advanced.get()
        for frame in self._advanced_frames:
            if show:
                frame.pack(fill="x", pady=(0, 12))
            else:
                frame.pack_forget()

    # ------------------------------------------------------------------ tabs
    def _build_tabs(self):
        nb = tb.Notebook(self, padding=10)
        nb.pack(fill="both", expand=True)
        self.nb = nb
        self.tab_start = tb.Frame(nb, padding=14)
        self.tab_settings = tb.Frame(nb, padding=14)
        self.tab_progress = tb.Frame(nb, padding=14)
        self.tab_results = tb.Frame(nb, padding=14)
        self.tab_charts = tb.Frame(nb, padding=14)
        self.tab_help = tb.Frame(nb, padding=14)
        nb.add(self.tab_start, text="  1. Start here  ")
        nb.add(self.tab_settings, text="  2. Settings  ")
        nb.add(self.tab_progress, text="  3. Progress  ")
        nb.add(self.tab_results, text="  4. Results  ")
        nb.add(self.tab_charts, text="  5. Charts  ")
        nb.add(self.tab_help, text="  What do these words mean?  ")

        self._build_start(self.tab_start)
        self._build_settings(self.tab_settings)
        self._build_progress(self.tab_progress)
        self._build_results(self.tab_results)
        self._build_charts(self.tab_charts)
        self._build_help(self.tab_help)

    # ----------------------------------------------------------------- start
    def _build_start(self, parent):
        step1 = tb.Labelframe(
            parent, text="  Step 1  -  choose your companies  ", padding=12
        )
        step1.pack(fill="x", pady=(0, 12))
        tb.Label(
            step1,
            text="A plain CSV file with four columns: company name, sector, market cap "
            "tier, and NSE/BSE ticker.\nUntick any company you want left out of this run.",
            bootstyle="secondary",
            justify="left",
            font=BODY,
        ).pack(anchor="w", pady=(0, 8))
        row = tb.Frame(step1)
        row.pack(fill="x")
        tb.Entry(row, textvariable=self.v_input).pack(
            side="left", fill="x", expand=True
        )
        tb.Button(row, text="Browse", bootstyle="secondary", command=self._browse).pack(
            side="left", padx=(8, 0)
        )
        tb.Button(
            row, text="Reload", bootstyle="secondary-outline", command=self._reload
        ).pack(side="left", padx=(6, 0))

        mid = tb.Frame(parent)
        mid.pack(fill="both", expand=True, pady=(0, 12))
        cols = ("inc", "name", "sector", "cap", "ticker")
        self.tree_c = ttk.Treeview(
            mid, columns=cols, show="headings", selectmode="none"
        )
        for key, label, w, anchor in (
            ("inc", "Include", 70, "center"),
            ("name", "Company", 330, "w"),
            ("sector", "Sector", 250, "w"),
            ("cap", "Size", 90, "w"),
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

        tools = tb.Frame(parent)
        tools.pack(fill="x", pady=(0, 12))
        for text, fn in (
            ("Include all", lambda: self._set_all(True)),
            ("Include none", lambda: self._set_all(False)),
            ("Flip selection", self._invert),
        ):
            tb.Button(tools, text=text, bootstyle="secondary-outline", command=fn).pack(
                side="left", padx=(0, 6)
            )
        tb.Label(tools, textvariable=self.v_count, bootstyle="secondary").pack(
            side="right"
        )

        step2 = tb.Labelframe(parent, text="  Step 2  -  run it  ", padding=12)
        step2.pack(fill="x")
        tb.Label(
            step2,
            text="The full calculation downloads five years of accounts and prices for "
            "every company,\nvalues each one six different ways, and writes an Excel "
            "workbook plus CSV files.\nBudget roughly one second per company, plus a "
            "minute or two for the AI models.",
            bootstyle="secondary",
            justify="left",
            font=BODY,
        ).pack(anchor="w", pady=(0, 10))
        btns = tb.Frame(step2)
        btns.pack(fill="x")
        self.btn_run = tb.Button(
            btns,
            text="Calculate intrinsic values",
            bootstyle="success",
            width=28,
            command=lambda: self._start("run"),
        )
        self.btn_run.pack(side="left")
        self.btn_screen = tb.Button(
            btns,
            text="Just check my data (no report)",
            bootstyle="info-outline",
            width=30,
            command=lambda: self._start("screen"),
        )
        self.btn_screen.pack(side="left", padx=10)
        tb.Label(
            btns,
            text="The second button only tests whether each company has enough data.\n"
            "It is fast, and it does NOT produce a spreadsheet.",
            bootstyle="secondary",
            justify="left",
            font=BODY,
        ).pack(side="left", padx=(10, 0))

    def _browse(self):
        p = filedialog.askopenfilename(
            title="Select your company list",
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
            messagebox.showerror(
                "Could not read that file",
                f"{type(e).__name__}: {e}\n\n"
                f"The file needs a header row reading:\n"
                f"company name, sector name, market cap, ticker",
            )
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
        self.v_count.set(f"{n} of {len(self.companies)} companies will be included")

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
    def _setting(self, parent, title, why, builder):
        """One captioned control: bold label, plain explanation, then the widget."""
        block = tb.Frame(parent)
        block.pack(fill="x", pady=(0, 14))
        tb.Label(block, text=title, font=H2).pack(anchor="w")
        tb.Label(
            block,
            text=why,
            bootstyle="secondary",
            justify="left",
            wraplength=520,
            font=BODY,
        ).pack(anchor="w", pady=(1, 5))
        holder = tb.Frame(block)
        holder.pack(anchor="w")
        builder(holder)
        return block

    def _build_settings(self, parent):
        canvas = tk.Canvas(parent, highlightthickness=0)
        sb = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        inner = tb.Frame(canvas, padding=(0, 0, 16, 0))
        inner.bind(
            "<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        tb.Label(
            inner,
            text="Everything here has a sensible default. You can run the whole "
            "thing without changing a single setting.",
            bootstyle="secondary",
            font=BODY,
        ).pack(anchor="w", pady=(0, 16))

        # ---------- always visible ----------
        basic = tb.Labelframe(
            inner, text="  The four decisions that matter  ", padding=14
        )
        basic.pack(fill="x", pady=(0, 12))

        self._setting(
            basic,
            "How much missing data will you tolerate?",
            "Some companies simply do not have five years of published accounts "
            "available. This sets how many complete years a company needs before "
            "it is valued at all. Raise it for a cleaner sample and fewer "
            "companies; lower it for more companies and shakier numbers. If your "
            "setting turns out to be impossible for every company, the program "
            "lowers it automatically and tells you.",
            lambda h: (
                tb.Spinbox(h, from_=1, to=5, textvariable=self.v_min_fy, width=6).pack(
                    side="left"
                ),
                tb.Label(h, text="  complete years out of 5", font=BODY).pack(
                    side="left"
                ),
            ),
        )
        tb.Label(
            basic,
            textvariable=self.v_gatehint,
            bootstyle="info",
            font=BODY,
            wraplength=520,
            justify="left",
        ).pack(anchor="w", pady=(0, 14))

        self._setting(
            basic,
            "Should the AI models run?",
            "Three pattern-matching models (XGBoost, Random Forest, LightGBM) learn "
            "from every company at once instead of valuing each one from first "
            "principles. They add a few minutes to the run. Switch them off if you "
            "only want the three classical valuation methods.",
            lambda h: tb.Checkbutton(
                h, text="Yes, include the AI valuations", variable=self.v_ml
            ).pack(anchor="w"),
        )

        self._setting(
            basic,
            "Should small gaps in the accounts be filled in?",
            "When one figure is missing from an otherwise complete year, the program "
            "can estimate it from the company's own trend or from its sector. Every "
            "estimated number is marked with an asterisk and explained on the "
            "'Methods' sheet - nothing is invented quietly. Turn this off to see "
            "only what was actually published.",
            lambda h: tb.Combobox(
                h,
                textvariable=self.v_estimation,
                values=["balanced", "aggressive", "off"],
                state="readonly",
                width=14,
            ).pack(anchor="w"),
        )

        self._setting(
            basic,
            "Should the charts be drawn?",
            "Produces the statistical charts comparing the six methods. Skipping "
            "this makes the run finish sooner; your spreadsheets are unaffected.",
            lambda h: tb.Checkbutton(
                h, text="Yes, draw the charts", variable=self.v_analyze
            ).pack(anchor="w"),
        )

        # ---------- advanced only ----------
        adv1 = tb.Labelframe(inner, text="  Data quality rules  ", padding=14)
        self._advanced_frames.append(adv1)
        self._setting(
            adv1,
            "What happens to companies that fail the data check?",
            "'Drop them' keeps them out of the report but still counts them when "
            "working out sector averages. 'Flag only' values everybody and just "
            "lists the doubtful ones. 'Off' skips the check entirely.",
            lambda h: [
                tb.Radiobutton(h, text=lbl, value=val, variable=self.v_screening).pack(
                    side="left", padx=(0, 14)
                )
                for val, lbl in (
                    ("enforce", "Drop them"),
                    ("report_only", "Flag only"),
                    ("off", "Off"),
                )
            ],
        )
        self._setting(
            adv1,
            "Years that need a comparison share price",
            "A company can have perfect accounts and still be untestable if its "
            "shares were not trading yet. This is the minimum number of years with "
            "a usable market price.",
            lambda h: tb.Spinbox(
                h, from_=0, to=5, textvariable=self.v_min_bench, width=6
            ).pack(anchor="w"),
        )
        self._setting(
            adv1,
            "Rescue the run if nothing qualifies",
            "If your threshold turns out to be unreachable for every single company, "
            "lower it automatically to the best figure achieved and carry on, rather "
            "than finishing with no report at all.",
            lambda h: tb.Checkbutton(
                h, text="Adjust automatically and warn me", variable=self.v_autorelax
            ).pack(anchor="w"),
        )
        self._setting(
            adv1,
            "Where excluded companies still count",
            "Their data is thin, not wrong. Removing them from the sector averages "
            "would degrade the valuations of every company that did qualify.",
            lambda h: (
                tb.Checkbutton(
                    h, text="Keep them in sector averages", variable=self.v_keep_peers
                ).pack(anchor="w"),
                tb.Checkbutton(
                    h, text="Keep them in AI training", variable=self.v_keep_ml
                ).pack(anchor="w"),
                tb.Checkbutton(
                    h,
                    text="Also list the companies that passed, for a full audit trail",
                    variable=self.v_sheet_all,
                ).pack(anchor="w"),
                tb.Checkbutton(
                    h,
                    text="A year only counts if it also has a share price",
                    variable=self.v_need_price,
                ).pack(anchor="w"),
            ),
        )

        adv2 = tb.Labelframe(
            inner, text="  Which share price to judge against  ", padding=14
        )
        self._advanced_frames.append(adv2)
        self._setting(
            adv2,
            "The comparison price",
            "Results are scored against the share price on the first trading day on "
            "or near 1 May after each financial year ends - about a month after the "
            "accounts close, so the market has seen them. The other two options "
            "average or take the closing price of the whole following year, and "
            "exist as robustness checks. Changing this changes every accuracy "
            "figure in your results.",
            lambda h: tb.Combobox(
                h,
                textvariable=self.v_bench,
                values=["may1", "mean", "close"],
                state="readonly",
                width=12,
            ).pack(anchor="w"),
        )
        self._setting(
            adv2,
            "How far from 1 May we may look",
            "1 May is a market holiday in Maharashtra and often sits next to a "
            "weekend, so an exact match is rare. This is how many days either side "
            "we will accept before giving up and leaving the cell blank.",
            lambda h: tb.Spinbox(
                h, from_=1, to=45, textvariable=self.v_offset, width=6
            ).pack(anchor="w"),
        )
        self._setting(
            adv2,
            "The price used inside the valuation",
            "Separate from the comparison price above. This is the average price "
            "during the financial year, used as an input to the calculations. "
            "Keeping the two apart is what stops the models seeing the future.",
            lambda h: (
                tb.Combobox(
                    h,
                    textvariable=self.v_meanbasis,
                    values=["trading", "calendar"],
                    state="readonly",
                    width=12,
                ).pack(side="left"),
                tb.Combobox(
                    h,
                    textvariable=self.v_exchange,
                    values=[".NS", ".BO"],
                    state="readonly",
                    width=8,
                ).pack(side="left", padx=(10, 0)),
            ),
        )

        adv3 = tb.Labelframe(inner, text="  Report and AI detail  ", padding=14)
        self._advanced_frames.append(adv3)
        self._setting(
            adv3,
            "How the AI models are tested",
            "'expanding' trains only on earlier years, which is correct but leaves "
            "the first years untested. 'loyo' uses every other year, which leaks "
            "future information and exists only for comparison. 'hybrid' does the "
            "first where possible and marks the rest.",
            lambda h: tb.Combobox(
                h,
                textvariable=self.v_mlsplit,
                values=["hybrid", "expanding", "loyo"],
                state="readonly",
                width=12,
            ).pack(anchor="w"),
        )
        self._setting(
            adv3,
            "How years are labelled and blanks explained",
            "Whether the year column reads 2023-24 or 2024, and whether an empty "
            "cell carries a short code, a full sentence, or nothing at all.",
            lambda h: (
                tb.Combobox(
                    h,
                    textvariable=self.v_fylabel,
                    values=["range", "int"],
                    state="readonly",
                    width=10,
                ).pack(side="left"),
                tb.Combobox(
                    h,
                    textvariable=self.v_reasons,
                    values=["code", "detailed", "off"],
                    state="readonly",
                    width=12,
                ).pack(side="left", padx=(10, 0)),
                tb.Spinbox(
                    h, from_=72, to=600, increment=4, textvariable=self.v_dpi, width=8
                ).pack(side="left", padx=(10, 0)),
            ),
        )
        self._setting(
            adv3,
            "Hand-entered figures and offline testing",
            "The override file lets you type in numbers the downloader could not "
            "find. Offline mode uses built-in fake data so you can test the program "
            "without touching the internet.",
            lambda h: (
                tb.Checkbutton(
                    h,
                    text="Use my hand-entered figures (data/fundamentals_override.csv)",
                    variable=self.v_overrides,
                ).pack(anchor="w"),
                tb.Checkbutton(
                    h, text="Offline test mode (fake data)", variable=self.v_offline
                ).pack(anchor="w"),
            ),
        )

    def _update_gate_hint(self):
        """Live 'what would this setting do' feedback, from the last screening."""
        if not self.last_records:
            self.v_gatehint.set(
                "Run 'Just check my data' once and this line will tell you how many "
                "companies survive at any setting."
            )
            return
        need = self._iget(self.v_min_fy, 3)
        need_b = self._iget(self.v_min_bench, 3)
        kept = [
            r
            for r in self.last_records
            if r["complete_fy"] >= need and r["benchmark_fy"] >= need_b
        ]
        total = len(self.last_records)
        best = max((r["complete_fy"] for r in self.last_records), default=0)
        msg = f"At this setting, {len(kept)} of {total} companies would be kept."
        if not kept:
            msg += (
                f"  No company reaches {need} complete years - the best any managed "
                f"was {best}. Set it to {best} or lower."
            )
        elif len(kept) < 10:
            msg += "  That is a small sample; sector averages get unreliable below ten."
        self.v_gatehint.set(msg)

    # -------------------------------------------------------------- progress
    def _build_progress(self, parent):
        head = tb.Frame(parent)
        head.pack(fill="x", pady=(0, 10))
        tb.Label(head, textvariable=self.v_headline, font=H2).pack(anchor="w")
        self.pbar = tb.Progressbar(
            parent, mode="determinate", bootstyle="success-striped"
        )
        self.pbar.pack(fill="x", pady=(0, 12))

        steps = tb.Labelframe(parent, text="  What the program is doing  ", padding=12)
        steps.pack(fill="x", pady=(0, 12))
        self.step_labels = {}
        for key, text in STEPS:
            lbl = tb.Label(steps, text=f"    {text}", bootstyle="secondary", font=BODY)
            lbl.pack(anchor="w", pady=1)
            self.step_labels[key] = (lbl, text)

        ctl = tb.Frame(parent)
        ctl.pack(fill="x", pady=(0, 8))
        self.btn_cancel = tb.Button(
            ctl,
            text="Stop",
            bootstyle="danger-outline",
            command=self._request_cancel,
            state="disabled",
        )
        self.btn_cancel.pack(side="left")
        tb.Checkbutton(
            ctl,
            text="Show the technical log",
            variable=self.v_shownlog,
            bootstyle="round-toggle",
            command=self._toggle_log,
        ).pack(side="left", padx=14)
        tb.Button(
            ctl,
            text="Save log",
            bootstyle="secondary-outline",
            command=self._save_console,
        ).pack(side="right")
        tb.Button(
            ctl, text="Clear", bootstyle="secondary-outline", command=self._clear
        ).pack(side="right", padx=6)

        self.logbox = tb.Frame(parent)
        self.console = tk.Text(self.logbox, wrap="none", font=MONO, height=18)
        ysb = ttk.Scrollbar(self.logbox, orient="vertical", command=self.console.yview)
        xsb = ttk.Scrollbar(
            self.logbox, orient="horizontal", command=self.console.xview
        )
        self.console.configure(yscrollcommand=ysb.set, xscrollcommand=xsb.set)
        self.console.grid(row=0, column=0, sticky="nsew")
        ysb.grid(row=0, column=1, sticky="ns")
        xsb.grid(row=1, column=0, sticky="ew")
        self.logbox.rowconfigure(0, weight=1)
        self.logbox.columnconfigure(0, weight=1)
        self.console.configure(state="disabled")

    def _toggle_log(self):
        if self.v_shownlog.get():
            self.logbox.pack(fill="both", expand=True)
        else:
            self.logbox.pack_forget()

    def _mark_step(self, key, done=False):
        if key not in self.step_labels:
            return
        lbl, text = self.step_labels[key]
        lbl.configure(
            text=f"  {TICK} {text}" if done else f"  >  {text}",
            bootstyle="success" if done else "primary",
        )

    def _reset_steps(self):
        for key, (lbl, text) in self.step_labels.items():
            lbl.configure(text=f"    {text}", bootstyle="secondary")

    def _clear(self):
        self.console.configure(state="normal")
        self.console.delete("1.0", "end")
        self.console.configure(state="disabled")

    def _save_console(self):
        p = filedialog.asksaveasfilename(
            defaultextension=".txt",
            initialdir=str(config.OUTPUT_DIR),
            initialfile="calculator_log.txt",
        )
        if p:
            Path(p).write_text(self.console.get("1.0", "end"), encoding="utf-8")

    def _echo(self, text):
        self.console.configure(state="normal")
        self.console.insert("end", text)
        self.console.see("end")
        self.console.configure(state="disabled")

    # --------------------------------------------------------------- results
    def _build_results(self, parent):
        self.v_resultsummary = tk.StringVar(
            value="No results yet. Run a calculation from the 'Start here' tab."
        )
        head = tb.Frame(parent)
        head.pack(fill="x", pady=(0, 10))
        tb.Label(
            head,
            textvariable=self.v_resultsummary,
            font=H2,
            wraplength=1000,
            justify="left",
        ).pack(anchor="w")
        tb.Label(
            head,
            text="A star (*) next to a number means part of it was estimated rather "
            "than published. The 'Methods' sheet in the workbook explains every one.",
            bootstyle="secondary",
            font=BODY,
        ).pack(anchor="w", pady=(4, 0))

        bar = tb.Frame(parent)
        bar.pack(fill="x", pady=(0, 8))
        tb.Button(
            bar,
            text="Open the Excel workbook",
            bootstyle="success",
            command=lambda: open_in_explorer(
                config.OUTPUT_DIR / f"{config.OUTPUT_BASENAME}.xlsx"
            ),
        ).pack(side="left")
        tb.Button(
            bar,
            text="Open the output folder",
            bootstyle="secondary-outline",
            command=lambda: open_in_explorer(config.OUTPUT_DIR),
        ).pack(side="left", padx=8)
        tb.Button(
            bar,
            text="Refresh",
            bootstyle="secondary-outline",
            command=self._load_results,
        ).pack(side="left")

        sub = tb.Notebook(parent)
        sub.pack(fill="both", expand=True)
        f1 = tb.Frame(sub, padding=6)
        f2 = tb.Frame(sub, padding=6)
        f3 = tb.Frame(sub, padding=6)
        sub.add(f1, text="  What each company looks worth  ")
        sub.add(f2, text="  Companies we could not value  ")
        sub.add(f3, text="  Full detail  ")
        self.tree_plain = self._scrolled_tree(f1)
        self.tree_x = self._scrolled_tree(f2)
        self.tree_r = self._scrolled_tree(f3)

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

    def _fill_tree(self, tree, path, max_rows=4000):
        tree.delete(*tree.get_children())
        tree["columns"] = ()
        if not Path(path).exists():
            return None
        try:
            df = pd.read_csv(path, dtype=str, keep_default_na=False)
        except Exception as e:
            self._echo(f"[gui] could not read {Path(path).name}: {e}\n")
            return None
        cols = list(df.columns)
        tree["columns"] = cols
        for c in cols:
            tree.heading(c, text=c)
            tree.column(c, width=min(max(90, len(str(c)) * 8), 300), anchor="w")
        for _, row in df.head(max_rows).iterrows():
            tree.insert("", "end", values=list(row))
        return df

    def _build_plain_table(self):
        """Turn the numeric export into something a non-specialist can read."""
        path = config.OUTPUT_DIR / f"{config.DATA_BASENAME}.csv"
        self.tree_plain.delete(*self.tree_plain.get_children())
        if not path.exists():
            return
        try:
            df = pd.read_csv(path)
        except Exception:
            return

        value_cols = [c for c in df.columns if "Intrinsic Value" in c]
        cols = [
            "Company",
            "Year",
            "Share price",
            "Estimated worth",
            "What this suggests",
        ]
        self.tree_plain["columns"] = cols
        for c, w in zip(cols, (300, 90, 110, 130, 220)):
            self.tree_plain.heading(c, text=c)
            self.tree_plain.column(c, width=w, anchor="w")

        band = getattr(config, "PLAIN_VERDICT_BAND", 0.10)
        cheap = dear = fair = 0
        for _, r in df.iterrows():
            price = pd.to_numeric(r.get("Market Price"), errors="coerce")
            vals = [
                v
                for v in (pd.to_numeric(r.get(c), errors="coerce") for c in value_cols)
                if pd.notna(v) and v > 0
            ]
            if pd.isna(price) or not vals:
                verdict, worth = "Not enough data that year", ""
            else:
                avg = sum(vals) / len(vals)
                worth = f"{avg:,.0f}"
                if price < avg * (1 - band):
                    verdict = "Price looks low vs the estimate"
                    cheap += 1
                elif price > avg * (1 + band):
                    verdict = "Price looks high vs the estimate"
                    dear += 1
                else:
                    verdict = "Price and estimate broadly agree"
                    fair += 1
            self.tree_plain.insert(
                "",
                "end",
                values=(
                    r.get("Company name", ""),
                    r.get("Financial Year", ""),
                    "" if pd.isna(price) else f"{price:,.0f}",
                    worth,
                    verdict,
                ),
            )

        n_co = df["Company name"].nunique() if "Company name" in df.columns else 0
        self.v_resultsummary.set(
            f"{n_co} companies valued over {len(df)} company-years.  "
            f"Price looked low in {cheap}, high in {dear}, and about right in {fair}.  "
            f"'Estimated worth' is the average across whichever of the six methods "
            f"produced a number that year."
        )

    def _load_results(self):
        out = config.OUTPUT_DIR
        self._fill_tree(self.tree_r, out / f"{config.OUTPUT_BASENAME}.csv")
        self._fill_tree(
            self.tree_x,
            out
            / f"{getattr(config, 'EXCLUSIONS_BASENAME', 'Intrinsic_Value_Excluded')}.csv",
        )
        self._build_plain_table()
        self._load_charts()

    # ---------------------------------------------------------------- charts
    def _build_charts(self, parent):
        tb.Label(
            parent,
            text="Charts comparing how the six valuation methods performed. "
            "Pick one from the list.",
            bootstyle="secondary",
            font=BODY,
        ).pack(anchor="w", pady=(0, 8))
        body = tb.Frame(parent)
        body.pack(fill="both", expand=True)
        left = tb.Frame(body)
        left.pack(side="left", fill="y", padx=(0, 12))
        self.lst_charts = tk.Listbox(left, width=36, height=24, font=MONO)
        self.lst_charts.pack(fill="y", expand=True)
        self.lst_charts.bind("<<ListboxSelect>>", self._show_chart)
        tb.Button(
            left,
            text="Refresh",
            bootstyle="secondary-outline",
            command=self._load_charts,
        ).pack(fill="x", pady=(6, 0))
        self.chart_panel = tb.Label(
            body,
            text="Charts appear here once a calculation has finished.",
            anchor="center",
            bootstyle="secondary",
        )
        self.chart_panel.pack(side="left", fill="both", expand=True)

    def _chart_dir(self):
        return config.OUTPUT_DIR / getattr(config, "CHART_DIR_NAME", "charts")

    def _load_charts(self):
        self.lst_charts.delete(0, "end")
        d = self._chart_dir()
        if d.exists():
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
                self._chart_ref = tk.PhotoImage(file=str(path))
            self.chart_panel.configure(image=self._chart_ref, text="")
        except Exception as e:
            self.chart_panel.configure(
                image="", text=f"Could not display {path.name}\n{type(e).__name__}: {e}"
            )

    # ------------------------------------------------------------------ help
    def _build_help(self, parent):
        txt = tk.Text(parent, wrap="word", font=("Segoe UI", 10), padx=16, pady=14)
        sb = ttk.Scrollbar(parent, orient="vertical", command=txt.yview)
        txt.configure(yscrollcommand=sb.set)
        txt.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        txt.tag_configure("h", font=("Segoe UI Semibold", 12), spacing1=12, spacing3=4)
        txt.tag_configure("p", spacing3=8)

        def head(s):
            txt.insert("end", s + "\n", "h")

        def para(s):
            txt.insert("end", s + "\n", "p")

        head("What is intrinsic value?")
        para(
            "The share price tells you what people are paying today. Intrinsic value "
            "is an estimate of what the business is actually worth, worked out from "
            "its published accounts. When the two differ a lot, either the market "
            "knows something the accounts do not, or the shares are mispriced. This "
            "program does not tell you which."
        )
        head("The three classical methods")
        para(
            "Discounted Cash Flow (DCF) forecasts the cash the business will generate "
            "over the next five years, then reduces those future amounts to what they "
            "are worth today. It suits steady, cash-generating companies and struggles "
            "with young or loss-making ones."
        )
        para(
            "P/E Relative asks what similar companies in the same sector are being "
            "valued at for each rupee of profit, then applies that to this company's "
            "profit. It needs the company to be profitable."
        )
        para(
            "EV/EBITDA values the whole business - shares plus debt - against its "
            "operating profit, then subtracts the debt. It is the fairest way to "
            "compare companies that carry very different amounts of borrowing."
        )
        head("The three AI methods")
        para(
            "XGBoost, Random Forest and LightGBM do not reason about a business at "
            "all. They study how the market has historically priced companies with "
            "similar financial profiles, and predict accordingly. They often beat the "
            "classical methods on accuracy and can never explain themselves as "
            "clearly. Both facts matter."
        )
        head("Why some companies get left out")
        para(
            "Two reasons. First, the data source publishes only about four years of "
            "annual accounts, so the earliest years are usually missing for everybody. "
            "Second, banks and similar lenders do not report the operating-profit "
            "figures these methods need - their accounts are structured differently, "
            "so a number calculated for them would be meaningless rather than merely "
            "imprecise. Every excluded company is listed with its reason."
        )
        head("What the asterisk means")
        para(
            "A star next to a figure means at least one input was estimated rather "
            "than taken from a published statement. The estimate is always derived "
            "from the company's own history or its sector, never guessed, and the "
            "'Methods' sheet records exactly how each one was produced."
        )
        head("The comparison price")
        para(
            "Results are judged against the share price around 1 May following each "
            "financial year - roughly a month after the accounts are published, so "
            "the market has had a chance to react to them. Using a price from during "
            "the year would let the calculation peek at information it should not have."
        )
        head("A word of caution")
        para(
            "Every number here is an estimate built from past accounts. Valuation "
            "methods disagree with each other for good reasons, and all of them can "
            "be wrong at the same time. Treat the output as a starting point for "
            "investigation, not a recommendation."
        )
        txt.configure(state="disabled")

    # ------------------------------------------------------------- statusbar
    def _build_statusbar(self):
        tb.Separator(self).pack(fill="x")
        bar = tb.Frame(self, padding=(16, 6))
        bar.pack(fill="x")
        tb.Label(
            bar, textvariable=self.v_status, bootstyle="secondary", font=BODY
        ).pack(side="left")
        tb.Label(
            bar,
            text=f"Files are saved to: {config.OUTPUT_DIR}",
            bootstyle="secondary",
            font=BODY,
        ).pack(side="right")

    # ----------------------------------------------------------- run control
    def _apply_settings(self):
        """Push widget state onto config. Every read guarded - see note 4."""
        mode = self.v_screening.get()
        config.SUFFICIENCY_ENABLED = mode != "off"
        if mode != "off":
            config.SUFFICIENCY_MODE = mode
        config.MIN_COMPLETE_FY = self._iget(self.v_min_fy, 3)
        config.MIN_BENCHMARK_FY = self._iget(self.v_min_bench, 3)
        config.SUFFICIENCY_AUTO_RELAX = bool(self.v_autorelax.get())
        config.SUFFICIENCY_REQUIRE_ANCHOR_PRICE = bool(self.v_need_price.get())
        config.SUFFICIENCY_KEEP_IN_PEERS = bool(self.v_keep_peers.get())
        config.SUFFICIENCY_KEEP_IN_ML = bool(self.v_keep_ml.get())
        config.EXCLUSION_SHEET_INCLUDE_PASSED = bool(self.v_sheet_all.get())

        config.BENCHMARK_BASIS = self.v_bench.get()
        config.BENCHMARK_MAX_OFFSET_DAYS = self._iget(self.v_offset, 10)
        config.FY_MEAN_BASIS = self.v_meanbasis.get()
        config.EXCHANGE_SUFFIX = self.v_exchange.get()

        config.ML_ENABLED = bool(self.v_ml.get())
        config.ML_SPLIT = self.v_mlsplit.get()
        config.ESTIMATION_MODE = self.v_estimation.get()
        config.ANALYSIS_ENABLED = bool(self.v_analyze.get())
        config.CHART_DPI = self._iget(self.v_dpi, 200)

        config.FY_LABEL_STYLE = self.v_fylabel.get()
        reasons = self.v_reasons.get()
        config.SHOW_REASONS = reasons != "off"
        if reasons != "off":
            config.REASON_STYLE = reasons
        config.USE_OVERRIDES = bool(self.v_overrides.get())
        config.OFFLINE = bool(self.v_offline.get())

    def _selected(self):
        return [c for c in self.companies if self.include.get(c["name"], True)]

    def _start(self, mode):
        if self.worker and self.worker.is_alive():
            return
        try:
            self._apply_settings()
        except Exception as e:
            messagebox.showerror(
                "A setting could not be read",
                f"{type(e).__name__}: {e}\n\nCheck the Settings tab for an empty or "
                f"non-numeric box.",
            )
            return

        if config.OFFLINE:
            import mock_source

            selected = mock_source.COMPANIES
            ticker_resolver.resolve = mock_source.resolve
        else:
            selected = self._selected()

        if not selected:
            messagebox.showwarning(
                "Nothing selected",
                "No companies are ticked on the 'Start here' tab.",
            )
            return

        if mode == "run" and not messagebox.askokcancel(
            "Ready to calculate",
            f"About to download data for {len(selected)} companies and value each "
            f"one six ways.\n\nThis takes a few minutes. You can stop it at any "
            f"point.\n\nContinue?",
        ):
            return

        self.cancel.clear()
        self.expected = len(selected)
        self.fetched = 0
        self._reset_steps()
        self.pbar.configure(maximum=max(self.expected, 1), value=0)
        self.btn_run.configure(state="disabled")
        self.btn_screen.configure(state="disabled")
        self.btn_cancel.configure(state="normal")
        self.v_headline.set(
            "Checking your data ..." if mode == "screen" else "Working ..."
        )
        self.v_status.set("Running")
        self.nb.select(self.tab_progress)
        self._echo(
            f"\n{'=' * 78}\n[gui] {mode} starting - {self.expected} companies, "
            f"gate={'off' if not config.SUFFICIENCY_ENABLED else config.SUFFICIENCY_MODE}, "
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
                records = pipeline.screen_only(selected)
                self.queue.put(("records", records))
                self.queue.put(("done", "screen_finished"))
            else:
                pipeline.run(selected)
                self.queue.put(("done", "finished"))
        except RunCancelled:
            self.queue.put(("done", "cancelled"))
        except BaseException as e:  # noqa: BLE001 - worker must never die silently
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
            self.v_headline.set("Stopping after the current company ...")

    def _drain(self):
        """Main thread. Empties the queue into the console, steps and progress bar."""
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                if kind == "out":
                    self._echo(payload)
                    self._interpret(payload)
                elif kind == "records":
                    self.last_records = payload
                    self._update_gate_hint()
                elif kind == "done":
                    self._finish(payload)
        except queue.Empty:
            pass
        self.after(120, self._drain)

    def _interpret(self, chunk):
        """Raw output -> headline, step ticks, progress bar."""
        hits = chunk.count("[fetch] ")
        if hits:
            self.fetched = min(self.fetched + hits, self.expected)
            self.pbar.configure(value=self.fetched)
        for line in chunk.splitlines():
            friendly = translate(line)
            if friendly:
                self.v_headline.set(friendly)
            for key, _ in STEPS:
                if line.startswith(f"[{key}]"):
                    self._mark_step(key)
        if "[gate]" in chunk:
            self._mark_step("fetch", done=True)
        if "[export]" in chunk:
            for k in ("fetch", "gate", "estimate", "ml"):
                self._mark_step(k, done=True)
        if "AUTO-ADJUSTED" in chunk:
            self.v_headline.set(
                "Your data was thinner than the setting allowed - threshold lowered "
                "automatically so you still get a report"
            )

    def _finish(self, outcome):
        self.btn_run.configure(state="normal")
        self.btn_screen.configure(state="normal")
        self.btn_cancel.configure(state="disabled")

        if outcome == "finished":
            for key, _ in STEPS:
                self._mark_step(key, done=True)
            self.pbar.configure(value=self.expected)
            self.v_headline.set("Finished. Your spreadsheet is ready.")
            self.v_status.set("Done")
            self._load_results()
            self.nb.select(self.tab_results)
        elif outcome == "screen_finished":
            self._mark_step("fetch", done=True)
            self._mark_step("gate", done=True)
            self.v_headline.set(
                "Data check finished. No spreadsheet was produced - that button only "
                "tests your data. Go to 'Start here' and press "
                "'Calculate intrinsic values' for the report."
            )
            self.v_status.set("Data check done")
            self._fill_tree(
                self.tree_x,
                config.OUTPUT_DIR
                / f"{getattr(config, 'EXCLUSIONS_BASENAME', 'Intrinsic_Value_Excluded')}.csv",
            )
            self.nb.select(self.tab_settings)
        elif outcome == "cancelled":
            self.v_headline.set("Stopped at your request. No files were written.")
            self.v_status.set("Stopped")
        else:
            self.v_headline.set(
                "Something went wrong. Turn on 'Show the technical log' above for "
                "the details."
            )
            self.v_status.set("Failed")
            self.v_shownlog.set(True)
            self._toggle_log()

    def _on_close(self):
        if self.worker and self.worker.is_alive():
            if not messagebox.askokcancel(
                "Still working",
                "A calculation is still running. Close anyway?\n\n"
                "Partly written files may be left behind.",
            ):
                return
            self.cancel.set()
        self.destroy()


def launch():
    setup_logging()
    App().mainloop()


if __name__ == "__main__":
    launch()
