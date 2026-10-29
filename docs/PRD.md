# INTVAL — Product Requirements Document

Oct 26, 2026 · @Pingaksh Gaur

## Summary

INTVAL is a personal research workstation that estimates what Indian listed companies are really worth, then compares that estimate with the share price. It runs on your own computer and is used through a web browser.

It answers one question for each company: **is the market price above or below a careful estimate of the company's value, and how sure can we be?** To answer it, INTVAL downloads company accounts and prices, values each company in several independent ways, blends those into one headline figure (the **HYBRID MODEL** value), and then hands each company to a team of 23 software "agents" that read news, filings, ownership data and the wider economy before signing a verdict.

It is built for one person doing serious equity research: an investor, analyst or student who wants a transparent, explainable valuation rather than a black-box tip. **It is a research tool, not investment advice.** It never trades, moves money or logs in anywhere, and its labels ("Undervalued", "Overvalued") describe a price against an estimate, not a recommendation.

## Goals and non-goals

INTVAL aims to give one honest, explained value per company and to show its working at every step.

**Goals**

1. **Value every company several ways.** Use classic valuation methods and machine-learning models side by side, so no single method dominates.
2. **Produce one headline value people can trust.** The HYBRID MODEL blends six "lenses" into one value, with a likely range, a confidence score and a safer "buy-below" price.
3. **Prove it against history.** Every model is scored against the price the share actually traded at one month after each financial year closed.
4. **Never hide a gap.** Every empty cell says why it is empty; every estimated number is marked as estimated.
5. **Research beyond the numbers.** A 23-agent team reads news, filings, ownership, market activity and the economy, and checks its own evidence before the chief signs a verdict.
6. **Let the user stay in control.** Every constant can be tuned, every agent can be instructed, switched off or re-weighted, and nothing is saved until the user commits it.
7. **Run cheaply.** Work offline, run without paid services, and use only free-tier AI providers or free models on the user's own computer when AI is switched on.
8. **Easy to share.** Someone without Python can install it with a normal setup program on Windows or Linux and open it from a shortcut.

**Non-goals**

- Giving buy or sell advice, or managing a portfolio.
- Placing trades or connecting to a broker.
- Real-time trading-grade data (prices from the free source can be delayed).
- Valuing every company in India: it focuses on a chosen list (about 43 covered companies today) plus a larger learning set for the machine-learning models.
- Serving many users: it is a single-user app that listens on your computer only.

## How it all fits together

Data flows one way, from sources through two engines into storage and on to the web app; your chat, instructions and settings flow back to the agents.

&#91;embedded content: how INTVAL fits together · sources, two engines, storage, web app\]

The valuation engine values every company from its accounts first; the research workforce starts from those base values, adds what it finds, and the chief signs the verdict you see in the app.

## The valuation engine

The valuation engine turns a company's accounts into an estimate of its worth per share, for every financial year in a chosen window (by default the last five years).

### Step 1 — Gather the data

- **Company list.** The user keeps a list of companies (name, sector, size, stock symbol) on the Universe page.
- **Finding the symbol.** If a symbol is missing, INTVAL looks it up: first a hand-checked list, then a saved cache, then a search.
- **Downloading.** For each company it downloads the income statement, balance sheet, cash-flow statement, daily prices and a risk measure (beta). It uses several providers, in an order the user sets in Configuration → Data sources:
  - **Yahoo Finance** goes first.
  - **Screener.in** fills the years and lines Yahoo lacks. It has ten or more years of accounts, against Yahoo's ~4.
  - **Yahoo's BSE listing** and the **NSE and BSE websites** fill gaps in accounts and prices.
  - **Financial Modeling Prep, EODHD and Alpha Vantage** join with a free key.

  The first provider with a figure supplies it, and later ones only fill what is still missing, including figures Yahoo only assumed (such as zero debt). Each year's notes say which provider filled what. If Yahoo fails entirely, the company is built from the others instead of being dropped.
- **Manual fixes.** A spreadsheet of hand-entered figures (the *override sheet*) always wins over downloaded numbers, so the user can patch a wrong or missing value.

### Step 2 — Check there is enough real data

Before anything is estimated, each company is checked on **reported** figures only. A company needs at least 3 complete years of accounts and 3 years with a benchmark price (both adjustable). Companies that fail are not silently dropped: they are listed with a plain-English reason such as *"Bank or lender – these methods do not fit"* or *"Not enough complete years of accounts"*, plus a suggested next step. If nobody passes, the bar is lowered for that run and a warning is shown.

### Step 3 — Fill small gaps, openly

Missing numbers are estimated by a fixed ladder of methods, best first: derive it from other reported numbers (for example, EBITDA = EBIT + depreciation), scale from a nearby year, grow by the company's own trend, or use the sector's typical ratio. Every estimated value is marked with an asterisk, and a "Methods" sheet records exactly how it was produced.

### Step 4 — Value each company several ways

| Method | Plain-language idea | Works best for |
| --- | --- | --- |
| Discounted cash flow (DCF) | Add up the cash the business will generate, worth less the further away it is | Mature, cash-generating companies |
| P/E relative | Price it like its sector peers, by earnings | Profitable companies with many peers |
| EV/EBITDA relative | Price the whole business like peers, by operating profit, then subtract debt | Capital-heavy industrial companies |
| Graham Number | A cautious ceiling price from earnings and book value | Stable, profitable companies |
| Residual income | Book value plus any profit earned above the cost of capital | Banks and loss-makers, where other methods fail |
| Machine learning (XGBoost, Random Forest, LightGBM, neural network) | Learn from many companies how prices re-rated given their accounts | Spotting patterns across the whole panel |
| Ensemble | A weighted blend of all the above, tuned by how each did in earlier years | A statistical cross-check |

Each method either returns a value or a specific reason it cannot (for example *"Not meaningful: negative earnings"*). One method failing never stops the others.

### Step 5 — The HYBRID MODEL (the headline value)

The HYBRID MODEL is INTVAL's main answer. It looks at a company through **six lenses**, each asking a different question:

| Lens | The question it answers |
| --- | --- |
| Cash flow | What will the business pay out over time? |
| Earnings power | What is it worth if it never grows again? |
| Asset | What is the balance sheet worth, given how well it earns? |
| Market | What do comparable companies trade at? |
| Conservative | What would a cautious, defensive buyer pay? |
| Learning | What has the market paid for similar companies before? |

It then works through these steps:

1. **Cost of money.** It sets the return an investor should demand, starting from the risk-free rate and adding premiums for size, debt and risks the agents found (governance, forensic, liquidity, macro, geopolitics, earnings swings).
2. **Growth.** It starts from the company's own growth and nudges it for industry, momentum, news and the economy, never above long-run economic growth.
3. **Growth must be earned.** A *growth-credibility gate* only pays for growth if the company has a moat (a durable advantage) that justifies it.
4. **Learn from past misses.** Each lens is corrected by how far off it was in **earlier** years only, so it never peeks at the answer.
5. **Blend by company type.** Mature companies, lenders, loss-makers and young companies weight the lenses differently. Lenses that disagree wildly with the rest are dropped.
6. **Quality and governance.** The value is raised for strong moats, clean earnings and sound finances, and cut for each confirmed red flag.
7. **Three scenarios.** It reruns with optimistic (bull), central (base) and pessimistic (bear) assumptions and weights them by how strongly the bull and bear analysts argued.

The result comes with:

- **A value per share** (the HYBRID MODEL value).
- **A range** (P10–P90): the value is expected to fall inside this band 8 times in 10.
- **A confidence score** from 0 to 100: the estimated chance the price lands within ±20% of the value.
- **A buy-below price**: the value minus a safety margin that grows with uncertainty and red flags.
- **A label** from price versus value: Deep value, Undervalued, Fairly valued, Overvalued, Avoid – red flags, or Insufficient evidence.

### Step 6 — Score against reality

Every estimate is compared with the **benchmark price**: the closing price on the trading day nearest 1 May, one month after the financial year ends. INTVAL reports how far off each method was (typical error, share within ±20%, bias, how often it called the direction right, which method won most often). In the latest back-test of 43 companies over five years, the calibrated HYBRID MODEL landed within ±20% about one time in three, with a median miss of about 33%.

### Step 7 — Outputs

Each run writes a spreadsheet and CSV files (the valuation grid, a numbers-only copy, a list of why cells are empty, a list of how estimates were made, and the companies left out), plus accuracy tables, charts and an HTML report. All of it is visible in the web app.

## The research workforce

The research workforce is a team of 23 software agents that research each company beyond its accounts and turn what they find into the HYBRID MODEL's inputs. Each agent is a small program with one job; most work by rules, and some can also ask an AI model to read or write text.

### Who is on the team

Every agent has a **callsign** like `EQR-02`: a three-letter team code and a number, where `00` is the team lead. Each team has its own colour throughout the app.

| Team | Code | Lead | Analysts and what they look at |
| --- | --- | --- | --- |
| Command | CMD | CMD-00 Chief Market Intelligence Officer | Runs the HYBRID MODEL on everyone's signals and signs each verdict |
| Market News Research | NWS | NWS-00 | 01 Research (news and exchange filings) · 02 News Credibility (how trustworthy each source is) · 03 Sentiment (tone, weighted by credibility) · 04 Stock Movement (returns against the Nifty) · 05 Market Impact (which news changes the business's value) |
| Equity Research | EQR | EQR-00 | 01 Fundamental (returns on capital, growth, margins, moat) · 02 Financial Forensics (accounting health scores) · 03 Pre-Earnings (quarterly trend into the next results) |
| Industry & Geopolitical | IGR | IGR-00 | 01 Industry (sector index and peers) · 02 Geopolitical Risk (volatility, rupee, crude oil, US rates, world news) |
| Market Activity & Ownership | MAO | MAO-00 | 01 Market Volume (liquidity and volume spikes) · 02 Insider Activity (promoter and insider trades) · 03 Fund Holdings (shareholding trend, pledges) · 04 Short-Seller (short reports and allegations) |
| Independent Review | IRV | IRV-00 | 01 Research Validation (enforces the evidence rules) · 02 Bull Case (strongest honest case for) · 03 Bear Case (strongest honest case against) |
| Operations | OPS | OPS-00 Run Orchestrator | Starts and finishes runs, reports data-source problems and AI usage |

### How a research run works

1. **Base valuation.** The run first values each company from its accounts, so every agent starts from the same numbers.
2. **The chief opens the company.** It posts the company in `#command`, and each lead assigns its analysts.
3. **Analysts work.** Each analyst downloads what it needs (news, filings, prices, ownership) or reuses what a teammate already downloaded, then files a **finding**: a score from −1 (bad) to +1 (good), a confidence, the signals behind it, and the evidence it used.
4. **Agents consult each other.** They exchange work only where their jobs genuinely depend on each other. For example, the short-seller analyst reads the volume and stock-movement analysts first, and the forensics analyst passes red flags to the bear case.
5. **Leads write team reports.** Each lead combines its analysts' findings, weighting each by its configured weight and confidence.
6. **Review.** The validation analyst checks every finding against the evidence rules (a source, a date, a link, not too old). Findings that fail cannot move the value. Bull and bear analysts then argue each side.
7. **The chief decides.** It turns the team reports into HYBRID MODEL inputs (risk premiums, growth nudges, quality scores, red flags, scenario odds), computes the value, range, confidence and label, and signs the verdict.
8. **Memory.** Everything is saved in a local database (the *blackboard*), so the next run knows what changed since the last one.

### Two kinds of run

|  | Quick sweep | Full research |
| --- | --- | --- |
| What it does | News and market activity only; slower analysts reuse their last full-run finding | All 23 agents on every company |
| Typical use | Several times a day, or when the app starts | Once a day, or on demand |
| AI calls | About half of a full run (none when run rule-based) | About 7–9 per company |

A full run over about 43 companies takes roughly 10–30 minutes, depending on how many AI calls are made and how fast the data sources answer. Sharing downloads between agents saves around 400 requests per full run.

## AI models

AI is optional: every number is calculated by ordinary code, and AI is used only to read text (headlines, filings) or write text (bull and bear cases, the chief's note, chat replies). With AI switched off or no keys entered, every agent falls back to its rule-based path and runs still finish.

**Providers.** INTVAL talks to free-tier services from Groq, Google Gemini and NVIDIA through the same standard interface, so any similar service can be added in settings. The user pastes their own keys in Configuration → AI providers, picks a model from each provider's live list, and presses **Test** to see the provider's exact reply.

**Local models.** Below the keys, a *Local models (Ollama)* section lets the agents use free models running on the user's own computer, with no key and no daily limit:

- It shows whether Ollama is installed and running, the models already downloaded, and the free disk space.
- The user downloads a free model from a list of 18, filtered by how much storage they can spare (up to 1, 2, 5 or 10 GB), or names any other model. Progress is shown live, and models that would not fit on the disk cannot be chosen.
- The user picks a fast and a smart model, tests them, and switches local models **on or off**. A second switch decides whether local models are tried **before** the cloud providers or only as the fallback.
- Ollama opens automatically when INTVAL starts (this can be turned off) and stays open after INTVAL stops.
- Local models are free and private but slower: a large model on an ordinary laptop takes about a minute per answer, so each answer is allowed up to five minutes.

**Two kinds of task.** *Fast* models handle bulk sorting (is this headline positive?). *Smart* models handle reasoning and writing. Each kind has an ordered list of providers to try.

**Staying within free limits.**

- **Pacing:** it keeps under each provider's per-minute and per-day limits, and remembers the daily count across runs.
- **Fall-through:** if a provider is busy, out of quota, errors or returns bad output, the request moves to the next provider.
- **Bad keys:** a provider that rejects the key is switched off for the rest of the run instead of being retried.
- **Cache:** an identical request within about 20 hours is answered from a saved copy at no cost.
- **Budget:** one run is capped at a set number of calls (400 by default).

**Guardrails on AI output.**

- Every fact an agent uses carries an evidence id with its source, link and date. An AI claim must cite those ids; claims citing ids that do not exist are thrown away.
- Red flags come only from rules (filing keywords, forensic scores, pledges, insider selling). AI alone can only note a "possible concern".
- Findings that fail the evidence rules cannot move the valuation.
- In chat, agents are told to ground every figure in their research and never invent numbers, prices or news.

## The web app, page by page

The web app is where all of INTVAL is used. It opens in the browser at `http://127.0.0.1:8765`, only on this computer, in a dark theme (a light theme is one click away).

### The frame around every page

- **Sidebar (left):** the pages, grouped into Analysis, Research workforce, Models & data and Operations. At the bottom, one compact **System** line shows five status dots (server, AI providers, last report, last research, price tracker); click it for the details. The collapse button (or `Ctrl+\`) shrinks the sidebar to icons.
- **Top bar:** a live market tape (Nifty 50, India VIX, USD/INR, Brent crude, US 10-year yield, gold, each with its one-month change), a light/dark switch, search (`Ctrl+K`) across companies, pages and actions, the alerts bell, the glossary (`?`), and a run indicator that opens the list of runs.
- **Every page** has its own loading, empty and error states, and a PDF button that exports the page.

### Analysis

**Command Center** — the home page and quickest overview.

- A band of headline figures (companies covered, median upside, labels, confidence).
- **Coverage map:** a tile per company, sized by market value and coloured by upside to the HYBRID MODEL value.
- **Signals:** what needs attention, such as red flags, label changes and data problems.
- **Upside vs confidence** chart, the **label mix** with the extremes, and a **model leaderboard** of accuracy.

**Markets** — the live market.

- Index cards (Nifty 50, Sensex, Bank, IT, Midcap 50, Financial Services, VIX) with intraday mini-charts, and a sector heat strip.
- A **scanner** over about 425 companies: top gainers and losers, most active, volume spikes, near 52-week highs or lows, overbought or oversold, and covered companies below their buy-below price.
- A full trading chart for any company or symbol: candles, bars, line and area styles; indicators (moving averages, Bollinger bands, VWAP, RSI, MACD); drawing tools (trend lines, rectangles, Fibonacci, measure, notes); right-click to add a price alert; the HYBRID MODEL value and buy-below drawn as lines.

**Watchlists** — named lists of the companies you follow closely (up to 250 across all lists).

- **Adding companies**, when a list is created or later, four ways:
  - **search** by name or symbol;
  - **whole sectors**: tick one or several sectors and take all of their companies or a few. The app's own lists plus NSE's index lists give about 1,000 companies, each with its industry;
  - **a spreadsheet**: Excel, CSV or pasted text;
  - **another list**.
- A list's page has three buttons: **Add companies**, **Research this list** and **More** (edit, focus the app, update prices, pause tracking, tracking settings).
- A headline band: how many are tracked, advancing vs declining, average change, how many sit below their buy-below price, and today's alerts.
- **Tiles or Table** view. In the table, click any column header to sort (click again to reverse); in tiles, the same column names appear as sort buttons.
- Clicking a company opens a **detail panel** beside the list, with its own scroll: a simple price chart (1 day to 1 year), the HYBRID MODEL re-valued at today's price, price-alert levels, a note, and a link to the full chart.
- A **live alerts** feed below.

**Coverage** — every researched company in a sortable grid with a column chooser, compact rows and CSV export. Selecting a row opens a quick inspector; `Enter` opens the full profile.

**Company profile** — one company in depth. A sticky bar shows price, HYBRID MODEL value, upside, buy-below and confidence. A section menu on the left follows your scrolling and highlights where you are:

- **Summary:** first **In plain words**, a short reading in everyday language. It says whether the share looks cheap, fairly priced or expensive and by how much, how sure the models are, the price a cautious buyer would wait for, what the models expect in a year, and the good and bad cases. It ends with short lists of what is in the company's favour and what to keep an eye on. Then the research note and key points.
- **Forecasts:** every model's predicted price over days, months or years, with **Show all** and **Remove all** at the right edge of the chart, and a forecast table.
- **Valuation:** lens contribution, the bridge from lens blend to final value, the build-up.
- **Drivers & risk:** risk premiums, growth nudges and quality.
- **Agents & evidence:** every analyst's finding with its evidence links.
- **Bull vs bear:** both cases side by side.
- **History:** how value, price and label moved across research runs.

**HYBRID MODEL Studio** — a safe sandbox for the model's constants.

- **Parameters** (left panel): every constant in groups, with a slider and a box to type in. A constant you changed is highlighted, shows its saved value, and offers a one-click link back to its **default**.
- **Canvas** (centre, scrolls on its own): the live value, price, range, label and confidence for the chosen company, the valuation range chart, the bridge and the lens contribution, all updating as you move a slider.
- **Inspector** (right panel): *Sensitivity* ranks which constants move this value most (click one to jump to it), *Changes* lists your edits, *Inputs* shows the company's raw inputs.
- Both side panels can be closed and reopened (buttons, slim edge tabs, or the `[` and `]` keys) to give the canvas more room.
- **Company / Portfolio** switch: Portfolio shows every company's value and label under your changes.
- **Scenarios** saves named sets of changes in the browser. **Discard** drops unsaved changes. **Defaults** loads the shipped value of every constant you changed, so you can review and commit it. **Commit** writes the changes to the settings file.

### Research workforce

**Overview** — the team at a glance: the current or last run (companies done, who is working, messages, calls saved, AI calls), a card per team listing every agent with live status (and markers for agents that are switched off or tuned), this run's verdicts and red flags, and recent runs (click one to replay it). Clicking an agent opens its profile; the gear opens its **settings**. **Research** starts a run on every covered company or on any chosen watchlist (quick sweep or full research); **Auto-start** sets whether the team starts by itself when the app opens.

**Agent Network** — the team as a live, full-screen map.

- **Layout:** a top bar (run picker, agent search, Views, Layers, Research, export, shortcuts, inspector toggle), a tool rail on the left, the inspector docked on the right and a replay bar along the bottom, so nothing covers the map.
- **Motion:** small coloured dots (*info-bits*) travel along the lines as agents exchange work, coloured by what they carry; busy agents glow, and counters tick up. Live during a run; afterwards any run can be replayed with a timeline and speed control.
- **Cards:** each agent is a card; a small arrow inside opens a brief info panel (role, status, work done, duty, settings, quick actions).
- **Layers:** show or hide analysts, data sources, outputs, the orchestrator, team bands, each kind of connection, captions, animation, score pop-ups and a mini-map; hide whole teams or single nodes.
- **Arrangements and views:** *Hierarchy* or *Radial* layout, compact or full cards, built-in views (Simple, Leads only, Data flow, Everything, Radial) and your own saved views.
- **Tools:** Select & move, Pan, Link (draw your own connection), Note (pin a note), Focus (show one agent and its connections) and Hide/delete, each with a keyboard shortcut.
- **Notes:** a tidy card in the map's own style, with a drag handle, five colours, edit and delete buttons, and when it was last changed. While writing there is a counter and a **Done** button (`Ctrl+Enter`); an empty note is discarded.
- **Real changes:** right-clicking an analyst can leave it out of research runs; links and notes are personal annotations only.
- **Light theme:** team colours are drawn darker so everything stays readable.

**Research Room** — the team's chat (see the next section).

### Models & data

**Model Performance** — how accurate each method has been, in five tabs:

- **Leaderboard:** each method's error, hit rate, bias and rank correlation; error by year; how often each wins.
- **Sectors:**
  - *which model suits each sector*: the most accurate method, its error, the runner-up, and the HYBRID MODEL's error;
  - how many sectors each method wins;
  - a sector-by-method error grid with the best method in each sector outlined;
  - a *sector valuation forecast by each model*: each method's median value against today's price, or its one-year projection;
  - *sector segregation and prediction*: per sector, how many companies sit below, near or above value, the top pick, and a chart of each sector's upside and one-year projection. Click a sector to list its companies.
- **Company:** every method by year for one company, plus HYBRID MODEL and Ensemble detail.
- **Training data:** how the machine-learning models grow, in plain words (see *Learning data* below).
- **Files & charts:** downloads, companies left out, the chart gallery.

**Universe** — the editable company list: add, delete, set sectors in bulk, import and export CSV, and checks for problems.

### Operations

**Operations** — start and watch jobs from one form:

- **What to run:** a valuation report, research (quick or full), a training-data refresh, or a data check.
- **Which companies:** all covered ones, a watchlist, or the ones you pick.
- **Which years.**
- **Options:** only the ones that apply. The rare ones (auto-train, rule-based research, offline test data) sit under *More options*.

Beside it, the live job shows its stages and log, and a table lists past jobs. Only one job runs at a time.

**Configuration** — every setting: run and data-quality settings, **data sources** (each provider on or off, the order they are trusted in, free keys), AI providers (key, model picker, test, fail-over order), local models through Ollama, research agents, economic inputs, notifications and sounds, and the raw settings file.

## Talking to and tuning the agents

The Research Room lets you read everything the agents say and talk to them; agent settings let you change how each one works from the next run on.

### The Research Room

- **Channels:** `#command` (the chief and the five leads), one channel per team, `#ops-run-control` (run start, finish and data problems), and a read-only **data-exchange trace** showing every download and every reuse between agents.
- **Direct exchanges:** private conversations between two agents, or between you and an agent.
- **Agents list:** every agent grouped by team (folded until you open a team), with a live status dot.
- **Messages:** findings show score, confidence, signals and expandable evidence links; team reports show how many findings they combine; verdicts show value against price and the label. Hover a message for **Reply**, **Details** (the data it carried and what it refers to), **Copy** and a company filter.
- **Tools:** search, filter by company or by kind of message, export to PDF, pick an older run to read, and a details side panel (channel members, agent profiles, message details).
- **Unread counts** and a "new messages" button keep track of activity.

### Talking to agents

Write to an agent directly, @mention up to three agents, or write in a channel (its lead answers). A "… is typing" line shows until the reply arrives, usually within seconds.

| You write | What happens |
| --- | --- |
| A question ("how does BEL look on debt?") | The agent answers in character from its latest research. With AI on, it writes a natural reply and never invents figures; without AI, it returns its latest finding on the company you named. |
| An instruction ("from now on focus on debt") | Saved as a standing instruction and added to the agent's AI requests from the next run. |
| "Be more cautious" / "be bolder" / "back to balanced" | Changes its stance. |
| "Sit out" / "you're back" | Leaves or rejoins research runs (analysts only). |
| "Re-check HAL", "look into Bharat Electronics" | Starts a quick research run on that company. |

**Commands** give precise control: `/verdict`, `/flags`, `/compare`, `/top`, `/ask`, `/recheck`, `/instruct`, `/forget`, `/profile`, `/enable`, `/disable`, `/weight`, `/stance`, `/llm`, `/status`, `/run` and `/help`. Typing `/` or `@` suggests completions.

### Agent settings

Each agent has a **Settings** tab (from the Overview, the Network inspector or the Research Room):

| Setting | What it changes |
| --- | --- |
| Takes part in runs | Leave an analyst out of research runs (leads and the chief always run) |
| Weight | How much its finding counts in the team report (0 to 3 times) |
| Stance | Cautious (scores ×0.75), balanced, or bold (scores ×1.25) |
| AI model | Auto, always fast, always smart, or off (rules only) |
| Confidence floor | Ignore its findings below a chosen confidence |
| Re-run in quick sweeps | Re-run a slow analyst in quick sweeps instead of reusing its last full-run finding |
| Standing instructions | Free text added to every AI request it sends and to its chat persona |

A **Defaults** button puts an agent back. Changes apply from the next run and are marked "tuned" on the agent's card.

## Live market data, watchlist and alerts

While the web app is open, a background **tracker** follows the watchlist and raises alerts; the valuation itself stays fixed until the next report or research run.

- **Polling:** every 30 seconds while the Indian market is open (09:15–15:30, Monday to Friday) and every 15 minutes otherwise. Both are adjustable under a watchlist's More → Tracking settings. Prices from the free source can be a little delayed; when it has no quote, the NSE and then the BSE website are asked.
- **Minute history:** every minute price is stored on this computer, so a tracked company builds an intraday history longer than the source's own 7-day limit. How long it is kept is adjustable.
- **Re-valuing at today's price:** the HYBRID MODEL value comes from the accounts, so it does not move with the price. Only the upside, the label and the buy-below test are recalculated at the live price.
- **Alerts** fire once per session when a price reaches a level you set, falls below the buy-below price, or moves more than 5% in a day (adjustable).
- **Where alerts show:** the Watchlist alerts feed and the **bell** in the top bar. The bell also collects research alerts (new red flags, label changes), in All, Live prices and Research tabs.
- **Sounds and pop-ups:** each of eight events (below buy-below, fell to your alert, rose to your alert, big move, run finished, run failed, an agent replies, interface clicks) has its own quiet sound, volume and on/off switch, with a master volume and optional quiet hours. Desktop pop-ups appear when the tab is in the background.
- **Holidays:** exchange holidays are not known; a price that stops moving for 20 minutes is marked as stale.
- **Limit:** the tracker only runs while the web app is running. For tracking with the computer off, the cloud schedule runs quick sweeps at fixed times.

## Learning data

The machine-learning models get better mainly by seeing more companies, so INTVAL keeps a separate **learning set** of companies it learns from but does not value.

- **What a lesson is:** one company in one financial year — that year's accounts, and how its price moved over the next year. A live price on its own teaches nothing, so tracker prices are not used for training.
- **The learning set:** every company INTVAL knows beyond the valued list: a training list, the auto-trainer's picks and the watchlists (about 380 companies). With Screener.in filling the older years, each company adds more lessons than the 2–3 that Yahoo's four years of accounts allowed.
- **Fetching:** *Model Performance → Training data → Refresh now* (or Operations → Refresh training data) downloads and caches their accounts; a cached company is reused for 7 days.
- **Train on all learning companies:** when on, every valuation run includes the learning set in training.
- **Daily feed:** when on, the app fetches new and stale companies after 16:15 each weekday when nothing else is running, and can retrain afterwards.
- **Auto-train:** a run mode that keeps adding training companies, batch by batch, until the model's confidence stops improving or a limit is reached, with live controls to pause, skip a sector, retrain, change the target or finish.
- **Did it help?** After every valuation run, the Training data tab records the number of companies learned from and the HYBRID MODEL's typical error, and says in plain words whether accuracy is improving, holding steady or slipping.

## Settings, files and storage

Everything INTVAL knows lives in plain files inside the project folder; nothing is sent to an outside server except data downloads and optional AI requests.

| What | Where | Notes |
| --- | --- | --- |
| Company list | `data/companies.csv` | Edited on the Universe page |
| Hand-entered figures | `data/fundamentals_override.csv` | Always wins over downloaded data |
| Valuation assumptions | `src/config.py` | Years, prices, discount rates, model switches |
| HYBRID MODEL and agent settings | `agent_settings.yaml` | Every constant, with comments; edited in the Studio and Configuration |
| Shipped defaults | `agent_settings.defaults.yaml` | The factory copy the Studio's **Defaults** restores from; never edited |
| AI keys | `.env` | Your own keys; never shared |
| Valuation results | `output/` | Spreadsheet, CSVs, charts, HTML report, run log |
| Research history | `output/intel/blackboard.sqlite` | Every run, message, finding and verdict |
| Latest research | `output/intel/latest/` | Dashboard, report and verdicts |
| Agent settings | `agent_profiles.json` (beside the blackboard) | Per-agent tuning and instructions |
| Live data | `data/live/` | Watchlists, alerts, minute prices, learning history, auto-start settings, data-source choices, the cached NSE sector lists, the update history |
| Backups | `backups/` | A copy of your data made before every update; the last five are kept |
| Browser-only preferences | The browser's storage | Map layouts, saved views, notes, panel choices, Studio scenarios |

A mistyped or deleted setting never crashes a run: the built-in default is used and the run log notes it.

## Running it

INTVAL runs on any computer with Python, or without Python through its installers; most people use the web app, and the cloud option keeps research going with the computer off.

**Installing it.** A setup program installs INTVAL with no Python needed:

- **Windows 10/11:** a setup wizard. The user picks the folder (Program Files or any other) and whether to install for everyone or just themselves. They can add a desktop shortcut and a Start-menu entry, and launch INTVAL when setup finishes. It appears in Settings → Apps with an uninstaller, which asks before deleting the user's data.
- **Linux:** a graphical setup wizard with the same choices (folder, desktop shortcut, applications menu, launch when finished), an uninstall script, and a text mode for computers without a screen.

The installed app opens the web app from its shortcut. There is no macOS installer yet.

**Updating it.** Each release also comes as an **updater** (`INTVAL-Update-<version>-windows-x64.exe`, `INTVAL-Update-<version>-linux-x86_64`). It upgrades an existing installation in place and never loses data:

1. It finds INTVAL wherever it was installed, for one user or for everyone. Where INTVAL is not installed, it refuses and points to the Setup.
2. It backs up everything the user owns to `backups/`: company lists, watchlists, the research agents' memory and history, training data, settings and keys.
3. It replaces only the program.
4. It adds the new version's training companies and settings sections without changing anything the user set.

The full Setup run over an existing copy installs into the same folder and does the same.

**On your computer, from the source code.** Install the requirements once, then:

| To | Run |
| --- | --- |
| Open the web app | `python run.py --web` |
| Run the valuation report from the terminal | `python run.py` |
| Try it with no internet, on made-up data | `python run.py --offline` |
| Run full research | `python run.py --agents` |
| Run a quick sweep | `python run.py --agents --quick` |
| Check AI keys | `python run.py --agents --llm-check` |
| Refresh the learning set | `python run.py --learn` |

In the web app, everything above is a button on the Operations page. Each job runs as its own separate process, so a crash or a closed tab cannot take the app down, and only one job runs at a time.

**Automatic start.** When the web app starts, the workforce begins a quick, rule-based sweep a few seconds later (so restarting never spends AI quota). The **Workforce** button turns this off, switches it to full research, allows AI, sets a "skip if a run finished recently" window, or starts a run now.

**In the cloud.** A ready-made GitHub Actions schedule runs on GitHub's machines on weekdays: quick sweeps at 08:45 and 12:45 and full research at 16:45 (India time). Each run saves its report as a download and commits its history to a separate branch so the next run remembers it. Keys are stored as GitHub secrets. In a public repository the results are public too, and the exchange website usually blocks cloud machines, so ownership data is thinner there. A free cloud virtual machine with a timer is a documented alternative.

## Safeguards and reliability

INTVAL is built so that a wrong input produces a visible gap, not a confident wrong answer, and a failure in one part never stops the rest.

**Honest numbers**

- **No peeking at the answer.** Valuing a year uses only data from that year and before; the benchmark price is never an input. The HYBRID MODEL learns only from earlier years' misses.
- **No silent blanks.** Every empty cell carries a reason code (for example *Field missing*, *Not meaningful*, *No peer benchmark*) and an explanation traced back to where the data was missing.
- **Estimates are marked.** Every estimated value carries an asterisk and a recorded method.
- **Failed companies are listed, not dropped,** with a plain-English reason.
- **Evidence rules.** Agent findings without a source, date or link, or that are too old, cannot move a valuation. AI claims must cite real evidence, and AI alone cannot raise a red flag.

**A sturdy app**

- Each job runs as its own process, one at a time, and every option is checked before it starts.
- Every download, field, model and export is protected separately, so one failure produces one reason code, not a crash. Full error details go to the run log.
- Studio what-ifs are calculated in memory and write nothing until **Commit**; **Defaults** can always restore the shipped constants.
- Each page has its own loading, empty and error states; if the server stops, a banner says so and the app reconnects by itself.
- Research runs interrupted by a server stop are closed automatically, so no agent is shown as "working" forever.
- Browser storage is always optional: if it is blocked, pages still work with default settings.
- An automated test suite (48 tests) covers the valuation, agents, chat, live data and settings, and the web code is type-checked on every build.

## Known limits and ideas for later

The main limits come from free data: few years of accounts, delayed prices and a blocked exchange website.

**Known limits**

- **Short history.** Yahoo serves about four years of accounts. Screener.in now fills the earlier years, but it has no cash or current-liabilities figures, so those can still be estimated for older years.
- **Exchange website blocks.** NSE and BSE often block cloud and VPN connections (and sometimes home ones); their website endpoints are unofficial and can change. When they do not answer, prices, quotes, insider and shareholding data come only from the other sources and are thinner.
- **Delayed prices.** Live prices can be delayed and exchange holidays are not known.
- **Banks and lenders** fit most methods poorly; residual income and the lender weighting help, but coverage is weaker.
- **What "accurate" means.** All methods are scored against the price one month after the year closes, so the calibration inherits that definition.
- **Machine-learning scores look better than real use,** because early years fall back to a method that uses future years for training.
- **AI providers retire models often;** a saved model may stop working and must be re-picked in Configuration.
- **Local models are slow on ordinary laptops** (about a minute per answer for a large model), so a full research run that uses them first can take hours; small models are much faster but write less well.
- **Installers are large and unsigned.** Each is roughly 120–190 MB, too big to keep in the code repository, so they are shared as release downloads. Windows warns before running an unsigned setup program, and Linux users must mark the file as runnable first.
- **Single user, single computer.** The app listens only on this computer; annotations and layouts live in one browser.
- **Map annotations** (your links and notes on the Agent Network) are visual only; they do not rewire how agents work.

**Ideas for later**

- [ ] Store map views and annotations on the server so they follow the user across browsers.
- [ ] Know exchange holidays so tracking pauses correctly.
- [ ] A container-based cloud option with stored history.
- [ ] More years of accounts from a second data source to deepen calibration.
- [ ] Let agents' standing instructions affect rule-based analysis, not only AI requests.

## Glossary

Plain-language meanings of every term used in this document and in the app, in alphabetical order.

| Term | Meaning |
| --- | --- |
| Agent | A small program with one research job, such as reading news or checking accounts. INTVAL has 23. |
| AI model (LLM) | A language model from an outside provider, used only to read or write text. Optional. |
| Altman Z'' | A score that estimates how close a company is to financial distress. |
| Anchor price | The average share price inside a financial year, used as an input to some methods. |
| Auto-start | The workforce starting a research run by itself when the web app opens. |
| Auto-train | A mode that keeps adding companies to the learning set until the model stops improving. |
| Bear case / bull case | The strongest honest argument against / for the company, written by the review team. |
| Benchmark price | The closing price on the trading day nearest 1 May, one month after the financial year ends. Used only to score accuracy. |
| Beneish M | A score that flags signs of earnings manipulation. |
| Beta | How much a share tends to move with the overall market. |
| Blackboard | The local database where agents share data and every run is remembered. |
| Book value | What the company's assets are worth on its balance sheet after subtracting its debts. |
| Bridge | A chart showing step by step how the lens blend becomes the final value. |
| Buy-below price | The value minus a safety margin; a price below it suggests a comfortable cushion. |
| Calibration | Correcting a method by how far off it was in earlier years. |
| Callsign | An agent's short name, such as EQR-02: team code plus number (00 is the lead). |
| Channel | A chat room in the Research Room, one per team plus #command and #ops. |
| Confidence score | 0–100: the estimated chance the price lands within ±20% of the value. |
| Cost of equity / cost of money | The yearly return an investor should demand for owning the share, given its risks. |
| Coverage | The list of companies INTVAL researches and values (about 43 today). |
| DCF (discounted cash flow) | Valuing a business by adding up its future cash, with later cash counting for less. |
| EBIT / EBITDA | Operating profit before interest and tax / before interest, tax, depreciation and amortisation. |
| Ensemble | A statistical blend of all the methods, weighted by their past accuracy. |
| EPS | Earnings per share: profit divided by the number of shares. |
| EV/EBITDA | Enterprise value (the whole business including debt) divided by EBITDA; a way to compare companies. |
| Evidence id | A tag on every fact an agent uses, linking it to its source, link and date. |
| Finding | One analyst's result for one company: a score from −1 to +1, a confidence and the evidence. |
| Financial year (FY) | 1 April to 31 March; FY2024 means April 2023 to March 2024. |
| Forensics | Checks on the quality and honesty of a company's accounts. |
| Graham Number | A cautious ceiling value from earnings and book value. |
| Growth-credibility gate | A rule that only pays for growth the company's moat can justify. |
| HYBRID MODEL | INTVAL's headline value: six lenses blended, adjusted for quality and red flags, and run through three scenarios. |
| Info-bit | A small moving dot on the Agent Network showing a piece of work passing between agents. |
| Label | Deep value, Undervalued, Fairly valued, Overvalued, Avoid – red flags, or Insufficient evidence: a description of price versus value. |
| Layers | The Agent Network menu that shows or hides parts of the map. |
| Learning set | Companies used only to train the machine-learning models, not valued. |
| Lens | One of six ways of valuing a company inside the HYBRID MODEL (cash flow, earnings power, asset, market, conservative, learning). |
| Machine learning (ML) | Models that learn patterns from many past examples: XGBoost, Random Forest, LightGBM and a neural network. |
| Margin of safety | The cushion subtracted from the value to get the buy-below price. |
| Moat | A lasting competitive advantage that protects a company's profits. |
| NSE | National Stock Exchange of India. |
| Override sheet | A spreadsheet of hand-entered figures that always replaces downloaded data. |
| P/E | Price divided by earnings per share. |
| P10–P90 range | The band the value is expected to fall in 8 times out of 10. |
| Piotroski score | A 0–9 score of a company's financial health. |
| Point-in-time | Using only information that was available at the time being valued. |
| Profile (agent) | An agent's settings: on/off, weight, stance, AI model, confidence floor, instructions. |
| Quick sweep / full research | A fast news-and-market run / a run of all 23 agents. |
| Reason code | A short label explaining why a value is missing, such as *Field missing*. |
| Red flag | A confirmed warning sign (for example a forensic alert or heavy pledging) that cuts the value. |
| Regime | The company type used for weighting: mature, lender, loss-maker or young. |
| Residual income | Valuing a company as its book value plus profit earned above the cost of capital. |
| Research Room | The chat page where agents report and where you talk to them. |
| Scenarios | Bull, base and bear versions of the valuation, weighted together. |
| Sensitivity | Which constants move a company's value the most. |
| Stance | An agent setting that makes its scores more cautious or bolder. |
| Studio | The HYBRID MODEL Studio: the page for safely trying and saving model constants. |
| Team report | A lead's combined score from its analysts' findings. |
| Tracker | The background process that follows watchlist prices while the app runs. |
| Upside | How far the value is above (+) or below (−) the current price, in percent. |
| Universe | The editable list of companies INTVAL knows about. |
| Validation | The review step that rejects findings lacking proper evidence. |
| Verdict | The chief's final call on a company: value, range, confidence, buy-below and label. |
| Watchlist | Up to 60 companies followed live, with alerts. |
| Workforce | The research team of 23 agents, and the button that controls its runs. |
