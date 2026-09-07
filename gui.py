# FILE: gui.py
"""
Desktop front end for the intrinsic value engine.

    python run.py --gui        (preferred)
    python gui.py              (also works)

WHAT CHANGED, AND WHY

The old window made you walk through five numbered tabs to do one thing. You
pressed Start on tab 1, were thrown to tab 3 to watch it, then had to find
tab 4 for the numbers and tab 5 for the pictures. Every one of those jumps was
the program's filing system leaking into the user's job.

There are now THREE pages, and they follow what a person actually does:

    1. Load your list      pick the CSV, tick the companies you want
    2. Run it              press the button, and watch it happen RIGHT HERE
    3. Results             opens by itself when the run finishes

Settings moved out of the tab strip entirely and into a gear icon in the
top-right corner, where every application on this machine keeps it. Beside it
sits an "i" that explains the vocabulary on hover. Neither is a place you have
to visit before you can start.

DESIGN NOTES

    1. COLOUR is defined once, in PALETTES, as two complete sets of hex values -
    one light, one dark - rather than borrowed from whichever ttkbootstrap
    theme happened to load. The old dark mode was unreadable for a specific
    reason: tk.Text, tk.Listbox and tk.Canvas are NOT ttk widgets and ignore
    themes completely, so the log, the chart list and the settings page stayed
    near-white with pale grey text on them. Every raw Tk widget is now
    registered with the app and repainted explicitly on every theme change.
    Muted text is a real colour per mode, never bootstyle="secondary", which
    renders at roughly 2:1 contrast on a dark ground.

    2. SCROLLING is handled by bind_wheel(). Tk's canvas has no mouse-wheel
    binding of its own, which is why the settings page used to need the
    scrollbar dragged by hand. Vertical wheel scrolls; SHIFT + wheel scrolls
    sideways - up for left, down for right - on tables, the log, and anything
    else wide. Binding at the widget level and returning "break" also stops the
    wheel silently changing the value of a combobox you happen to be hovering
    over, which is a Tk default that has surprised people for twenty years.

    3. The pipeline runs on a WORKER THREAD. A real run is minutes of network I/O;
    on the main thread the window would stop repainting. Only the worker calls
    pipeline code, only the main thread touches widgets, and they communicate
    through a queue drained by a timer.

    4. stdout IS REDIRECTED into that queue, so every diagnostic the pipeline
    prints appears live. The GUI additionally TRANSLATES those lines into plain
    English for the progress panel - the raw text stays available under
    "Show the technical log".

    5. CANCELLATION rides on the redirect: QueueWriter.write() raises RunCancelled
    when the flag is set, so the run stops at the next print. RunCancelled
    inherits from BaseException because pipeline.py is full of 'except
    Exception' guards that would otherwise swallow it.

6. EVERY SETTINGS READ IS GUARDED. A spinbox holding "" or "abc" used to raise
   inside the settings reader, the exception vanished into Tk's silent error
   handler, and the Run button appeared to do nothing whatsoever.

7. matplotlib is pinned to Agg before any pyplot import, because charts render
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

# ---------------------------------------------------------------- typography

_WIN = sys.platform.startswith("win")
_UI = (
    "Segoe UI"
    if _WIN
    else ("Helvetica Neue" if sys.platform == "darwin" else "DejaVu Sans")
)
_UI_SEMI = "Segoe UI Semibold" if _WIN else _UI
_SYM = "Segoe UI Symbol" if _WIN else _UI

FONT_H1 = (_UI_SEMI, 16)
FONT_H2 = (_UI_SEMI, 12)
FONT_H3 = (_UI_SEMI, 10)
FONT_BODY = (_UI, 10)
FONT_SMALL = (_UI, 9)
FONT_BTN = (_UI_SEMI, 10)
FONT_ICON = (_SYM, 14)
FONT_MONO = ("Consolas", 9) if _WIN else ("Menlo", 10)

# ------------------------------------------------------------------ palettes
#
# Two complete colour sets. Contrast of body text against its own surface is
# above 12:1 in both, and muted text above 4.5:1, which is the readability
# floor rather than an aspiration.

PALETTES = {
    "light": {
        "mode": "light",
        "bg": "#EEF2F7",  # the desk the cards sit on
        "surface": "#FFFFFF",  # cards, panels, tables
        "surface_2": "#E4EAF2",  # inset strips, headers, status bar
        "border": "#CBD5E1",
        "text": "#0F172A",
        "muted": "#4B5A6E",
        "accent": "#2563EB",
        "accent_fg": "#FFFFFF",
        "success": "#0E9F6E",
        "success_fg": "#FFFFFF",
        "danger": "#DC2626",
        "warning": "#B45309",
        "info": "#0E7490",
        "sel_bg": "#DBE9FE",
        "sel_fg": "#0B2C6B",
        "row_alt": "#F6F8FC",
        "console_bg": "#0F1724",
        "console_fg": "#D6E2F5",
        "tip_bg": "#111C2E",
        "tip_fg": "#EAF1FB",
        "shade": -0.13,  # hover direction: darken
    },
    "dark": {
        "mode": "dark",
        "bg": "#0D131E",
        "surface": "#161F2D",
        "surface_2": "#1E2938",
        "border": "#314054",
        "text": "#E9EFF8",
        "muted": "#A6B5CA",
        "accent": "#5B9CFF",
        "accent_fg": "#06101F",
        "success": "#34D399",
        "success_fg": "#062018",
        "danger": "#F87171",
        "warning": "#FBBF24",
        "info": "#5EEAD4",
        "sel_bg": "#27425F",
        "sel_fg": "#FFFFFF",
        "row_alt": "#1A2534",
        "console_bg": "#080D16",
        "console_fg": "#CBD9EE",
        "tip_bg": "#22303F",
        "tip_fg": "#EAF1FB",
        "shade": 0.16,  # hover direction: lighten
    },
}

ICON_GEAR = "⚙"  # gear
ICON_INFO = "ℹ"  # information source
ICON_SUN = "☼"  # white sun
ICON_MOON = "☾"  # last quarter moon
TICK = "✓"
BOX_ON = "☑"
BOX_OFF = "☐"

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

# The hover card behind the "i" button. Deliberately short - eight lines a
# person can read without deciding to read. The full glossary is one click
# away, in the same place.
QUICK_GLOSSARY = [
    (
        "Intrinsic value",
        "What the business looks worth from its own accounts, "
        "rather than what people are paying for it today.",
    ),
    (
        "DCF",
        "Adds up the cash the company should produce in future, "
        "discounted back to what it is worth now.",
    ),
    (
        "P/E Relative",
        "Asks what rivals in the same sector are worth per rupee "
        "of profit, then applies that here.",
    ),
    (
        "EV/EBITDA",
        "Values the whole business, shares plus debt, against its "
        "operating profit. Fairest across different debt levels.",
    ),
    (
        "The three AI methods",
        "XGBoost, Random Forest and LightGBM learn how the "
        "market has priced similar companies before, and copy that pattern.",
    ),
    (
        "The star (*)",
        "At least one figure behind that number was estimated, not "
        "published. The Methods sheet says exactly how.",
    ),
    (
        "Comparison price",
        "The share price about a month after the year ended - "
        "late enough that the market had seen the accounts.",
    ),
    (
        "Left out",
        "A company with too few complete years, or no traded price to "
        "check against. Every one is listed with the reason, in plain words.",
    ),
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


def shade(color, amount):
    """
    Move a colour toward white (amount > 0) or black (amount < 0).

    Used for hover and pressed states so every button derives its own states
    from its base colour instead of needing three hand-picked hex values.
    """
    try:
        c = color.lstrip("#")
        r, g, b = (int(c[i : i + 2], 16) for i in (0, 2, 4))
    except Exception:
        return color
    if amount >= 0:
        r = r + (255 - r) * amount
        g = g + (255 - g) * amount
        b = b + (255 - b) * amount
    else:
        f = 1.0 + amount
        r, g, b = r * f, g * f, b * f
    clamp = lambda v: max(0, min(255, int(round(v))))  # noqa: E731
    return "#%02x%02x%02x" % (clamp(r), clamp(g), clamp(b))


# ------------------------------------------------------------------ scrolling


def _wheel_units(event):
    """
    One wheel event -> a signed number of scroll notches.

    Windows and macOS deliver event.delta (a multiple of 120 on Windows, a
    small number on macOS); X11 delivers Button-4 and Button-5 instead. Sign
    is flipped so that a positive result means "scroll toward the end", which
    is what yview_scroll and xview_scroll expect.
    """
    num = getattr(event, "num", 0)
    if num == 4:
        return -1
    if num == 5:
        return 1
    delta = int(getattr(event, "delta", 0) or 0)
    if delta == 0:
        return 0
    if abs(delta) >= 120:
        return -(delta // 120)
    return -1 if delta > 0 else 1


def _walk(widget):
    """The widget and every descendant, skipping ones that scroll themselves."""
    if getattr(widget, "_ivc_native_scroll", False):
        return []
    found = [widget]
    try:
        children = widget.winfo_children()
    except Exception:
        children = []
    for child in children:
        found.extend(_walk(child))
    return found


def bind_wheel(widget, vertical=None, horizontal=None, recurse=True):
    """
    Wire the mouse wheel to callbacks, over `widget` and everything inside it.

    Plain wheel calls `vertical`, Shift + wheel calls `horizontal`. Shift and
    wheel-up means LEFT, shift and wheel-down means RIGHT, which is the
    convention every browser and spreadsheet uses.

    Both handlers return "break". That is deliberate: without it the wheel
    also reaches the class binding underneath, which on a Combobox or Spinbox
    silently changes the value you were only scrolling past.
    """
    step = int(getattr(config, "GUI_SCROLL_STEP", 3) or 3)

    def on_vertical(event):
        n = _wheel_units(event)
        if n and vertical:
            try:
                vertical(n * step)
            except tk.TclError:
                pass
        return "break"

    def on_horizontal(event):
        n = _wheel_units(event)
        if n and horizontal:
            try:
                horizontal(n * step)
            except tk.TclError:
                pass
        return "break"

    for w in (_walk(widget) if recurse else [widget]):
        try:
            w.bind("<MouseWheel>", on_vertical)
            w.bind("<Button-4>", on_vertical)
            w.bind("<Button-5>", on_vertical)
            w.bind("<Shift-MouseWheel>", on_horizontal)
            w.bind("<Shift-Button-4>", on_horizontal)
            w.bind("<Shift-Button-5>", on_horizontal)
        except tk.TclError:
            pass


def scrollbar(parent, orient, command):
    """
    A slim, rounded scrollbar that follows the current theme.

    ttkbootstrap draws scrollbars from generated images rather than plain ttk
    elements, so style.configure() cannot recolour them - asking for the
    "round" bootstyle it already knows about is what gets a thin one that
    matches light and dark properly. Falls back to a stock ttk scrollbar on
    any ttkbootstrap old enough not to have it.
    """
    try:
        return tb.Scrollbar(parent, orient=orient, command=command, bootstyle="round")
    except Exception:
        return ttk.Scrollbar(parent, orient=orient, command=command)


def bind_wheel_native(widget):
    """
    Give a Treeview, Text or Listbox its own wheel handling.

    These already scroll vertically through a class binding, but that binding
    is what we suppress everywhere else, and none of them scrolls sideways on
    Shift by default. Doing it explicitly keeps one rule across the whole
    window instead of three different ones.

    A Treeview measures a horizontal "unit" in something close to a single
    pixel, so three of them per notch moves the table about the width of one
    letter and feels broken. Text and Listbox measure a unit as a character.
    Hence the multiplier: the aim is roughly the same distance travelled on
    screen whatever is under the pointer.
    """
    widget._ivc_native_scroll = True
    across = 16 if isinstance(widget, ttk.Treeview) else 1
    bind_wheel(
        widget,
        vertical=lambda n: widget.yview_scroll(n, "units"),
        horizontal=lambda n: widget.xview_scroll(n * across, "units"),
        recurse=False,
    )
    return widget


class ScrollFrame(ttk.Frame):
    """
    A vertically scrolling region that actually responds to the mouse wheel.

    Put content in `.body`. Call `.finish()` once the content exists, which
    binds the wheel across everything that was added.
    """

    def __init__(self, master, app, padding=0, surface=False, hbar=False):
        super().__init__(master, style="App.TFrame")
        self.app = app
        self._hbar_wanted = hbar

        self.canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0, takefocus=0)
        self.vbar = scrollbar(self, "vertical", self.canvas.yview)
        self.body = ttk.Frame(
            self.canvas,
            style="Card.TFrame" if surface else "App.TFrame",
            padding=padding,
        )
        self._window = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.canvas.configure(yscrollcommand=self.vbar.set)

        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.vbar.grid(row=0, column=1, sticky="ns")
        if hbar:
            self.hbar = scrollbar(self, "horizontal", self.canvas.xview)
            self.canvas.configure(xscrollcommand=self.hbar.set)
            self.hbar.grid(row=1, column=0, sticky="ew")
        else:
            self.hbar = None
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        self.body.bind("<Configure>", self._sync_region)
        self.canvas.bind("<Configure>", self._sync_width)
        app.register_tk(self.canvas, "surface" if surface else "bg")

    def _sync_region(self, _event=None):
        try:
            self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        except tk.TclError:
            pass

    def _sync_width(self, event):
        # Without a horizontal bar the content should simply be as wide as the
        # viewport, so wraplength labels wrap where the eye expects them to.
        if self.hbar is None:
            self.canvas.itemconfigure(self._window, width=event.width)

    def scroll_y(self, units):
        self.canvas.yview_scroll(units, "units")

    def scroll_x(self, units):
        self.canvas.xview_scroll(units, "units")

    def finish(self):
        bind_wheel(self, self.scroll_y, self.scroll_x)
        self._sync_region()


# ------------------------------------------------------------------- tooltip


class HoverCard:
    """
    A small translucent panel that appears under a widget on hover and goes
    away the moment the pointer leaves. Used by the "i" button in the header.
    """

    def __init__(self, widget, app, title, entries, note=None, delay=120, width=520):
        self.widget = widget
        self.app = app
        self.title = title
        self.entries = entries
        self.note = note
        self.delay = delay
        self.width = width
        self._after = None
        self._tip = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _event=None):
        self._cancel()
        self._after = self.widget.after(self.delay, self._show)

    def _cancel(self):
        if self._after is not None:
            try:
                self.widget.after_cancel(self._after)
            except Exception:
                pass
            self._after = None

    def _hide(self, _event=None):
        self._cancel()
        if self._tip is not None:
            try:
                self._tip.destroy()
            except Exception:
                pass
            self._tip = None

    def _show(self):
        if self._tip is not None or not self.widget.winfo_exists():
            return
        p = self.app.pal
        tip = tk.Toplevel(self.widget)
        tip.wm_overrideredirect(True)
        try:
            tip.attributes("-alpha", 0.97)
            tip.attributes("-topmost", True)
        except tk.TclError:
            pass

        edge = tk.Frame(tip, background=p["border"], padx=1, pady=1)
        edge.pack(fill="both", expand=True)
        inner = tk.Frame(edge, background=p["tip_bg"], padx=16, pady=14)
        inner.pack(fill="both", expand=True)

        tk.Label(
            inner,
            text=self.title,
            font=FONT_H3,
            background=p["tip_bg"],
            foreground=p["tip_fg"],
            anchor="w",
            justify="left",
        ).pack(fill="x", pady=(0, 8))

        for term, meaning in self.entries:
            line = tk.Frame(inner, background=p["tip_bg"])
            line.pack(fill="x", pady=(0, 6))
            tk.Label(
                line,
                text=term,
                font=(_UI_SEMI, 9),
                background=p["tip_bg"],
                foreground=p["accent"] if p["mode"] == "dark" else "#93B8FF",
                anchor="w",
                justify="left",
                width=20,
            ).pack(side="left", anchor="n")
            tk.Label(
                line,
                text=meaning,
                font=FONT_SMALL,
                background=p["tip_bg"],
                foreground=p["tip_fg"],
                anchor="w",
                justify="left",
                wraplength=self.width - 190,
            ).pack(side="left", fill="x", expand=True)

        if self.note:
            tk.Label(
                inner,
                text=self.note,
                font=(_UI, 8),
                background=p["tip_bg"],
                foreground=p["muted"],
                anchor="w",
                justify="left",
                wraplength=self.width - 30,
            ).pack(fill="x", pady=(8, 0))

        tip.update_idletasks()
        w, h = tip.winfo_reqwidth(), tip.winfo_reqheight()
        x = self.widget.winfo_rootx() + self.widget.winfo_width() - w
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 8
        x = max(8, min(x, self.widget.winfo_screenwidth() - w - 8))
        if y + h > self.widget.winfo_screenheight() - 8:
            y = max(8, self.widget.winfo_rooty() - h - 8)
        tip.wm_geometry(f"+{int(x)}+{int(y)}")
        self._tip = tip


# ------------------------------------------------------------- glossary window


GLOSSARY = [
    (
        "What is intrinsic value?",
        "The share price tells you what people are paying today. Intrinsic value "
        "is an estimate of what the business is actually worth, worked out from "
        "its published accounts. When the two differ a lot, either the market "
        "knows something the accounts do not, or the shares are mispriced. This "
        "program does not tell you which.",
    ),
    (
        "Discounted Cash Flow (DCF)",
        "Forecasts the cash the business will generate over the next five years, "
        "then reduces those future amounts to what they are worth today. It suits "
        "steady, cash-generating companies and struggles with young or "
        "loss-making ones.",
    ),
    (
        "P/E Relative",
        "Asks what similar companies in the same sector are being valued at for "
        "each rupee of profit, then applies that to this company's profit. It "
        "needs the company to be profitable.",
    ),
    (
        "EV/EBITDA",
        "Values the whole business - shares plus debt - against its operating "
        "profit, then subtracts the debt. It is the fairest way to compare "
        "companies that carry very different amounts of borrowing.",
    ),
    (
        "The three AI methods",
        "XGBoost, Random Forest and LightGBM do not reason about a business at "
        "all. They study how the market has historically priced companies with "
        "similar financial profiles, and predict accordingly. They often beat "
        "the classical methods on accuracy and can never explain themselves as "
        "clearly. Both facts matter.",
    ),
    (
        "Why some companies get left out",
        "Two reasons. First, the data source publishes only about four years of "
        "annual accounts, so the earliest years are usually missing for "
        "everybody. Second, banks and similar lenders do not report the "
        "operating-profit figures these methods need - their accounts are "
        "structured differently, so a number calculated for them would be "
        "meaningless rather than merely imprecise. Every excluded company is "
        "listed with its reason, in plain English, on the 'Left Out' sheets of "
        "the workbook.",
    ),
    (
        "What the asterisk means",
        "A star next to a figure means at least one input was estimated rather "
        "than taken from a published statement. The estimate is always derived "
        "from the company's own history or its sector, never guessed, and the "
        "'Methods' sheet records exactly how each one was produced.",
    ),
    (
        "The comparison price",
        "Results are judged against the share price around 1 May following each "
        "financial year - roughly a month after the accounts are published, so "
        "the market has had a chance to react to them. Using a price from during "
        "the year would let the calculation peek at information it should not "
        "have had.",
    ),
    (
        "A word of caution",
        "Every number here is an estimate built from past accounts. Valuation "
        "methods disagree with each other for good reasons, and all of them can "
        "be wrong at the same time. Treat the output as a starting point for "
        "investigation, not a recommendation.",
    ),
]


class GlossaryDialog(tk.Toplevel):
    """The long-form version of the hover card, for anyone who wants it."""

    def __init__(self, app):
        super().__init__(app)
        self.app = app
        p = app.pal
        self.title("What do these words mean?")
        self.configure(background=p["bg"])
        self.geometry("760x620")
        self.minsize(560, 420)
        self.transient(app)

        header = ttk.Frame(self, style="Header.TFrame", padding=(20, 16))
        header.pack(fill="x")
        ttk.Label(header, text="What do these words mean?", style="H1.TLabel").pack(
            anchor="w"
        )
        ttk.Label(
            header,
            text="Nine ideas, in the order they turn up in your results.",
            style="Sub.TLabel",
        ).pack(anchor="w", pady=(2, 0))

        sf = ScrollFrame(self, app, padding=(20, 16, 20, 20))
        sf.pack(fill="both", expand=True)
        for title, text in GLOSSARY:
            card = ttk.Frame(sf.body, style="Card.TFrame", padding=(16, 14))
            card.pack(fill="x", pady=(0, 10))
            ttk.Label(card, text=title, style="CardTitle.TLabel").pack(anchor="w")
            ttk.Label(
                card,
                text=text,
                style="CardBody.TLabel",
                wraplength=640,
                justify="left",
            ).pack(anchor="w", pady=(5, 0))
        sf.finish()

        foot = ttk.Frame(self, style="Bar.TFrame", padding=(20, 12))
        foot.pack(fill="x")
        ttk.Button(
            foot, text="Close", style="Accent.TButton", command=self.destroy
        ).pack(side="right")
        self.bind("<Escape>", lambda _e: self.destroy())


# ------------------------------------------------------------ settings window


class SettingsDialog(tk.Toplevel):
    """
    Every setting, in five short categories, all visible.

    There is no "Advanced" switch any more. Hiding half the controls behind a
    toggle only ever taught people that the program had a part they were not
    qualified to look at. Instead each control carries two or three sentences
    of ordinary English and sits to the RIGHT of that explanation, so a
    category is four or five lines tall rather than four or five screens.
    """

    def __init__(self, app):
        super().__init__(app)
        self.app = app
        p = app.pal
        # Traces we add to the app's variables. They MUST be removed when this
        # window closes: a trace whose callback lives in a destroyed Toplevel
        # raises out of Tcl the next time anything touches the variable.
        self._traces = []
        self.title("Settings")
        self.configure(background=p["bg"])
        self.geometry("900x680")
        self.minsize(720, 520)
        self.transient(app)

        header = ttk.Frame(self, style="Header.TFrame", padding=(20, 14))
        header.pack(fill="x")
        ttk.Label(header, text="Settings", style="H1.TLabel").pack(anchor="w")
        ttk.Label(
            header,
            text="Every one of these has a sensible default. You can run the "
            "whole program without touching a single one.",
            style="Sub.TLabel",
        ).pack(anchor="w", pady=(2, 0))

        nb = ttk.Notebook(self, padding=(14, 12))
        nb.pack(fill="both", expand=True)

        # Short tab names on purpose: five long ones get squeezed and clipped
        # by the notebook, and the section heading inside each page carries
        # the full sentence anyway.
        for label, builder in (
            ("  Companies  ", self._page_quality),
            ("  Prices & dates  ", self._page_prices),
            ("  Models  ", self._page_models),
            ("  Report  ", self._page_report),
            ("  Files & testing  ", self._page_files),
        ):
            sf = ScrollFrame(self, app, padding=(4, 4, 12, 8))
            nb.add(sf, text=label)
            builder(sf.body)
            sf.finish()

        foot = ttk.Frame(self, style="Bar.TFrame", padding=(20, 12))
        foot.pack(fill="x")
        ttk.Label(
            foot,
            text="Changes take effect on the next run. Nothing is saved to disk.",
            style="Status.TLabel",
        ).pack(side="left")
        ttk.Button(
            foot,
            text="Done",
            style="Accent.TButton",
            command=self.destroy,
        ).pack(side="right")
        ttk.Button(
            foot,
            text="Reset to recommended",
            style="Ghost.TButton",
            command=self._reset,
        ).pack(side="right", padx=(0, 8))
        self.bind("<Escape>", lambda _e: self.destroy())
        self.bind("<Destroy>", self._drop_traces)

    def _drop_traces(self, event=None):
        if event is not None and event.widget is not self:
            return
        for var, tid in self._traces:
            try:
                var.trace_remove("write", tid)
            except Exception:
                pass
        self._traces = []

    # ------------------------------------------------- friendly drop-downs
    def _choice(self, holder, var, options, width=22):
        """
        A combobox that SHOWS ordinary words and STORES the engine's value.

        The underlying settings are strings like "report_only" and "may1".
        They belong in config.py and in the log; they do not belong in front
        of someone who just wants their spreadsheet. The Tk variable keeps the
        real value, the box displays the readable one, and the two are kept in
        step in both directions so 'Reset to recommended' updates the display
        as well.
        """
        to_label = {value: label for value, label in options}
        to_value = {label: value for value, label in options}
        shown = tk.StringVar(value=to_label.get(var.get(), var.get()))

        box = ttk.Combobox(
            holder,
            textvariable=shown,
            values=[label for _, label in options],
            state="readonly",
            width=width,
        )
        box.pack(anchor="e")

        def picked(_event=None):
            var.set(to_value.get(shown.get(), var.get()))

        def follow(*_args):
            label = to_label.get(var.get())
            if label is not None and shown.get() != label:
                shown.set(label)

        box.bind("<<ComboboxSelected>>", picked)
        self._traces.append((var, var.trace_add("write", follow)))
        return box

    # ------------------------------------------------------------- one row
    def _row(self, parent, title, why, builder):
        """Title and explanation on the left, the control itself on the right."""
        card = ttk.Frame(parent, style="Card.TFrame", padding=(16, 13))
        card.pack(fill="x", pady=(0, 8))
        card.columnconfigure(0, weight=1)
        card.columnconfigure(1, minsize=230)

        ttk.Label(card, text=title, style="CardTitle.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            card,
            text=why,
            style="CardMuted.TLabel",
            wraplength=420,
            justify="left",
        ).grid(row=1, column=0, sticky="w", pady=(3, 0))

        holder = ttk.Frame(card, style="Card.TFrame")
        holder.grid(row=0, column=1, rowspan=2, sticky="e", padx=(18, 0))
        builder(holder)
        return card

    def _section(self, parent, text):
        ttk.Label(parent, text=text, style="Section.TLabel").pack(
            anchor="w", pady=(6, 8)
        )

    # ------------------------------------------------------------- category 1
    def _page_quality(self, body):
        a = self.app
        self._section(body, "How strict should the program be about missing data?")

        self._row(
            body,
            "Complete years needed",
            "A company is only valued if this many of its five financial years "
            "have every figure the calculation needs. Higher means fewer "
            "companies but cleaner numbers.",
            lambda h: ttk.Spinbox(
                h, from_=1, to=5, textvariable=a.v_min_fy, width=8
            ).pack(anchor="e"),
        )

        hint = ttk.Frame(body, style="Panel.TFrame", padding=(14, 10))
        hint.pack(fill="x", pady=(0, 10))
        ttk.Label(
            hint,
            textvariable=a.v_gatehint,
            style="Hint.TLabel",
            wraplength=780,
            justify="left",
        ).pack(anchor="w")

        self._row(
            body,
            "Years needing a comparison price",
            "A company can have perfect accounts and still be untestable if its "
            "shares were not trading yet. This is the fewest years that must "
            "carry a usable market price.",
            lambda h: ttk.Spinbox(
                h, from_=0, to=5, textvariable=a.v_min_bench, width=8
            ).pack(anchor="e"),
        )

        self._row(
            body,
            "What happens to companies that fail",
            "'Leave them out' keeps them off the report but still counts them in "
            "sector averages. 'Flag only' values everybody and marks the doubtful "
            "ones. 'Off' skips the check.",
            lambda h: self._choice(
                h,
                a.v_screening,
                [
                    ("enforce", "Leave them out"),
                    ("report_only", "Flag only, keep them"),
                    ("off", "Do not check at all"),
                ],
            ),
        )

        self._row(
            body,
            "Rescue the run if nothing qualifies",
            "If your threshold turns out to be impossible for every company, "
            "lower it automatically to the best figure anyone achieved and carry "
            "on, rather than finishing with no report at all.",
            lambda h: ttk.Checkbutton(
                h,
                text="Adjust and warn me",
                variable=a.v_autorelax,
                style="Card.TCheckbutton",
            ).pack(anchor="e"),
        )

        self._section(body, "Where left-out companies still count")

        self._row(
            body,
            "Keep them in the background maths",
            "Their data is thin, not wrong. Removing them from the sector "
            "averages would make the valuations worse for every company that "
            "did qualify, so by default they stay in.",
            lambda h: (
                ttk.Checkbutton(
                    h,
                    text="Sector averages",
                    variable=a.v_keep_peers,
                    style="Card.TCheckbutton",
                ).pack(anchor="w"),
                ttk.Checkbutton(
                    h,
                    text="AI training data",
                    variable=a.v_keep_ml,
                    style="Card.TCheckbutton",
                ).pack(anchor="w", pady=(4, 0)),
            ),
        )

        self._row(
            body,
            "A year only counts with a share price",
            "Tick this and a financial year is treated as incomplete unless a "
            "share price for that year was found too. It is the stricter and "
            "more honest reading.",
            lambda h: ttk.Checkbutton(
                h,
                text="Require a price",
                variable=a.v_need_price,
                style="Card.TCheckbutton",
            ).pack(anchor="e"),
        )

        self._row(
            body,
            "List the companies that passed as well",
            "Turns the 'left out' sheets from a list of casualties into a full "
            "audit of every company you submitted. Useful when you have to show "
            "your working.",
            lambda h: ttk.Checkbutton(
                h,
                text="Full audit trail",
                variable=a.v_sheet_all,
                style="Card.TCheckbutton",
            ).pack(anchor="e"),
        )

    # ------------------------------------------------------------- category 2
    def _page_prices(self, body):
        a = self.app
        self._section(body, "Which share price the answers are judged against")

        self._row(
            body,
            "The comparison price",
            "'may1' uses the price on the first trading day near 1 May after the "
            "year ends - about a month after the accounts appear. The other two "
            "are cross-checks. Changing this changes every accuracy figure.",
            lambda h: self._choice(
                h,
                a.v_bench,
                [
                    ("may1", "1 May after year end"),
                    ("mean", "Average of the next year"),
                    ("close", "Close of the next year"),
                ],
            ),
        )

        self._row(
            body,
            "How far from 1 May we may look",
            "1 May is a market holiday in Maharashtra and often sits beside a "
            "weekend, so an exact match is rare. This is how many days either "
            "side are acceptable before the cell is left blank.",
            lambda h: ttk.Spinbox(
                h, from_=1, to=45, textvariable=a.v_offset, width=8
            ).pack(anchor="e"),
        )

        self._section(body, "The price used inside the calculation")

        self._row(
            body,
            "How the year's average price is worked out",
            "'trading' averages only the days the market was open, 'calendar' "
            "averages across the whole year. This one feeds the valuation; the "
            "comparison price above only scores it.",
            lambda h: self._choice(
                h,
                a.v_meanbasis,
                [
                    ("trading", "Days the market was open"),
                    ("calendar", "Every calendar day"),
                ],
            ),
        )

        self._row(
            body,
            "Which exchange to look up",
            "'.NS' is the National Stock Exchange, '.BO' is the Bombay Stock "
            "Exchange. Use NSE unless a company you want is only listed on BSE.",
            lambda h: self._choice(
                h,
                a.v_exchange,
                [
                    (".NS", "National Stock Exchange"),
                    (".BO", "Bombay Stock Exchange"),
                ],
            ),
        )

    # ------------------------------------------------------------- category 3
    def _page_models(self, body):
        a = self.app
        self._section(body, "Which methods run, and how hard they try")

        self._row(
            body,
            "Run the three AI models",
            "XGBoost, Random Forest and LightGBM learn from every company at "
            "once instead of valuing each from first principles. They add a few "
            "minutes. Untick for the three classical methods only.",
            lambda h: ttk.Checkbutton(
                h,
                text="Include AI valuations",
                variable=a.v_ml,
                style="Card.TCheckbutton",
            ).pack(anchor="e"),
        )

        self._row(
            body,
            "How the AI models are tested",
            "'expanding' trains only on earlier years, which is correct but "
            "leaves the first years untested. 'loyo' uses every other year and "
            "leaks the future. 'hybrid' does the honest one where it can.",
            lambda h: self._choice(
                h,
                a.v_mlsplit,
                [
                    ("hybrid", "Hybrid - recommended"),
                    ("expanding", "Earlier years only"),
                    ("loyo", "All other years (leaks)"),
                ],
            ),
        )

        self._row(
            body,
            "Fill small gaps in the accounts",
            "When one figure is missing from an otherwise complete year, it can "
            "be estimated from the company's own trend or its sector. Every "
            "estimate is marked with a star and explained. 'off' shows only what "
            "was published.",
            lambda h: self._choice(
                h,
                a.v_estimation,
                [
                    ("balanced", "Balanced - recommended"),
                    ("aggressive", "Fill as much as possible"),
                    ("off", "Off - published only"),
                ],
            ),
        )

    # ------------------------------------------------------------- category 4
    def _page_report(self, body):
        a = self.app
        self._section(body, "What comes out at the end")

        self._row(
            body,
            "Draw the charts",
            "Produces the statistical charts comparing how the six methods "
            "performed. Skipping this finishes sooner and does not change a "
            "single number in your spreadsheet.",
            lambda h: ttk.Checkbutton(
                h,
                text="Draw the charts",
                variable=a.v_analyze,
                style="Card.TCheckbutton",
            ).pack(anchor="e"),
        )

        self._row(
            body,
            "Chart sharpness",
            "Dots per inch. 200 is crisp on screen and fine in a document. Go "
            "higher only if you are printing them large - the files get big and "
            "slow to draw.",
            lambda h: ttk.Spinbox(
                h, from_=72, to=600, increment=4, textvariable=a.v_dpi, width=8
            ).pack(anchor="e"),
        )

        self._row(
            body,
            "How years are labelled",
            "'range' writes the year as 2023-24, which is how Indian financial "
            "years are normally quoted. 'int' writes 2024, the internal number.",
            lambda h: self._choice(
                h,
                a.v_fylabel,
                [("range", "Write it as 2023-24"), ("int", "Write it as 2024")],
            ),
        )

        self._row(
            body,
            "How empty cells are explained",
            "'code' puts a short marker in the cell, 'detailed' writes a full "
            "sentence, 'off' leaves it blank. Detailed is friendlier; code keeps "
            "the grid narrow enough to read.",
            lambda h: self._choice(
                h,
                a.v_reasons,
                [
                    ("code", "A short code"),
                    ("detailed", "A full sentence"),
                    ("off", "Leave the cell blank"),
                ],
            ),
        )

    # ------------------------------------------------------------- category 5
    def _page_files(self, body):
        a = self.app
        self._section(body, "Your own figures, and testing without the internet")

        self._row(
            body,
            "Use my hand-entered figures",
            "Anything you type into data/fundamentals_override.csv is used "
            "instead of the downloaded number, and is recorded as manually "
            "supplied so nobody mistakes it for published data.",
            lambda h: ttk.Checkbutton(
                h,
                text="Use overrides",
                variable=a.v_overrides,
                style="Card.TCheckbutton",
            ).pack(anchor="e"),
        )

        self._row(
            body,
            "Offline test mode",
            "Runs the whole program on built-in fake companies without touching "
            "the internet. Useful for checking the program works; the numbers "
            "mean nothing at all.",
            lambda h: ttk.Checkbutton(
                h,
                text="Use fake data",
                variable=a.v_offline,
                style="Card.TCheckbutton",
            ).pack(anchor="e"),
        )

        self._row(
            body,
            "Where your files are written",
            "Everything the program produces - the workbook, the CSVs, the "
            "charts and the log - lands in this folder. It is created if it is "
            "not there.",
            lambda h: ttk.Button(
                h,
                text="Open folder",
                style="Ghost.TButton",
                command=lambda: open_in_explorer(config.OUTPUT_DIR),
            ).pack(anchor="e"),
        )

    # --------------------------------------------------------------- reset
    def _reset(self):
        if not messagebox.askokcancel(
            "Reset settings",
            "Put every setting back to the recommended default?\n\n"
            "This does not touch your company list or any file you have already "
            "produced.",
            parent=self,
        ):
            return
        self.app.reset_settings()


# ---------------------------------------------------------------------- app


class App(tb.Window):
    def __init__(self):
        # A safe built-in theme to get a root window; _apply_theme immediately
        # swaps in whichever curated theme this ttkbootstrap actually ships.
        super().__init__(themename="flatly")
        self.title("Intrinsic Value Calculator")
        self.geometry(getattr(config, "GUI_WINDOW_SIZE", "1360x880"))
        self.minsize(*getattr(config, "GUI_MIN_SIZE", (1120, 720)))

        self.companies = []
        self.include = {}
        self.queue = queue.Queue()
        self.cancel = threading.Event()
        self.worker = None
        self.expected = 0
        self.fetched = 0
        self.last_records = None
        self._chart_ref = None
        self._tk_widgets = []  # raw Tk widgets that need repainting by hand
        self._trees = []  # Treeviews whose tag colours need repainting
        self.pal = PALETTES["light"]
        self.pages = {}
        self.nav_buttons = {}
        self.current_page = None

        self._build_vars()
        self._apply_theme()
        self._build_header()
        self._build_nav()
        self._build_pages()
        self._build_statusbar()

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(150, self._drain)

        if config.DEFAULT_INPUT.exists():
            self._load_companies(config.DEFAULT_INPUT)
        self._update_gate_hint()
        self.show_page("upload")

    # ------------------------------------------------------------------ vars
    def _build_vars(self):
        g = getattr
        self.v_input = tk.StringVar(value=str(config.DEFAULT_INPUT))
        self.v_dark = tk.BooleanVar(value=g(config, "GUI_START_IN_DARK", False))

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
        self.v_resultsummary = tk.StringVar(
            value="No results yet. Load your list, then press Calculate on the Run page."
        )

        # Live feedback: moving the strictness dial re-estimates survivors
        # against the last screening, so the effect is visible before running.
        for var in (self.v_min_fy, self.v_min_bench):
            var.trace_add("write", lambda *_: self._update_gate_hint())

    def _iget(self, var, fallback):
        """IntVar.get() raises on empty or non-numeric spinbox text. See note 6."""
        try:
            return int(var.get())
        except Exception:
            return fallback

    def reset_settings(self):
        """Put every setting back to what config.py shipped with."""
        import importlib

        try:
            importlib.reload(config)
        except Exception:
            log.exception("config reload failed; resetting from current values")
        g = getattr
        self.v_screening.set(
            "off"
            if not g(config, "SUFFICIENCY_ENABLED", True)
            else g(config, "SUFFICIENCY_MODE", "enforce")
        )
        self.v_min_fy.set(g(config, "MIN_COMPLETE_FY", 3))
        self.v_min_bench.set(g(config, "MIN_BENCHMARK_FY", 3))
        self.v_autorelax.set(g(config, "SUFFICIENCY_AUTO_RELAX", True))
        self.v_need_price.set(g(config, "SUFFICIENCY_REQUIRE_ANCHOR_PRICE", True))
        self.v_keep_peers.set(g(config, "SUFFICIENCY_KEEP_IN_PEERS", True))
        self.v_keep_ml.set(g(config, "SUFFICIENCY_KEEP_IN_ML", True))
        self.v_sheet_all.set(g(config, "EXCLUSION_SHEET_INCLUDE_PASSED", False))
        self.v_bench.set(g(config, "BENCHMARK_BASIS", "may1"))
        self.v_offset.set(g(config, "BENCHMARK_MAX_OFFSET_DAYS", 10))
        self.v_meanbasis.set(g(config, "FY_MEAN_BASIS", "trading"))
        self.v_exchange.set(g(config, "EXCHANGE_SUFFIX", ".NS"))
        self.v_ml.set(g(config, "ML_ENABLED", True))
        self.v_mlsplit.set(g(config, "ML_SPLIT", "hybrid"))
        self.v_estimation.set(g(config, "ESTIMATION_MODE", "balanced"))
        self.v_analyze.set(g(config, "ANALYSIS_ENABLED", True))
        self.v_dpi.set(g(config, "CHART_DPI", 200))
        self.v_fylabel.set(g(config, "FY_LABEL_STYLE", "range"))
        self.v_reasons.set(
            "off"
            if not g(config, "SHOW_REASONS", True)
            else g(config, "REASON_STYLE", "code")
        )
        self.v_overrides.set(g(config, "USE_OVERRIDES", True))
        self.v_offline.set(g(config, "OFFLINE", False))

    # ----------------------------------------------------------------- theme
    def register_tk(self, widget, role):
        """
        Remember a raw Tk widget so it can be repainted on a theme change.

        ttk widgets follow the theme. tk.Text, tk.Listbox and tk.Canvas do not
        - they keep whatever colours they were born with, which is what made
        the old dark mode unreadable.
        """
        self._tk_widgets.append((widget, role))
        self._paint_tk(widget, role)
        return widget

    def _paint_tk(self, widget, role):
        p = self.pal
        try:
            if role == "console":
                widget.configure(
                    background=p["console_bg"],
                    foreground=p["console_fg"],
                    insertbackground=p["console_fg"],
                    selectbackground=p["sel_bg"],
                    selectforeground=p["sel_fg"],
                    highlightthickness=0,
                    borderwidth=0,
                    relief="flat",
                )
            elif role == "text":
                widget.configure(
                    background=p["surface"],
                    foreground=p["text"],
                    insertbackground=p["text"],
                    selectbackground=p["sel_bg"],
                    selectforeground=p["sel_fg"],
                    highlightthickness=0,
                    borderwidth=0,
                    relief="flat",
                )
            elif role == "listbox":
                widget.configure(
                    background=p["surface"],
                    foreground=p["text"],
                    selectbackground=p["sel_bg"],
                    selectforeground=p["sel_fg"],
                    highlightthickness=0,
                    borderwidth=0,
                    relief="flat",
                    activestyle="none",
                )
            elif role == "surface":
                widget.configure(background=p["surface"])
            else:
                widget.configure(background=p["bg"])
        except tk.TclError:
            pass

    def _apply_theme(self):
        """Swap the base theme, then lay our own palette over the top of it."""
        dark = bool(self.v_dark.get())
        self.pal = PALETTES["dark" if dark else "light"]

        try:
            available = set(self.style.theme_names())
        except Exception:
            available = set()
        wanted = getattr(
            config,
            "GUI_DARK_THEMES" if dark else "GUI_LIGHT_THEMES",
            ("darkly",) if dark else ("flatly",),
        )
        for name in wanted:
            if name in available:
                try:
                    self.style.theme_use(name)
                    break
                except Exception:
                    continue

        # theme_use rebuilds every ttk style from scratch, so our overrides
        # have to be laid down afterwards, every single time.
        self._style_widgets()
        for widget, role in list(self._tk_widgets):
            try:
                if widget.winfo_exists():
                    self._paint_tk(widget, role)
            except Exception:
                pass
        self._paint_trees()

    def _style_widgets(self):
        p = self.pal
        st = self.style
        hover = p["shade"]
        press = hover * 1.9

        self.configure(background=p["bg"])
        st.configure(".", font=FONT_BODY, background=p["bg"], foreground=p["text"])

        # ---- frames
        st.configure("TFrame", background=p["bg"])
        st.configure("App.TFrame", background=p["bg"])
        st.configure("Card.TFrame", background=p["surface"])
        st.configure("Panel.TFrame", background=p["surface_2"])
        st.configure("Header.TFrame", background=p["surface"])
        st.configure("Bar.TFrame", background=p["surface_2"])
        st.configure("TSeparator", background=p["border"])

        # ---- labels on the app background
        st.configure("TLabel", background=p["bg"], foreground=p["text"], font=FONT_BODY)
        st.configure(
            "PageTitle.TLabel", background=p["bg"], foreground=p["text"], font=FONT_H2
        )
        st.configure(
            "PageHint.TLabel",
            background=p["bg"],
            foreground=p["muted"],
            font=FONT_SMALL,
        )
        st.configure(
            "Section.TLabel", background=p["bg"], foreground=p["muted"], font=FONT_H3
        )

        # ---- labels on a card
        st.configure(
            "H1.TLabel", background=p["surface"], foreground=p["text"], font=FONT_H1
        )
        st.configure(
            "Sub.TLabel",
            background=p["surface"],
            foreground=p["muted"],
            font=FONT_SMALL,
        )
        st.configure(
            "CardTitle.TLabel",
            background=p["surface"],
            foreground=p["text"],
            font=FONT_H3,
        )
        st.configure(
            "CardHead.TLabel",
            background=p["surface"],
            foreground=p["text"],
            font=FONT_H2,
        )
        st.configure(
            "CardBody.TLabel",
            background=p["surface"],
            foreground=p["text"],
            font=FONT_BODY,
        )
        st.configure(
            "CardMuted.TLabel",
            background=p["surface"],
            foreground=p["muted"],
            font=FONT_SMALL,
        )
        st.configure(
            "CardOk.TLabel",
            background=p["surface"],
            foreground=p["success"],
            font=FONT_BODY,
        )
        st.configure(
            "CardNow.TLabel",
            background=p["surface"],
            foreground=p["accent"],
            font=FONT_BODY,
        )
        st.configure(
            "Hint.TLabel",
            background=p["surface_2"],
            foreground=p["info"],
            font=FONT_SMALL,
        )
        st.configure(
            "Status.TLabel",
            background=p["surface_2"],
            foreground=p["muted"],
            font=FONT_SMALL,
        )

        # ---- buttons
        def button(name, bg, fg, outline=False, pad=(16, 9), font=FONT_BTN):
            base_bg = p["surface"] if outline else bg
            border = bg if outline else bg
            st.configure(
                name,
                background=base_bg,
                foreground=bg if outline else fg,
                bordercolor=border,
                lightcolor=base_bg,
                darkcolor=base_bg,
                borderwidth=1,
                relief="flat",
                focusthickness=0,
                focuscolor="",
                padding=pad,
                font=font,
                anchor="center",
            )
            on = (
                shade(base_bg, hover)
                if not outline
                else shade(bg, 0.82 if p["mode"] == "light" else -0.62)
            )
            down = (
                shade(base_bg, press)
                if not outline
                else shade(bg, 0.72 if p["mode"] == "light" else -0.5)
            )
            st.map(
                name,
                background=[
                    ("disabled", p["surface_2"]),
                    ("pressed", down),
                    ("active", on),
                ],
                foreground=[("disabled", p["muted"])],
                bordercolor=[("disabled", p["border"])],
                lightcolor=[("pressed", down), ("active", on)],
                darkcolor=[("pressed", down), ("active", on)],
                relief=[("pressed", "flat"), ("active", "flat")],
            )

        button("Accent.TButton", p["accent"], p["accent_fg"])
        button("Success.TButton", p["success"], p["success_fg"], pad=(20, 11))
        button("Danger.TButton", p["danger"], "#FFFFFF", outline=True, pad=(14, 8))
        button(
            "Ghost.TButton",
            p["muted"],
            p["text"],
            outline=True,
            pad=(13, 8),
            font=FONT_BODY,
        )
        button(
            "Link.TButton",
            p["accent"],
            p["accent"],
            outline=True,
            pad=(10, 6),
            font=FONT_SMALL,
        )

        # Ghost buttons read better with the normal text colour than with the
        # muted one they borrow their border from.
        st.configure("Ghost.TButton", foreground=p["text"], bordercolor=p["border"])
        st.map("Ghost.TButton", foreground=[("disabled", p["muted"])])

        # ---- header icon buttons: square, quiet, unmistakably clickable
        st.configure(
            "Icon.TButton",
            background=p["surface"],
            foreground=p["muted"],
            bordercolor=p["surface"],
            lightcolor=p["surface"],
            darkcolor=p["surface"],
            borderwidth=1,
            relief="flat",
            focusthickness=0,
            focuscolor="",
            padding=(10, 6),
            font=FONT_ICON,
        )
        st.map(
            "Icon.TButton",
            background=[("active", p["surface_2"]), ("pressed", p["surface_2"])],
            foreground=[("active", p["accent"]), ("pressed", p["accent"])],
            bordercolor=[("active", p["border"])],
            lightcolor=[("active", p["surface_2"])],
            darkcolor=[("active", p["surface_2"])],
        )

        # ---- the three-step navigation pills
        for name, bg, fg in (
            ("Nav.TButton", p["bg"], p["muted"]),
            ("NavOn.TButton", p["surface"], p["text"]),
        ):
            st.configure(
                name,
                background=bg,
                foreground=fg,
                bordercolor=p["border"] if name.startswith("NavOn") else p["bg"],
                lightcolor=bg,
                darkcolor=bg,
                borderwidth=1,
                relief="flat",
                focusthickness=0,
                focuscolor="",
                padding=(22, 11),
                font=FONT_BTN,
                anchor="center",
            )
            st.map(
                name,
                background=[("active", p["surface"])],
                foreground=[("active", p["text"])],
                bordercolor=[("active", p["border"])],
                lightcolor=[("active", p["surface"])],
                darkcolor=[("active", p["surface"])],
            )

        # ---- inputs
        for name in ("TEntry", "TCombobox", "TSpinbox"):
            st.configure(
                name,
                fieldbackground=p["surface"],
                background=p["surface"],
                foreground=p["text"],
                insertcolor=p["text"],
                bordercolor=p["border"],
                lightcolor=p["border"],
                darkcolor=p["border"],
                arrowcolor=p["muted"],
                selectbackground=p["sel_bg"],
                selectforeground=p["sel_fg"],
                padding=(8, 6),
            )
            st.map(
                name,
                fieldbackground=[
                    ("readonly", p["surface"]),
                    ("disabled", p["surface_2"]),
                ],
                foreground=[("readonly", p["text"]), ("disabled", p["muted"])],
                bordercolor=[("focus", p["accent"]), ("hover", p["muted"])],
                lightcolor=[("focus", p["accent"])],
                darkcolor=[("focus", p["accent"])],
                arrowcolor=[("disabled", p["border"])],
            )
        # The combobox drop-down list is a raw Tk listbox reached only through
        # the option database.
        self.option_add("*TCombobox*Listbox.background", p["surface"])
        self.option_add("*TCombobox*Listbox.foreground", p["text"])
        self.option_add("*TCombobox*Listbox.selectBackground", p["sel_bg"])
        self.option_add("*TCombobox*Listbox.selectForeground", p["sel_fg"])
        self.option_add("*TCombobox*Listbox.font", FONT_BODY)

        # ---- checkbuttons live on cards almost everywhere
        for name in ("TCheckbutton", "Card.TCheckbutton", "TRadiobutton"):
            st.configure(
                name,
                background=p["surface"],
                foreground=p["text"],
                font=FONT_BODY,
                focuscolor="",
                padding=(2, 3),
            )
            st.map(
                name,
                background=[("active", p["surface"])],
                foreground=[("disabled", p["muted"]), ("active", p["text"])],
            )
        st.configure(
            "Bar.TCheckbutton", background=p["surface_2"], foreground=p["text"]
        )
        st.map("Bar.TCheckbutton", background=[("active", p["surface_2"])])

        # ---- notebook (used inside Results and Settings)
        st.configure(
            "TNotebook", background=p["bg"], borderwidth=0, tabmargins=(0, 6, 0, 0)
        )
        st.configure(
            "TNotebook.Tab",
            background=p["bg"],
            foreground=p["muted"],
            padding=(14, 10),
            font=FONT_H3,
            borderwidth=0,
        )
        st.map(
            "TNotebook.Tab",
            background=[("selected", p["surface"]), ("active", p["surface_2"])],
            foreground=[("selected", p["text"]), ("active", p["text"])],
        )

        # ---- tables
        st.configure(
            "Treeview",
            background=p["surface"],
            fieldbackground=p["surface"],
            foreground=p["text"],
            bordercolor=p["border"],
            lightcolor=p["surface"],
            darkcolor=p["surface"],
            borderwidth=0,
            rowheight=27,
            font=FONT_BODY,
        )
        st.map(
            "Treeview",
            background=[("selected", p["sel_bg"])],
            foreground=[("selected", p["sel_fg"])],
        )
        st.configure(
            "Treeview.Heading",
            background=p["surface_2"],
            foreground=p["text"],
            relief="flat",
            borderwidth=0,
            padding=(9, 8),
            font=FONT_H3,
        )
        st.map(
            "Treeview.Heading",
            background=[("active", shade(p["surface_2"], hover * 0.5))],
            relief=[("active", "flat")],
        )

        # ---- scrollbars: thin, quiet, and coloured to match
        for orient in ("Vertical", "Horizontal"):
            st.configure(
                f"{orient}.TScrollbar",
                background=p["border"],
                troughcolor=p["bg"],
                bordercolor=p["bg"],
                lightcolor=p["border"],
                darkcolor=p["border"],
                arrowcolor=p["muted"],
                arrowsize=13,
                borderwidth=0,
                relief="flat",
            )
            st.map(
                f"{orient}.TScrollbar",
                background=[("active", p["muted"]), ("pressed", p["accent"])],
                arrowcolor=[("active", p["text"])],
            )

        # ---- progress bar
        st.configure(
            "Run.Horizontal.TProgressbar",
            background=p["accent"],
            troughcolor=p["surface_2"],
            bordercolor=p["surface_2"],
            lightcolor=p["accent"],
            darkcolor=p["accent"],
            thickness=10,
        )
        st.configure(
            "Done.Horizontal.TProgressbar",
            background=p["success"],
            troughcolor=p["surface_2"],
            bordercolor=p["surface_2"],
            lightcolor=p["success"],
            darkcolor=p["success"],
            thickness=10,
        )

    def _paint_trees(self):
        p = self.pal
        for tree in list(self._trees):
            try:
                if not tree.winfo_exists():
                    continue
                tree.tag_configure("odd", background=p["row_alt"])
                tree.tag_configure("even", background=p["surface"])
                tree.tag_configure("off", foreground=p["muted"])
                tree.tag_configure("low", foreground=p["success"])
                tree.tag_configure("high", foreground=p["danger"])
            except tk.TclError:
                pass

    def _toggle_theme(self):
        self.v_dark.set(not self.v_dark.get())
        self._apply_theme()
        self.btn_theme.configure(text=ICON_SUN if self.v_dark.get() else ICON_MOON)

    # ---------------------------------------------------------------- header
    def _build_header(self):
        bar = ttk.Frame(self, style="Header.TFrame", padding=(24, 16))
        bar.pack(fill="x")

        left = ttk.Frame(bar, style="Header.TFrame")
        left.pack(side="left", fill="x", expand=True)
        ttk.Label(left, text="Intrinsic Value Calculator", style="H1.TLabel").pack(
            anchor="w"
        )
        ttk.Label(
            left,
            text="Works out what Indian listed companies appear to be worth, then "
            "compares that with what their shares actually traded at.",
            style="Sub.TLabel",
        ).pack(anchor="w", pady=(2, 0))

        right = ttk.Frame(bar, style="Header.TFrame")
        right.pack(side="right")

        # Gear last in the pack order = furthest right, in the corner.
        self.btn_settings = ttk.Button(
            right, text=ICON_GEAR, style="Icon.TButton", command=self.open_settings
        )
        self.btn_settings.pack(side="right", padx=(6, 0))
        HoverCard(
            self.btn_settings,
            self,
            "Settings",
            [("Click to open", "Every option the program has, in five short groups.")],
        )

        self.btn_theme = ttk.Button(
            right,
            text=ICON_SUN if self.v_dark.get() else ICON_MOON,
            style="Icon.TButton",
            command=self._toggle_theme,
        )
        self.btn_theme.pack(side="right", padx=(6, 0))
        HoverCard(
            self.btn_theme,
            self,
            "Light and dark",
            [
                (
                    "Click to switch",
                    "Swaps the whole window between the light and dark colour sets.",
                )
            ],
        )

        self.btn_info = ttk.Button(
            right, text=ICON_INFO, style="Icon.TButton", command=self.open_glossary
        )
        self.btn_info.pack(side="right")
        HoverCard(
            self.btn_info,
            self,
            "What do these words mean?",
            QUICK_GLOSSARY,
            note="Click the i for the longer version of all of this.",
        )

        ttk.Separator(self, orient="horizontal").pack(fill="x")

    def open_settings(self):
        SettingsDialog(self)

    def open_glossary(self):
        GlossaryDialog(self)

    # ------------------------------------------------------------------- nav
    def _build_nav(self):
        rail = ttk.Frame(self, style="App.TFrame", padding=(24, 14, 24, 0))
        rail.pack(fill="x")
        for key, label in (
            ("upload", "1.  Load your list"),
            ("run", "2.  Run it"),
            ("results", "3.  Results"),
        ):
            btn = ttk.Button(
                rail,
                text=label,
                style="Nav.TButton",
                command=lambda k=key: self.show_page(k),
            )
            btn.pack(side="left", padx=(0, 8))
            self.nav_buttons[key] = btn

    def show_page(self, key):
        page = self.pages.get(key)
        if page is None:
            return
        page.tkraise()
        self.current_page = key
        for name, btn in self.nav_buttons.items():
            btn.configure(style="NavOn.TButton" if name == key else "Nav.TButton")

    # ----------------------------------------------------------------- pages
    def _build_pages(self):
        holder = ttk.Frame(self, style="App.TFrame", padding=(24, 14, 24, 14))
        holder.pack(fill="both", expand=True)
        holder.rowconfigure(0, weight=1)
        holder.columnconfigure(0, weight=1)

        for key in ("upload", "run", "results"):
            frame = ttk.Frame(holder, style="App.TFrame")
            frame.grid(row=0, column=0, sticky="nsew")
            self.pages[key] = frame

        self._build_upload(self.pages["upload"])
        self._build_run(self.pages["run"])
        self._build_results(self.pages["results"])

    # ---------------------------------------------------------- page: upload
    def _build_upload(self, parent):
        parent.rowconfigure(1, weight=1)
        parent.columnconfigure(0, weight=1)

        card = ttk.Frame(parent, style="Card.TFrame", padding=(18, 16))
        card.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        ttk.Label(card, text="Your company list", style="CardHead.TLabel").pack(
            anchor="w"
        )
        ttk.Label(
            card,
            text="A plain CSV file with four columns: company name, sector, market "
            "cap tier, and the NSE or BSE ticker. Untick anything you want left "
            "out of this run.",
            style="CardMuted.TLabel",
            wraplength=900,
            justify="left",
        ).pack(anchor="w", pady=(4, 12))

        row = ttk.Frame(card, style="Card.TFrame")
        row.pack(fill="x")
        ttk.Entry(row, textvariable=self.v_input).pack(
            side="left", fill="x", expand=True
        )
        ttk.Button(
            row, text="Browse", style="Accent.TButton", command=self._browse
        ).pack(side="left", padx=(10, 0))
        ttk.Button(
            row, text="Reload", style="Ghost.TButton", command=self._reload
        ).pack(side="left", padx=(8, 0))

        table = ttk.Frame(parent, style="Card.TFrame", padding=(2, 2))
        table.grid(row=1, column=0, sticky="nsew")
        table.rowconfigure(0, weight=1)
        table.columnconfigure(0, weight=1)

        cols = ("inc", "name", "sector", "cap", "ticker")
        self.tree_c = ttk.Treeview(
            table, columns=cols, show="headings", selectmode="none"
        )
        for key, label, w, anchor in (
            ("inc", "Include", 80, "center"),
            ("name", "Company", 340, "w"),
            ("sector", "Sector", 250, "w"),
            ("cap", "Size", 100, "w"),
            ("ticker", "Ticker", 130, "w"),
        ):
            self.tree_c.heading(key, text=label)
            self.tree_c.column(key, width=w, anchor=anchor)
        ysb = scrollbar(table, "vertical", self.tree_c.yview)
        xsb = scrollbar(table, "horizontal", self.tree_c.xview)
        self.tree_c.configure(yscrollcommand=ysb.set, xscrollcommand=xsb.set)
        self.tree_c.grid(row=0, column=0, sticky="nsew")
        ysb.grid(row=0, column=1, sticky="ns")
        xsb.grid(row=1, column=0, sticky="ew")
        self.tree_c.bind("<Button-1>", self._toggle_row)
        bind_wheel_native(self.tree_c)
        self._trees.append(self.tree_c)

        foot = ttk.Frame(parent, style="App.TFrame")
        foot.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        for text, fn in (
            ("Include all", lambda: self._set_all(True)),
            ("Include none", lambda: self._set_all(False)),
            ("Flip selection", self._invert),
        ):
            ttk.Button(foot, text=text, style="Ghost.TButton", command=fn).pack(
                side="left", padx=(0, 8)
            )
        ttk.Button(
            foot,
            text="Next: run it  →",
            style="Accent.TButton",
            command=lambda: self.show_page("run"),
        ).pack(side="right")
        ttk.Label(foot, textvariable=self.v_count, style="PageHint.TLabel").pack(
            side="right", padx=(0, 14)
        )
        self._paint_trees()

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
        for i, c in enumerate(self.companies):
            on = self.include.get(c["name"], True)
            stripe = "odd" if i % 2 else "even"
            self.tree_c.insert(
                "",
                "end",
                iid=c["name"],
                values=(
                    BOX_ON if on else BOX_OFF,
                    c["name"],
                    c.get("sector", ""),
                    c.get("cap", ""),
                    c.get("ticker") or "",
                ),
                tags=(stripe,) if on else (stripe, "off"),
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
        self.tree_c.set(iid, "inc", BOX_ON if on else BOX_OFF)
        tags = list(self.tree_c.item(iid, "tags"))
        stripe = "odd" if "odd" in tags else "even"
        self.tree_c.item(iid, tags=(stripe,) if on else (stripe, "off"))
        self._update_count()

    def _set_all(self, state):
        for k in self.include:
            self.include[k] = state
        self._refresh_company_tree()

    def _invert(self):
        for k in self.include:
            self.include[k] = not self.include[k]
        self._refresh_company_tree()

    # ------------------------------------------------------------- page: run
    def _build_run(self, parent):
        """
        Start AND watch, on one page.

        The old version threw you onto a separate Progress tab the instant you
        pressed the button, which meant the thing you had just been looking at
        vanished. Nothing moves now: the buttons stay where they are and the
        panel underneath them fills in.
        """
        parent.rowconfigure(1, weight=1)
        parent.columnconfigure(0, weight=1)

        top = ttk.Frame(parent, style="Card.TFrame", padding=(18, 16))
        top.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        ttk.Label(top, text="Run the calculation", style="CardHead.TLabel").pack(
            anchor="w"
        )
        ttk.Label(
            top,
            text="The full calculation downloads five years of accounts and prices "
            "for every company, values each one six different ways, and writes an "
            "Excel workbook plus CSV files. Budget roughly a second per company, "
            "plus a minute or two for the AI models.",
            style="CardMuted.TLabel",
            wraplength=900,
            justify="left",
        ).pack(anchor="w", pady=(4, 14))

        btns = ttk.Frame(top, style="Card.TFrame")
        btns.pack(fill="x")
        self.btn_run = ttk.Button(
            btns,
            text="Calculate intrinsic values",
            style="Success.TButton",
            command=lambda: self._start("run"),
        )
        self.btn_run.pack(side="left")
        self.btn_screen = ttk.Button(
            btns,
            text="Just check my data",
            style="Ghost.TButton",
            command=lambda: self._start("screen"),
        )
        self.btn_screen.pack(side="left", padx=(10, 0))
        ttk.Label(
            btns,
            text="The second button only tests whether each company has enough "
            "data.\nIt is fast, and it does not produce a spreadsheet.",
            style="CardMuted.TLabel",
            justify="left",
        ).pack(side="left", padx=(16, 0))

        # ---- the live panel
        panel = ttk.Frame(parent, style="Card.TFrame", padding=(18, 16))
        panel.grid(row=1, column=0, sticky="nsew")
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(4, weight=1)

        head = ttk.Frame(panel, style="Card.TFrame")
        head.grid(row=0, column=0, sticky="ew")
        ttk.Label(head, textvariable=self.v_headline, style="CardHead.TLabel").pack(
            side="left"
        )
        self.btn_cancel = ttk.Button(
            head,
            text="Stop",
            style="Danger.TButton",
            command=self._request_cancel,
            state="disabled",
        )
        self.btn_cancel.pack(side="right")

        self.pbar = ttk.Progressbar(
            panel, mode="determinate", style="Run.Horizontal.TProgressbar"
        )
        self.pbar.grid(row=1, column=0, sticky="ew", pady=(12, 14))

        steps = ttk.Frame(panel, style="Card.TFrame")
        steps.grid(row=2, column=0, sticky="ew")
        self.step_labels = {}
        for key, text in STEPS:
            lbl = ttk.Label(steps, text=f"     {text}", style="CardMuted.TLabel")
            lbl.pack(anchor="w", pady=2)
            self.step_labels[key] = (lbl, text)

        ctl = ttk.Frame(panel, style="Card.TFrame")
        ctl.grid(row=3, column=0, sticky="ew", pady=(14, 8))
        ttk.Checkbutton(
            ctl,
            text="Show the technical log",
            variable=self.v_shownlog,
            style="Card.TCheckbutton",
            command=self._toggle_log,
        ).pack(side="left")
        ttk.Button(
            ctl, text="Save log", style="Ghost.TButton", command=self._save_console
        ).pack(side="right")
        ttk.Button(ctl, text="Clear", style="Ghost.TButton", command=self._clear).pack(
            side="right", padx=(0, 8)
        )

        self.logbox = ttk.Frame(panel, style="Card.TFrame")
        self.logbox.grid(row=4, column=0, sticky="nsew")
        self.logbox.grid_remove()
        self.console = tk.Text(self.logbox, wrap="none", font=FONT_MONO, height=14)
        ysb = scrollbar(self.logbox, "vertical", self.console.yview)
        xsb = scrollbar(self.logbox, "horizontal", self.console.xview)
        self.console.configure(yscrollcommand=ysb.set, xscrollcommand=xsb.set)
        self.console.grid(row=0, column=0, sticky="nsew")
        ysb.grid(row=0, column=1, sticky="ns")
        xsb.grid(row=1, column=0, sticky="ew")
        self.logbox.rowconfigure(0, weight=1)
        self.logbox.columnconfigure(0, weight=1)
        self.console.configure(state="disabled")
        bind_wheel_native(self.console)
        self.register_tk(self.console, "console")

    def _toggle_log(self):
        if self.v_shownlog.get():
            self.logbox.grid()
        else:
            self.logbox.grid_remove()

    def _mark_step(self, key, done=False):
        if key not in self.step_labels:
            return
        lbl, text = self.step_labels[key]
        lbl.configure(
            text=f"  {TICK}  {text}" if done else f"  ▸  {text}",
            style="CardOk.TLabel" if done else "CardNow.TLabel",
        )

    def _reset_steps(self):
        for key, (lbl, text) in self.step_labels.items():
            lbl.configure(text=f"     {text}", style="CardMuted.TLabel")

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

    # --------------------------------------------------------- page: results
    def _build_results(self, parent):
        parent.rowconfigure(1, weight=1)
        parent.columnconfigure(0, weight=1)

        head = ttk.Frame(parent, style="Card.TFrame", padding=(18, 16))
        head.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        ttk.Label(
            head,
            textvariable=self.v_resultsummary,
            style="CardHead.TLabel",
            wraplength=980,
            justify="left",
        ).pack(anchor="w")
        ttk.Label(
            head,
            text="A star (*) next to a number means part of it was estimated rather "
            "than published. The 'Methods' sheet in the workbook explains every one, "
            "and the 'Left Out' sheets say in plain English why any company is missing.",
            style="CardMuted.TLabel",
            wraplength=980,
            justify="left",
        ).pack(anchor="w", pady=(6, 14))

        bar = ttk.Frame(head, style="Card.TFrame")
        bar.pack(fill="x")
        ttk.Button(
            bar,
            text="Open the Excel workbook",
            style="Success.TButton",
            command=lambda: open_in_explorer(
                config.OUTPUT_DIR / f"{config.OUTPUT_BASENAME}.xlsx"
            ),
        ).pack(side="left")
        ttk.Button(
            bar,
            text="Open the output folder",
            style="Ghost.TButton",
            command=lambda: open_in_explorer(config.OUTPUT_DIR),
        ).pack(side="left", padx=(10, 0))
        ttk.Button(
            bar, text="Refresh", style="Ghost.TButton", command=self._load_results
        ).pack(side="left", padx=(8, 0))

        sub = ttk.Notebook(parent)
        sub.grid(row=1, column=0, sticky="nsew")

        f1 = ttk.Frame(sub, style="Card.TFrame", padding=6)
        f2 = ttk.Frame(sub, style="Card.TFrame", padding=6)
        f3 = ttk.Frame(sub, style="Card.TFrame", padding=6)
        f4 = ttk.Frame(sub, style="Card.TFrame", padding=6)
        sub.add(f1, text="  What each company looks worth  ")
        sub.add(f2, text="  Companies we could not value  ")
        sub.add(f3, text="  Full detail  ")
        sub.add(f4, text="  Charts  ")

        self.tree_plain = self._scrolled_tree(f1)
        self.tree_x = self._scrolled_tree(f2)
        self.tree_r = self._scrolled_tree(f3)
        self._build_charts(f4)
        self._paint_trees()

    def _scrolled_tree(self, parent):
        tree = ttk.Treeview(parent, show="headings")
        ysb = scrollbar(parent, "vertical", tree.yview)
        xsb = scrollbar(parent, "horizontal", tree.xview)
        tree.configure(yscrollcommand=ysb.set, xscrollcommand=xsb.set)
        tree.grid(row=0, column=0, sticky="nsew")
        ysb.grid(row=0, column=1, sticky="ns")
        xsb.grid(row=1, column=0, sticky="ew")
        parent.rowconfigure(0, weight=1)
        parent.columnconfigure(0, weight=1)
        bind_wheel_native(tree)
        self._trees.append(tree)
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
            tree.column(c, width=min(max(100, len(str(c)) * 9), 320), anchor="w")
        for i, (_, row) in enumerate(df.head(max_rows).iterrows()):
            tree.insert("", "end", values=list(row), tags=("odd" if i % 2 else "even",))
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
        for c, w in zip(cols, (320, 100, 120, 140, 250)):
            self.tree_plain.heading(c, text=c)
            self.tree_plain.column(c, width=w, anchor="w")

        band = getattr(config, "PLAIN_VERDICT_BAND", 0.10)
        cheap = dear = fair = 0
        for i, (_, r) in enumerate(df.iterrows()):
            price = pd.to_numeric(r.get("Market Price"), errors="coerce")
            vals = [
                v
                for v in (pd.to_numeric(r.get(c), errors="coerce") for c in value_cols)
                if pd.notna(v) and v > 0
            ]
            extra = ()
            if pd.isna(price) or not vals:
                verdict, worth = "Not enough data that year", ""
            else:
                avg = sum(vals) / len(vals)
                worth = f"{avg:,.0f}"
                if price < avg * (1 - band):
                    verdict = "Price looks low vs the estimate"
                    cheap += 1
                    extra = ("low",)
                elif price > avg * (1 + band):
                    verdict = "Price looks high vs the estimate"
                    dear += 1
                    extra = ("high",)
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
                tags=("odd" if i % 2 else "even",) + extra,
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

        # Prefer the plain-English exclusion file; fall back to the technical
        # one for reports produced before that sheet existed.
        plain = out / (
            f"{getattr(config, 'PLAIN_EXCLUSIONS_BASENAME', 'Why_Companies_Were_Left_Out')}.csv"
        )
        technical = out / (
            f"{getattr(config, 'EXCLUSIONS_BASENAME', 'Intrinsic_Value_Excluded')}.csv"
        )
        self._fill_tree(self.tree_x, plain if plain.exists() else technical)

        self._build_plain_table()
        self._load_charts()
        self._paint_trees()

    # ---------------------------------------------------------------- charts
    def _build_charts(self, parent):
        parent.rowconfigure(1, weight=1)
        parent.columnconfigure(1, weight=1)

        ttk.Label(
            parent,
            text="Charts comparing how the six valuation methods performed. "
            "Pick one from the list.",
            style="CardMuted.TLabel",
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(4, 10), padx=6)

        left = ttk.Frame(parent, style="Card.TFrame")
        left.grid(row=1, column=0, sticky="ns", padx=(6, 12))
        left.rowconfigure(0, weight=1)

        self.lst_charts = tk.Listbox(left, width=34, font=FONT_SMALL)
        lsb = scrollbar(left, "vertical", self.lst_charts.yview)
        self.lst_charts.configure(yscrollcommand=lsb.set)
        self.lst_charts.grid(row=0, column=0, sticky="ns")
        lsb.grid(row=0, column=1, sticky="ns")
        self.lst_charts.bind("<<ListboxSelect>>", self._show_chart)
        bind_wheel_native(self.lst_charts)
        self.register_tk(self.lst_charts, "listbox")

        ttk.Button(
            left, text="Refresh", style="Ghost.TButton", command=self._load_charts
        ).grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))

        self.chart_panel = ttk.Label(
            parent,
            text="Charts appear here once a calculation has finished.",
            anchor="center",
            style="CardMuted.TLabel",
        )
        self.chart_panel.grid(row=1, column=1, sticky="nsew", padx=(0, 6))

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

    # ------------------------------------------------------------- statusbar
    def _build_statusbar(self):
        ttk.Separator(self, orient="horizontal").pack(fill="x")
        bar = ttk.Frame(self, style="Bar.TFrame", padding=(24, 8))
        bar.pack(fill="x")
        ttk.Label(bar, textvariable=self.v_status, style="Status.TLabel").pack(
            side="left"
        )
        link = ttk.Label(
            bar,
            text=f"Files are saved to: {config.OUTPUT_DIR}",
            style="Status.TLabel",
            cursor="hand2",
        )
        link.pack(side="right")
        link.bind("<Button-1>", lambda _e: open_in_explorer(config.OUTPUT_DIR))

    # ------------------------------------------------------------ gate hint
    def _update_gate_hint(self):
        """Live 'what would this setting do' feedback, from the last screening."""
        if not self.last_records:
            self.v_gatehint.set(
                "Press 'Just check my data' on the Run page once, and this line "
                "will tell you how many companies survive at any setting."
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

    # ----------------------------------------------------------- run control
    def _apply_settings(self):
        """Push widget state onto config. Every read guarded - see note 6."""
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
                f"{type(e).__name__}: {e}\n\nOpen Settings from the gear icon and "
                f"look for an empty or non-numeric box.",
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
                "No companies are ticked on the 'Load your list' page.",
            )
            self.show_page("upload")
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
        self.pbar.configure(
            maximum=max(self.expected, 1), value=0, style="Run.Horizontal.TProgressbar"
        )
        self.btn_run.configure(state="disabled")
        self.btn_screen.configure(state="disabled")
        self.btn_cancel.configure(state="normal")
        self.v_headline.set(
            "Checking your data ..." if mode == "screen" else "Working ..."
        )
        self.v_status.set("Running")
        self.show_page("run")  # stay here; the panel below fills in
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
            self.pbar.configure(
                value=self.expected, style="Done.Horizontal.TProgressbar"
            )
            self.v_headline.set("Finished. Your spreadsheet is ready.")
            self.v_status.set("Done")
            self._load_results()
            self.show_page("results")  # the one automatic jump, and it is earned
        elif outcome == "screen_finished":
            self._mark_step("fetch", done=True)
            self._mark_step("gate", done=True)
            self.pbar.configure(
                value=self.expected, style="Done.Horizontal.TProgressbar"
            )
            self.v_headline.set(
                "Data check finished. No spreadsheet was produced - that button only "
                "tests your data. Press 'Calculate intrinsic values' for the report."
            )
            self.v_status.set("Data check done")
            self._load_results()
        elif outcome == "cancelled":
            self.v_headline.set("Stopped at your request. No files were written.")
            self.v_status.set("Stopped")
        else:
            self.v_headline.set(
                "Something went wrong. Tick 'Show the technical log' below for the "
                "details."
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
