# The web app

```bash
pip install -r requirements.txt
python run.py --web
```

This opens <http://127.0.0.1:8765>. The server listens on this computer only.
Use `--port 9000` to change the port, or `--no-browser` if you don't want a
tab opened. The built app ships in `web/dist`, so Node is only needed if you
want to change the UI.

The colours are VS Code's **Dark 2026** theme; the layout, type (Inter and JetBrains Mono, bundled) and components are the app's own.

## Layout

An analyst workspace:
- **Side navigation:** grouped into Analysis, Models & data and Operations, with live status for the server, AI providers, last report and last research. Collapse it with `Ctrl+\`.
- **Top bar:** a live market tape (Nifty 50, India VIX, USD/INR, Brent, US 10Y, gold, with 1-month change), global search (`Ctrl+K`), an alerts inbox (red flags and changes), the glossary (`?`), and a run indicator that opens the runs drawer.

| Page | |
|---|---|
| **Command Center** | Metric band; coverage treemap (tile size = market cap, colour = upside); signals feed; upside vs confidence; label mix and extremes; model leaderboard |
| **Markets** | Live index cards (Nifty 50, Sensex, Bank, IT, Midcap 50, Financial Services, VIX) with intraday sparklines and a sector heat strip. A scanner over every company the app knows (about 425): top gainers and losers, most active, volume spikes, near 52-week high or low, RSI extremes, and covered companies below their buy-below price. Candlestick or line charts from 1 day to the full history, with the HYBRID MODEL value and buy-below drawn on the chart. Look up any NSE or BSE symbol |
| **Watchlist** | The companies you track, as tiles or a table: live price, change, intraday sparkline, day range, the HYBRID MODEL re-valued at the live price, and change since you added it. Each company has a live chart (including every minute bar the tracker stored), price alerts and a note. An alerts feed lists level crossings, buy-below crossings and big daily moves |
| **Learning** | How many extra companies train the ML models, how many are cached, the switches for daily feeding and retraining, and a record of every valuation run (training rows, HYBRID MODEL confidence and error), so you can see whether more data helped |
| **Coverage** | Sortable data grid with a column chooser and density toggle, inline range bars and CSV export. Selecting a row opens an inspector; `↑ ↓` move between rows and `Enter` opens the profile |
| **Equity profile** | Sticky figures bar and a section index that follows your scrolling. Sections: summary, valuation (lens contribution, bridge, build-up), drivers and risk, agents and evidence, bull vs bear, history |
| **HYBRID MODEL Studio** | Parameter tree on the left. In the centre, a live canvas with figures, range, bridge and lens contribution. On the right, an inspector with sensitivity, changes and inputs. Named scenario sets, a portfolio mode, and **Commit** to save |
| **Model Performance** | Leaderboard, error by year, win rate, sector × model matrix, company explorer, HYBRID MODEL and Ensemble detail, chart gallery, companies left out, files |
| **Universe** | Editable grid of the company list: bulk select, delete or set sector, CSV import and export, checks |
| **Operations** | New-job form (type, scope, period, options, auto-train) beside a live job detail (stage timeline, auto-train controls, log) and the jobs table |
| **Configuration** | Run settings (everything the old desktop app had), AI providers (key, live model picker, Test for each provider, fail-over order), research agents, macro inputs, the settings file |

Shortcuts:

| Keys | Action |
|---|---|
| `Ctrl+K` | Search |
| `Alt+1`–`9` | Go to a page |
| `Esc` / `Ctrl+Z` | In a chart: cancel the drawing tool / undo the last drawing |
| `Ctrl+\` | Collapse or expand the sidebar |
| `?` | Glossary |
| `↑ ↓` / `Enter` | Move between rows / open one, in grids |

## Charts

Every price chart (Markets, and each company in the Watchlist) is built on
TradingView's Lightweight Charts:

- **Chart types:** candles, hollow candles, Heikin-Ashi, bars (OHLC), line,
  area, and baseline (green above the previous close, red below).
- **ƒx Indicators**, each listed with its formula: volume, SMA 20/50/200,
  EMA 9/21, Bollinger Bands (20, 2) and VWAP (intraday) on the price; RSI 14
  and MACD (12, 26, 9) in their own panes underneath, each with its own scale
  and kept in step with the price chart.
- **Drawing tools** (left toolbar): trend line, ray, horizontal and vertical
  lines, rectangle, Fibonacci retracement, measure (change, % and bars), notes
  and an eraser, with a magnet that snaps to open, high, low or close.
  Drawings are saved per company in your browser. `Ctrl+Z` undoes, `Esc`
  cancels.
- **Hover:** a legend with OHLC, change, volume and indicator values, and a
  floating panel next to the cursor.
- **Right-click:** add a line or note at that price, set a price alert (for
  tracked companies), copy the price, delete a drawing, reset the view, switch
  between regular, logarithmic and percent scales, save the chart as an image,
  or go fullscreen.
- The HYBRID MODEL value, buy-below price, previous close and your alert
  levels are drawn as labelled lines.

## Light and dark

The sun and moon button at the left of the top-right toolbar switches between
VS Code's **Dark 2026** and **Light 2026** palettes. The new theme spreads
out in a circle from the button. The choice is remembered by the browser.

## Live market data

Prices come from Yahoo Finance. NSE quotes there can lag the exchange by up
to 15 minutes, and the app says so on every chart.

- **The tracker** runs inside `python run.py --web`. While the market is open
  (09:15–15:30 IST, Monday to Friday) it polls the watchlist every 30 seconds;
  otherwise every 15 minutes. Both are adjustable under **Watchlist →
  Tracking**. It stores every minute bar in `data/live/market.db`, so a tracked
  company builds up an intraday history longer than Yahoo's 7-day window.
  Exchange holidays are not known; a price that stops moving for 20 minutes
  is marked.
- **Alerts** fire once per session when a price crosses a level you set, falls
  below the HYBRID MODEL buy-below price, or moves more than 5% in a day.
  They appear in the Watchlist and in the bell.
- **Live re-valuation.** The HYBRID MODEL value comes from a company's
  accounts, so it does not move with the price. Only the upside, the label
  and the buy-below test are recomputed at the live price.
- **The tracker only runs while the web app is running.** To track with the
  computer off, the GitHub Actions workflow in [AGENTS.md](AGENTS.md) runs
  quick sweeps at fixed times instead.

Everything live (watchlist, alerts, minute bars, learning history) is stored in
`data/live/`, which git ignores.

## Learning data

The ML models (XGBoost, Random Forest, LightGBM, MLP) learn from one row per
company per financial year: that year's accounts, and how the price moved
over the next year. A live price on its own is not a training example, so
the tracker's prices are used to value at today's price, not to train.

What grows the training set is more companies. The **learning set** is every
company the app knows beyond the ones you value: `data/training_universe.csv`,
the auto-trainer's picks and the watchlist (383 companies at the time of
writing).

- `python run.py --learn` (or **Learning → Fetch now**) downloads and caches
  their accounts for your report's year window. A cached company is reused
  for 7 days.
- While **Train on all learning companies** is on, every valuation run started
  from the web app adds `--train-universe data/live/learning_universe.csv`.
- With the daily feed on, the app fetches new and stale companies after
  16:15 IST each day when no other job is running, and can retrain afterwards.
- After every valuation run, the Learning page records the training rows, the
  HYBRID MODEL's mean confidence and its median error. More data raises
  confidence only if it makes the lenses agree and calibrate better; this
  record shows whether it did. Yahoo serves about four years of accounts per
  company, so most add 2–3 labelled rows.

## AI models

Providers retire models often. In September 2026, Groq dropped the Llama 3.x
models and NVIDIA ended `meta/llama-3.*-instruct`, which is why none of the
original defaults worked. So:

- The model list comes **live from each provider**, filtered to models that
  can chat.
- **Test** sends a small JSON task and shows the provider's exact reply or
  error. For example: "reached its end of life", or "Function not found for
  account" (NVIDIA lists some models that a free key cannot call).
- A saved model that is no longer offered is flagged.

## Why it doesn't break

- **Runs are separate processes.** Every run is a child `python run.py …`
  process, and only one runs at a time.
- **Run inputs are checked.** The server validates every run option before
  passing it on as a command-line flag.
- **The Studio's what-ifs are safe.** They are pure in-process
  calculations and write nothing until you press Commit.
- **Errors stay contained.** Every page has its own error boundary and
  loading, error and empty states.
- **Losing the server is handled.** If it stops, a banner says so and the app
  reconnects by itself.

## Changing the UI

```bash
cd web
npm install
npm run dev     # http://localhost:5173 with hot reload; run 'python run.py --web --no-browser' alongside
npm run build   # rewrites web/dist, which 'python run.py --web' serves
```

The stack is React 18, TypeScript, Vite, TanStack Query, React Router,
Recharts and VS Code's Codicons.
