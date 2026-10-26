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
- **Top bar:** a live market tape (Nifty 50, India VIX, USD/INR, Brent, US 10Y, gold, with 1-month change), the watchlist focus picker, global search (`Ctrl+K`), an alerts inbox (red flags and changes), the glossary (`?`), and a run indicator that opens the runs drawer.

| Page | |
|---|---|
| **Command Center** | Metric band; coverage treemap (tile size = market cap, colour = upside); signals feed; upside vs confidence; label mix and extremes; model leaderboard |
| **Markets** | Live index cards (Nifty 50, Sensex, Bank, IT, Midcap 50, Financial Services, VIX) with intraday sparklines and a sector heat strip. A scanner over every company the app knows (about 425): top gainers and losers, most active, volume spikes, near 52-week high or low, RSI extremes, and covered companies below their buy-below price. Candlestick or line charts from 1 day to the full history, with the HYBRID MODEL value and buy-below drawn on the chart. Look up any NSE or BSE symbol |
| **Watchlists** | A library of named lists, each with a description and colour, shown as cards with their companies and today's moves. Create (empty, from your coverage, from a sector or as a copy), edit, reorder, pin, duplicate, delete, focus the app on a list, or start research on its covered companies. A company can be on several lists; up to 100 companies are tracked across all of them |
| **A watchlist** | The companies on one list, as tiles or a table: live price, change, intraday sparkline, day range, the HYBRID MODEL re-valued at the live price, and change since you added it. Each company has a live chart (including every minute bar the tracker stored), price alerts and a note. An alerts feed lists level crossings, buy-below crossings and big daily moves |
| **Research workforce** | Overview of the 23 agents: run status, every team and agent with live status, this run's verdicts and red flags, recent runs, and each agent's profile and settings |
| **Agent Network** | The agents as a full-screen live map: info-bits travel the edges as they exchange work; replay any run; layers, views and tools to simplify, focus, annotate and rearrange the map |
| **Research Room** | The agents' chat: team channels, direct exchanges, live status. Talk to any agent: it answers, keeps your instructions and acts on requests |
| **Learning** | How many extra companies train the ML models, how many are cached, the switches for daily feeding and retraining, and a record of every valuation run (training rows, HYBRID MODEL confidence and error), so you can see whether more data helped |
| **Coverage** | Sortable data grid with a column chooser and density toggle, inline range bars and CSV export. Selecting a row opens an inspector; `↑ ↓` move between rows and `Enter` opens the profile |
| **Equity profile** | Sticky figures bar and a section index that follows your scrolling. Sections: summary, valuation (lens contribution, bridge, build-up), model forecasts, drivers and risk, agents and evidence, bull vs bear, history |
| **HYBRID MODEL Studio** | Parameter tree on the left. In the centre, a live canvas with figures, range, bridge and lens contribution. On the right, an inspector with sensitivity, changes and inputs. Named scenario sets, a portfolio mode, and **Commit** to save. **Discard** drops uncommitted edits; **Defaults** loads the shipped value (`agent_settings.defaults.yaml`) of every constant you changed, to review and commit. The page scrolls as a whole while the parameter list and inspector stay in view |
| **Model Performance** | Leaderboard, error by year, win rate, sector × model matrix, company explorer, HYBRID MODEL and Ensemble detail, chart gallery, companies left out, files |
| **Universe** | Editable grid of the company list: bulk select, delete, set sector or add to a watchlist, CSV import, export, checks |
| **Operations** | New-job form (type, scope, period, options, auto-train) beside a live job detail (stage timeline, auto-train controls, log) and the jobs table |
| **Configuration** | Run settings (everything the old desktop app had), AI providers (any OpenAI-compatible service or Anthropic, several keys each, live model picker, Test for each key, fail-over order), research agents, macro inputs, the settings file |

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

## Notifications

The bell collects live price alerts (from the Watchlist tracker) and research
alerts (red flags and changes from the latest research run), in All, Live
prices and Research tabs.

- **Delete:** the × on a row deletes a live alert, or hides a research alert in
  this browser. **Clear all** empties the current tab.
- **On / off:** the switch in the panel turns the badge, sounds and pop-ups
  off. Alerts are still recorded.
- **Sounds:** short, quiet synthesised cues: Glass, Rise, Fall, Pulse, Bloom,
  Chord, Low, Tick, Marimba or silent. Eight events each have their own cue,
  volume and on/off switch: below buy-below, fell to your alert, rose to your
  alert, big daily move, run finished, run failed, an agent replies, and
  interface clicks. There is a master volume and optional quiet hours (they can
  cross midnight). Settings are in the panel (gear) and in **Configuration →
  Notifications & sounds**. Browsers only play sound after you have clicked
  somewhere on the page.
- **Desktop pop-ups** (optional) appear when the tab is in the background.

## Research workforce

The 23 research agents (see [AGENTS.md](AGENTS.md) for who is who) have three pages.

The workforce **starts working as soon as the web app starts** (a quick,
rule-based sweep that makes no LLM calls). The **Workforce** button controls
this and starts a run on demand.

- **Overview** (`/agents`): the run at a glance (companies done, who is working,
  messages, calls saved, LLM calls), a card per team listing every agent with its
  live status, this run's verdicts and red flags, and the recent runs (click one
  to replay it). Click an agent for its profile; the gear opens its **settings**.
- **Agent Network:** the agents as a live map that fills the page.
  - **Around the map, never over it:** a top bar (run, search, Views, Layers,
    Workforce, export, shortcuts, inspector), a tool rail on the left, the
    inspector docked on the right (`I` hides it) and the replay bar along the bottom.
  - **Simple by default:** compact cards, only the main connections, no captions
    or score pop-ups. **Layers** switches on what you need: full cards, the
    orchestrator, data sources, outputs, team bands, each kind of connection,
    edge captions, info-bits (and which kinds), score pop-ups, the mini-map, and
    your annotations. Hide or show whole teams; hidden nodes are listed there to
    bring back. With analysts off the map shows leads only and their traffic goes
    to the lead.
  - **Arrangements:** *Hierarchy* (sources → teams → chief → outputs) or
    *Radial* (the chief in the middle, leads around it, analysts fanned outside).
    Dragged positions are remembered per arrangement.
  - **Views:** built-in presets (Simple, Leads only, Data flow, Everything,
    Radial) and your own saved views.
  - **Tools** (left rail): Select & move `V`, Pan `H`, Link `K` (drag between
    two nodes to draw your own connection, with a caption), Note `N` (pin a
    note), Focus `G` (show one node and its connections only) and Hide / delete
    `X`. `Shift`+drag pans with any tool; `Esc` clears everything.
  - **Changes that reach the agents:** right-click an analyst to leave it out of
    research runs (or bring it back), or open its **Settings**. Links and notes
    are your own annotations and stay in this browser.
  - **Motion:** info-bits travel the edges in the colour of what they carry;
    senders recoil and receivers are knocked; busy agents glow; counters bump.
    Live during a run; afterwards any run replays with a scrubber and speed control.
  - **Light theme:** a pale canvas with team colours inked darker, so nodes,
    edges and captions keep their contrast.
- **Research Room:** the agents' chat.
  - **Sidebar:** team channels, direct exchanges, the data trace, and every
    agent (grouped by team, folded until you open a team).
  - **Messages:** findings show score, confidence, signals and evidence links;
    team reports show how many findings they combine; verdicts show value
    against price. Hover a message for **Reply**, **Details**, **Copy** and a
    company filter.
  - **Talking to agents:** DM an agent, @mention up to three, or write in a
    channel (its lead answers). Agents answer in character - with an AI model
    when one is set up, grounded in their latest research - keep your
    instructions ("focus on debt", "be more cautious") for the next run, and act
    on requests ("re-check HAL"). "… is typing" shows until the reply lands.
    See [AGENTS.md](AGENTS.md#talking-to-the-agents) for the commands.

### Agent settings

Each agent (Overview, Network inspector, Research Room → agent → **Settings**)
has: on/off in runs (analysts only), weight in its team report (x0–3), stance
(cautious x0.75, balanced, bold x1.25 on its scores), AI model (auto, fast,
smart or off), a confidence floor below which its findings are ignored, whether
it re-runs in quick sweeps, and standing instructions added to every AI prompt
it sends. **Defaults** puts an agent back. Settings are stored in
`agent_profiles.json` next to the blackboard and apply from the next run.

## Export

Every titled panel, every page header, every data grid, each price chart, the
agent graph, the chat and the notifications panel has an **Export** menu that
offers only the formats that suit what it holds:

| What | Formats |
|---|---|
| Data (grids, lists, tables) | Excel (XLSX), CSV, Word (DOCX), Markdown, PDF |
| A chart, graph or panel | PNG, PDF, Word |
| A whole page | PDF, Word |

Choosing a format opens a short editor with a preview before anything is
saved: title, note and file name; for data, the columns, a row limit, sheet
name, frozen header and filter (Excel), separator (CSV), page size,
orientation, text size and striped rows (PDF and Word); for pictures, screen
or light colours, sharpness, margin and a title band. Lists become real text
tables across as many pages as needed; charts and panels become images
exactly as they look.

## Watchlist focus

The picker in the top bar focuses the app on one watchlist. Coverage, the
Command Center, Universe (display only: saving still writes the whole list),
Model Performance (its tables recomputed for the list's companies), the
workforce overview and the Research Room then show only that list's
companies, with a thin bar naming the list and a **Show all** button. The
choice is remembered in this browser; **All companies** brings everything
back exactly as before.

## Model forecasts

Each company profile shows every model's predicted price over days, months
and years, and a table at 1 week, 1 month, 1 quarter, 6 months, 1, 3 and 5
years. Each path starts at today's price and closes the gap to the model's
value as fast as the market has historically followed that model — the share
of the gap closed in a year is fitted on every company-year pair in the
valuation report — while the value grows at the company's long-run rate.
Hovering a price shows its range (one historical spread either side).

**Conviction** (0–100) is how strongly a model believes its prediction: how
well its gaps foretold the next year's move (35%), its hit rate within ±20%
(25%), how steady its view of this company has been (20%) and how close it
sits to the other models (20%). These are projections from history, not
advice.

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
- **Any provider.** Add one from 16 presets (Groq, Gemini, NVIDIA, Anthropic,
  OpenAI, OpenRouter, Mistral, DeepSeek, Together, Fireworks, Cerebras, xAI,
  Perplexity, Azure OpenAI, Ollama, LM Studio) or as a custom
  OpenAI-compatible endpoint. Edit its address, key header, limits and models,
  switch it off, or remove it. Web-app providers are saved in
  `llm_providers.json` on top of `agent_settings.yaml`.
- **Several keys per provider**, stored in `.env` as `NAME`, `NAME_2`, ….
  They are tried in order: a rate-limited key hands over to the next, a
  rejected key is skipped for the rest of the run. Test, reorder or remove
  each key; only the last four characters are ever shown.

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
