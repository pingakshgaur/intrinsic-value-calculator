# FILE: tests/test_sources.py
"""
Tests for the data-provider layer: Screener.in parsing, the price fallback
chain, the merge in data_hub, and the provider settings. No network: every
provider is replaced by a stub, and Screener.in is fed a page in its own
table layout.

    python -m pytest tests -q
"""

import datetime as dt
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
for sub in ("", "src", "src/sources", "src/models", "src/io_layer", "tools"):
    p = str(ROOT / sub)
    if p not in sys.path:
        sys.path.insert(0, p)

import config  # noqa: E402
import data_hub  # noqa: E402
import overrides  # noqa: E402
import price_chain  # noqa: E402
import screener_source as SCR  # noqa: E402
import source_settings as SS  # noqa: E402
import yf_source  # noqa: E402

PAGE = """
<html><body>
<section id="quarters"><table class="data-table"><tr><th></th><th>Jun 2024</th></tr><tr><td>Sales</td><td>9</td></tr></table></section>
<section id="profit-loss" class="card">
  <div class="flex"><h2>Profit &amp; Loss</h2></div>
  <div class="responsive-holder"><table class="data-table">
    <thead><tr><th class="text"></th><th>Mar 2022</th><th>Mar 2023</th><th>Mar 2024</th><th>TTM</th></tr></thead>
    <tbody>
      <tr><td class="text"><button>Sales&nbsp;<span>+</span></button></td><td>1,000</td><td>1,200</td><td>1,500</td><td>1,600</td></tr>
      <tr><td class="text">Operating Profit</td><td>200</td><td>240</td><td>300</td><td>310</td></tr>
      <tr><td class="text">Interest</td><td>10</td><td>12</td><td>15</td><td>15</td></tr>
      <tr><td class="text">Depreciation</td><td>40</td><td>45</td><td>50</td><td>52</td></tr>
      <tr><td class="text">Profit before tax</td><td>170</td><td>200</td><td>260</td><td>270</td></tr>
      <tr><td class="text">Tax %</td><td>25%</td><td>24%</td><td>25%</td><td></td></tr>
      <tr><td class="text"><button>Net Profit&nbsp;+</button></td><td>127.5</td><td>152</td><td>195</td><td>200</td></tr>
      <tr><td class="text">EPS in Rs</td><td>12.75</td><td>15.20</td><td>19.50</td><td>20</td></tr>
    </tbody></table></div>
</section>
<section id="balance-sheet"><table class="data-table">
  <tr><th></th><th>Mar 2022</th><th>Mar 2023</th><th>Mar 2024</th></tr>
  <tr><td>Equity Capital</td><td>100</td><td>100</td><td>100</td></tr>
  <tr><td>Reserves</td><td>500</td><td>620</td><td>780</td></tr>
  <tr><td>Borrowings +</td><td>80</td><td>60</td><td>0</td></tr>
  <tr><td>Fixed Assets +</td><td>400</td><td>430</td><td>470</td></tr>
  <tr><td>CWIP</td><td>20</td><td>10</td><td>30</td></tr>
  <tr><td>Total Assets</td><td>900</td><td>1,000</td><td>1,150</td></tr>
</table></section>
<section id="cash-flow"><table class="data-table">
  <tr><th></th><th>Mar 2022</th><th>Mar 2023</th><th>Mar 2024</th></tr>
  <tr><td>Cash from Operating Activity +</td><td>150</td><td>170</td><td>220</td></tr>
</table></section>
</body></html>
"""
CR = 1e7


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(SS, "SETTINGS", tmp_path / "sources.json")
    monkeypatch.setattr(SS, "ENV_FILE", tmp_path / ".env")
    for k in SS.KEY_NAMES:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(config, "REQUEST_PAUSE", 0)
    monkeypatch.setattr(overrides, "_cache", {})
    yield tmp_path


def test_screener_page_maps_to_rupee_fields():
    got = SCR.statements(SCR.parse_tables(PAGE))
    assert sorted(got) == [2022, 2023, 2024]          # TTM and the quarterly table are ignored
    y = got[2024]
    assert y["revenue"] == pytest.approx(1500 * CR)
    assert y["ebit"] == pytest.approx((260 + 15) * CR)  # PBT + interest
    assert y["ebitda"] == pytest.approx((275 + 50) * CR)
    assert y["tax_rate"] == pytest.approx(0.25)
    assert y["equity"] == pytest.approx(880 * CR)
    assert y["total_debt"] == 0
    assert y["shares"] == pytest.approx(195 * CR / 19.5)
    assert y["ocf"] == pytest.approx(220 * CR)
    # capex = change in fixed assets + CWIP, plus depreciation: (500 - 440) + 50
    assert y["capex"] == pytest.approx(110 * CR) and y["_estimated"] == ["capex"]
    assert "capex" not in got[2022]                    # no earlier year to difference against


def test_screener_lender_layout_has_no_ebit():
    page = PAGE.replace("Operating Profit", "Financing Profit")
    y = SCR.statements(SCR.parse_tables(page))[2024]
    assert "ebit" not in y and y["net_income"] == pytest.approx(195 * CR)


def test_settings_order_off_and_keys(tmp_path):
    assert SS.enabled("statements")[:2] == ["yahoo", "screener"]
    assert "fmp" not in SS.enabled()                   # needs a key
    (tmp_path / ".env").write_text("FMP_API_KEY=abc\n", encoding="utf-8")
    assert "fmp" in SS.enabled("statements") and SS.key("fmp") == "abc"
    SS.save(order=["screener", "yahoo"], off=["bse"])
    assert SS.enabled("statements")[:2] == ["screener", "yahoo"]
    assert "bse" not in SS.enabled("prices")
    with pytest.raises(ValueError):
        SS.save(order=["nope"])
    with pytest.raises(ValueError):
        SS.save(off=["yahoo", "screener", "fmp", "eodhd", "yahoo_bse"])


def _closes(start="2020-03-20", end="2026-05-10"):
    idx = pd.bdate_range(start, end)
    return pd.Series([100.0 + i * 0.01 for i in range(len(idx))], index=idx)


def test_price_chain_falls_through_to_the_first_provider_with_prices(monkeypatch):
    calls = []

    def none(name):
        return lambda t, a, b: calls.append(name) or None

    monkeypatch.setitem(price_chain.FETCH, "yahoo_bse", none("yahoo_bse"))
    monkeypatch.setitem(price_chain.FETCH, "nse", lambda t, a, b: calls.append("nse") or _closes("2026-04-01"))  # too short
    monkeypatch.setitem(price_chain.FETCH, "bse", lambda t, a, b: calls.append("bse") or _closes())
    s, used, problems = price_chain.closes("ALPHA.NS", dt.date(2020, 3, 22), dt.date(2026, 4, 5), skip=("yahoo",))
    assert used == "bse" and calls == ["yahoo_bse", "nse", "bse"] and len(problems) == 2
    assert s.index.is_monotonic_increasing


def _yahoo_year(fy, **vals):
    d = {k: None for k in yf_source.FIELDS}
    d.update({"price": 100.0, "price_bench": 101.0, "price_fwd": 102.0, "_assumed": [], "_diag": {}, "_notes": []})
    d.update(vals)
    return d


def test_hub_fills_missing_and_assumed_fields_and_keeps_overrides(monkeypatch, tmp_path):
    # Yahoo: FY2024 complete but debt only assumed; FY2021 not served at all
    y24 = _yahoo_year(2024, ebit=275 * CR, ebitda=325 * CR, eps=19.5, net_income=195 * CR, da=50 * CR, capex=1.0,
                      ocf=220 * CR, total_debt=0.0, cash=0.0, shares=1e8, tax_rate=0.25, delta_nwc=0.0)
    y24["_assumed"] = ["total_debt"]
    y24["_notes"] = ["total debt not reported; assumed zero (debt-free)"]
    y21 = _yahoo_year(2021)
    y21["_diag"] = {"ebit": ("NO DATA FOR THIS FY", "older than Yahoo serves")}
    monkeypatch.setattr(yf_source, "fetch_company", lambda t, fy, **k: {"ticker": t, "beta": 1.0, "price_source": "Yahoo Finance",
                                                                        "years": {2021: y21, 2024: y24}})
    monkeypatch.setitem(data_hub.STATEMENTS, "screener", lambda t: {
        2021: {"ebit": 150 * CR, "net_income": 110 * CR, "eps": 11.0, "da": 30 * CR, "total_debt": 90 * CR},
        2024: {"total_debt": 5 * CR, "ebit": 999.0}})
    monkeypatch.setitem(data_hub.STATEMENTS, "yahoo_bse", lambda t: {})
    ov = tmp_path / "ov.csv"
    ov.write_text("ticker,fy,ebit\nALPHA.NS,2021,160\n", encoding="utf-8")
    monkeypatch.setattr(config, "OVERRIDE_FILE", ov)
    monkeypatch.setattr(overrides, "_cache", None)

    got = data_hub.fetch_company("ALPHA.NS", [2021, 2024])
    a, b = got["years"][2021], got["years"][2024]
    assert b["ebit"] == 275 * CR                       # Yahoo's reported figure is kept
    assert b["total_debt"] == 5 * CR and "total_debt" not in b["_assumed"]
    assert not any("assumed zero (debt-free)" in n for n in b["_notes"])
    assert a["ebit"] == 160                            # the override sheet beats Screener.in
    assert a["ebitda"] == 160 + 30 * CR and a["eps"] == 11.0 and "ebit" not in a["_diag"]
    assert any(n.startswith("filled from Screener.in") for n in a["_notes"])
    assert a["cash"] == 0.0 and "cash" in a["_assumed"]  # nobody had it: the usual assumption
    assert "Screener.in" in got["sources"]


def test_hub_builds_a_company_when_yahoo_fails(monkeypatch):
    def boom(*a, **k):
        raise ConnectionError("blocked")

    monkeypatch.setattr(yf_source, "fetch_company", boom)
    monkeypatch.setattr(price_chain, "closes", lambda t, a, b, skip=(): (_closes(), "nse", []))
    monkeypatch.setitem(data_hub.STATEMENTS, "screener", lambda t: SCR.statements(SCR.parse_tables(PAGE)))
    monkeypatch.setitem(data_hub.STATEMENTS, "yahoo_bse", lambda t: {})
    got = data_hub.fetch_company("ALPHA.NS", [2023, 2024])
    y = got["years"][2024]
    assert y["ebit"] == pytest.approx(275 * CR) and y["price"] and y["price_bench"]
    assert got["price_source"] == "NSE India" and "Screener.in" in got["sources"]
    assert any("Yahoo Finance unavailable" in n for n in y["_notes"])


def test_hub_skips_a_provider_that_cannot_fill_the_gaps(monkeypatch):
    y = _yahoo_year(2024, ebit=1.0, ebitda=2.0, eps=1.0, net_income=1.0, da=1.0, capex=1.0, ocf=1.0, total_debt=1.0,
                    shares=1.0, tax_rate=0.25, delta_nwc=0.0, revenue=1.0, assets=1.0, equity=1.0)  # only cash and cur_liab missing
    monkeypatch.setattr(yf_source, "fetch_company", lambda t, fy, **k: {"ticker": t, "beta": 1.0, "price_source": "Yahoo Finance", "years": {2024: y}})
    monkeypatch.setitem(data_hub.STATEMENTS, "screener", lambda t: (_ for _ in ()).throw(AssertionError("asked Screener.in for cash")))
    monkeypatch.setitem(data_hub.STATEMENTS, "yahoo_bse", lambda t: {2024: {"cash": 7.0}})
    assert data_hub.fetch_company("ALPHA.NS", [2024])["years"][2024]["cash"] == 7.0


def test_quote_fallback_backs_off(monkeypatch):
    calls = []
    monkeypatch.setattr(price_chain.nse_source, "fetch_last_price", lambda t: calls.append(("nse", t)) or None)
    monkeypatch.setattr(price_chain.bse_source, "fetch_last_price", lambda t: calls.append(("bse", t)) or None)
    monkeypatch.setattr(price_chain, "_quote_miss", {})
    monkeypatch.setattr(price_chain, "_site_fail", {})
    assert price_chain.last_price("ZED.NS") == (None, None)
    assert price_chain.last_price("ZED.NS") == (None, None)       # the same symbol is not asked again at once
    assert len(calls) == 2
    for t in ("A.NS", "B.NS", "C.NS"):
        price_chain.last_price(t)
    n = len(calls)
    price_chain.last_price("D.NS")                                 # both websites failed three times: skipped
    assert len(calls) == n


def test_probe_reports_a_provider_answering(monkeypatch):
    import pandas as pd
    import price_chain

    monkeypatch.setitem(price_chain.FETCH, "nse", lambda t, a, b: pd.Series([1.0, 2.0], index=pd.to_datetime(["2026-01-01", "2026-01-02"])))
    r = price_chain.probe("nse")
    assert r["ok"] and "2 daily prices" in r["detail"]
    monkeypatch.setitem(price_chain.FETCH, "bse", lambda t, a, b: None)
    assert not price_chain.probe("bse")["ok"]
    monkeypatch.setattr(price_chain.source_settings, "has_key", lambda k: False)
    assert "needs a free key" in price_chain.probe("fmp")["detail"]
