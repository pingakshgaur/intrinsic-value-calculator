# Market Intelligence Agents

A 23-agent research team built around the intrinsic value calculator. The
agents read filings, news, ownership and market data, check each other's work,
and turn what they find into an agent-adjusted intrinsic value. The value comes
with a bull/base/bear range, a confidence score and a "research buy-below"
level.

> The agents only research. They never place trades, move money or log in
> anywhere. Their labels ("Undervalued", "Overvalued", ...) describe the price
> against an estimated value. They are not recommendations.

## The team

```
Chief Market Intelligence Officer      HYBRID MODEL + verdict + executive summary
├─ Market News Research Lead
│   ├─ Research Analyst                news + NSE filings, red flags in filings
│   ├─ News Credibility Analyst        source tiers, promotional coverage
│   ├─ Sentiment Analyst               credibility-weighted tone
│   ├─ Stock Movement Analyst          returns vs Nifty, abnormal moves
│   └─ Market Impact Analyst           which news changes business value
├─ Equity Research Lead
│   ├─ Fundamental Research Analyst    ROIC, ROE, growth, margins, moat
│   ├─ Financial Forensics Analyst     Piotroski, Altman Z'', Beneish M, accruals
│   └─ Pre-Earnings Intelligence       quarterly trend into the next results
├─ Head of Industry & Geopolitical Research
│   ├─ Industry Research Analyst       sector index, peers, sector outlook
│   └─ Geopolitical Risk Analyst       VIX, INR, crude, US yields, geo news
├─ Head of Market Activity & Ownership Research
│   ├─ Market Volume Intelligence      liquidity, volume spikes, delivery %
│   ├─ Insider Activity Analyst        promoter/insider trades (SEBI PIT)
│   ├─ Fund Holdings Research          shareholding trend, pledges, institutions
│   └─ Short-Seller Research           short reports, allegations, distress
└─ Independent Research Review Lead
    ├─ Research Validation Analyst     enforces the evidence rules
    ├─ Bull Case Analyst               strongest honest case for
    └─ Bear Case Analyst               strongest honest case against
```

All the code is in `src/agents/`, one file per team.

## Nomenclature

Every agent has a callsign, `TEAM-NN`. TEAM is a three-letter team code, `00` is
the team's lead (`CMD-00` is the chief), and `01`, `02`, … are its analysts in
the order they run. Each team has a colour, used everywhere in the web app.

| Team | Code | Colour | Lead | Analysts |
|---|---|---|---|---|
| Command | CMD | gold | CMD-00 Chief Market Intelligence Officer | — |
| Market News Research | NWS | blue | NWS-00 | 01 Research · 02 News Credibility · 03 Sentiment · 04 Stock Movement · 05 Market Impact |
| Equity Research | EQR | green | EQR-00 | 01 Fundamental · 02 Financial Forensics · 03 Pre-Earnings |
| Industry & Geopolitical | IGR | orange | IGR-00 | 01 Industry · 02 Geopolitical Risk |
| Market Activity & Ownership | MAO | teal | MAO-00 | 01 Market Volume · 02 Insider Activity · 03 Fund Holdings · 04 Short-Seller |
| Independent Review | IRV | purple | IRV-00 | 01 Research Validation · 02 Bull Case · 03 Bear Case |
| Operations | OPS | grey | OPS-00 Run Orchestrator | — |

## How the agents talk

For each company the agents share one blackboard (`CompanyContext`). A feed one
analyst downloads is reused by the next, findings are filed there for the
leads, the review team and the chief, and run-wide facts live in one shared
dict. That is the cheapest exchange possible: no extra requests and no extra
LLM calls. In a full run of 43 companies, about 400 feed requests are saved
this way.

`src/agents/comms.py` and `src/agents/protocol.py` make the exchange visible as
chat. Every message is written from data the agents already produced, so the
conversation itself costs **no API calls**. Writes are batched into the
blackboard: one commit per ~25 messages or per second.

| Channel | Who | What |
|---|---|---|
| `#command` | chief + 5 leads | the chief opens coverage; leads file team reports; the chief signs verdicts |
| `#nws-market-news`, `#eqr-equity-research`, `#igr-industry-geo`, `#mao-market-activity`, `#irv-review` | a team | the lead assigns the company; analysts file findings and red flags |
| `#ops-run-control` | orchestrator | run start and finish, data-source problems, LLM usage |
| trace | everyone | every feed fetched, and every reuse by another agent |
| `dm:A\|B` | two agents | cross-team exchanges |

Direct exchanges follow the real data dependencies in the code; nobody talks
for the sake of it:

- MAO-04 (short-seller) asks MAO-01 for accumulation and liquidity, and NWS-04
  for relative strength, before it works: it reads both.
- NWS-02 tells NWS-03 and NWS-05 when its credibility weights are ready; their
  scores use them.
- EQR-02 passes forensic red flags to IRV-03 for the bear case. EQR-03 raises a
  disagreement with EQR-01 when their earnings-momentum reads point in
  opposite directions.
- IRV-01 messages only the analysts whose work failed validation (exceptions
  only), and posts one summary to its team.
- IRV-02 and IRV-03 ask the lead pushing hardest their way for its strongest
  validated point.
- CMD-00 asks the lead whose score is the outlier what is driving it, then
  posts the verdict. Its message refers to the team reports, and each report
  refers to its analysts' findings, so you can follow any verdict back to the
  evidence.

## Talking to the agents

In the web app's **Research Room** you can post in any channel or message an
agent directly. The agents answer from the latest research, with no LLM call:

| Type | Answer |
|---|---|
| `/verdict HAL` | the chief's verdict |
| `/flags HAL` | validated red flags, from IRV-01 |
| `/compare HAL BEL` | two verdicts side by side |
| `/top 5` | the widest gaps to the HYBRID MODEL value |
| `@EQR-02 HAL` or `/ask EQR-02 HAL` | that analyst's latest finding on HAL |
| `/status` | the current or last run |
| `/run quick` or `/run full`, optionally `HAL,BEL` and `no-llm` | starts a research run |
| `/help` | the list |

## Hybrid intelligence

Numbers are always computed in Python. An LLM is used only where text has to
be read (headlines, filings) or written (bull/bear cases, the chief's note).
Every LLM step has a rule-based fallback, so a run with no API keys still
completes.

LLM safeguards:

- **Evidence ids.** Every fact an agent uses carries an id, a source, a URL
  and a date. A claim the LLM writes must cite those ids, and claims citing
  ids that don't exist are dropped.
- **No red flags from the LLM alone.** Red flags come from rules (filing
  keywords, forensic scores, pledges, insider selling). An LLM can only note a
  "possible concern".
- **Validation before the verdict.** Findings that fail the evidence rules
  (no source, stale, no URL) are not allowed to move the valuation.

## Free-tier LLM routing

`src/agents/llm.py` speaks the OpenAI-compatible API that Groq, Gemini and
NVIDIA all offer, so no SDKs are needed.

| Feature | What it does |
|---|---|
| Tiers | `fast` (bulk classification) and `smart` (reasoning and writing), each with an ordered provider list in `llm.routes` |
| Pacing | Stays under each provider's requests-per-minute and tokens-per-minute limits. The daily count is stored in the database, so separate cloud jobs on the same day share it |
| Fall-through | A 429 error, server error, timeout, bad JSON or spent quota moves the request to the next provider |
| Bad key | The provider is switched off for the rest of the run, not retried |
| Cache | Identical prompts within `llm.cache_hours` cost nothing |
| Budget | `llm.max_calls_per_run` caps one run |

A full run makes roughly 7–9 LLM calls per company, plus 2 shared ones per
run. For 43 companies that's about 350 calls, which fits Groq's free daily
limit on its own. Quick runs use about half as many, and the cache absorbs
repeats.

Model names change over time; providers retired every original default in
2026. Pick models from each provider's live list, and test them, in the web
app under **Settings → AI providers**. From the terminal, `--llm-check`
shows the provider's exact error.

## The HYBRID MODEL

The agents turn their findings into the inputs of the **HYBRID MODEL**. Its
method is in [HYBRID_MODEL.md](HYBRID_MODEL.md), and its constants are in
`agent_settings.yaml → hybrid_model` and the web app's **Hybrid Lab**. Each
agent output feeds the formula by name; `chief.py` lists the mapping:

| HYBRID MODEL input | From |
|---|---|
| Risk premia (liquidity, governance, forensic, macro, geopolitical, earnings volatility) | Market Volume; Insider / Fund Holdings / Credibility / Short-Seller; Forensics; Geopolitical; Fundamental |
| Growth tilts (industry, momentum, news, macro) | Industry; Fundamental + Pre-Earnings; Market Impact; Geopolitical |
| Quality (moat, earnings quality, financial strength, capital allocation) | Fundamental; Forensics |
| Red flags → governance haircut | Every validated analyst |
| Scenario odds | Bull and Bear conviction |
| Confidence | Evidence coverage, validation pass rate, team agreement |

Signals the agents did not supply come from the company's own accounts, the
same way the valuation report computes them.

## Running it on your computer

```bash
pip install -r requirements.txt
copy .env.example .env           # then paste your keys into .env
python run.py --agents --llm-check
python run.py --agents           # full run over data/companies.csv
python run.py --agents --quick   # fast news/market sweep
python run.py --agents --tickers HAL,BEL --no-llm
```

Output goes to `output/intel/latest/`:

- `dashboard.html`: open it in a browser.
- `report.md`
- `verdicts.json`

History is kept in `output/intel/blackboard.sqlite`, which is how each run
knows what changed since the last one.

**Auto-start.** `python run.py --web` starts the workforce a few seconds after
the server comes up: a quick sweep, rule-based, so restarting the app never
spends LLM quota. It is skipped only when another job is already running.
The **Workforce** button on the Agent Network page turns this off, switches
to a full run, lets it use the AI models, sets a "skip if a run finished in
the last N minutes" window, and starts a run on demand. The settings are
saved in `data/live/autostart.json`; the API is `GET`/`PUT
/api/agents/autostart` and `POST /api/agents/autostart/run`.

## Running it in the cloud (PC can stay off)

### Option A: GitHub Actions (set up and recommended)

`.github/workflows/market-intel.yml` runs on GitHub's machines:

| When (IST, Mon–Fri) | Mode |
|---|---|
| 08:45 | quick: pre-market news and market sweep |
| 12:45 | quick: midday sweep |
| 16:45 | full: valuation plus all 23 agents |

You can also start a run any time from the **Actions** tab with
**Run workflow**, choosing full or quick and, optionally, tickers.

Setup:

1. Push the code to GitHub.
2. In **Settings → Secrets and variables → Actions**, add `GROQ_API_KEY`,
   `GEMINI_API_KEY` and `NVIDIA_API_KEY` (any subset works).
3. In **Settings → Actions → General → Workflow permissions**, choose
   **Read and write**. The job needs this to save history.
4. In the **Actions** tab, enable workflows if GitHub asks, then run it once
   by hand.

Each run:

- shows the report on its run page,
- uploads `dashboard.html` as a downloadable artifact,
- commits the database and reports to the `intel-reports` branch, which is
  how the next run remembers this one.

Things to know:

- **Visibility.** In a **public** repo, the `intel-reports` branch, run logs
  and artifacts are public too. Make the repo private if you want the
  research to stay private.
- **Cost.** Public repos get unlimited free minutes. Private repos get 2,000
  free minutes a month. A full run of 43 companies takes about 10–20 minutes,
  so this schedule uses about 700–900 minutes a month.
- **Timing.** GitHub may start scheduled runs late when it is busy. It also
  pauses schedules in public repos after 60 days without activity.
- **NSE.** The NSE website usually blocks cloud and datacentre IPs, and it
  blocked this PC's connection too during testing. The agents then use
  Yahoo Finance and news instead, and the run report says so. Insider and
  shareholding data are thinner when this happens.

### Option B: an always-free cloud VM

Oracle Cloud Always Free (an Ampere VM) or Google Cloud's e2-micro free tier
can run `python run.py --agents` on a cron schedule:

```
15 11 * * 1-5  cd ~/ivc && .venv/bin/python run.py --agents
15 3,7 * * 1-5 cd ~/ivc && .venv/bin/python run.py --agents --quick
```

The VM keeps the history on its disk, so no git branch is needed. Serve
`output/intel/latest/` with any static web server, or download it. NSE may
block these IPs as well.

### Option C: Google Cloud Run Jobs + Cloud Scheduler

Use this if you want containers rather than a VM. It fits the free tier, but
needs a Dockerfile and somewhere to store the history, such as a Cloud
Storage bucket. That isn't set up yet.

## Tuning

Everything is in `agent_settings.yaml`:

- `macro:` update by hand when RBI policy, CPI or GDP change.
- `hybrid_model:` (or the Hybrid Lab) premium caps, growth tilts, lens weights, gate, calibration, quality, haircut, scenarios,
  margin of safety, label thresholds.
- `sector_exposure:` how sensitive each sector is to crude, INR, US rates,
  China, geopolitics and regulation.
- `agents:` analyst weights. A weight of 0 switches that analyst off.
- `sources.credibility:` which outlets you trust, and how much.

A mistyped or deleted setting never crashes a run. The built-in default is
used and the run log notes it.
