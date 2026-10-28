# HYBRID MODEL

The project's headline intrinsic value. The code is in
[`src/hybrid_formula.py`](../src/hybrid_formula.py), the constants are in
`agent_settings.yaml → hybrid_model`, and you can try every constant live in
the web app's **Hybrid Lab**.

## Where it runs

| Where | Inputs | Signals |
|---|---|---|
| **Valuation report** (`python run.py`) | Every company, every financial year | From the company's own accounts, using only years up to the one being valued |
| **Research runs** (`python run.py --agents`) | Each company's latest year, at today's price | The 23 agents' readings, with the accounts filling any gaps |

Because it runs in the report, the HYBRID MODEL is back-tested and scored
against the 1-May price like every other model. Its numbers are in the
accuracy tables and in `output/Hybrid_Model_Detail.csv`.

## The formula, step by step

1. **Cost of equity.** `k = max(Rf + β_adj × ERP, floor) + Σ premia`.
   - The premia are size (market-cap bands), leverage (debt/equity), and five
     agent risks scaled by caps: liquidity, governance, forensic, macro,
     geopolitical, plus earnings volatility.
   - The premia are capped in total.
2. **Growth.** `g = g_base + Σ tilts`, where the tilts come from industry,
   earnings momentum, news and macro. Long-run growth `g_T` is the smallest of:
   the terminal setting, nominal GDP, and `k` minus the minimum spread.
3. **Six lenses.** Each lens answers a different question:

   | Lens | Question | Method |
   |---|---|---|
   | Cash flow | What will the business pay out? | Three-stage FCFF DCF at `k` and `g`. The starting cash flow blends observed FCFF with `NOPAT × (1 − g/RONIC)`, where `RONIC = WACC + 2% + 4% × moat`. Lenders use residual income instead. |
   | Earnings power | What is it worth if it never grows? | Normalised NOPAT ÷ WACC, plus cash, minus debt |
   | Asset | What is the balance sheet worth? | Book value × justified P/B, `(ROE − g_T)/(k − g_T)` |
   | Market | What do peers pay? | Peer-regression P/E and EV/EBITDA |
   | Conservative | What would a defensive buyer pay? | Graham Number |
   | Learning | What has the market paid for similar profiles? | Consensus of the machine-learning models |

4. **Growth-credibility gate.** Growth is only paid for when the moat earns it.
   - The growth share is `1 − earnings power / cash flow`.
   - The allowed share is `base + moat_bonus × max(0, moat)`.
   - Above the allowed share, the cash-flow lens is cut back to
     `earnings power / (1 − allowed share)`.
5. **Calibration.** This step is point-in-time: a year never learns from
   itself.
   - Each lens is shifted by its own median miss against the 1-May price in
     **earlier** years. The sector's history is used when it has enough
     observations, otherwise the whole panel's. The shift is shrunk by
     `n/(n + shrink_k)`.
   - Each lens's weight is scaled by its relative accuracy over those years.
6. **Blend.**
   - Each lens's weight = its weight for the company's type (mature, lender,
     loss-maker or young) × its calibrated skill × an estimate penalty.
   - Lenses more than `outlier_ratio` away from the weighted median are
     dropped.
   - `V_core` is the weighted geometric mean of the remaining lenses.
7. **Quality and governance.** `V = V_core × Q × (1 − H)`.
   - `Q` adds up moat, earnings quality, financial strength and capital
     allocation, and is clamped.
   - `H` is a haircut per red flag, capped.
8. **Scenarios.** Steps 1–7 run again with bull and bear shifts to `g`, `k`
   and `Q`. Bull and bear conviction tilt the probabilities.
   **HYBRID MODEL value = Σ p × V.**
9. **Uncertainty.**
   - `σ = √(lens dispersion² + base σ²)`.
   - Range (P10–P90) = `value × e^(∓1.2816σ)`.
   - Confidence = the chance the price lands within ±20% of the value,
     scaled by the share of lenses that produced a value. After a research
     run, it is blended with evidence coverage, validation and agreement.
10. **Margin of safety and label.**
    - `MOS = base + low-confidence add-on + per red flag`, capped.
    - Buy-below = `value × (1 − MOS)`.
    - The label comes from price ÷ value. It is a description, not a
      recommendation.

## Back-test (43 companies, FY2021–FY2025, 211 scored company-years)

| Model | Median absolute error | Within ±20% | Median bias |
|---|---:|---:|---:|
| HYBRID MODEL, before calibration | 49.5% | 21.8% | −20% |
| **HYBRID MODEL, with calibration** | **33.4%** | **33.2%** | **−8%** |
| Ensemble | 31.1% | 33.2% | −9% |
| LightGBM | 24.1% | 41.7% | +16% |

The learners score lower, but their early folds use future years (the
`hybrid` ML split), so their errors look smaller than they would in real
use. The HYBRID MODEL never uses future data. Unlike the learners, it also
explains every rupee: each lens, weight, gate and adjustment is in the
detail file and on the research pages.

## Tuning

Open **Hybrid Lab**, pick a company or **All companies**, and move any
constant:
- The value, range, lenses and build-up update live.
- **What moves this value** ranks the constants by their effect.
- **All companies** shows every company's value and label under your changes.

Nothing is written until **Save as model defaults**, which writes
`agent_settings.yaml` and keeps its comments. After saving, run the
valuation report or the research again to refresh the stored values.
