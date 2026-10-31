# HYBRID MODEL

The project's headline intrinsic value. The code is in
[`src/hybrid_formula.py`](../src/hybrid_formula.py), the constants are in
`agent_settings.yaml → hybrid_model`, and you can try every constant live in
the web app's **HYBRID MODEL Studio**.

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

## Back-test (latest report: 42 companies in 9 sectors, FY2000–FY2026, 798 scored company-years)

Each value is scored against the closing price nearest 1 May after the
financial year ends. Calibration, peer medians and the learners now draw on the
whole learning pool (553 companies in 23 sectors), not only the report's own
companies. From `output/metrics_overall.csv`, best first:

| Model | Median absolute error | Within ±20% | Rank correlation | Scored |
|---|---:|---:|---:|---:|
| XGBoost | 17.9% | 53.7% | 0.98 | 792 |
| LightGBM | 18.0% | 55.7% | 0.99 | 792 |
| Random Forest | 18.3% | 53.5% | 0.99 | 792 |
| Ensemble | 20.4% | 49.4% | 0.94 | 798 |
| MLP Neural Network | 22.1% | 46.2% | 0.98 | 792 |
| **HYBRID MODEL** | **23.8%** | **43.2%** | **0.90** | 798 |
| P/E Relative | 47.2% | 23.4% | 0.74 | 792 |
| EV/EBITDA | 47.6% | 20.9% | 0.74 | 793 |
| Residual Income | 67.7% | 13.0% | 0.59 | 798 |
| Graham Number | 69.3% | 11.5% | 0.59 | 792 |
| DCF | 105.0% | 10.4% | 0.46 | 747 |

The learners score lower, but their early folds use future years (the
`hybrid` ML split), so their errors look smaller than they would in real
use. The HYBRID MODEL never uses future data. Unlike the learners, it also
explains every rupee: each lens, weight, gate and adjustment is in the
detail file and on the research pages.

## Tuning

Open **HYBRID MODEL Studio**, pick a company or the portfolio, and move any
constant:
- The value, range, lenses and build-up update live.
- The inspector's **sensitivity** ranks the constants by their effect.
- **Portfolio** mode shows every company's value and label under your changes.

Nothing is written until **Commit**, which writes `agent_settings.yaml`
and keeps its comments. After saving, run the
valuation report or the research again to refresh the stored values.
