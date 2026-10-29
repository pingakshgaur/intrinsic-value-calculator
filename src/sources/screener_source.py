# FILE: src/sources/screener_source.py
"""
Screener.in annual accounts: ten or more years of profit & loss, balance sheet
and cash flow for any NSE or BSE company - the depth Yahoo Finance lacks.

The public company page (/company/<SYMBOL>/consolidated/, falling back to the
standalone page) carries three tables, in rupees crore:

    #profit-loss    Sales, Operating Profit, Other Income, Interest,
                    Depreciation, Profit before tax, Tax %, Net Profit, EPS
    #balance-sheet  Equity Capital, Reserves, Borrowings, Total Assets,
                    Fixed Assets, CWIP
    #cash-flow      Cash from Operating Activity

Mapped to the fetch layer's fields in absolute rupees:

    revenue     Sales (banks: Revenue)
    ebit        Profit before tax + Interest
    da          Depreciation;  ebitda = ebit + da
    net_income  Net Profit;  eps = EPS in Rs;  shares = Net Profit / EPS
    tax_rate    Tax %
    total_debt  Borrowings;  equity = Equity Capital + Reserves;  assets = Total Assets
    ocf         Cash from Operating Activity
    capex       change in (Fixed Assets + CWIP) + Depreciation - an estimate,
                marked as such in the notes

Cash and current liabilities are not on the page and are left to the other
sources. Any failure returns {} so the fetch carries on with what it has.
"""

import datetime as dt
import logging
import re
from html.parser import HTMLParser

import requests

from fy_utils import fy_for_period_end, num

log = logging.getLogger(__name__)
BASE = "https://www.screener.in/company/{sym}/{kind}"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
           "Accept": "text/html,application/xhtml+xml", "Accept-Language": "en-IN,en;q=0.9"}
CRORE = 1e7
MONTHS = {m: i for i, m in enumerate(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}
SECTIONS = ("profit-loss", "balance-sheet", "cash-flow")


class _Tables(HTMLParser):
    """Collects the first data table inside each <section id=...> of interest:
    {section: [[cell text, ...], ...]} with the header row first."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.section, self.depth, self.rows, self.cell, self.in_table = {}, None, 0, None, None, False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "section":
            if self.section:
                self.depth += 1
            elif a.get("id") in SECTIONS and a.get("id") not in self.out:
                self.section, self.depth, self.rows = a["id"], 0, []
        elif self.section and tag == "table" and not self.in_table and not self.rows:
            self.in_table = True
        elif self.in_table and tag == "tr":
            self.rows.append([])
        elif self.in_table and tag in ("td", "th"):
            self.cell = []

    def handle_endtag(self, tag):
        if self.in_table and tag in ("td", "th") and self.cell is not None:
            if self.rows:
                self.rows[-1].append(" ".join("".join(self.cell).split()))
            self.cell = None
        elif self.in_table and tag == "table":
            self.in_table = False
        elif tag == "section" and self.section:
            if self.depth:
                self.depth -= 1
            else:
                self.out[self.section] = [r for r in self.rows if r]
                self.section = None

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)


def parse_tables(html):
    p = _Tables()
    p.feed(html)
    return p.out


def _period(label):
    """'Mar 2024' -> (date of the period end) or None (TTM, blank)."""
    m = re.match(r"^([A-Z][a-z]{2})\s+(\d{4})$", (label or "").strip())
    if not m or m.group(1) not in MONTHS:
        return None
    y, mo = int(m.group(2)), MONTHS[m.group(1)]
    nxt = dt.date(y + (mo == 12), mo % 12 + 1, 1)
    return nxt - dt.timedelta(days=1)


def _value(cell):
    s = (cell or "").replace(",", "").replace("%", "").strip()
    if s in ("", "-", "--"):
        return None
    return num(s)


def _rows(table):
    """-> ([period end dates or None], {row label: [values]})"""
    if not table:
        return [], {}
    head = [_period(h) for h in table[0][1:]]
    rows = {}
    for r in table[1:]:
        if not r:
            continue
        label = re.sub(r"\s*\+\s*$", "", r[0]).strip().lower()
        rows.setdefault(label, [_value(c) for c in r[1:]])
    return head, rows


def _pick(rows, *names):
    for n in names:
        if n in rows:
            return rows[n]
    return None


def _by_fy(head, values, scale=1.0):
    out = {}
    if values is None:
        return out
    for when, v in zip(head, values):
        if when is not None and v is not None:
            out[fy_for_period_end(when, 365)] = v * scale
    return out


def statements(tables):
    """Parsed tables -> {fy: {field: value in rupees}} (only the fields that are present)."""
    pl_h, pl = _rows(tables.get("profit-loss"))
    bs_h, bs = _rows(tables.get("balance-sheet"))
    cf_h, cf = _rows(tables.get("cash-flow"))
    f = {
        "revenue": _by_fy(pl_h, _pick(pl, "sales", "revenue", "revenue from operations"), CRORE),
        "interest": _by_fy(pl_h, _pick(pl, "interest"), CRORE),
        "da": _by_fy(pl_h, _pick(pl, "depreciation"), CRORE),
        "pbt": _by_fy(pl_h, _pick(pl, "profit before tax"), CRORE),
        "tax_pct": _by_fy(pl_h, _pick(pl, "tax %", "tax")),
        "net_income": _by_fy(pl_h, _pick(pl, "net profit", "profit after tax"), CRORE),
        "eps": _by_fy(pl_h, _pick(pl, "eps in rs", "eps")),
        "equity_capital": _by_fy(bs_h, _pick(bs, "equity capital", "share capital"), CRORE),
        "reserves": _by_fy(bs_h, _pick(bs, "reserves"), CRORE),
        "total_debt": _by_fy(bs_h, _pick(bs, "borrowings", "borrowing"), CRORE),
        "assets": _by_fy(bs_h, _pick(bs, "total assets"), CRORE),
        "fixed": _by_fy(bs_h, _pick(bs, "fixed assets", "net block"), CRORE),
        "cwip": _by_fy(bs_h, _pick(bs, "cwip", "capital work in progress"), CRORE),
        "ocf": _by_fy(cf_h, _pick(cf, "cash from operating activity", "cash from operating activities"), CRORE),
    }
    # banks and lenders: "Interest" is what they pay depositors, so PBT + interest is no EBIT
    lender = "financing profit" in pl
    out = {}
    for fy in sorted({y for d in f.values() for y in d}):
        d = {}
        for k in ("revenue", "da", "net_income", "eps", "total_debt", "assets", "ocf"):
            if fy in f[k]:
                d[k] = f[k][fy]
        if fy in f["pbt"] and not lender:
            d["ebit"] = f["pbt"][fy] + f["interest"].get(fy, 0.0)
            d["pretax"] = f["pbt"][fy]
            if "da" in d:
                d["ebitda"] = d["ebit"] + d["da"]
        if fy in f["tax_pct"] and 0 <= f["tax_pct"][fy] <= 100:
            d["tax_rate"] = f["tax_pct"][fy] / 100
        if fy in f["equity_capital"] or fy in f["reserves"]:
            d["equity"] = f["equity_capital"].get(fy, 0.0) + f["reserves"].get(fy, 0.0)
        if d.get("net_income") and d.get("eps"):
            shares = d["net_income"] / d["eps"]
            if shares > 0:
                d["shares"] = shares
        # capex is not on the page: the growth in gross-ish fixed assets plus what depreciation wore away
        now = f["fixed"].get(fy, None)
        before = f["fixed"].get(fy - 1, None)
        if now is not None and before is not None and "da" in d:
            gross = (now + f["cwip"].get(fy, 0.0)) - (before + f["cwip"].get(fy - 1, 0.0)) + d["da"]
            if gross >= 0:
                d["capex"] = gross
                d["_estimated"] = ["capex"]
        if d:
            out[fy] = d
    return out


def _symbol(ticker):
    return ticker.split(".")[0].upper()


def fetch(ticker, session=None, timeout=20):
    """-> {fy: {field: value}} from the consolidated page, else the standalone one; {} on failure."""
    s = session or requests.Session()
    sym = _symbol(ticker)
    for kind in ("consolidated/", ""):
        try:
            r = s.get(BASE.format(sym=sym, kind=kind), headers=HEADERS, timeout=timeout)
            if r.status_code != 200:
                continue
            got = statements(parse_tables(r.text))
            # a consolidated page with no rows means the company files standalone only
            if got:
                return got
        except Exception as e:  # noqa: BLE001 - the fetch layer carries on with the other sources
            log.info("screener.in failed for %s (%s): %s", ticker, kind or "standalone", e)
    return {}
