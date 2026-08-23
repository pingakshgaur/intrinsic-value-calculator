# FILE: src/io_layer/exporter.py
"""
Three outputs:
  Intrinsic_Value_Report.*        clean grid - values (* = estimated) or a code
  Intrinsic_Value_Diagnostics.*   full explanation for every empty cell
  Intrinsic_Value_Methods.*       provenance for every filled cell
"""

import logging

import pandas as pd

import config
from result import Result, R

log = logging.getLogger(__name__)

COLUMNS = [
    "Company name",
    "Sector Name",
    "Financial Year",
    "Market Price",
    "(DCF) Intrinsic Value",
    "(P/E Relative Valuation) Intrinsic Value",
    "(EV/EBITDA Valuation) Intrinsic Value",
    "(XGBoost) Intrinsic Value",
    "(Random Forest) Intrinsic Value",
    "(LightGBM) Intrinsic Value",
]

VALUE_KEYS = [
    ("price", COLUMNS[3]),
    ("dcf", COLUMNS[4]),
    ("pe", COLUMNS[5]),
    ("ev", COLUMNS[6]),
    ("xgboost", COLUMNS[7]),
    ("random_forest", COLUMNS[8]),
    ("lightgbm", COLUMNS[9]),
]

DIAG_COLUMNS = [
    "Company name",
    "Sector Name",
    "Financial Year",
    "Model",
    "Reason code",
    "Explanation",
]

METHOD_COLUMNS = [
    "Company name",
    "Financial Year",
    "Model",
    "Value",
    "Estimated?",
    "Method",
]


def _res(r, key):
    v = r.get(key)
    return (
        v
        if isinstance(v, Result)
        else Result.bad(R.NOT_COMPUTABLE, "value was never computed")
    )


def build_dataframe(rows):
    out, prev = [], None
    for r in rows:
        if prev is not None and r["company"] != prev:
            out.append({c: "" for c in COLUMNS})
        rec = {COLUMNS[0]: r["company"], COLUMNS[1]: r["sector"], COLUMNS[2]: r["fy"]}
        for key, col in VALUE_KEYS:
            rec[col] = _res(r, key).text()
        out.append(rec)
        prev = r["company"]
    return pd.DataFrame(out, columns=COLUMNS)


def build_diagnostics(rows):
    recs = []
    for r in rows:
        for key, col in VALUE_KEYS:
            res = _res(r, key)
            if res.ok:
                continue
            recs.append(
                {
                    DIAG_COLUMNS[0]: r["company"],
                    DIAG_COLUMNS[1]: r["sector"],
                    DIAG_COLUMNS[2]: r["fy"],
                    DIAG_COLUMNS[3]: col,
                    DIAG_COLUMNS[4]: res.code or "",
                    DIAG_COLUMNS[5]: res.detail or "",
                }
            )
    return pd.DataFrame(recs, columns=DIAG_COLUMNS)


def build_methods(rows):
    recs = []
    for r in rows:
        for key, col in VALUE_KEYS:
            res = _res(r, key)
            if not res.ok:
                continue
            recs.append(
                {
                    METHOD_COLUMNS[0]: r["company"],
                    METHOD_COLUMNS[1]: r["fy"],
                    METHOD_COLUMNS[2]: col,
                    METHOD_COLUMNS[3]: round(res.value, 2),
                    METHOD_COLUMNS[4]: "YES" if res.estimated else "no",
                    METHOD_COLUMNS[5]: res.method
                    or "directly computed from reported figures",
                }
            )
    return pd.DataFrame(recs, columns=METHOD_COLUMNS)


def _style(ws, df, widths, wrap_last=False):
    from openpyxl.styles import Alignment, Font

    for i, col in enumerate(df.columns, start=1):
        letter = ws.cell(row=1, column=i).column_letter
        ws.column_dimensions[letter].width = widths.get(i - 1, 20)
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.alignment = Alignment(
            wrap_text=True, vertical="center", horizontal="center"
        )
    last = len(df.columns)
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            wrap = wrap_last and cell.column == last
            cell.alignment = Alignment(
                wrap_text=wrap,
                vertical="top",
                horizontal="right" if cell.column > 3 else "left",
            )


def export(rows):
    try:
        config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        df = build_dataframe(rows)
        csv_path = config.OUTPUT_DIR / f"{config.OUTPUT_BASENAME}.csv"
        xlsx_path = config.OUTPUT_DIR / f"{config.OUTPUT_BASENAME}.xlsx"
        df.to_csv(csv_path, index=False, encoding="utf-8-sig")

        aux_paths = []
        dd = mm = None

        if config.WRITE_DIAGNOSTICS:
            dd = build_diagnostics(rows)
            p = config.OUTPUT_DIR / f"{config.DIAGNOSTICS_BASENAME}.csv"
            dd.to_csv(p, index=False, encoding="utf-8-sig")
            aux_paths.append(p)

        if getattr(config, "WRITE_METHOD_SHEET", False):
            mm = build_methods(rows)
            p = config.OUTPUT_DIR / f"{config.METHODS_BASENAME}.csv"
            mm.to_csv(p, index=False, encoding="utf-8-sig")
            aux_paths.append(p)

        try:
            with pd.ExcelWriter(xlsx_path, engine="openpyxl") as xw:
                df.to_excel(xw, index=False, sheet_name="Intrinsic Values")
                _style(
                    xw.sheets["Intrinsic Values"],
                    df,
                    {
                        0: 34,
                        1: 26,
                        2: 14,
                        3: 16,
                        4: 22,
                        5: 22,
                        6: 22,
                        7: 22,
                        8: 22,
                        9: 22,
                    },
                )
                xw.sheets["Intrinsic Values"].freeze_panes = "D2"

                if dd is not None:
                    dd.to_excel(xw, index=False, sheet_name="Diagnostics")
                    _style(
                        xw.sheets["Diagnostics"],
                        dd,
                        {0: 34, 1: 26, 2: 14, 3: 30, 4: 26, 5: 90},
                        wrap_last=True,
                    )
                    xw.sheets["Diagnostics"].freeze_panes = "A2"

                if mm is not None:
                    mm.to_excel(xw, index=False, sheet_name="Methods")
                    _style(
                        xw.sheets["Methods"],
                        mm,
                        {0: 34, 1: 14, 2: 30, 3: 16, 4: 12, 5: 80},
                        wrap_last=True,
                    )
                    xw.sheets["Methods"].freeze_panes = "A2"
        except Exception as e:
            log.exception("xlsx write failed")
            xlsx_path = f"(xlsx skipped: {type(e).__name__}: {e})"

        return csv_path, xlsx_path, aux_paths
    except Exception as e:
        log.exception("export failed")
        return f"(export failed: {type(e).__name__}: {e})", "", []
