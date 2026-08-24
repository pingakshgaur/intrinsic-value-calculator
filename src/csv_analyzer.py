# FILE: src/csv_analyzer.py
"""
csv_analyzer.py — statistical analysis and visualisation layer for INTVAL-Calc.

Consumes the results grid written by src/io_layer/exporter.py and emits HD
charts, each with its interpretation rendered directly into the image, plus
machine-readable metric tables and an HTML index.

INPUT
    Any CSV carrying the 16-column results schema. Tolerant of:
      - blank separator rows (dropped)
      - '#' comment lines above the header (skipped)
      - currency-prefixed cells such as 'Rs 1,234.50' (coerced)
      - minor header wording drift (fuzzy column resolution)

METRICS
    Per model, and sliced by sector / financial year / company:

    MAE      mean absolute error, in rupees
    RMSE     root mean squared error, in rupees. Penalises large misses
             quadratically, so a model with a few catastrophic outliers
             scores far worse here than on MAE. RMSE >> MAE signals
             instability rather than uniform inaccuracy.
    MAPE     mean absolute percentage error. Scale-free, so it is the only
             metric comparable across companies of different price levels.
    MedAPE   median absolute percentage error. Reported alongside MAPE
             because MAPE is dragged upward by a handful of blow-ups; a wide
             MAPE/MedAPE gap means the average is not representative.
    Bias     mean signed error (estimate - market). Negative means the model
             systematically prices below the market benchmark.
    Hit20    share of observations within +/-20 percent of the benchmark.
    Spearman rank correlation between estimate and benchmark. A model can
             have poor MAPE yet high Spearman: it gets the *ordering* right
             while being miscalibrated in level. For relative-value screening
             that is often the more useful property.
    Wins     count of observations where this model was closest in absolute
             terms among all models that produced a value for that row.

CHARTS
    sector_<name>_levels.png       FY vs value per company, all 7 series
    sector_<name>_normalised.png   FY vs (estimate / benchmark), overlaid
    overall_model_accuracy.png     MAPE and RMSE ranking across all rows
    closest_model_win_rate.png     how often each model was nearest
    accuracy_by_sector.png         MAPE heatmap, model x sector
    accuracy_by_year.png           MAPE trajectory per model across FYs
    error_distribution.png         signed percentage-error distributions
    metrics_table.png              full metric table as an image

CAVEAT ON THE BENCHMARK
    The benchmark is the 52-week high of the assessment year, which is the
    maximum of a price distribution rather than a central value. Every model
    will therefore show negative bias, and MAPE carries a constant upward
    offset. Comparisons *between* models remain valid because all six face
    the identical benchmark; absolute error levels do not represent
    mispricing and must not be read as such.
"""

from __future__ import annotations

import argparse
import html
import json
import math
import re
import sys
import textwrap
from datetime import datetime
from pathlib import Path
from typing import Optional, Sequence

import numpy as np
import pandas as pd

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec
from matplotlib.lines import Line2D
from matplotlib.ticker import FuncFormatter

# --------------------------------------------------------------------------
# Schema and styling
# --------------------------------------------------------------------------

COL_COMPANY = "Company name"
COL_SECTOR = "Sector Name"
COL_FY = "Financial Year"
COL_MARKET = "Market Price"

MODEL_SPECS: list[tuple[str, str]] = [
    ("DCF", "(DCF) Intrinsic Value"),
    ("P/E Relative", "(P/E Relative Valuation) Intrinsic Value"),
    ("EV/EBITDA", "(EV/EBITDA Valuation) Intrinsic Value"),
    ("XGBoost", "(XGBoost) Intrinsic Value"),
    ("Random Forest", "(Random Forest) Intrinsic Value"),
    ("LightGBM", "(LightGBM) Intrinsic Value"),
]

MODEL_NAMES = [m for m, _ in MODEL_SPECS]

# 'Rs' rather than the rupee glyph: U+20B9 is missing from several default
# matplotlib font stacks and renders as a blank box in saved PNGs.
CURRENCY = "Rs"

COLOURS: dict[str, str] = {
    "Market Price": "#111111",
    "DCF": "#1f77b4",
    "P/E Relative": "#d62728",
    "EV/EBITDA": "#2ca02c",
    "XGBoost": "#ff7f0e",
    "Random Forest": "#9467bd",
    "LightGBM": "#17becf",
}

MARKERS: dict[str, str] = {
    "Market Price": "o",
    "DCF": "s",
    "P/E Relative": "^",
    "EV/EBITDA": "D",
    "XGBoost": "v",
    "Random Forest": "P",
    "LightGBM": "X",
}

plt.rcParams.update(
    {
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "axes.grid": True,
        "grid.alpha": 0.25,
        "grid.linewidth": 0.6,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "font.size": 10,
        "axes.titlesize": 12,
        "axes.titleweight": "bold",
        "legend.frameon": False,
    }
)


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def _resolve_columns(df: pd.DataFrame) -> dict[str, str]:
    """
    Map canonical names to the actual headers present, tolerating wording
    drift. Raises with a readable message if anything essential is missing.
    """
    lookup = {_norm(c): c for c in df.columns}
    mapping: dict[str, str] = {}

    wanted = [COL_COMPANY, COL_SECTOR, COL_FY, COL_MARKET] + [c for _, c in MODEL_SPECS]
    for target in wanted:
        key = _norm(target)
        if key in lookup:
            mapping[target] = lookup[key]
            continue
        # Fuzzy fallback, but never onto a difference column: "(DCF) Intrinsic
        # Value" and "Difference (Market - DCF)" both contain "dcf", and
        # silently binding the model to its own difference column would make
        # every error look tiny and every chart wrong.
        hits = [
            orig
            for k, orig in lookup.items()
            if (key in k or k in key) and "difference" not in k
        ]
        if len(hits) == 1:
            mapping[target] = hits[0]

    missing_core = [
        c for c in (COL_COMPANY, COL_SECTOR, COL_FY, COL_MARKET) if c not in mapping
    ]
    if missing_core:
        raise ValueError(
            "Results CSV is missing required column(s): "
            + ", ".join(missing_core)
            + f"\nHeaders found: {list(df.columns)}"
        )
    return mapping


_NUMERIC_CLEAN = re.compile(r"[^0-9eE.\-+]")


def _coerce_numeric(series: pd.Series) -> pd.Series:
    """Strip currency prefixes, thousands separators and stray glyphs."""
    if pd.api.types.is_numeric_dtype(series):
        return pd.to_numeric(series, errors="coerce")

    def clean_one(value) -> Optional[str]:
        # pandas .replace() substitutes NaN rather than None, and float NaN
        # will not survive a regex call, so test with pd.isna rather than
        # an identity check against None.
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return None
        text = str(value).strip()
        text = text.replace("\u20b9", "").replace(",", "")
        text = re.sub(r"(?i)^\s*rs\.?\s*", "", text).strip()
        if text.lower() in {"", "nan", "none", "-", "n/a", "na", "excluded"}:
            return None
        return _NUMERIC_CLEAN.sub("", text) or None

    return pd.to_numeric(series.map(clean_one), errors="coerce")


def load_results(csv_path: Path) -> pd.DataFrame:
    """Load and normalise the results grid into a tidy analysis frame."""
    csv_path = Path(csv_path)
    if not csv_path.exists():
        raise FileNotFoundError(f"Results CSV not found: {csv_path}")

    raw = pd.read_csv(csv_path, comment="#", skip_blank_lines=True)
    raw = raw.dropna(how="all")
    if raw.empty:
        raise ValueError(f"Results CSV contains no data rows: {csv_path}")

    mapping = _resolve_columns(raw)

    out = pd.DataFrame(
        {
            COL_COMPANY: raw[mapping[COL_COMPANY]].astype(str).str.strip(),
            COL_SECTOR: raw[mapping[COL_SECTOR]].astype(str).str.strip(),
            COL_FY: raw[mapping[COL_FY]].astype(str).str.strip(),
            COL_MARKET: _coerce_numeric(raw[mapping[COL_MARKET]]),
        }
    )

    present_models: list[str] = []
    for model, col in MODEL_SPECS:
        if col in mapping:
            out[model] = _coerce_numeric(raw[mapping[col]])
            present_models.append(model)
        else:
            out[model] = np.nan

    # Drop rows that carry no company label (residual separator artefacts).
    out = out[out[COL_COMPANY].str.len() > 0]
    out = out[~out[COL_COMPANY].str.lower().isin({"nan", "none"})]

    out["_fy_start"] = out[COL_FY].str.extract(r"(\d{4})")[0].astype(float)
    out = out.dropna(subset=["_fy_start"])
    out["_fy_start"] = out["_fy_start"].astype(int)

    out = out.sort_values([COL_SECTOR, COL_COMPANY, "_fy_start"]).reset_index(drop=True)
    out.attrs["present_models"] = present_models
    out.attrs["source"] = str(csv_path)
    return out


# --------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------


def _metrics_for(actual: pd.Series, pred: pd.Series) -> dict:
    mask = actual.notna() & pred.notna() & (actual != 0)
    a = actual[mask].astype(float)
    p = pred[mask].astype(float)
    n = int(len(a))

    if n == 0:
        return {
            "N": 0,
            "MAE": np.nan,
            "RMSE": np.nan,
            "MAPE %": np.nan,
            "MedAPE %": np.nan,
            "Bias": np.nan,
            "Bias %": np.nan,
            "Hit +/-20% ": np.nan,
            "Spearman": np.nan,
        }

    err = p - a  # signed: estimate minus benchmark
    ape = (err.abs() / a.abs()) * 100

    spearman = np.nan
    if n >= 3 and a.nunique() > 1 and p.nunique() > 1:
        spearman = float(a.corr(p, method="spearman"))

    return {
        "N": n,
        "MAE": float(err.abs().mean()),
        "RMSE": float(np.sqrt((err**2).mean())),
        "MAPE %": float(ape.mean()),
        "MedAPE %": float(ape.median()),
        "Bias": float(err.mean()),
        "Bias %": float(((err / a) * 100).mean()),
        "Hit +/-20% ": float((ape <= 20).mean() * 100),
        "Spearman": spearman,
    }


def compute_metrics(df: pd.DataFrame, models: Sequence[str]) -> pd.DataFrame:
    rows = {m: _metrics_for(df[COL_MARKET], df[m]) for m in models}
    out = pd.DataFrame(rows).T
    out.index.name = "Model"
    return out


def compute_grouped_metrics(
    df: pd.DataFrame, models: Sequence[str], by: str
) -> pd.DataFrame:
    frames = []
    for key, sub in df.groupby(by, sort=True):
        m = compute_metrics(sub, models).reset_index()
        m.insert(0, by, key)
        frames.append(m)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def compute_wins(df: pd.DataFrame, models: Sequence[str]) -> pd.DataFrame:
    """
    Per observation, flag the model whose estimate is nearest the benchmark.
    Rows with no benchmark, or with no model output at all, are skipped.
    Exact ties award a win to every tied model.
    """
    records = []
    for idx, row in df.iterrows():
        market = row[COL_MARKET]
        if pd.isna(market):
            continue
        errs = {m: abs(row[m] - market) for m in models if pd.notna(row[m])}
        if not errs:
            continue
        best = min(errs.values())
        for m, e in errs.items():
            records.append(
                {
                    COL_COMPANY: row[COL_COMPANY],
                    COL_SECTOR: row[COL_SECTOR],
                    COL_FY: row[COL_FY],
                    "Model": m,
                    "AbsError": e,
                    "Won": bool(math.isclose(e, best, rel_tol=1e-9, abs_tol=1e-9)),
                }
            )
    return pd.DataFrame(records)


def win_rate_table(wins: pd.DataFrame, models: Sequence[str]) -> pd.DataFrame:
    if wins.empty:
        return pd.DataFrame(
            {"Model": list(models), "Contested": 0, "Wins": 0, "Win rate %": np.nan}
        ).set_index("Model")
    grp = wins.groupby("Model")
    tbl = pd.DataFrame(
        {
            "Contested": grp.size(),
            "Wins": grp["Won"].sum(),
        }
    )
    tbl["Win rate %"] = (tbl["Wins"] / tbl["Contested"] * 100).round(1)
    return tbl.reindex([m for m in models if m in tbl.index])


# --------------------------------------------------------------------------
# Figure canvas with rendered caption
# --------------------------------------------------------------------------


class Canvas:
    """
    A figure laid out in inches rather than fractions, so the caption block,
    the tick labels and any figure-level legend cannot collide.

    Vertical budget, top to bottom:
        title_pad_in    suptitle, plus optional figure legend
        chart_height_in plot area
        xlabel_pad_in   rotated tick labels and axis label
        caption block   wrapped text, height derived from line count
        0.30 in         bottom margin
    """

    LINE_SPACING = 1.55
    LEFT_MARGIN = 0.055

    def __init__(
        self,
        width_in: float,
        chart_height_in: float,
        title: str,
        caption: str,
        caption_fontsize: float = 9.5,
        title_pad_in: float = 0.62,
        xlabel_pad_in: float = 0.70,
    ):
        # Empirical average glyph advance for DejaVu Sans at a given point
        # size, expressed in inches: fontsize/72 * 0.52.
        char_in = (caption_fontsize / 72.0) * 0.52
        usable_in = width_in * (1 - 2 * self.LEFT_MARGIN)
        chars = max(60, int(usable_in / char_in))

        lines: list[str] = []
        for para in caption.strip().split("\n"):
            para = para.strip()
            if not para:
                lines.append("")
                continue
            lines.extend(textwrap.wrap(para, width=chars) or [""])
        self.caption_lines = lines

        line_in = (caption_fontsize / 72.0) * self.LINE_SPACING
        cap_h = len(lines) * line_in + 0.30
        total_h = title_pad_in + chart_height_in + xlabel_pad_in + cap_h

        self.fig = plt.figure(figsize=(width_in, total_h))
        self.title = title
        self.total_h = total_h
        self._cap_h = cap_h
        self._line_in = line_in
        self._cap_fontsize = caption_fontsize
        self._title_pad_in = title_pad_in

        self._chart_top = 1.0 - (title_pad_in / total_h)
        self._chart_bottom = (cap_h + xlabel_pad_in) / total_h

    def grid(self, nrows: int = 1, ncols: int = 1, **kw) -> GridSpec:
        return GridSpec(
            nrows,
            ncols,
            figure=self.fig,
            top=self._chart_top,
            bottom=self._chart_bottom,
            left=kw.pop("left", 0.07),
            right=kw.pop("right", 0.98),
            **kw,
        )

    def single_axis(self, **kw):
        gs = self.grid(1, 1, **kw)
        return self.fig.add_subplot(gs[0, 0])

    def figure_legend(self, handles, ncol: int) -> None:
        """Place a legend in the title band, clear of every subplot title."""
        y = 1.0 - (0.42 / self.total_h)
        self.fig.legend(
            handles=handles,
            loc="upper center",
            bbox_to_anchor=(0.5, y),
            ncol=ncol,
            fontsize=9.5,
        )

    def save(self, path: Path, dpi: int = 200) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        self.fig.suptitle(
            self.title,
            y=1.0 - (0.06 / self.total_h),
            va="top",
            fontsize=14,
            fontweight="bold",
        )

        y = (self._cap_h - 0.06) / self.total_h
        step = self._line_in / self.total_h
        for line in self.caption_lines:
            self.fig.text(
                self.LEFT_MARGIN,
                y,
                line,
                ha="left",
                va="top",
                fontsize=self._cap_fontsize,
                color="#222222",
                family="sans-serif",
            )
            y -= step

        self.fig.savefig(path, dpi=dpi, facecolor="white", pad_inches=0.06)
        plt.close(self.fig)
        return path


def _money_formatter(x, _pos):
    if abs(x) >= 1_00_000:
        return f"{x/1_00_000:,.1f}L"
    if abs(x) >= 1_000:
        return f"{x/1_000:,.1f}k"
    return f"{x:,.0f}"


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(text).lower()).strip("_") or "unnamed"


# --------------------------------------------------------------------------
# Charts
# --------------------------------------------------------------------------


def chart_sector_levels(
    df: pd.DataFrame, sector: str, models: Sequence[str], outdir: Path, dpi: int
) -> Optional[Path]:
    sub = df[df[COL_SECTOR] == sector]

    # A company whose ticker never resolved, or whose fetch failed outright,
    # has no benchmark and no estimates. Drawing it as an empty panel implies
    # the models failed on it, when in fact the data never arrived. Those rows
    # belong in the diagnostics sheet; excluding them here keeps the chart
    # about model performance.
    value_cols = [COL_MARKET] + list(models)
    has_data = sub.groupby(COL_COMPANY)[value_cols].apply(
        lambda g: bool(g.notna().to_numpy().any())
    )
    companies = sorted(has_data[has_data].index)
    skipped = sorted(has_data[~has_data].index)
    if not companies:
        return None

    ncols = min(3, len(companies))
    nrows = math.ceil(len(companies) / ncols)

    metrics = compute_metrics(sub, models).sort_values("MAPE %")
    valid = metrics[metrics["N"] > 0]
    if valid.empty:
        return None
    best = valid.index[0]
    worst = valid.index[-1]

    caption = (
        f"Reading this chart. One panel per company in {sector}. The x axis is the "
        f"financial year whose fundamentals were valued; the y axis is value per share in "
        f"{CURRENCY}. The heavy black line is the benchmark market price, defined as the "
        f"52-week high of the assessment year, the FY after the one valued. Each coloured line is one model's "
        f"intrinsic value for that year. A model tracks the benchmark well when its line "
        f"runs parallel to the black line and close to it: parallel but offset means the "
        f"model reads the direction of value correctly while being miscalibrated in level, "
        f"which a constant multiple can repair. Crossing or diverging lines mean the model "
        f"is getting the direction wrong, which no rescaling can fix.\n"
        f"What it shows here. Across {sector}, {best} is closest to the benchmark on average "
        f"({valid.loc[best, 'MAPE %']:.1f} percent mean absolute error, "
        f"{CURRENCY} {valid.loc[best, 'MAE']:,.0f} in level terms), while {worst} is furthest "
        f"({valid.loc[worst, 'MAPE %']:.1f} percent). Panels are drawn on independent y scales "
        f"because share prices differ by an order of magnitude across cap tiers; compare the "
        f"shape of the gap within each panel, not the height of the lines between panels.\n"
        f"Caution. Because the benchmark is a 52-week high rather than a mean, every model is "
        f"expected to sit below the black line. Treat the ranking as meaningful and the "
        f"absolute distance as inflated."
        + (
            f" {len(skipped)} company/companies in this sector produced no data at all "
            f"and are omitted here rather than drawn as empty panels "
            f"({', '.join(skipped[:4])}{' and others' if len(skipped) > 4 else ''}); "
            f"see the Diagnostics sheet for why."
            if skipped
            else ""
        )
    )

    canvas = Canvas(
        width_in=15,
        chart_height_in=3.5 * nrows,
        title=f"{sector} — model estimates against market benchmark",
        caption=caption,
        title_pad_in=1.15,
        xlabel_pad_in=0.95,
    )
    gs = canvas.grid(nrows, ncols, hspace=0.55, wspace=0.26, left=0.06)

    fy_order = sorted(
        sub[COL_FY].unique(), key=lambda f: int(re.match(r"(\d{4})", f).group(1))
    )
    xpos = {f: i for i, f in enumerate(fy_order)}

    for i, company in enumerate(companies):
        ax = canvas.fig.add_subplot(gs[i // ncols, i % ncols])
        cdf = sub[sub[COL_COMPANY] == company].sort_values("_fy_start")
        x = [xpos[f] for f in cdf[COL_FY]]

        ax.plot(
            x,
            cdf[COL_MARKET],
            color=COLOURS["Market Price"],
            lw=2.6,
            marker=MARKERS["Market Price"],
            ms=6,
            zorder=10,
            label="Market Price",
        )
        for m in models:
            if cdf[m].notna().sum() == 0:
                continue
            ax.plot(
                x,
                cdf[m],
                color=COLOURS[m],
                lw=1.5,
                alpha=0.9,
                marker=MARKERS[m],
                ms=5,
                label=m,
            )

        ax.set_title(company, fontsize=11)
        ax.set_xticks(range(len(fy_order)))
        ax.set_xticklabels(fy_order, rotation=45, ha="right", fontsize=8.5)
        ax.yaxis.set_major_formatter(FuncFormatter(_money_formatter))
        ax.set_ylabel(f"Value per share ({CURRENCY})", fontsize=9)

    handles = [
        Line2D(
            [],
            [],
            color=COLOURS[k],
            marker=MARKERS[k],
            lw=2.6 if k == "Market Price" else 1.5,
            label=k,
        )
        for k in ["Market Price"] + list(models)
    ]
    canvas.figure_legend(handles, ncol=len(handles))

    return canvas.save(outdir / f"sector_{_slug(sector)}_levels.png", dpi=dpi)


def chart_sector_normalised(
    df: pd.DataFrame, sector: str, models: Sequence[str], outdir: Path, dpi: int
) -> Optional[Path]:
    sub = df[df[COL_SECTOR] == sector].copy()
    if sub.empty or sub[COL_MARKET].notna().sum() == 0:
        return None

    fy_order = sorted(
        sub[COL_FY].unique(), key=lambda f: int(re.match(r"(\d{4})", f).group(1))
    )
    xpos = {f: i for i, f in enumerate(fy_order)}

    ratios = {}
    for m in models:
        r = sub[m] / sub[COL_MARKET]
        ratios[m] = r.replace([np.inf, -np.inf], np.nan)

    means = {m: float(np.nanmean(v)) for m, v in ratios.items() if v.notna().any()}
    if not means:
        return None
    tightest = min(means, key=lambda m: abs(means[m] - 1.0))

    caption = (
        f"Reading this chart. Every point is one company-year in {sector}, plotted as the "
        f"model's intrinsic value divided by the benchmark market price. Dividing out the "
        f"price level lets a small cap and a large cap sit on the same axis, which the "
        f"levels chart cannot do. The dashed line at 1.0 is exact agreement. Points below "
        f"1.0 mean the model valued the company below the benchmark; points above mean it "
        f"valued it higher. Vertical spread within a year is disagreement across companies; "
        f"drift in the cloud across years is a regime effect hitting the whole sector.\n"
        f"What it shows here. {tightest} sits nearest parity with a mean ratio of "
        f"{means[tightest]:.2f}. A ratio consistently near a fixed value other than 1.0 is a "
        f"calibration finding, not a failure: it says the model is a stable fraction of the "
        f"52-week high and can be scaled. A ratio that swings across years is the more "
        f"serious problem, because there is no single scalar that repairs it.\n"
        f"Caution. Ratios below 1.0 are the expected default here given the peak-price "
        f"benchmark. Judge models by the tightness of their cloud, not by its height."
    )

    canvas = Canvas(
        width_in=14,
        chart_height_in=6.0,
        title=f"{sector} — estimate-to-benchmark ratio, all companies overlaid",
        caption=caption,
        title_pad_in=1.05,
    )
    ax = canvas.single_axis()

    rng = np.random.default_rng(42)
    for j, m in enumerate(models):
        vals = ratios[m]
        if vals.notna().sum() == 0:
            continue
        offset = (j - (len(models) - 1) / 2) * 0.09
        x = np.array([xpos[f] for f in sub[COL_FY]], dtype=float) + offset
        x = x + rng.normal(0, 0.012, size=len(x))
        ax.scatter(
            x,
            vals,
            s=52,
            color=COLOURS[m],
            alpha=0.78,
            marker=MARKERS[m],
            edgecolors="white",
            linewidths=0.6,
            label=m,
        )

    ax.axhline(1.0, color="#111111", lw=2.0, ls="--", zorder=1)
    ax.text(
        0.995,
        1.0,
        "parity ",
        ha="right",
        va="bottom",
        fontsize=9,
        color="#111111",
        transform=matplotlib.transforms.blended_transform_factory(
            ax.transAxes, ax.transData
        ),
    )
    ax.set_xticks(range(len(fy_order)))
    ax.set_xticklabels(fy_order, fontsize=10)
    ax.set_xlabel("Financial year valued", fontsize=10.5)
    ax.set_ylabel("Intrinsic value / market benchmark", fontsize=10.5)
    ax.set_xlim(-0.6, len(fy_order) - 0.4)
    canvas.figure_legend(
        [
            Line2D(
                [], [], color=COLOURS[m], marker=MARKERS[m], ls="none", ms=8, label=m
            )
            for m in models
        ],
        ncol=len(models),
    )

    return canvas.save(outdir / f"sector_{_slug(sector)}_normalised.png", dpi=dpi)


def chart_overall_accuracy(
    metrics: pd.DataFrame, outdir: Path, dpi: int
) -> Optional[Path]:
    valid = metrics[metrics["N"] > 0].sort_values("MAPE %")
    if valid.empty:
        return None

    best, worst = valid.index[0], valid.index[-1]
    spread = valid.loc[worst, "MAPE %"] - valid.loc[best, "MAPE %"]
    rmse_leader = valid["RMSE"].idxmin()

    caption = (
        f"Reading this chart. Left panel ranks models by mean absolute percentage error "
        f"across every company-year in the dataset; shorter bars are better. Right panel "
        f"ranks the same models by root mean squared error in {CURRENCY}. The two panels "
        f"answer different questions. MAPE asks how wrong the typical estimate is. RMSE "
        f"squares each error before averaging, so it asks how badly the model fails when it "
        f"fails. A model that ranks well on MAPE but poorly on RMSE is usually right but "
        f"occasionally catastrophic, which is the more dangerous profile for a valuation "
        f"tool: users calibrate their trust on the typical case and get hurt by the tail.\n"
        f"What it shows here. {best} leads on percentage error at "
        f"{valid.loc[best, 'MAPE %']:.1f} percent against {valid.loc[worst, 'MAPE %']:.1f} "
        f"percent for {worst}, a spread of {spread:.1f} percentage points. On RMSE the "
        f"leader is {rmse_leader}. Where the MAPE leader and the RMSE leader differ, the "
        f"disagreement is itself the finding and belongs in the results discussion.\n"
        f"Caution. Sample sizes differ by model because a model that excluded a company-year "
        f"contributes no observation for it. The N column in metrics_overall.csv records "
        f"this; a model with materially fewer observations is not being compared on equal "
        f"footing and its apparent advantage may be survivorship."
    )

    canvas = Canvas(
        width_in=14,
        chart_height_in=5.4,
        title="Overall model accuracy against market benchmark",
        caption=caption,
    )
    gs = canvas.grid(1, 2, wspace=0.26, left=0.09)

    ax1 = canvas.fig.add_subplot(gs[0, 0])
    order = valid.sort_values("MAPE %", ascending=True)
    bars = ax1.barh(
        range(len(order)),
        order["MAPE %"],
        color=[COLOURS[m] for m in order.index],
        alpha=0.9,
    )
    ax1.set_yticks(range(len(order)))
    ax1.set_yticklabels(order.index, fontsize=10)
    ax1.invert_yaxis()
    ax1.set_xlabel("MAPE (%) — lower is better", fontsize=10.5)
    ax1.set_title("Mean absolute percentage error", fontsize=11.5)
    for b, v, n in zip(bars, order["MAPE %"], order["N"]):
        ax1.text(
            b.get_width() * 1.01,
            b.get_y() + b.get_height() / 2,
            f" {v:.1f}%  (n={int(n)})",
            va="center",
            fontsize=9,
        )
    ax1.set_xlim(0, order["MAPE %"].max() * 1.28)

    ax2 = canvas.fig.add_subplot(gs[0, 1])
    order2 = valid.sort_values("RMSE", ascending=True)
    bars2 = ax2.barh(
        range(len(order2)),
        order2["RMSE"],
        color=[COLOURS[m] for m in order2.index],
        alpha=0.9,
    )
    ax2.set_yticks(range(len(order2)))
    ax2.set_yticklabels(order2.index, fontsize=10)
    ax2.invert_yaxis()
    ax2.set_xlabel(f"RMSE ({CURRENCY}) — lower is better", fontsize=10.5)
    ax2.set_title("Root mean squared error", fontsize=11.5)
    for b, v in zip(bars2, order2["RMSE"]):
        ax2.text(
            b.get_width() * 1.01,
            b.get_y() + b.get_height() / 2,
            f" {v:,.0f}",
            va="center",
            fontsize=9,
        )
    ax2.set_xlim(0, order2["RMSE"].max() * 1.26)
    ax2.xaxis.set_major_formatter(FuncFormatter(_money_formatter))

    return canvas.save(outdir / "overall_model_accuracy.png", dpi=dpi)


def chart_win_rate(
    wins: pd.DataFrame, table: pd.DataFrame, outdir: Path, dpi: int
) -> Optional[Path]:
    if table.empty or table["Contested"].sum() == 0:
        return None

    ranked = table.sort_values("Win rate %", ascending=False)
    champion = ranked.index[0]
    share = ranked.iloc[0]["Win rate %"]
    n_models = len(ranked)
    chance = 100.0 / n_models if n_models else np.nan

    caption = (
        f"Reading this chart. For every company-year, the model whose estimate lands nearest "
        f"the benchmark in absolute terms scores one win. The bars show what share of "
        f"contested observations each model won. The dashed line marks {chance:.1f} percent, "
        f"the rate a model would achieve by chance if all {n_models} were "
        f"indistinguishable. Bars meaningfully above that line indicate real skill; bars near "
        f"it indicate the model is adding nothing beyond noise.\n"
        f"What it shows here. {champion} wins most often at {share:.1f} percent of "
        f"observations. Note what this metric does not say: winning most often is not the "
        f"same as being most accurate on average. A model can take many narrow wins while "
        f"losing badly on the observations it misses, which is exactly why this chart is "
        f"read alongside the MAPE and RMSE ranking rather than instead of it. Where the "
        f"win-rate champion and the MAPE leader are the same model, the evidence converges "
        f"and the conclusion is strong; where they differ, neither result alone supports a "
        f"claim about which approach is superior.\n"
        f"Caution. Ties are awarded to every tied model, and a model that produced no value "
        f"for an observation is neither credited nor penalised for it."
    )

    canvas = Canvas(
        width_in=13,
        chart_height_in=5.2,
        title="How often each model was closest to the benchmark",
        caption=caption,
        xlabel_pad_in=1.0,
    )
    ax = canvas.single_axis(left=0.10)

    bars = ax.bar(
        range(len(ranked)),
        ranked["Win rate %"],
        color=[COLOURS[m] for m in ranked.index],
        alpha=0.9,
        width=0.62,
    )
    ax.axhline(chance, color="#555555", ls="--", lw=1.4)
    ax.text(
        len(ranked) - 0.4,
        chance,
        f"  chance = {chance:.1f}%",
        va="bottom",
        ha="right",
        fontsize=9,
        color="#555555",
    )
    ax.set_xticks(range(len(ranked)))
    ax.set_xticklabels(ranked.index, rotation=18, ha="right", fontsize=10)
    ax.set_ylabel("Share of observations won (%)", fontsize=10.5)
    ax.set_ylim(0, max(ranked["Win rate %"].max() * 1.25, chance * 1.6))
    for b, v, w, c in zip(
        bars, ranked["Win rate %"], ranked["Wins"], ranked["Contested"]
    ):
        ax.text(
            b.get_x() + b.get_width() / 2,
            b.get_height(),
            f"{v:.1f}%\n{int(w)}/{int(c)}",
            ha="center",
            va="bottom",
            fontsize=9,
        )

    return canvas.save(outdir / "closest_model_win_rate.png", dpi=dpi)


def chart_accuracy_by_sector(
    by_sector: pd.DataFrame, models: Sequence[str], outdir: Path, dpi: int
) -> Optional[Path]:
    if by_sector.empty:
        return None

    pivot = by_sector.pivot(index="Model", columns=COL_SECTOR, values="MAPE %")
    pivot = pivot.reindex([m for m in models if m in pivot.index])
    if pivot.dropna(how="all").empty:
        return None

    per_sector_best = {
        s: pivot[s].idxmin() for s in pivot.columns if pivot[s].notna().any()
    }
    winners = pd.Series(list(per_sector_best.values())).value_counts()
    consistent = winners.index[0] if not winners.empty else "none"
    spread_by_model = (pivot.max(axis=1) - pivot.min(axis=1)).sort_values()
    steadiest = spread_by_model.index[0] if not spread_by_model.empty else "none"

    caption = (
        f"Reading this chart. Rows are models, columns are sectors, and each cell is that "
        f"model's MAPE within that sector. Darker cells are worse. Read across a row to see "
        f"whether a model holds up everywhere or only in the sectors that suit it; read down "
        f"a column to see which sector is hardest to value regardless of method. The best "
        f"cell in each column is shown in bold.\n"
        f"What it shows here. {consistent} takes the top spot in the largest number of "
        f"sectors ({int(winners.iloc[0]) if not winners.empty else 0} of {pivot.shape[1]}). "
        f"{steadiest} varies least across sectors, with a spread of "
        f"{spread_by_model.iloc[0]:.1f} percentage points between its best and worst sector. "
        f"Stability across sectors is a separate and arguably more valuable property than "
        f"peak accuracy in one: a model that wins narrowly everywhere generalises, while a "
        f"model that wins hugely in one sector and collapses elsewhere has likely fitted a "
        f"sector-specific quirk. For a comparative study, that distinction is the result.\n"
        f"Caution. Cells backed by very few observations are volatile. Check the N column in "
        f"metrics_by_sector.csv before drawing conclusions from any single cell."
    )

    canvas = Canvas(
        width_in=14,
        chart_height_in=1.0 + 0.62 * len(pivot),
        title="MAPE by model and sector",
        caption=caption,
        xlabel_pad_in=1.05,
    )
    ax = canvas.single_axis(left=0.16, right=0.94)

    data = pivot.values.astype(float)
    im = ax.imshow(data, cmap="RdYlGn_r", aspect="auto")
    ax.set_xticks(range(pivot.shape[1]))
    ax.set_xticklabels([textwrap.fill(str(c), 18) for c in pivot.columns], fontsize=9.5)
    ax.set_yticks(range(pivot.shape[0]))
    ax.set_yticklabels(pivot.index, fontsize=10)
    ax.grid(False)

    for i in range(pivot.shape[0]):
        for j in range(pivot.shape[1]):
            v = data[i, j]
            if np.isnan(v):
                ax.text(
                    j, i, "n/a", ha="center", va="center", fontsize=9, color="#777777"
                )
                continue
            lo, hi = np.nanmin(data), np.nanmax(data)
            norm = 0.5 if hi == lo else (v - lo) / (hi - lo)
            ax.text(
                j,
                i,
                f"{v:.1f}",
                ha="center",
                va="center",
                fontsize=10,
                color="white" if norm > 0.62 else "#111111",
                fontweight=(
                    "bold"
                    if pivot.index[i] == per_sector_best.get(pivot.columns[j])
                    else "normal"
                ),
            )

    cb = canvas.fig.colorbar(im, ax=ax, fraction=0.024, pad=0.015)
    cb.set_label("MAPE (%)", fontsize=9.5)

    return canvas.save(outdir / "accuracy_by_sector.png", dpi=dpi)


def chart_accuracy_by_year(
    by_year: pd.DataFrame, models: Sequence[str], outdir: Path, dpi: int
) -> Optional[Path]:
    if by_year.empty:
        return None

    pivot = by_year.pivot(index=COL_FY, columns="Model", values="MAPE %")
    pivot = pivot.reindex(
        sorted(pivot.index, key=lambda f: int(re.match(r"(\d{4})", f).group(1)))
    )
    pivot = pivot[[m for m in models if m in pivot.columns]]
    if pivot.dropna(how="all").empty:
        return None

    year_means = pivot.mean(axis=1)
    hardest = year_means.idxmax()
    easiest = year_means.idxmin()

    caption = (
        f"Reading this chart. One line per model, tracing its MAPE across the financial years "
        f"in the panel. Lower is better. Flat lines mean the model performs consistently "
        f"through changing market conditions. Lines that rise and fall together indicate the "
        f"difficulty is coming from the market environment, not from any particular method: "
        f"when all six models degrade in the same year, the benchmark moved in a way that no "
        f"fundamentals-based estimate anticipated.\n"
        f"What it shows here. {hardest} was the hardest year to value, averaging "
        f"{year_means[hardest]:.1f} percent error across models, while {easiest} was the "
        f"easiest at {year_means[easiest]:.1f} percent. Divergence between the machine "
        f"learning models and the traditional models in any single year is worth "
        f"investigating directly, since the two families fail for different reasons: "
        f"traditional models break when their inputs break, whereas learned models break "
        f"when the year falls outside the distribution they were trained on.\n"
        f"Caution. The most recent financial year in the panel may have an incomplete "
        f"assessment window, since its 52-week high is drawn from a year that has not yet "
        f"finished. A partial window truncates the observed maximum and mechanically "
        f"flatters every model. Confirm the window status before interpreting the final point "
        f"on each line."
    )

    canvas = Canvas(
        width_in=13.5,
        chart_height_in=5.4,
        title="Model accuracy across financial years",
        caption=caption,
        title_pad_in=1.05,
    )
    ax = canvas.single_axis(left=0.09)

    x = range(len(pivot.index))
    for m in pivot.columns:
        ax.plot(x, pivot[m], color=COLOURS[m], lw=2.0, marker=MARKERS[m], ms=7, label=m)

    ax.set_xticks(list(x))
    ax.set_xticklabels(pivot.index, fontsize=10)
    ax.set_xlabel("Financial year valued", fontsize=10.5)
    ax.set_ylabel("MAPE (%) — lower is better", fontsize=10.5)
    canvas.figure_legend(
        [
            Line2D([], [], color=COLOURS[m], marker=MARKERS[m], lw=2.0, label=m)
            for m in pivot.columns
        ],
        ncol=len(pivot.columns),
    )

    return canvas.save(outdir / "accuracy_by_year.png", dpi=dpi)


def chart_error_distribution(
    df: pd.DataFrame, models: Sequence[str], outdir: Path, dpi: int
) -> Optional[Path]:
    data, labels = [], []
    for m in models:
        mask = df[COL_MARKET].notna() & df[m].notna() & (df[COL_MARKET] != 0)
        if mask.sum() == 0:
            continue
        pct = (
            (df.loc[mask, m] - df.loc[mask, COL_MARKET]) / df.loc[mask, COL_MARKET]
        ) * 100
        data.append(pct.values)
        labels.append(m)
    if not data:
        return None

    medians = {l: float(np.median(d)) for l, d in zip(labels, data)}
    iqrs = {
        l: float(np.percentile(d, 75) - np.percentile(d, 25))
        for l, d in zip(labels, data)
    }
    tightest = min(iqrs, key=iqrs.get)
    least_biased = min(medians, key=lambda k: abs(medians[k]))

    caption = (
        f"Reading this chart. Each box summarises the distribution of signed percentage "
        f"errors for one model, where a value of -30 means the estimate came in 30 percent "
        f"below the benchmark. The box spans the middle half of observations, the line inside "
        f"is the median, whiskers reach the bulk of the remainder and separate points are "
        f"outliers. Two things matter and they are independent. The position of the box "
        f"relative to the zero line is bias, meaning systematic over or undervaluation. The "
        f"width of the box is dispersion, meaning inconsistency. Bias is correctable by "
        f"rescaling; dispersion is not.\n"
        f"What it shows here. {least_biased} is least biased with a median error of "
        f"{medians[least_biased]:+.1f} percent. {tightest} is the most consistent, with the "
        f"middle half of its errors spanning {iqrs[tightest]:.1f} percentage points. A model "
        f"that is badly biased but tight is more useful than one centred on zero but wildly "
        f"scattered, because the first can be corrected with a single constant and the second "
        f"cannot be corrected at all.\n"
        f"Caution. Boxes are expected to sit below zero because the benchmark is a 52-week "
        f"high. The informative comparison is which model sits closest to zero relative to "
        f"the others, and how wide each box is, not whether any box straddles zero."
    )

    canvas = Canvas(
        width_in=13.5,
        chart_height_in=5.6,
        title="Distribution of signed percentage error by model",
        caption=caption,
        xlabel_pad_in=1.0,
    )
    ax = canvas.single_axis(left=0.09)

    # 'labels' was renamed 'tick_labels' in Matplotlib 3.9.
    label_kw = (
        "tick_labels"
        if tuple(int(p) for p in matplotlib.__version__.split(".")[:2]) >= (3, 9)
        else "labels"
    )
    bp = ax.boxplot(
        data,
        **{label_kw: labels},
        patch_artist=True,
        widths=0.55,
        medianprops=dict(color="#111111", lw=2.0),
        flierprops=dict(
            marker="o",
            ms=4,
            alpha=0.5,
            markerfacecolor="#888888",
            markeredgecolor="none",
        ),
    )
    for patch, label in zip(bp["boxes"], labels):
        patch.set_facecolor(COLOURS[label])
        patch.set_alpha(0.62)
        patch.set_edgecolor("#333333")

    ax.axhline(0, color="#111111", lw=1.6, ls="--")
    ax.set_ylabel("(estimate - benchmark) / benchmark, %", fontsize=10.5)
    ax.set_xticklabels(labels, rotation=18, ha="right", fontsize=10)

    return canvas.save(outdir / "error_distribution.png", dpi=dpi)


def chart_metrics_table(
    metrics: pd.DataFrame, wins: pd.DataFrame, outdir: Path, dpi: int
) -> Optional[Path]:
    if metrics.empty:
        return None

    tbl = metrics.copy()
    if not wins.empty:
        tbl = tbl.join(wins[["Win rate %"]], how="left")

    display = tbl.copy()
    for col in display.columns:
        if col == "N":
            display[col] = display[col].map(
                lambda v: f"{int(v)}" if pd.notna(v) else "-"
            )
        elif col == "Spearman":
            display[col] = display[col].map(
                lambda v: f"{v:+.3f}" if pd.notna(v) else "-"
            )
        elif "%" in col:
            display[col] = display[col].map(
                lambda v: f"{v:.1f}" if pd.notna(v) else "-"
            )
        else:
            display[col] = display[col].map(
                lambda v: f"{v:,.0f}" if pd.notna(v) else "-"
            )

    caption = (
        "Reading this table. Every metric computed over every company-year, one row per "
        f"model. MAE and RMSE are in {CURRENCY} per share; MAPE, MedAPE, Bias percent and "
        "the hit rate are percentages; Spearman is a rank correlation between -1 and +1. A "
        "large gap between MAPE and MedAPE means a few extreme observations are inflating "
        "the mean, in which case MedAPE is the fairer summary. A high Spearman alongside a "
        "poor MAPE means the model ranks companies correctly while missing the level, which "
        "makes it usable for relative screening even though its absolute estimates are "
        "unreliable.\n"
        "Using this table. This is the source for the results table in the thesis. Every "
        "number here is reproduced in metrics_overall.csv alongside the per-sector, per-year "
        "and per-company breakdowns, so no figure needs to be transcribed by hand from an "
        "image."
    )

    nrows = len(display)
    canvas = Canvas(
        width_in=15.5,
        chart_height_in=0.55 + 0.42 * nrows,
        title="Full metric table — all models, all observations",
        caption=caption,
        xlabel_pad_in=0.25,
    )
    ax = canvas.single_axis(left=0.135, right=0.985)
    ax.axis("off")
    ax.grid(False)

    table = ax.table(
        cellText=display.values,
        colLabels=display.columns,
        rowLabels=display.index,
        cellLoc="center",
        rowLoc="left",
        loc="center",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(10)
    table.scale(1, 1.7)

    for (r, c), cell in table.get_celld().items():
        cell.set_edgecolor("#dddddd")
        if r == 0:
            cell.set_facecolor("#f0f0f0")
            cell.set_text_props(fontweight="bold")
        elif c == -1:
            model = display.index[r - 1]
            cell.set_facecolor(COLOURS.get(model, "#ffffff"))
            cell.set_alpha(0.28)
            cell.set_text_props(fontweight="bold")
        elif r % 2 == 0:
            cell.set_facecolor("#fafafa")

    return canvas.save(outdir / "metrics_table.png", dpi=dpi)


# --------------------------------------------------------------------------
# Report assembly
# --------------------------------------------------------------------------


def _chart_dir_name() -> str:
    try:
        import config  # flat import: same module instance as the rest of the run

        return getattr(config, "CHART_DIR_NAME", "charts")
    except Exception:
        return "charts"


def _write_html(outdir: Path, charts: list[Path], summary: dict) -> Path:
    sub = _chart_dir_name()
    cards = "\n".join(
        f'<figure><img src="{sub}/{html.escape(p.name)}" alt="{html.escape(p.stem)}">'
        f"<figcaption>{html.escape(p.stem.replace('_', ' '))}</figcaption></figure>"
        for p in charts
    )
    rows = "\n".join(
        f"<tr><td>{html.escape(str(k))}</td><td>{html.escape(str(v))}</td></tr>"
        for k, v in summary.items()
    )
    doc = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>INTVAL-Calc — analysis report</title>
<style>
 body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
      max-width:1200px;margin:0 auto;padding:32px;color:#1a1a1a;line-height:1.55}}
 h1{{margin-bottom:4px}} .sub{{color:#666;margin-top:0}}
 table{{border-collapse:collapse;margin:20px 0}}
 td{{border:1px solid #e0e0e0;padding:6px 12px}}
 td:first-child{{font-weight:600;background:#fafafa}}
 figure{{margin:36px 0}} img{{width:100%;border:1px solid #e0e0e0;border-radius:6px}}
 figcaption{{color:#666;font-size:13px;margin-top:8px;text-transform:capitalize}}
</style></head><body>
<h1>INTVAL-Calc — analysis report</h1>
<p class="sub">Generated {html.escape(datetime.now().strftime('%d %B %Y, %H:%M'))}</p>
<table>{rows}</table>
{cards}
</body></html>"""
    path = outdir / "analysis_report.html"
    path.write_text(doc, encoding="utf-8")
    return path


def run_analysis(
    csv_path: Path,
    outdir: Optional[Path] = None,
    dpi: int = 200,
    quiet: bool = False,
) -> dict:
    """
    Entry point. Reads the results CSV, writes charts and metric tables into
    <outdir>/charts and <outdir>, returns a summary dict.
    """

    def log(msg: str) -> None:
        if not quiet:
            print(msg, flush=True)

    csv_path = Path(csv_path)
    outdir = Path(outdir) if outdir else csv_path.parent
    charts_dir = outdir / _chart_dir_name()
    charts_dir.mkdir(parents=True, exist_ok=True)

    log(f"[analyzer] reading {csv_path}")
    df = load_results(csv_path)
    models = [m for m in MODEL_NAMES if df[m].notna().any()]
    if not models:
        raise ValueError("No model columns contain any numeric values.")

    scored = df[df[COL_MARKET].notna()]
    log(
        f"[analyzer] {len(df)} rows, {df[COL_COMPANY].nunique()} companies, "
        f"{df[COL_SECTOR].nunique()} sectors, {len(models)} models with data"
    )
    if len(scored) < len(df):
        log(
            f"[analyzer] note: {len(df) - len(scored)} row(s) have no market "
            f"benchmark and are excluded from all metrics"
        )

    metrics = compute_metrics(scored, models)
    by_sector = compute_grouped_metrics(scored, models, COL_SECTOR)
    by_year = compute_grouped_metrics(scored, models, COL_FY)
    by_company = compute_grouped_metrics(scored, models, COL_COMPANY)
    wins = compute_wins(scored, models)
    wins_tbl = win_rate_table(wins, models)

    metrics.round(4).to_csv(outdir / "metrics_overall.csv")
    by_sector.round(4).to_csv(outdir / "metrics_by_sector.csv", index=False)
    by_year.round(4).to_csv(outdir / "metrics_by_year.csv", index=False)
    by_company.round(4).to_csv(outdir / "metrics_by_company.csv", index=False)
    wins_tbl.to_csv(outdir / "metrics_win_rate.csv")
    log(f"[analyzer] wrote 5 metric tables to {outdir}")

    charts: list[Path] = []

    for sector in sorted(df[COL_SECTOR].unique()):
        for fn in (chart_sector_levels, chart_sector_normalised):
            p = fn(df, sector, models, charts_dir, dpi)
            if p:
                charts.append(p)
                log(f"[analyzer]   {p.name}")

    for p in (
        chart_overall_accuracy(metrics, charts_dir, dpi),
        chart_win_rate(wins, wins_tbl, charts_dir, dpi),
        chart_accuracy_by_sector(by_sector, models, charts_dir, dpi),
        chart_accuracy_by_year(by_year, models, charts_dir, dpi),
        chart_error_distribution(scored, models, charts_dir, dpi),
        chart_metrics_table(metrics, wins_tbl, charts_dir, dpi),
    ):
        if p:
            charts.append(p)
            log(f"[analyzer]   {p.name}")

    valid = metrics[metrics["N"] > 0]
    summary = {
        "Source CSV": csv_path.name,
        "Observations": len(df),
        "Scored observations": len(scored),
        "Companies": df[COL_COMPANY].nunique(),
        "Sectors": df[COL_SECTOR].nunique(),
        "Financial years": ", ".join(sorted(df[COL_FY].unique())),
        "Models compared": ", ".join(models),
        "Lowest MAPE": (
            f"{valid['MAPE %'].idxmin()} ({valid['MAPE %'].min():.1f}%)"
            if not valid.empty
            else "n/a"
        ),
        "Lowest RMSE": (
            f"{valid['RMSE'].idxmin()} ({CURRENCY} {valid['RMSE'].min():,.0f})"
            if not valid.empty
            else "n/a"
        ),
        "Most frequent winner": (
            f"{wins_tbl['Win rate %'].idxmax()} "
            f"({wins_tbl['Win rate %'].max():.1f}% of observations)"
            if not wins_tbl.empty and wins_tbl["Win rate %"].notna().any()
            else "n/a"
        ),
        "Charts written": len(charts),
        "Benchmark": "52-week high of the assessment year (the FY after the one valued)",
    }

    report = _write_html(outdir, charts, summary)
    (outdir / "analysis_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )

    log("")
    log("=" * 66)
    for k, v in summary.items():
        log(f"  {k:<24} {v}")
    log("=" * 66)
    log(f"[analyzer] report: {report}")

    return {
        "summary": summary,
        "charts": charts,
        "report": report,
        "metrics": metrics,
        "outdir": outdir,
    }


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="csv_analyzer",
        description="Analyse the INTVAL-Calc results grid and emit HD charts.",
    )
    ap.add_argument(
        "csv",
        nargs="?",
        default="output/Intrinsic_Value_Data.csv",
        help="path to the results CSV (default: %(default)s)",
    )
    ap.add_argument(
        "-o",
        "--outdir",
        default=None,
        help="output folder (default: alongside the CSV)",
    )
    ap.add_argument(
        "--dpi", type=int, default=200, help="chart resolution (default: %(default)s)"
    )
    ap.add_argument(
        "-q", "--quiet", action="store_true", help="suppress progress output"
    )
    args = ap.parse_args(argv)

    try:
        run_analysis(
            Path(args.csv),
            Path(args.outdir) if args.outdir else None,
            dpi=args.dpi,
            quiet=args.quiet,
        )
    except Exception as exc:
        print(f"[analyzer] FAILED: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
