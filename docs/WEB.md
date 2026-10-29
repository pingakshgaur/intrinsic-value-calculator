# The web app

```bash
pip install -r requirements.txt
python run.py --web
```

This opens <http://127.0.0.1:8765>. The server listens on this computer only.
Use `--port 9000` to change the port, or `--no-browser` if you don't want a
tab opened. The built app ships in `web/dist`, so Node is only needed if you
want to change the UI.

Other ways to open it: on Windows, double-click `Launch Workbench.bat` or the
`INTVAL Workbench` shortcut in the project folder; with an installed copy (see
the README's *Installers*), use the INTVAL desktop or menu shortcut. Starting
it a second time just opens the browser on the running app.

The colours are VS Code's **Dark 2026** theme; the layout, type (Inter and JetBrains Mono, bundled) and components are the app's own.

## Layout

An analyst workspace:
- **Side navigation:** grouped into Analysis, Research workforce and Operations (jobs, Model Performance, Configuration), with live status for the server, AI providers, last report and last research. Collapse it with `Ctrl+\`.
- **Top bar:** a live market tape (Nifty 50, India VIX, USD/INR, Brent, US 10Y, gold, with 1-month change), the watchlist focus picker, global search (`Ctrl+K`), an alerts inbox (red flags and changes), the glossary (`?`), and a run indicator that opens the runs drawer.

- **Menus and dropdowns** are one component everywhere (`web/src/components/Select.tsx`). Every choice, from sectors and companies to runs, models and sounds, opens the same themed list. Use the arrow keys, Home/End, Enter and Escape, or type to jump. Lists longer than 12 get a filter box. Action buttons such as *Copy to*, *Move to*, *Research*, *Set sector* and *Add to watchlist* open the same menu. Menus open on the page's top layer, so a table or panel never cuts them off, and they flip upward near the bottom of the window. Escape closes only the topmost menu.

| Page | |
|---|---|
| **Command Center** | Metric band; coverage treemap (tile size = market cap, colour = upside); signals feed; upside vs confidence; label mix and extremes; model leaderboard |
| **Markets** | A **research radar**, refreshed with every price update: companies trading under their HYBRID MODEL buy-below price, the biggest gaps to value, the live forecast's lean for today (tracked companies) and today's unusual moves (volume spikes, moves over 4%, alerts that fired); click one to chart it. A scanner over every company the app knows (about 425): top gainers and losers, most active, volume spikes, near 52-week high or low, RSI extremes, and covered companies below their buy-below price. Candlestick or line charts from 1 day to the full history, with the HYBRID MODEL value and buy-below drawn on the chart. Look up any NSE or BSE symbol |
| **Watchlists** | A library of named lists, each with a description and colour, shown as cards with their companies and today's moves. Pin, duplicate, delete or focus the app on a list. A company can be on several lists; up to 600 companies are tracked across all of them (room for the NIFTY 500) |
| **Adding companies** | When you create a list, and later with **Add companies**, there are five ways in: **Search** by name or NSE/BSE symbol (a symbol the app has not seen is fine) — or an index name: `NIFTY50`, `nifty 500`, `Bank Nifty`, `Large cap`, `Mid cap` offer to add every company in it, **Indices** (NIFTY 50, Next 50, 100, 200, 500, Total Market, SENSEX; large, mid, small and micro cap by SEBI's split; the NSE sector indices — from NSE's published lists, cached for a week; offline, NIFTY 50 and SENSEX fall back to a bundled list and the size classes to the companies the app knows with that size), **Sectors** (tick one or several and take all of their companies, or pick a few; **Get NSE lists** adds NSE's index lists of about 1,000 companies with their industry), **Spreadsheet** (Excel `.xlsx`, CSV or pasted text with a symbol or name column; unrecognised names are listed) and **Another list**. Picks collect at the bottom until you add them |
| **A watchlist** | The companies on one list, as tiles or a table, with a **search box** (name, symbol, sector or label) and a checkbox each: tick several (Shift+click for a range) to remove them, or copy or move them to another list. The header has three buttons: **Add companies**, **Research this list** and **More** (edit name and colour, focus the app, update prices, pause tracking, tracking settings). The list shows live price, change, intraday sparkline, day range, the HYBRID MODEL re-valued at the live price, its confidence, the research score, red flags and change since you added it. Clicking a company opens a side panel: live chart, its research in brief, the next hours and days, price alerts and a note. **Full analysis** (or double-click, or `Enter` in the table) opens its page. An alerts feed lists level crossings, buy-below crossings and big daily moves |
| **Research workforce** | Overview of the 23 agents: run status, every team and agent with live status, this run's verdicts and red flags, recent runs, and each agent's profile and settings. **Research** starts a run on every covered company or on any watchlist; **Auto-start** sets whether the workforce starts by itself |
| **Agent Network** | The agents as a full-screen live map: info-bits travel the edges as they exchange work; replay any run; layers, views and tools to simplify, focus, annotate and rearrange the map; **Research** on any watchlist from the top bar |
| **Research Room** | The agents' chat: team channels, direct exchanges, live status. Talk to any agent: it answers, keeps your instructions and acts on requests |
| **Company analysis** | `/watchlist/<list>/<symbol>` (or `/company/<name>` from anywhere else; the old `/coverage/…` links still work). Sticky figures bar (live price when tracked), previous / next through the list (`Alt+↑ ↓`) and a section index that follows your scrolling. Sections: **live** (a full-width chart with the price alerts under it, then the **live forecast**; your note is a button under the figures bar that opens as a floating panel), summary (opening with **In plain words**: a short, jargon-free reading of whether the share looks cheap, how sure the models are, what could go right or wrong and what the models expect in a year), valuation (lens contribution, bridge, build-up), model forecasts (**Show all** / **Remove all** lines at the panel's right edge), drivers and risk, agents and evidence, bull vs bear, history. Tables wider than their panel scroll sideways |
| **HYBRID MODEL Studio** | Parameter tree on the left. In the centre, a live canvas with figures, range, bridge and lens contribution. On the right, an inspector with sensitivity, changes and inputs. Named scenario sets, a portfolio mode, and **Commit** to save. **Discard** drops uncommitted edits; **Defaults** loads the shipped value (`agent_settings.defaults.yaml`) of every constant you changed, to review and commit. The page scrolls as a whole while the parameter list and inspector stay in view |
| **Model Performance** | Five tabs. **Leaderboard**: every model's error, hit rate, bias and rank correlation, error by year, win rate. **Sectors**: which model suits each sector (best model, its error, the runner-up, the HYBRID MODEL), sectors won by each model, the sector × model error matrix with the best outlined, the **sector valuation forecast by model** (each model's median value against today's price, or its one-year projection), and **sector segregation and prediction** (companies below, near and above value per sector, the top pick, and a chart of each sector's upside and projection; click a sector for its companies). **Company**: every model by year for one company, HYBRID MODEL detail, Ensemble detail. **Training data**: see below. **Files & charts**: downloads, companies left out, chart gallery — a chart opens in a full-window viewer with previous / next (buttons, `← →`), a thumbnail strip, zoom (`+ −`, double-click, the wheel) with drag to pan, open in a new tab and download. A model in the leaderboard opens to its breakdown: error by year, sectors won, where it is most and least accurate |
| **Operations** | **New job** across the top: what to run (valuation report, research, refresh training data, data check), then one row with the companies (every covered company or a watchlist), the depth or the years, the one option that applies, **Advanced** (auto-train, rule-based research, offline test data) and **Start**. Below it, full width, the live job detail (stage timeline, auto-train controls, log), and under that the recent jobs |
| **Configuration** | Run settings (everything the old desktop app had), **data sources** (switch each provider on or off, set the order they are trusted in, enter free keys), AI providers (any OpenAI-compatible service or Anthropic, several keys each, live model picker, Test for each key, fail-over order), local models through Ollama (download, choose, switch on or off, open with INTVAL), research agents, macro inputs, the settings file |

Shortcuts:

| Keys | Action |
|---|---|
| `Ctrl+K` | Search |
| `Alt+1`–`9` | Go to a page |
| `Esc` / `Ctrl+Z` | In a chart: cancel the drawing tool / undo the last drawing |
| `Ctrl+\` | Collapse or expand the sidebar |
| `?` | Glossary |
| `↑ ↓` / `Enter` | Move between rows / open one, in grids |

## Onboarding

Search **onboarding** (or *tour*, *welcome*, *guide*) in the top-bar search,
or use the link at the top of the glossary, to start a guided tour of the
whole workbench. It opens on a welcome page with nine chapters: finding your
way, the Command Center, markets and watchlists, company analysis, the Studio, the research workforce, models and data, operations and
settings, and power tips. Start from the beginning or jump into any chapter;
each chapter is also its own search result.

The tour opens each page for you, then a spotlight glides to the part it is
describing, with a card beside it explaining what it does and, often,
something to try. The page stays usable underneath. `←` `→` or `Enter` move,
`Esc` leaves, and the coloured bar on the card jumps between chapters. Your
place is remembered in this browser, so search offers **Resume onboarding**.
A part that is missing or hidden at the current window size is explained on
the card instead of being skipped silently.

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
rule-based sweep that makes no LLM calls). **Auto-start** on the Overview
controls this. **Research** (on the Overview, the Agent Network, the Command
Center and each watchlist) starts a run on demand: pick every covered company or any
watchlist, a quick sweep or full research, and start. A watchlist run
researches every company on the list, valued before or not; the list you last
used, or the one the app is focused on, is preselected.

- **Overview** (`/agents`): the run at a glance (companies done, who is working,
  messages, calls saved, LLM calls), a card per team listing every agent with its
  live status, this run's verdicts and red flags, and the recent runs (click one
  to replay it). Click an agent for its profile; the gear opens its **settings**.
- **Agent Network:** the agents as a live map that fills the page.
  - **Around the map, never over it:** a top bar (run, search, Views, Layers,
    Research, export, shortcuts, inspector), a tool rail on the left, the
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
    note; also right-click the map → **Add a note here**), Focus `G` (show one
    node and its connections only) and Hide / delete `X`. `Shift`+drag pans
    with any tool; `Esc` clears everything.
  - **Notes:** a card with a drag handle, five colours, edit and delete
    buttons and the time it was last changed. While writing, a counter and
    **Done** sit under the text; `Ctrl+Enter` or `Esc` finishes, and an empty
    note is thrown away.
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
agent graph, the chat and the notifications panel has a **download** button
whose menu offers only the formats that suit what it holds:

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

The picker in the top bar focuses the app on one watchlist. The Command
Center, Model Performance (its tables recomputed for the list's companies), the
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
to 15 minutes, and the app says so on every chart. When Yahoo has no quote
for a tracked company, the tracker asks the NSE and then the BSE website
(Configuration → Data sources).

- **The tracker** runs inside `python run.py --web`. While the market is open
  (09:15–15:30 IST, Monday to Friday) it polls the watchlist every 30 seconds;
  otherwise every 15 minutes. Both are adjustable under a watchlist's **More →
  Tracking settings**. It stores every minute bar in `data/live/market.db`, so a tracked
  company builds up an intraday history longer than Yahoo's 7-day window.
  Exchange holidays are not known; a price that stops moving for 20 minutes
  is marked.
- **Alerts** fire once per session when a price crosses a level you set, falls
  below the HYBRID MODEL buy-below price, or moves more than 5% in a day.
  They appear in the Watchlist and in the bell.
- **Live re-valuation.** The HYBRID MODEL value comes from a company's
  accounts, so it does not move with the price. Only the upside, the label
  and the buy-below test are recomputed at the live price.
- **When no provider answers**, the watchlist, the charts and the forecasts
  fall back to the last prices the tracker stored, marked as stale, so the
  workbench keeps working on what it knows.
- **The tracker only runs while the web app is running.** To track with the
  computer off, the GitHub Actions workflow in [AGENTS.md](AGENTS.md) runs
  quick sweeps at fixed times instead.

Everything live (watchlist, alerts, minute bars, learning history) is stored in
`data/live/`, which git ignores.

## Live forecasts

Every company page (and, in brief, a watchlist's side panel) shows where the
price may be in **15 minutes, 1 hour, 1 day, 1 week, 1, 3 and 6 months, 1, 3
and 5 years**: a median price, a band that holds 8 in 10 outcomes, the chance
it ends higher, and the main driver. It is computed on request in well under a
second by `server/forecast_live.py` (`GET /api/live/forecast?ticker=`), and
recomputed with every tracker poll while the market is open.

| Part | What it is |
|---|---|
| Band | Lognormal, from the stock's own volatility: recent (EWMA) for short horizons, blending into long-run for long ones; intraday from its stored minute bars |
| Drift | The market's long-run return, 11% a year |
| Recent moves | A small reversal or follow-through of the latest 15-minute and daily moves, fitted (AR(1)) to its own history, shrunk and capped |
| 3-month trend | A shrunk 3-month momentum, fading beyond three months |
| Pull to value | From months out, the gap to the HYBRID MODEL value closes at a half-life of about 1.7 years, weighted by the model's confidence |

The same rules are re-run walk-forward on the stock's own last year to show
how often the 1-day (and, with enough stored minute bars, 15-minute)
direction was right and how often the 1-day band held the outcome. The first
forecast for a company uses the prices already stored and downloads five
years of daily prices in the background for the next one. The Markets radar
uses a lighter version (`/api/live/forecast/quick`) for every tracked company
at once. A statistical projection, not advice: it cannot see news, results
or the order book.

## Training data (Model Performance → Training data)

The ML models (XGBoost, Random Forest, LightGBM, MLP) learn from one row per
company per financial year: that year's accounts, and how the price moved
over the next year. A live price on its own is not a training example, so
the tracker's prices are used to value at today's price, not to train.

What grows the training set is more companies. The **learning set** is every
company the app knows beyond the ones you value: `data/training_universe.csv`,
the auto-trainer's picks and the watchlist (383 companies at the time of
writing).

The tab says three things in plain words: how many companies the models learn
from, how many are ready to use, and whether learning from more of them has
made the HYBRID MODEL more accurate.

- `python run.py --learn` (or **Refresh now**, or Operations → Refresh training
  data) downloads and caches their accounts for your report's year window. A
  cached company is reused for 7 days.
- While **Learn from all of these companies in every valuation run** is on,
  every valuation run started from the web app adds
  `--train-universe data/live/learning_universe.csv`.
- With **Refresh their data every evening** on, the app fetches new and stale
  companies after 16:15 IST each day when no other job is running, and with
  **Retrain the models after each refresh** it retrains afterwards.
- After every valuation run the app records the training rows and the HYBRID
  MODEL's typical (median) error; **Accuracy over time** charts it against the
  number of companies learned from. More data helps only if it makes the
  lenses agree and calibrate better; this chart shows whether it did. With
  Screener.in on, older years now come with the accounts, so each company adds
  more labelled rows than the 2-3 Yahoo alone allowed.
- `/learning` from earlier versions opens this tab.

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
- **Any provider.** Add one from 15 presets (Groq, Gemini, NVIDIA, Anthropic,
  OpenAI, OpenRouter, Mistral, DeepSeek, Together, Fireworks, Cerebras, xAI,
  Perplexity, Azure OpenAI, LM Studio; Ollama has its own section below) or as a custom
  OpenAI-compatible endpoint. Edit its address, key header, limits and models,
  switch it off, or remove it. Web-app providers are saved in
  `llm_providers.json` on top of `agent_settings.yaml`.
- **Several keys per provider**, stored in `.env` as `NAME`, `NAME_2`, ….
  They are tried in order: a rate-limited key hands over to the next, a
  rejected key is skipped for the rest of the run. Test, reorder or remove
  each key; only the last four characters are ever shown.
- **Local models (Ollama)**, in their own section: Configuration → Local AI (Ollama)
  ([`server/ollama_api.py`](../server/ollama_api.py)):
  - Shows whether Ollama is installed and running, the models already on
    this computer, and the free disk space where Ollama keeps them.
  - **Download** any of 18 free models, filtered by how much storage you can
    spare (≤ 1, 2, 5, 10 GB), or any other tag from the Ollama library. Live
    progress, and models that would not fit on the disk are disabled. Delete a
    model to free its space.
  - Pick the **fast** and **smart** model and press **Test** on any of them.
  - **On / Off** switches the `ollama` provider for the agents. **Try local
    models before cloud providers** puts it first in the fail-over order;
    otherwise it is the fallback when the cloud keys run out.
  - **Open Ollama whenever INTVAL starts** (on by default) launches Ollama
    with the web app. It is started detached, so it stays open after INTVAL
    stops. The choice is saved in `data/live/ollama.json`.
  - A local model gets up to 5 minutes per reply (`LOCAL_TIMEOUT` in
    `llm_providers.py`): a 12B model on a laptop CPU takes about a minute.

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
