# Intrinsic Value Calculator (INTVAL-Calc)

A research engine that estimates the **intrinsic value per share** of Indian listed companies across a range of financial years, using **four traditional valuation models** and **four machine-learning models**, and then scores each estimate against the price the share actually traded at shortly after the year closed.

It ships with a command-line interface, a browser app (`python run.py --web`), an offline mock dataset for testing, a fundamentals override sheet for filling data gaps by hand, and an analysis stage that produces accuracy metrics, HD charts and an HTML report.

> **Not investment advice.** This is a research instrument. Its output is only as good as the assumptions in [`src/config.py`](src/config.py), and every one of those assumptions can be argued with.

> **New: browser workbench.** `python run.py --web` opens a React UI in VS Code's Dark 2026 theme. You can explore the research and every model's results, start runs and watch them live, and edit companies and settings. See [docs/WEB.md](docs/WEB.md).

> **New: Market Intelligence Agents.** `python run.py --agents` runs a 23-agent research team: news, filings, forensics, ownership, macro and geopolitics, plus bull/bear review. The team turns its findings into an agent-adjusted intrinsic value, with every constant editable in [`agent_settings.yaml`](agent_settings.yaml). It can run on GitHub's cloud on a schedule, using free Groq / Gemini / NVIDIA API keys. See [docs/AGENTS.md](docs/AGENTS.md).

> **New: local AI with Ollama.** The agents can also use free models running on your own computer, with no API key or daily limit. Configuration → *Local AI (Ollama)* finds the models you already have, downloads new ones sized to the disk space you can spare, and switches them on or off. Ollama opens with INTVAL and stays open after it stops. See [docs/WEB.md](docs/WEB.md#ai-models).

> **New: installers.** Share INTVAL with people who don't have Python: `packaging/` builds a Windows setup `.exe` and a Linux setup wizard (folder choice, desktop shortcut, launch when finished, uninstaller). See [Installers](#installers-share-it-without-python).

> **New in 1.1.**
> - **More data sources, with fallback.** Yahoo Finance is no longer the only source. Screener.in fills the years Yahoo lacks (ten or more years of accounts against Yahoo's ~4), and the NSE and BSE websites take over prices and live quotes when Yahoo has none. Financial Modeling Prep, EODHD and Alpha Vantage join with a free key. You set the order in Configuration → Data sources. See [§9](#9-data-layer).
> - **Sector analysis.** Model Performance → Sectors shows which model is most accurate in each sector, what every model says each sector is worth today with a one-year projection, and how each sector splits into companies below, near and above value.
> - **Watchlists by sector or spreadsheet.** Fill a list as you create it, or later: search, take whole sectors at once (including NSE's index lists of ~1,000 companies), import Excel/CSV/pasted text, or copy another list.
> - **Research any watchlist** in one click from the Research workforce, the Agent Network, the Command Center or Coverage. Every company on the list is researched, valued before or not.
> - **A plain-English summary** at the top of every company's profile.
> - **A simpler workbench.** One place to start each kind of run, and no repeated buttons. Learning is now Model Performance → Training data.
> - **An updater** (`INTVAL-Update-<version>-…`) that upgrades an existing install in place. It backs up your data first and keeps it all: companies, watchlists, research history, the agents' memory, training data, settings and keys.

---

## Table of contents

1. [What it does](#1-what-it-does)
2. [Quick start](#2-quick-start)
3. [Project structure](#3-project-structure)
4. [How a run works (pipeline)](#4-how-a-run-works-pipeline)
5. [Input files](#5-input-files)
6. [Command-line reference](#6-command-line-reference)
7. [The web app](#7-the-web-app)
8. [Financial years and prices](#8-financial-years-and-prices)
9. [Data layer](#9-data-layer)
10. [Data-sufficiency check](#10-data-sufficiency-check)
11. [Estimation (gap-filling) layer](#11-estimation-gap-filling-layer)
12. [Valuation models](#12-valuation-models)
13. [Error handling and reason codes](#13-error-handling-and-reason-codes)
14. [Outputs](#14-outputs)
15. [Analysis stage (metrics and charts)](#15-analysis-stage-metrics-and-charts)
16. [Tools](#16-tools)
17. [Configuration reference](#17-configuration-reference)
18. [Testing offline](#18-testing-offline)
19. [Known limitations](#19-known-limitations)
20. [Troubleshooting](#20-troubleshooting)
21. [Extending the system](#21-extending-the-system)
22. [Glossary](#22-glossary)

---

## 1. What it does

For each company in your list and each financial year in the chosen window, the engine:

1. **Downloads** the income statement, balance sheet, cash-flow statement, daily price history and beta from Yahoo Finance (`yfinance`), with the NSE website as a fallback for prices only.
2. **Checks data sufficiency.** Companies without enough *reported* data are set aside, and the reason is recorded in plain English.
3. **Fills gaps** with documented estimation methods. Every estimated value is marked with `*`.
4. **Values the company** with up to eight models:

   | Traditional | Machine learning |
   |---|---|
   | DCF (two-stage FCFF) | XGBoost |
   | P/E Relative (sector median) | Random Forest |
   | EV/EBITDA (sector median) | LightGBM |
   | Graham Number | MLP Neural Network |

5. **Compares** each estimate with the **benchmark market price**: the closing price on the trading day nearest **1 May** after the financial year ends.
6. **Exports** an Excel workbook and several CSVs (report, numeric twin, diagnostics, methods, excluded companies).
7. **Analyses** model accuracy (MAE, RMSE, MAPE, MedAPE, bias, hit rate, Spearman, win rate) and renders charts plus an HTML report.

### Design principles

- **No silent blanks.** Every cell holds either a number or the specific reason no number exists.
- **Per-model exclusion.** If one model fails (for example, negative FCFF kills the DCF), the other models for that row still run.
- **Point-in-time discipline.** Valuing FY*t* uses only data from FY*t* and earlier. The benchmark price is taken *after* the year closes and is never used as an input.
- **Estimates are always visible.** Estimated values carry `*` in the report, and the Methods sheet records exactly how each one was produced.
- **Failed companies are listed, not dropped.** Excluded companies appear on their own sheet with the reason.

---

## 2. Quick start

**Just want to use it?** Run an installer from [Installers](#installers-share-it-without-python) (`INTVAL-Setup-…-windows-x64.exe` or `INTVAL-Setup-…-linux-x86_64`). It needs no Python, and the app opens in your browser. The steps below are for running it from the source code.

### Requirements

- **Python 3.10+** (the code uses `X | None` type syntax; the local `.venv` runs Python 3.14).

### Install

```bash
python -m venv .venv
```

```bash
.venv\Scripts\activate
```

```bash
pip install -r requirements.txt
```

Dependencies ([`requirements.txt`](requirements.txt)):

| Package | Purpose |
|---|---|
| `yfinance>=0.2.40` | Primary data source: financial statements and price history |
| `requests>=2.31` | NSE fallback and Yahoo ticker search |
| `pandas>=2.0`, `numpy>=1.24` | Data handling and maths |
| `matplotlib>=3.7` | Charts |
| `openpyxl>=3.1` | `.xlsx` writer |
| `scikit-learn>=1.4` | Random Forest, MLP, StandardScaler |
| `xgboost>=2.0` | XGBoost regressor |
| `lightgbm>=4.3` | LightGBM regressor |
| `fastapi>=0.110`, `uvicorn>=0.29` | The web app's local server |
| `PyYAML>=6.0`, `feedparser>=6.0` | HYBRID MODEL / agent settings and news feeds |

### Run

```bash
python run.py
```

This reads `data/companies.csv`, values FY2021 to FY2025, and writes everything to `output/`.

```bash
python run.py --web
```

This opens the web app in your browser instead (see §7). On Windows, double-clicking `Launch Workbench.bat` (or the `INTVAL Workbench` shortcut) does the same with the project's `.venv`, and just opens the browser if the app is already running.

```bash
python run.py --offline
```

This runs against the built-in synthetic dataset, with no network access needed.

### Installers (share it without Python)

`packaging/` turns the project into installers that need no Python or Node on the other computer. They land in `installers/`, which is git-ignored because each is several hundred MB; share them as GitHub release downloads.

| Platform | Build it with | You get |
|---|---|---|
| Windows 10/11 x64 | `powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1` | `INTVAL-Setup-<version>-windows-x64.exe`: a setup wizard (Inno Setup) with install folder choice, just-me or all-users, Start-menu and desktop shortcuts, launch when finished, and an uninstaller in Settings → Apps that asks before deleting your data |
| Linux x86_64 | `powershell -File packaging\build_linux.ps1` (Docker), or `bash packaging/linux/build_linux.sh` on Linux | `INTVAL-Setup-<version>-linux-x86_64`: a graphical setup wizard with the same choices (folder, desktop shortcut, applications menu, launch when finished) and an `uninstall.sh`; `--silent` installs without a display |

Each build also makes the **updater**: `INTVAL-Update-<version>-windows-x64.exe` and `INTVAL-Update-<version>-linux-x86_64`. Run it on a computer that already has INTVAL to upgrade in place:

1. It finds the existing installation wherever it is, per-user or all-users (on Windows from the uninstall entry; on Linux from `~/.config/intval/install.json` or the default folders). It refuses to run where INTVAL is not installed.
2. It backs up everything you own to `backups/<date>-<old>-to-<new>/` inside the install folder: `data/` (company lists, watchlists, training-data state), `output/intel/` (the research agents' memory and history), `agent_settings.yaml`, `.env` and `llm_providers.json`. The last five backups are kept.
3. It replaces only the program (`INTVAL.exe`, `_internal/`, `web/dist/`, docs and factory defaults).
4. It runs `INTVAL --migrate` ([`src/migrate.py`](src/migrate.py)). This adds the training companies the new version ships that your lists do not have, and any new settings sections, without changing a value you set. It is safe to run twice.

Shortcuts and the uninstaller stay as they are. An all-users install on Windows asks for administrator rights. The full Setup also works over an existing install: it now defaults to the folder INTVAL is already in, points you to the updater, and runs the same migration.

The installed app is one program (`INTVAL.exe` / `INTVAL`) that opens the workbench in your browser. Its data, settings and reports live in the install folder, which the Windows installer makes writable even under Program Files. macOS installers have to be built on a Mac and are not set up.

How the installed app differs from a source checkout: it sets `INTVAL_HOME` to its own folder (read by `config.PROJECT_ROOT` and `server/data.py`), opens the web app when started with no arguments, and runs background jobs by calling itself (`INTVAL.exe <run.py flags>`) instead of `python run.py`. It ships `agent_settings.defaults.yaml` as its starting settings, never your `.env`, `llm_providers.json`, `output/` or `data/live/`. The Linux build uses the CPU-only `xgboost-cpu` package, which leaves out NVIDIA's ~300 MB GPU library.

---

## 3. Project structure

```
intrinsic-value-calculator/
│
├── run.py                        Entry point (CLI + --web). Sets up sys.path and logging,
│                                 parses flags, pushes them onto config, dispatches.
├── Launch Workbench.bat          Double-click launcher: starts the web app and opens the browser.
├── INTVAL Workbench.lnk          Shortcut to the launcher, with the project icon.
├── agent_settings.yaml           Your HYBRID MODEL constants and research-agent settings.
├── agent_settings.defaults.yaml  Factory defaults for the above (the web app's "reset").
├── requirements.txt              Python dependencies.
├── .env.example                  Template for API keys (copy to .env).
├── .gitignore                    Ignores output/, .cache/, .venv/, build/, installers/, secrets, editor files.
├── .vscode/settings.json         python.analysis.extraPaths so the flat imports resolve in VS Code.
├── .github/workflows/
│   └── market-intel.yml          Scheduled cloud run of the research agents.
│
├── assets/
│   ├── intval.ico                Project icon (same as the web app's tab icon), for Windows.
│   └── intval.png                The same icon as a 512 px PNG.
│
├── docs/
│   ├── PRD.md                    Product requirements document.
│   ├── WEB.md                    The browser workbench.
│   ├── AGENTS.md                 The market intelligence agents.
│   └── HYBRID_MODEL.md           The HYBRID MODEL formula.
│
├── src/                          The valuation engine and the research agents.
│   ├── config.py                 ALL assumptions and switches. Single source of truth.
│   ├── model_registry.py         The one list of models; which are enabled; column names.
│   ├── pipeline.py               Orchestrator: fetch → screen → estimate → value → export → analyse.
│   ├── sufficiency.py            Data-sufficiency check (runs before estimation).
│   ├── estimation.py             Gap-filling ladder (back-cast, CAGR, sector ratios, identities).
│   ├── overrides.py              Loads data/fundamentals_override.csv; manual values always win.
│   ├── result.py                 Result carrier (value | reason) + reason-code vocabulary.
│   ├── fy_utils.py               FY date maths, benchmark date, FY labels, numeric helpers.
│   ├── plain_reasons.py          Translates exclusion verdicts into plain English.
│   ├── csv_analyzer.py           Accuracy metrics, HD charts, HTML report.
│   ├── hybrid_formula.py         The HYBRID MODEL formula, shared by the report and the agents.
│   ├── auto_train.py             Grows the ML training universe one company at a time.
│   ├── learning.py               Learning data: every company the app knows beyond the input list.
│   ├── ssl_trust.py              Makes Python trust the certificates Windows trusts.
│   │
│   ├── migrate.py                After an update: back up, then add new training companies and settings sections.
│   │
│   ├── sources/                  Where the data comes from (Configuration → Data sources sets the order).
│   │   ├── data_hub.py           One company from every provider, merged: Yahoo first, the others fill gaps.
│   │   ├── source_settings.py    Which providers are on, their order, their keys (data/live/sources.json, .env).
│   │   ├── yf_source.py          Yahoo Finance: statements, prices, benchmark, per-field diagnosis.
│   │   ├── screener_source.py    Screener.in: ten-plus years of annual accounts for NSE/BSE companies.
│   │   ├── price_chain.py        Daily closes from the first provider that has them (Yahoo NSE/BSE, NSE, BSE, keyed).
│   │   ├── nse_source.py         NSE website: closes, last price, index constituents with their industry.
│   │   ├── bse_source.py         BSE website: closes and last price by scrip code.
│   │   ├── keyed_sources.py      Financial Modeling Prep, EODHD, Alpha Vantage (free keys).
│   │   ├── ticker_resolver.py    Company name → Yahoo ticker (explicit → manual map → cache → search).
│   │   └── mock_source.py        Deterministic offline dataset that triggers every reason code.
│   │
│   ├── models/                   One file per valuation model.
│   │   ├── model_dcf.py          Two-stage FCFF DCF.
│   │   ├── model_pe.py           Sector-median P/E relative valuation.
│   │   ├── model_ev_ebitda.py    Sector-median EV/EBITDA relative valuation.
│   │   ├── model_graham.py       Graham Number.
│   │   ├── model_residual_income.py Residual Income (Edwards-Bell-Ohlson).
│   │   ├── capital.py            Cost-of-capital helpers for Residual Income and the Hybrid.
│   │   ├── model_ensemble.py     Ensemble (formerly "Hybrid"): gated, error-weighted blend.
│   │   ├── model_hybrid_model.py Runs the HYBRID MODEL over every company-year in the report.
│   │   ├── ml_common.py          Shared ML pipeline: features, labels, folds, preprocessing, metrics.
│   │   ├── model_xgboost.py      XGBoost estimator spec.
│   │   ├── model_random_forest.py Random Forest estimator spec.
│   │   ├── model_lightgbm.py     LightGBM estimator spec.
│   │   └── model_mlp.py          MLP (StandardScaler + MLPRegressor pipeline).
│   │
│   ├── io_layer/
│   │   ├── inputs.py             Tolerant CSV reader (auto-detects delimiter/header) + terminal input.
│   │   └── exporter.py           Writes report, numeric twin, diagnostics, methods, exclusions.
│   │
│   └── agents/                   The 23-agent research team (see docs/AGENTS.md).
│       ├── runner.py             One research cycle, start to finish.
│       ├── chief.py              The five research leads and the Chief Market Intelligence Officer.
│       ├── team_equity.py        Equity research team (numbers only).
│       ├── team_news.py          Market news team.
│       ├── team_market.py        Market activity and ownership team.
│       ├── team_industry.py      Industry and geopolitical team.
│       ├── team_review.py        Independent review team (runs last).
│       ├── base.py               Evidence, Finding, Agent: the shared vocabulary.
│       ├── blackboard.py         The SQLite file every agent reads and writes.
│       ├── comms.py              Roster and message bus.
│       ├── protocol.py           Who tells whom what, and when, for one company.
│       ├── context.py            Everything the team knows about one company during a run.
│       ├── feeds.py              Every outside fact the agents use.
│       ├── forensics.py          Forensic accounting scores.
│       ├── llm.py                LLM router across free API tiers.
│       ├── llm_providers.py      Every AI provider, how to reach it, and its keys.
│       ├── profiles.py           Per-agent tuning set from the web app.
│       ├── settings.py           Loads agent_settings.yaml.
│       ├── report.py             Markdown, JSON and HTML run outputs.
│       └── notify.py             Optional Telegram alert after a run.
│
├── server/                       Local web API (FastAPI) for the browser app.
│   ├── app.py                    Routes: JSON under /api, the built React app everywhere else.
│   ├── data.py                   Readers for everything the calculator and agents write to disk.
│   ├── jobs.py                   Background runs (each a child `python run.py ...`).
│   ├── prefs.py                  Run preferences.
│   ├── live.py                   Live market data, scanner and watchlists (quotes fall back to NSE / BSE).
│   ├── directory.py              The sector directory: known companies + NSE's index lists, by sector.
│   ├── learning_api.py           The web side of src/learning.py.
│   ├── hybrid_api.py             HYBRID MODEL Studio: live what-if evaluations.
│   ├── agents_api.py             The research workforce: roster, messages, live state.
│   ├── agent_chat.py             The Research Room chat with the agents.
│   ├── autostart.py              Starts the research workforce with the web app.
│   ├── llm_api.py                AI provider management.
│   ├── ollama_api.py             Ollama: local models, downloads, launch with INTVAL.
│   └── yaml_patch.py             Edits agent_settings.yaml without losing its comments.
│
├── web/                          React front end (src/ = source, dist/ = the built app).
│
├── tools/                        Standalone scripts.
│   ├── analyze.py                Re-run the analysis stage on an existing results CSV.
│   ├── make_override_template.py Builds a fill-in sheet of every missing fundamental.
│   ├── build_training_universe.py Builds data/training_universe.csv from NSE lists.
│   └── screener.py               Optional: screens a candidate universe into a companies CSV.
│
├── tests/
│   ├── test_agents.py            HYBRID MODEL and research agents (offline).
│   ├── test_live.py              Live market layer, watchlists, sector directory, learning data (offline).
│   ├── test_sources.py           Data providers: Screener.in parsing, price fallback, the merge (offline).
│   ├── test_update.py            Updating without losing data: migration, backups, the Linux updater.
│   └── test_ollama.py            The Ollama section and local-model calls (offline).
│
├── packaging/                    Builds the installers into installers/ (see §2).
│   ├── intval.spec               PyInstaller recipe: the app frozen into one folder.
│   ├── stage.py                  Adds web/dist, starter data and default settings.
│   ├── wizard_art.py             Draws the installers' artwork from the icon.
│   ├── build_windows.ps1         Windows: freeze → stage → Inno Setup.
│   ├── windows/intval.iss        The Windows setup wizard.
│   ├── build_linux.ps1           Linux, from Windows through Docker.
│   └── linux/
│       ├── build_linux.sh        Linux: freeze → stage → one-file installer.
│       └── installer.py          The Linux setup wizard (Tk), with a text mode.
│
├── data/
│   ├── companies.csv             Main input (~42 companies, 9 sectors, explicit NSE tickers).
│   ├── training_universe.csv     ML training universe (tools/build_training_universe.py).
│   ├── auto_training_universe.csv Candidate pool for auto-train.
│   ├── fundamentals_override.csv Manual fundamentals sheet (currently header only).
│   └── live/                     Watchlist and minute-bar store (git-ignored).
│
├── output/                       Generated on each run (git-ignored; see §14).
│   └── intel/                    The research agents' memory and reports.
├── installers/                   The built setup files (git-ignored; see §2).
├── build/                        PyInstaller work folders (git-ignored, safe to delete).
└── .cache/                       Ticker lookups and the training-data download cache (git-ignored).
```

### Import convention

Every module is imported **flat** (`import config`, never `import src.config`). [`run.py`](run.py), [`server/__init__.py`](server/__init__.py) and [`tools/analyze.py`](tools/analyze.py) each add `src/`, `src/sources/`, `src/models/`, `src/io_layer/` and `tools/` to `sys.path` at startup. Mixing the two import styles would load two copies of `config`, and CLI flags would stop taking effect. [`.vscode/settings.json`](.vscode/settings.json) mirrors these paths so the editor resolves the imports.

---

## 4. How a run works (pipeline)

[`src/pipeline.py`](src/pipeline.py) → `run(companies, extra_training=None)`:

```
run.py
  │  setup_logging()  →  output/run_log.txt (DEBUG)
  │  apply_args()     →  CLI flags written onto config
  │  load_companies() →  --offline mock | --input CSV | data/companies.csv | terminal prompt
  ▼
pipeline.run()
  │
  ├─ overrides.ensure_template_exists() / load()
  │
  ├─ build_universe()           per company:
  │     ticker_resolver.resolve()  →  ticker
  │     yf_source.fetch_company()  →  {beta, years:{FY:{fields, _diag, _notes}}}
  │        └─ nse_source (price fallback)    └─ overrides.apply() per FY
  │
  ├─ sufficiency.screen()       ON REPORTED DATA ONLY (before estimation)
  │     └─ auto-relax if nobody passes
  │
  ├─ (optional) --train-universe → extra companies for ML training only
  │
  ├─ estimation.fill_universe() gap-filling, every fill recorded in _method
  │
  ├─ peer tables                model_pe.build_sector_pe_table()
  │                             model_ev_ebitda.build_sector_table()
  │
  ├─ ML stage                   ml_common.build_dataset() → run_models() → write_diagnostics()
  │
  ├─ value                      for each kept company × FY (oldest first):
  │                             DCF, P/E, EV/EBITDA, Graham, + each enabled ML model
  │                             each wrapped in guard() → CALCULATION ERROR on crash
  │
  ├─ exporter.export()          report CSV/XLSX, data twin, diagnostics, methods, exclusions
  │
  ├─ console summary            model coverage, ML fold performance, reason tally,
  │                             plain-English summary
  │
  └─ csv_analyzer.run_analysis() metrics CSVs, charts, analysis_report.html
```

**Why the order matters:**

- The **sufficiency check runs before estimation**, because estimation can produce a plausible value for almost any gap. Run afterwards, the check would never fail anyone.
- **Estimation runs before the peer tables** are built, so sector medians use the filled data.
- **All companies are fetched before any valuation**, because the relative models need sector medians built from every company.

`pipeline.screen_only()` runs fetch → screen → export exclusions and then stops (`--screen-only`).

---

## 5. Input files

### `data/companies.csv`

```csv
company name,sector name,market cap,ticker
Hindustan Aeronautics Limited,Defence and Aerospace,Large,HAL.NS
Bharat Electronics Limited,Defence and Aerospace,Large,BEL.NS
```

| Column | Required | Notes |
|---|---|---|
| `company name` | ✅ | Aliases: `company`, `name` |
| `sector name` | ✅ (else `Unclassified`) | Alias: `sector`. Determines peer groups for P/E and EV/EBITDA. |
| `market cap` | — | `Large` / `Mid` / `Small`. Alias: `cap`. Becomes the ML feature `cap_tier_ord`. |
| `ticker` | Recommended | Skips the name search. A bare symbol gets `EXCHANGE_SUFFIX` (`.NS`) appended. |

The reader in [`src/io_layer/inputs.py`](src/io_layer/inputs.py) is tolerant:
- **Detects the delimiter automatically** (`,` tab `;` `|`), so a spreadsheet copy-paste saved as `.csv` still loads.
- **Detects a missing header** and falls back to positional columns.
- **Reports ragged rows by line number** instead of crashing. If a company name contains a comma, quote it: `"Emami, Ltd",FMCG,Mid,EMAMILTD.NS`.
- Handles UTF-8 files with or without a BOM.

The current sample covers Defence & Aerospace, IT, Power & Renewables, Healthcare & Medical Devices, Metals & Mining, FMCG, Autos, FinTech and Tobacco. **Aim for at least 4 companies per sector.** With fewer, the peer medians become largely self-referential.

### `data/fundamentals_override.csv`

```
ticker,fy,ebit,ebitda,eps,net_income,da,capex,delta_nwc,ocf,total_debt,cash,shares,revenue,assets,cur_liab,equity
```

- One row per company-year. Blank cells are ignored.
- **Override values always win** over the downloaded data, and they are applied *before* the sufficiency check, so they count as reported data.
- **Units:** absolute rupees for money fields (not crore or lakh), rupees per share for `eps`, an absolute count for `shares`.
- Generate a pre-filled template with `python run.py --make-override-template`.

### Other files in `data/`

`training_universe.csv` and `auto_training_universe.csv` feed the ML training and auto-train stages. To value a different list, pass any standard-format companies CSV with `--input`.

---

## 6. Command-line reference

```bash
python run.py [options]
```

| Flag | Effect |
|---|---|
| `--web` | Open the web app (`--port`, `--no-browser`) |
| `--input PATH` | Companies CSV (default `data/companies.csv`; if that is missing, you are prompted in the terminal) |
| `--offline` | Use the synthetic mock dataset; no network |
| `--start-year FY` / `--end-year FY` | Financial-year window, named by the year the FY **ends** (2021 = 2020-21). Default 2021–2025 |
| `--models LIST` | Comma list from `dcf,pe,ev,graham,xgboost,random_forest,lightgbm,mlp`. Models you leave out lose their columns |
| `--no-ml` | Disable the whole ML stage |
| `--ml-split {expanding,loyo}` | ML fold strategy (config default is `hybrid`) |
| `--train-universe PATH` | Extra CSV of companies used **only** to train the ML models |
| `--train-universe auto` | Fetch training companies one by one until the Ensemble is confident (§16, Auto-train). Tuned with `--auto-target`, `--auto-max`, `--auto-sectors`, `--auto-min-listed-years`, `--auto-batch`, `--auto-patience`, `--auto-sector-rank`, `--auto-include-financials`, `--auto-no-cache` |
| `--benchmark-basis {may1,mean,close}` | Benchmark price basis; `mean` and `close` are robustness re-runs |
| `--mean-basis {trading,calendar}` | How the in-FY mean (anchor) price is averaged |
| `--fy-labels {range,int}` | Financial Year column shows `2023-24` or `2024` |
| `--exchange {.NS,.BO}` | Default suffix for bare tickers |
| `--reasons {code,detailed,off}` | How empty cells are annotated in the main report |
| `--no-overrides` | Ignore `fundamentals_override.csv` |
| `--make-override-template` | Fetch, then write a fill-in sheet for every gap |
| `--screening {enforce,report,off}` | Data-sufficiency check mode |
| `--min-complete-fy N` | Complete FYs required to stay in |
| `--min-benchmark-fy N` | FYs that must carry a benchmark price |
| `--screen-only` | Fetch and screen, write the exclusion sheet, then stop |
| `--no-analyze` | Skip the charts and statistics stage |
| `--dpi N` | Chart resolution (default 200) |

Examples:

```bash
python run.py --start-year 2022 --end-year 2025 --models dcf,pe,ev,graham
```

```bash
python run.py --screen-only --min-complete-fy 3
```

```bash
python run.py --benchmark-basis mean --no-ml
```

---

## 7. The web app

```bash
python run.py --web
```

This opens `http://127.0.0.1:8765` in your browser. The server listens on this
computer only, and every run is a separate `python run.py` process, so a
crash or a closed tab cannot take the app down. The app replaces the old
Tkinter desktop GUI, and every one of that GUI's features is in it:

| Page | What it does |
|---|---|
| **Command Center** | Headline numbers, a coverage map of every researched company, signals, upside vs confidence, the model leaderboard, and one **Research** button |
| **Markets** | Live indices, a market scanner and charts |
| **Watchlists** | Named lists tracked live, with alerts and notes. Add companies by search, whole sectors, a spreadsheet or another list; research a list in one click |
| **Coverage** | Every researched company. Each has a profile: a plain-English summary, the valuation, every model's forecast (with Show all / Remove all), drivers and risk, the agents' evidence, bull vs bear, history |
| **HYBRID MODEL Studio** | Change any constant and see values, ranges, lenses and the bridge respond live, then commit |
| **Research workforce** | The 23 agents: Overview (teams, run output, past runs, **Research** on any watchlist, auto-start), the live Agent Network (with your own links and notes) and the Research Room chat |
| **Model Performance** | Leaderboard · **Sectors** (best model per sector, sector forecast by model, sector segregation and prediction) · Company (every model, HYBRID MODEL and Ensemble detail) · **Training data** (what the AI models learn from, in plain words) · Files & charts |
| **Universe** | Edit `data/companies.csv` |
| **Operations** | One form for every job: a valuation report, research (quick or full), a training-data refresh or a data check, on every company, a watchlist or the ones you pick. Jobs are followed live |
| **Configuration** | Run settings, **data sources**, AI providers (including local Ollama models), research agents, notifications, macro inputs, the raw settings file |

[docs/WEB.md](docs/WEB.md) has the details.

---

## 8. Financial years and prices

### Financial-year convention

**FY *N* = 1 April *N*−1 → 31 March *N*.** FY2024 is labelled `2023-24`.

`config.set_fy_range(start, end)` moves the window. It swaps the ends if they are reversed, caps `end` at the latest *completed* FY, applies a floor of `FY_MIN_ALLOWED` (2000), and limits the span to `FY_MAX_SPAN` (30) years. Everything downstream reads `config.FY_LIST`.

Statement columns are mapped to FYs by the **midpoint of the reporting period** (`fy_utils.fy_for_period_end`). As a result, companies with non-March year-ends (for example, Siemens reports October–September) still land in the correct FY.

### Three prices, not interchangeable

| Field | What it is | Used for |
|---|---|---|
| `price` (**anchor**) | Mean of daily closes **inside** FY*t* | **Model input:** WACC equity weight, observed P/E and EV/EBITDA multiples, ML features |
| `price_fwd` | Mean of daily closes in FY*t+1* | Numerator of the ML training label only |
| `price_bench` (**benchmark**) | Close on the trading day **nearest 1 May** of year *t* (one month after FY*t* ends) | **Scoring only**, shown as "Market Price" in the report |

- **Anchor guards:** fewer than `MIN_TRADING_DAYS_FOR_FY` (60) sessions in the year means the price is unavailable. Fewer than `PARTIAL_YEAR_SESSIONS` (200) means the price is used but flagged as a partial year, which is typical for recent IPOs.
- **Benchmark:** 1 May is Maharashtra Day, a market holiday, so the nearest session within `BENCHMARK_MAX_OFFSET_DAYS` (10) is used. The date actually used is published in the *Benchmark Date* column.
- **Robustness bases:** `--benchmark-basis mean` (mean of FY*t+1*) and `close` (last close of FY*t+1*).
- Prices are fetched with `auto_adjust=False`. They are adjusted for splits and bonuses, but not for dividends.

---

## 9. Data layer

### Ticker resolution: [`src/sources/ticker_resolver.py`](src/sources/ticker_resolver.py)

The resolver tries these sources in order:
1. **Explicit ticker** from the CSV.
2. **`MANUAL` map** of hand-verified symbols, matched on the raw name *and* the name with suffixes such as "Limited" stripped.
3. **Cache** in `.cache/tickers.json`.
4. **Yahoo search**: full name, then trimmed name, then a BSE (`.BO`) preference.

Successful search results are cached. A failure becomes `TICKER NOT RESOLVED` for that company.

### Yahoo extraction: [`yf_source.py`](src/sources/yf_source.py)

- Downloads the income statement, balance sheet, cash flow, price history (from the start of the first FY to the end of FY+1) and the `info` block for beta. **Each download is wrapped separately.**
- **Alias lists** resolve renamed line items. For example, `ebit` matches `EBIT` → `Operating Income` → `Total Operating Income As Reported`, and `eps` prefers Diluted over Basic.
- **Sign normalisation:** `capex` is stored as a positive magnitude, and `delta_nwc` is positive when working capital increases.
- **Fields per year:** `ebit, ebitda, eps, net_income, da, capex, delta_nwc, ocf, total_debt, cash, shares, tax_rate, revenue, assets, cur_liab, equity, price, price_fwd, price_bench, price_bench_date`.
- **Effective tax rate:** `tax_provision / pretax`, clamped to [5%, 45%]. Falls back to 25.17%.
- **Beta** is accepted only within (0.1, 3.0). Otherwise `DEFAULT_BETA` (1.0) is used.
- **Every missing field** records a `(code, detail)` pair in `d["_diag"]`. Every provenance note goes to `d["_notes"]`.
- Overrides are applied per FY at the end, through `overrides.apply()`.

### Every provider, merged: [`src/sources/data_hub.py`](src/sources/data_hub.py)

The pipeline, the learning feed and the auto-trainer fetch through `data_hub.fetch_company`. It asks the providers in the order set in **Configuration → Data sources** (saved in `data/live/sources.json`). The first provider with a figure supplies it, and later ones fill only what is still missing.

| Order | Provider | Supplies | Key |
|---|---|---|---|
| 1 | Yahoo Finance (NSE listing), [`yf_source.py`](src/sources/yf_source.py) | statements (~4 years), prices, quotes | none |
| 2 | Screener.in, [`screener_source.py`](src/sources/screener_source.py) | ten-plus years of P&L, balance sheet, cash flow | none |
| 3 | Yahoo Finance (BSE listing, `.BO`) | statements, prices | none |
| 4 | NSE website, [`nse_source.py`](src/sources/nse_source.py) | daily closes, last price, index lists with each company's industry | none |
| 5 | BSE website, [`bse_source.py`](src/sources/bse_source.py) | daily closes, last price | none |
| 6–8 | Financial Modeling Prep, EODHD, Alpha Vantage, [`keyed_sources.py`](src/sources/keyed_sources.py) | statements and/or prices | free key in `.env` (`FMP_API_KEY`, `EODHD_API_KEY`, `ALPHAVANTAGE_API_KEY`) |

- **What counts as missing:** a field with no value, and any field Yahoo only *assumed* (zero debt, zero cash, no working-capital change, statutory tax, today's share count). A reported figure from a later provider replaces the assumption and removes its note.
- **Screener.in mapping** (rupees crore → rupees): EBIT = profit before tax + interest; EBITDA = EBIT + depreciation; equity = equity capital + reserves; shares = net profit ÷ EPS. Capex is estimated as the change in fixed assets and CWIP plus depreciation, and is flagged as an estimate. Lenders (banks, NBFCs) get no EBIT from it, because their "interest" is what they pay depositors.
- **Prices** come from [`price_chain.py`](src/sources/price_chain.py). Yahoo NSE comes first, then Yahoo BSE, then NSE, then BSE, then the keyed providers. A series counts only if it covers a quarter of the window.
- **If Yahoo fails outright**, the company is built from the other providers instead of being dropped.
- **Manual overrides still beat every provider.**
- **Notes say where each number came from**, e.g. "filled from Screener.in: ebit, eps, shares". The console run log adds `via Screener.in` per company.
- **Live quotes:** when Yahoo has no quote for a tracked company, the tracker asks NSE, then BSE.
- **Sector lists:** NSE's index lists (Total Market, Nifty 500, Microcap 250) feed the watchlists' sector import (`server/directory.py`), cached for a week.
- **Unofficial endpoints:** the NSE and BSE endpoints are the ones their own websites use. They need cookies and a browser-like header, change without notice, and **block many datacentre and VPN addresses**, so they work best from a home connection. A provider that does not answer is skipped; nothing stops a run.

---

## 10. Data-sufficiency check

[`src/sufficiency.py`](src/sufficiency.py) runs after the fetch and before estimation. It only inspects **reported or override** data.

- A year is **complete** when every field in `SUFFICIENCY_REQUIRED_FIELDS` is present: revenue, ebit, ebitda, net_income, eps, ocf, capex, shares, total_debt, cash and equity. The in-FY anchor price is also required if `SUFFICIENCY_REQUIRE_ANCHOR_PRICE` is on.
- A company **passes** with at least `MIN_COMPLETE_FY` complete years **and** at least `MIN_BENCHMARK_FY` years that have a benchmark price. Both default to 3, and both are clamped to the window length.
- **Modes:** `enforce` drops failing companies from the report. `report_only` flags them without dropping anyone. Disabling the check keeps everyone.
- **Auto-relax:** if *nobody* passes, the threshold drops to the best result any company achieved, for this run only, and a loud warning is printed.
- **Excluded companies stay in the peer medians and the ML training data by default** (`SUFFICIENCY_KEEP_IN_PEERS`, `SUFFICIENCY_KEEP_IN_ML`). Thin data is not wrong data.
- Each record also reports how many years each traditional model *could* still have run, which helps you see near-misses.

**Why the default is 3:** a 52-company screening run on 30 Aug 2026 found that no company had more than 3 complete years, including TCS, Infosys, HUL and ITC. yfinance serves only about 4 annual periods, so the earliest years are missing for everyone. This is a limit of the data source, not a judgement on the companies.

[`src/plain_reasons.py`](src/plain_reasons.py) sorts each excluded company into exactly one plain-English category, in this order:

1. *Nothing could be downloaded*
2. *Bank or lender – these methods do not fit*
3. *Company is too new or listed too recently*
4. *Not enough complete years of accounts*
5. *Not enough share-price history*

Each category comes with a short explanation and a suggested next step.

---

## 11. Estimation (gap-filling) layer

[`src/estimation.py`](src/estimation.py), mode `ESTIMATION_MODE = "balanced"` (`"off"` disables it).

For each field, the first rung of this ladder that works wins:

| Rung | Method |
|---|---|
| 1 | Reported by yfinance |
| 2 | Manual override |
| 3 | Derived identity: `EBITDA = EBIT + D&A`, `EPS = Net income / Shares` |
| 4 | `backcast_revenue`: nearest known year scaled by the revenue ratio |
| 5 | `backcast_cagr`: nearest known year scaled by the company's own CAGR |
| 6 | `sector_ratio`: revenue × sector-median margin for that sector-year (falls back to the global median) |

- Revenue is filled first, because every ratio depends on it. Shares are carried over from the nearest year.
- Back-casts are clamped to between `BACKCAST_MIN_RATIO` (0.33×) and `BACKCAST_MAX_RATIO` (3×) of the source value.
- `delta_nwc` defaults to 0 and `tax_rate` to the statutory rate.
- **Every fill is recorded** in `d["_method"][field]`. From there it flows into `Result.method`, the `*` marker in the report, and the Methods sheet.
- `normalised(years, fy, field)` returns the median of the positive values up to FY*t*. The models use it when one year is loss-making but the company's history is profitable (`USE_NORMALISED_EARNINGS`, which needs at least 2 years).

---

## 12. Valuation models

All models share one contract: they **return a `Result`** (a value, or a reason code plus detail) and **never raise**. [`src/model_registry.py`](src/model_registry.py) defines the model list, the column names and the enabled flags, and every other module reads from it.

### 12.1 DCF: [`model_dcf.py`](src/models/model_dcf.py)

```
FCFF   = EBIT × (1 − t) + D&A − CapEx − ΔNWC        (fallback: OCF − CapEx)
Ke     = Rf + β × ERP = 7.05% + β × 5.50%
WACC   = E/(D+E)·Ke + D/(D+E)·Kd·(1 − t),  Kd = 8.5%,  E = anchor price × shares
WACC   = max(WACC, g_terminal + 2%)
g      = CAGR of positive FCFF up to FY t, clamped to [2%, 18%]  (default 8%)
EV     = Σ FCFF₀(1+g)ⁿ/(1+WACC)ⁿ  (n = 1..5)  +  TV/(1+WACC)⁵
TV     = FCFF₅ × (1 + 5%) / (WACC − 5%)
Value  = (EV − (Debt − Cash)) / Shares
```

If FCFF for the year is negative, the model uses the median of the positive FCFF years (at least 2 needed) and marks the result as estimated. Failure codes: `NOT MEANINGFUL` (shares ≤ 0, or FCFF negative with no positive history), `NEGATIVE EQUITY VALUE`, `CALCULATION ERROR`.

### 12.2 P/E Relative: [`model_pe.py`](src/models/model_pe.py)

```
Value = EPS(FY) × benchmark P/E(sector, FY)
observed P/E = anchor price / EPS,  kept only if EPS > 0 and 2 ≤ P/E ≤ 120
```

The benchmark P/E comes from the first of these that works:

1. Sector median **excluding the company itself**, if there are ≥ `MIN_PEERS_FOR_MEDIAN` (2) peers.
2. Sector median including the company.
3. The company's own historical median.
4. The whole-universe median for that FY.
5. Otherwise, `NO PEER BENCHMARK`.

Negative EPS is normalised when history allows it.

### 12.3 EV/EBITDA: [`model_ev_ebitda.py`](src/models/model_ev_ebitda.py)

```
observed EV/EBITDA = (price × shares + debt − cash) / EBITDA,  kept if 1 ≤ x ≤ 60
Value = (EBITDA × benchmark multiple − (Debt − Cash)) / Shares
```

The benchmark follows the same ladder as P/E. Net debt is subtracted exactly once. Banks and NBFCs never produce a usable multiple.

### 12.4 Graham Number: [`model_graham.py`](src/models/model_graham.py)

```
Value = √(22.5 × EPS × Book value per share)        22.5 = P/E 15 × P/B 1.5
```

This is a conservative **ceiling price**, not a full valuation. It needs positive EPS (normalised when history allows) and positive book value. Results above `GRAHAM_MAX_MULTIPLE_OF_BVPS` (8×) book value per share are reported but flagged on the Methods sheet.

### 12.4b Residual Income: [`model_residual_income.py`](src/models/model_residual_income.py)

```
Value = B₀ + RI₁ / (1 + Ke − ω)          RI₁ = (ROE* − Ke) × B₀
```

- `B₀` is book equity at FY end.
- `ROE*` is the median ROE (on average equity) over the last `RI_ROE_LOOKBACK` (3) years up to FY*t*, clamped to [−50%, 60%].
- `Ke` is CAPM on the **adjusted beta**.
- `ω` (`RI_PERSISTENCE` = 0.62) is how long excess returns persist, from Ohlson's linear-information model.

This model works for **banks** and **loss-makers**: a below-par ROE gives a value below book instead of a refusal. Most of its value comes from the observed book value rather than a terminal-value assumption.

**Adjusted beta** ([`capital.py`](src/models/capital.py)): `β_adj = 0.67 × β_company + 0.33 × β_sector-median`. When Yahoo has no beta for the company, the sector median is used. The original DCF keeps the raw beta so that the baseline stays unchanged.

### 12.4c Ensemble (formerly "Hybrid"): [`model_ensemble.py`](src/models/model_ensemble.py)

```
Ensemble = exp( Σ_k w_k · (ln V_k − c_k) )   over the components k that apply to this company-year
```

The Ensemble runs after the single models, over the whole grid, and has four layers:

1. **Regime gate.** Each company-year is classed as `lender`, `loss_maker`, `young` or `mature`. `HYBRID_REGIME_WEIGHTS` sets which components apply; a 0 removes a component outright (for example, no DCF or EV/EBITDA for a lender).

2. **Upgraded components:**
   - **DCF+:** three stages. Growth starts from a blend of reinvestment rate × ROIC and the historical CAGR, holds for 5 years, then fades to the terminal rate over 5 more. The terminal value uses the value-driver formula `TV = NOPAT(1+g)(1 − g/RONIC)/(WACC − g)`, which charges for the reinvestment that growth requires. Discounted with the adjusted beta.
   - **Residual Income.**
   - **P/E-reg and EV-reg:** the benchmark multiple is predicted by a ridge regression on fundamentals (ROE or EBITDA margin, growth, leverage), pooled across years ≤ *t* and demeaned by year. It is then blended 50/50 with the ex-self sector median. Thin sectors borrow information from the whole sample.
   - **Graham.**
   - **ML consensus:** the geometric mean of the learners, counted as one vote.

3. **Calibration and learned weights, all point-in-time.** For each component, the errors `ln(V/benchmark)` from earlier years in the same sector are used (falling back to the whole sample). Each component is shifted by its median miss `c_k`, shrunk by evidence `n/(n+10)`. Its weight is the inverse squared remaining error relative to the other components, also shrunk toward equal. That weight is then multiplied by the regime weight and by 0.75 if the component rests on estimated inputs. Components more than 3× from the weighted median are dropped as outliers.

4. **Uncertainty.** A correlated Monte Carlo over each component's historical error, plus the disagreement between models, gives a **P10–P90 range** and a **confidence score from 0 to 100** (High ≥ 60, Medium ≥ 35). The score is a probability: the simulated chance that the market price lands within ±20% (`HYBRID_CONF_TOLERANCE`) of the Ensemble value, discounted when components are missing or rest on estimated inputs. Each run prints a **calibration check** comparing the predicted percentage with the share that actually landed within 20%.

Every row's regime, component values, calibrations, weights, range and confidence are written to `output/Ensemble_Detail.csv`. Set `HYBRID_BIAS_CORRECT = False` to see the uncalibrated ensemble.

**Limits:** the first year of any window has no error history, so it falls back to the regime-weighted equal mix. The weights reward closeness to the 1-May price, so the Ensemble inherits the study's own definition of "accurate".

### 12.4d HYBRID MODEL: [`hybrid_formula.py`](src/hybrid_formula.py)

The headline value. Six lenses (cash flow, earnings power, asset, market, conservative, learning) are each calibrated against their own earlier misses. They are blended by company type, with a growth-credibility gate that only pays for growth the moat earns. The result is then adjusted for quality and governance, and run through bull / base / bear scenarios. It runs in the valuation report for every company-year (from the accounts alone, point-in-time) and in the research runs (with the agents' signals). Every constant is in `agent_settings.yaml -> hybrid_model` and can be tuned live in the web app's HYBRID MODEL Studio. Full method: [docs/HYBRID_MODEL.md](docs/HYBRID_MODEL.md). Per-row detail: `output/Hybrid_Model_Detail.csv`.

### 12.5 Machine-learning models: [`ml_common.py`](src/models/ml_common.py)

**Target.** There is no ground-truth intrinsic value to train on, so the models learn a forward price ratio:

```
label = price_fwd / price            (mean price FY t+1 ÷ mean price FY t)
IV    = price × predicted ratio
```

**Features (21 + sector one-hots):** ebitda_margin, net_margin, roe, roce, debt_to_equity, net_debt_to_ebitda, interest_free_proxy, capex_to_revenue, ocf_to_ebitda, accruals_ratio, asset_turnover, earnings_yield, book_to_price, fcf_yield, ev_ebitda, revenue/ebitda/eps 1-year growth, beta, log_market_cap, cap_tier_ord. A row needs at least `ML_MIN_FEATURES` (4) of these. Missing values are filled from the sector-year median (`ML_IMPUTE_FROM_SECTOR`).

**Validation.** Each fold represents one FY:
- `expanding`: trains only on years before *t*. This is correct, but it leaves the early years empty.
- `loyo`: leave-one-year-out. This leaks future data, so use it for comparison only.
- `hybrid` (default): uses expanding where there are at least `ML_MIN_TRAIN_ROWS` (25) labelled rows, and falls back to LOYO otherwise. Every LOYO prediction is marked as estimated.

**Discipline:**
- Winsorisation (1%/99%) and median fill are fitted **on the training fold only**.
- Predicted ratios outside `ML_RATIO_BOUNDS` (0.25–4.0) are clipped and marked as estimated. With estimation off, they become `PREDICTION OUT OF BAND` instead.
- A missing library becomes `LIBRARY NOT INSTALLED` for that model alone.

| Model | Key settings |
|---|---|
| XGBoost | 400 trees, depth 4, lr 0.05, L2 = 2, min_child_weight 5 |
| Random Forest | 500 trees, depth 8, min_samples_leaf 5, max_features sqrt |
| LightGBM | 400 trees, depth 4, 15 leaves, min_child_samples 10 |
| MLP | StandardScaler → (64, 32) ReLU, Adam, α = 1e-3, early stopping (15% validation) |

All models use `random_state = ML_RANDOM_STATE` (42). The ML stage also writes `ml_metrics.csv` (RMSE, MAE and directional accuracy per fold), `ml_feature_importance.csv` and `ml_dataset.csv`.

### 12.6 Which model suits which company

| Model | Good for | Breaks down for |
|---|---|---|
| DCF | Mature, cash-generative companies | Loss-makers, early-stage companies, banks, cyclicals at the bottom of the cycle |
| P/E Relative | Profitable companies in sectors with plenty of peers | Loss-makers, thin sectors |
| EV/EBITDA | Capital-intensive industrials | Banks and NBFCs, asset-light companies |
| Graham | Conservative ceiling for stable earners | Growth companies (it sits far below their price), loss-makers |
| ML | Pattern-based re-rating signal across the panel | Small samples. Read Random Forest as the baseline. |

---

## 13. Error handling and reason codes

[`src/result.py`](src/result.py):

```python
@dataclass
class Result:
    value: float | None
    code: str | None       # stable reason code on failure
    detail: str | None     # specific explanation
    method: str | None     # set only when the value was estimated
```

| Code | Meaning |
|---|---|
| `TICKER NOT RESOLVED` | The name matched no exchange symbol |
| `FETCH FAILED` | The download raised an error |
| `SOURCE UNAVAILABLE` | A whole statement came back empty |
| `NO DATA FOR THIS FY` | No statement period matched this FY |
| `FIELD MISSING` | The statement exists, but this line item is absent |
| `PRICE UNAVAILABLE` | No price, or too few sessions |
| `NOT MEANINGFUL` | The maths is defined but economically meaningless (negative EPS or EBITDA, zero shares) |
| `NO PEER BENCHMARK` | No usable sector median and no own history |
| `NEGATIVE EQUITY VALUE` | EV is below net debt, or book value is ≤ 0 |
| `CALCULATION ERROR` | Division by zero, NaN, or an unhandled exception |
| `NOT COMPUTABLE` | A dependency was itself unavailable |
| `MODEL NOT APPLICABLE` | Structural exclusion, or the ML stage is disabled |
| `INSUFFICIENT TRAINING DATA` | The ML fold has fewer than `ML_MIN_TRAIN_ROWS` labelled rows |
| `NO FORWARD PRICE` | No FY+1 price, so no training label |
| `FEATURES INCOMPLETE` | Too few ML features could be computed |
| `LIBRARY NOT INSTALLED` | The ML library is missing or broken |
| `PREDICTION OUT OF BAND` | The ML ratio is outside the plausible range |

The detail text propagates from the point of failure (for example, `yf_source`'s `_diag`) through the model to the cell. A cell can therefore say *why* EBIT was missing, not just that the DCF failed.

**Exception capture is layered:** each statement download, each field pick, the whole-company fetch, each model call (`guard()`), the export (a failed XLSX still leaves the CSV), and the top level. Full tracebacks go to `output/run_log.txt`.

---

## 14. Outputs

Everything is written to `output/`. The folder is git-ignored because it is regenerated on every run.

| File | Contents |
|---|---|
| `Intrinsic_Value_Report.csv` / `.xlsx` | **Main grid.** Company, Sector, FY, Market Price (1-May benchmark), then for each enabled model: *Intrinsic Value* and *Difference (Market − Model)*. Values are formatted `₹1,234.56`, with `*` if estimated; otherwise a reason code. |
| `Intrinsic_Value_Data.csv` | **Numeric twin:** the same columns as plain floats, plus `FY (internal)`, `Benchmark Date` and `Valuation Anchor Price`. This is what the analyzer reads. |
| `Intrinsic_Value_Diagnostics.csv` | One row per empty cell: model, reason code, full explanation |
| `Intrinsic_Value_Methods.csv` | One row per filled cell: value, whether it was estimated, and the method |
| `Intrinsic_Value_Excluded.csv` | Sufficiency verdicts: complete and benchmark FY counts, reasons, missing fields by year, models still computable, fields supplied by override |
| `Why_Companies_Were_Left_Out.*` | Plain-English version of the exclusion sheet (summary, per company, year by year) |
| `ml_metrics.csv`, `ml_feature_importance.csv`, `ml_dataset.csv` | ML diagnostics |
| `metrics_overall.csv`, `metrics_by_sector.csv`, `metrics_by_year.csv`, `metrics_by_company.csv`, `metrics_win_rate.csv` | Accuracy tables |
| `charts/*.png` | HD charts (see §15) |
| `analysis_report.html` | HTML index of all charts and the headline summary |
| `run_log.txt` | DEBUG log with full tracebacks |
| `screening_report.csv` | Written by `tools/screener.py` |

The **workbook** contains these sheets: *Intrinsic Values*, *Diagnostics*, *Methods*, *Excluded Companies*, and the three *Left Out* sheets.

**Sign convention:** `Difference = Market Price − Intrinsic Value`. A positive difference means the market is above the model, so the model says *overvalued*. A negative difference means the model says *undervalued*.

### Console summary

At the end of a run, the console prints:
- model coverage (valued and estimated counts per model)
- benchmark-date statistics
- ML fold RMSE, MAE and directional accuracy
- a "why cells are blank" tally by reason code
- an **IN PLAIN ENGLISH** block that counts how many company-years looked cheap, expensive or about right, using a ±`PLAIN_VERDICT_BAND` (10%) band around the average across models

---

## 15. Analysis stage (metrics and charts)

[`src/csv_analyzer.py`](src/csv_analyzer.py) runs automatically after export. You can re-run it on its own:

```bash
python tools/analyze.py
```

```bash
python tools/analyze.py output/Intrinsic_Value_Data.csv -o output/run7 --dpi 300
```

**Metrics** are computed per model, and also by sector, by year and by company:

| Metric | Meaning |
|---|---|
| MAE | Mean absolute error, in ₹ |
| RMSE | Root mean squared error, in ₹. RMSE ≫ MAE means a few large misses. |
| MAPE | Mean absolute percentage error, the scale-free headline figure |
| MedAPE | Median absolute percentage error. A wide gap from MAPE means outliers dominate. |
| Bias | Mean signed error. Negative means the model prices below the market. |
| Hit20 | Share of estimates within ±20% of the benchmark |
| Spearman | Rank correlation: does the model get the ordering right? |
| Wins | How often this model was the closest of all models for a row |

**Charts**, each with its interpretation drawn into the image:

| Chart | What it shows |
|---|---|
| `sector_<name>_levels.png` | Each model's value per company over the years |
| `sector_<name>_normalised.png` | Estimate ÷ benchmark over time |
| `overall_model_accuracy.png` | Models ranked by MAPE and RMSE |
| `closest_model_win_rate.png` | How often each model was closest |
| `accuracy_by_sector.png` | MAPE heatmap, model × sector |
| `accuracy_by_year.png` | MAPE per model across years |
| `error_distribution.png` | Distribution of signed percentage errors |
| `metrics_table.png` | The full metrics table as an image |

The loader tolerates blank separator rows, `#` comment lines, currency-prefixed cells and small changes in header wording.

---

## 16. Tools

### `tools/make_override_template.py`

```bash
python run.py --make-override-template
```

This fetches every company with overrides switched off and writes `data/fundamentals_override.csv`. The sheet has one row per company-year. Fetched values are pre-filled, existing override values are kept, and the gaps are left blank. Fill the blanks from Screener.in or annual reports, in **absolute rupees**, then re-run.

### Auto-train: `--train-universe auto`

```bash
python run.py --train-universe auto
```

```bash
python run.py --train-universe auto --auto-max 150 --auto-target 50 --auto-batch 5
```

This grows the ML training set **one company at a time** until the Hybrid is confident enough, then values your list as normal. In the web app: Operations → Valuation report → More options → **Auto-train**.

1. **Candidates:** the NIFTY Total Market (~750 companies), filtered as follows:
   - **Listing age:** only companies whose official NSE listing date (`EQUITY_L.csv`) is at least `--auto-min-listed-years` ago (default 10).
   - **Sector:** Financial Services is left out unless you pass `--auto-include-financials`.
   - **Duplicates:** companies already in your list are left out.
2. **Sectors:** the top `--auto-sectors` (default 10). With `--auto-sector-rank performance` (the default), sectors are ranked by median share-price return over the 5 years **before** the valuation window, so the ranking uses no hindsight. With `breadth`, they're ranked by the number of long-listed companies.
3. **Order:** companies are drawn **at random** within each sector, and the sectors take turns, so stopping early still leaves a balanced sample. Every run prints its random seed, and `--auto-seed N` replays exactly the same draw. Each learned company gets its own line on screen: ticker, sector, cap, listing year, and years of accounts and prices. Fetched companies are cached in `.cache/train_cache/` for `AUTO_CACHE_DAYS` (7), so re-runs are fast.
4. **Retraining:** every `--auto-batch` companies (default 10), the ML models are retrained and the Ensemble is re-scored on your companies. The **meter** shows the Ensemble's average confidence, meaning its predicted chance of landing within ±20% of the real price.
5. **Stopping:** it stops at the first of these:
   - the confidence target is reached (`--auto-target`, default 60 = "High")
   - *(optional, off by default)* `--auto-patience N` retrains in a row each gain less than 0.5 points
   - `--auto-max` companies have been learned (default 100)
   - the candidates run out
   - you stop it

**Controls.** In a Windows terminal, use these keys: **P** pause/resume, **S** skip the current company, **X** skip the current sector, **R** retrain now, **+ / −** change the target by 5, **Q** stop and finish with what has been learned (Ctrl+C does the same). The web app's Operations page has the same controls as buttons.

**Outputs:**
- `data/auto_training_universe.csv`: the companies learned, in `companies.csv` format. Reuse it with `--train-universe data/auto_training_universe.csv`.
- `output/auto_train_log.csv`: confidence, real hit rate, labelled rows and ML directional accuracy after every retrain.

The console shows three labelled steps: **1**, download *your* list (the companies being valued); **2**, learn from the live market; **3**, value your list with the trained models.

**Expect it to run to the company limit rather than reach "High".** More training data sharpens the ML component, but it cannot remove the genuine year-ahead uncertainty in share prices. Screener.in is not used (see `build_training_universe.py` below). All data comes from NSE's published files and Yahoo Finance.

### `tools/build_training_universe.py`

```bash
python tools/build_training_universe.py
```

```bash
python run.py --train-universe data/training_universe.csv
```

This builds `data/training_universe.csv` in the `companies.csv` format, from NSE's official index constituent files on niftyindices.com:
- **Universe:** NIFTY 500.
- **Cap:** Large, Mid or Small from NIFTY 100 / Midcap 150 / Smallcap 250 membership, the same split AMFI uses.
- **Sector names** are mapped onto those in `companies.csv`.
- **Companies already in `companies.csv`** are removed, so nothing is counted twice.
- **Financial Services** is left out unless you pass `--include-financials`.

Other flags: `--max-per-sector N` for a quicker run, and `--from-dir` to use local copies of the four CSVs. Screener.in is deliberately not scraped (its `robots.txt` and terms disallow it). To use a Screener screen, export it from your own account.

### `tools/screener.py` (optional)

```bash
python tools/screener.py --relax --per-bucket 2 --out data/companies.csv
```

This screens a candidate universe on fundamentals and writes the companies that pass, plus `output/screening_report.csv` (every candidate, every metric, every pass/fail reason).

| Criterion | Default |
|---|---|
| ROCE floor (every year checked) | 18% over 4 years |
| P/E ceiling | 20 |
| Down from 52-week high | ≥ 25% |
| Debt/equity | ≤ 1.0 |
| Sales CAGR | ≥ 5% |
| Complete FYs | 4 |
| Market cap | ≥ ₹300 cr |

`--relax` loosens the criteria step by step: it drops the near-lows test, raises the P/E ceiling to 30, lowers the ROCE floor to 15%, raises the P/E ceiling to 40, lowers ROCE to 12%, and finally drops the sales-growth test. Cap buckets: Large ≥ ₹50,000 cr, Mid ≥ ₹15,000 cr. Other flags: `--universe CSV`, `--no-cache`, `--report-only`.

> ⚠️ **Selection bias.** If you screen on low P/E and price drawdown and then compare intrinsic value with market price, the result is circular: the study will mechanically report "undervalued". Keep screened names as a separate, labelled sub-sample.
>
> FII holding is **not** available from yfinance. The `fii_pct_unverified` column is Yahoo's generic institutional-holding field.
>
> The screener's docstring still mentions `main.py` and defaults `--out` to `companies.csv` in the current directory. Pass `--out data/companies.csv` to write to the place `run.py` reads from.

---

## 17. Configuration reference

All settings live in [`src/config.py`](src/config.py). CLI flags and the web app's run settings write to the same values at runtime.

### Financial years and prices

| Setting | Default | Notes |
|---|---|---|
| `FY_START` / `FY_END` | 2021 / 2025 | Change them with `set_fy_range()` |
| `FY_MIN_ALLOWED` / `FY_MAX_SPAN` | 2000 / 30 | Guards on the window |
| `FY_MEAN_BASIS` | `"trading"` | or `"calendar"` |
| `MIN_TRADING_DAYS_FOR_FY` | 60 | Below this, the anchor price is unavailable |
| `PARTIAL_YEAR_SESSIONS` | 200 | Below this, the year is flagged as partial |
| `BENCHMARK_BASIS` | `"may1"` | or `"mean"`, `"close"` |
| `BENCHMARK_MONTH/DAY` | 5 / 1 | Benchmark target date |
| `BENCHMARK_MAX_OFFSET_DAYS` | 10 | Maximum gap to the nearest session |

### Cost of capital and DCF

| Setting | Default |
|---|---|
| `RISK_FREE_RATE` | 0.0705 (10-year G-Sec) |
| `EQUITY_RISK_PREMIUM` | 0.0550 |
| `DEFAULT_BETA` | 1.00 |
| `COST_OF_DEBT` | 0.0850 |
| `DEFAULT_TAX_RATE` | 0.2517 |
| `PROJECTION_YEARS` | 5 |
| `TERMINAL_GROWTH` | 0.05 |
| `MIN_GROWTH` / `MAX_GROWTH` / `DEFAULT_GROWTH` | 0.02 / 0.18 / 0.08 |
| `WACC_SPREAD_OVER_G` | 0.02 |

### Relative valuation and Graham

| Setting | Default |
|---|---|
| `PE_BOUNDS` | (2.0, 120.0) |
| `EV_EBITDA_BOUNDS` | (1.0, 60.0) |
| `MIN_PEERS_FOR_MEDIAN` | 2 |
| `GRAHAM_MULTIPLIER` | 22.5 |
| `GRAHAM_MAX_MULTIPLE_OF_BVPS` | 8.0 |

### Models and ML

| Setting | Default |
|---|---|
| `MODELS_ENABLED` | all 8 `True` |
| `ML_ENABLED` | `True` (master switch for the ML stage) |
| `ML_SPLIT` | `"hybrid"` |
| `ML_MIN_TRAIN_ROWS` | 25 |
| `ML_WINSOR_PCT` | (0.01, 0.99) |
| `ML_RATIO_BOUNDS` | (0.25, 4.0) |
| `ML_IMPUTE_FROM_SECTOR` | `True` |
| `ML_MIN_FEATURES` | 4 |
| `ML_RANDOM_STATE` | 42 |

### Sufficiency, estimation and output

| Setting | Default |
|---|---|
| `SUFFICIENCY_ENABLED` / `SUFFICIENCY_MODE` | `True` / `"enforce"` |
| `MIN_COMPLETE_FY` / `MIN_BENCHMARK_FY` | 3 / 3 |
| `SUFFICIENCY_KEEP_IN_PEERS` / `_IN_ML` | `True` / `True` |
| `SUFFICIENCY_AUTO_RELAX` | `True` |
| `ESTIMATION_MODE` | `"balanced"` (`"off"`, `"aggressive"`) |
| `ESTIMATE_MARKER` | `"*"` |
| `BACKCAST_MIN_RATIO` / `MAX_RATIO` | 0.33 / 3.0 |
| `USE_NORMALISED_EARNINGS` / `NORMALISED_MIN_YEARS` | `True` / 2 |
| `USE_OVERRIDES` | `True` |
| `SHOW_REASONS` / `REASON_STYLE` | `True` / `"code"` |
| `FY_LABEL_STYLE` | `"range"` |
| `ANALYSIS_ENABLED` / `CHART_DPI` | `True` / 200 |
| `PLAIN_SUMMARY` / `PLAIN_VERDICT_BAND` | `True` / 0.10 |
| `EXCHANGE_SUFFIX` / `CURRENCY_SYMBOL` | `".NS"` / `"₹"` |
| `REQUEST_PAUSE` | 0.6 s between network calls |


---

## 18. Testing offline

```bash
python run.py --offline
```

[`src/sources/mock_source.py`](src/sources/mock_source.py) builds a deterministic synthetic universe that follows whatever FY window you choose:

| Fixture | Triggers |
|---|---|
| MOCK CLEAN ALPHA / BETA / GAMMA | Happy path: three peers, every model values |
| MOCK DEPTH GAP | `NO DATA FOR THIS FY` in the early years |
| MOCK LOSS MAKER | `NOT MEANINGFUL` / normalisation paths |
| MOCK NO PRICE SOLO | `PRICE UNAVAILABLE` + `NO PEER BENCHMARK` |
| MOCK HEAVY DEBT (+ MOCK INFRA PEER) | `NEGATIVE EQUITY VALUE` |
| MOCK BANK STYLE | `FIELD MISSING` (no EBIT/EBITDA) |
| MOCK ZERO SHARES | `NOT MEANINGFUL` on zero shares |
| MOCK GHOST CORP | `TICKER NOT RESOLVED` |
| MOCK CRASH CORP | `FETCH FAILED` |

The mock benchmark date is 2 May, which exercises the "nearest session" path. A run passes when every expected code appears in the tally and the three clean companies produce numbers in all models.

---

## 19. Known limitations

1. **Source depth was the binding constraint.** yfinance serves only about 4 annual periods. Screener.in now fills the earlier years automatically (see §9). It has no cash or current-liabilities line, so those still come from Yahoo or the key-based providers, and `fundamentals_override.csv` remains the last resort.
2. **Recent IPOs** have no price before listing and only a partial first year. This thins the peer medians.
3. **Screener selection bias.** See §16.
4. **WACC is partly circular.** The equity weight uses the market price. This is standard practice, but worth stating.
5. **Beta quality.** Yahoo's beta is often measured against a non-Indian index, or is missing. Since beta drives the DCF, this matters.
6. **Terminal value dominates the DCF.** At 5% terminal growth and a 5-year horizon, TV is typically 70–85% of EV.
7. **Consolidated vs standalone** statements are not guaranteed to be consistent across companies.
8. **Publication lag is not modelled.** FY*t* accounts are used as if they were known on 31 March. The 1-May benchmark partly mitigates this.
9. **Banks and financial companies** fall outside DCF and EV/EBITDA by construction.
10. **The ML sample is small.** A few hundred company-years means fold results are noisy. `hybrid` and `loyo` folds use future years and are marked accordingly.
11. **Report cells are strings** (`₹1,234.56*`). Use `Intrinsic_Value_Data.csv` for any numerical work.

---

## 20. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Every company is `TICKER NOT RESOLVED` | No network, or Yahoo search is blocked. Add a `ticker` column. |
| Every company shows `prices 0/5 fundamentals 0/5`; the log says `CERTIFICATE_VERIFY_FAILED` / `unable to get local issuer certificate` | An antivirus (e.g. Norton Web/Mail Shield) or a proxy is re-signing HTTPS traffic. `src/ssl_trust.py` makes Python trust the Windows certificate store and runs automatically (`USE_SYSTEM_CERTS = True`). |
| The earliest FY is always `NO DATA FOR THIS FY` | Expected (source depth). Use the override sheet. |
| `[gate] AUTO-ADJUSTED` | No company met `MIN_COMPLETE_FY`. Report the threshold actually used. |
| A whole sector shows `NO PEER BENCHMARK` | Fewer than 2 valid peers. Add companies to that sector. |
| ML cells show `INSUFFICIENT TRAINING DATA` | Too few labelled rows per fold. Use `--train-universe` with a larger list. |
| `LIBRARY NOT INSTALLED` | `pip install xgboost lightgbm scikit-learn` |
| `Web UI unavailable: ...` | `pip install fastapi uvicorn` |
| The browser shows "The web UI is not built yet" | `cd web`, `npm install`, `npm run build` |
| The Ollama section says "not installed" | Install Ollama from ollama.com/download, then reload the page; INTVAL finds it in its usual places |
| Ollama is installed but "not running" | Press **Start Ollama**, or leave *Open Ollama whenever INTVAL starts* on |
| A local model's Test takes a minute or fails with a timeout | Large models are slow on a CPU. Local servers get 5 minutes per reply (`LOCAL_TIMEOUT` in `src/agents/llm_providers.py`); pick a smaller model such as `llama3.2:3b` |
| Windows says "Windows protected your PC" when running the setup | The installer is not code-signed. Click **More info → Run anyway** |
| The Linux installer won't start | Downloads lose the executable bit: `chmod +x INTVAL-Setup-*-linux-x86_64` |
| The installed app can't save settings or reports | Install it in a folder you can write to; the Windows installer makes its folder writable, even in Program Files |
| The NSE fallback never returns anything | NSE blocks VPN and datacentre IPs. Run from a home connection. |
| Yahoo rate-limit errors | Raise `REQUEST_PAUSE` to 1.5–2.0 |
| ₹ shows as `â‚¹` in Excel | Open the `.xlsx`, or import the CSV as UTF-8 |
| A CSV row shifts its columns | An unquoted comma in the company name. Quote the field. |
| CLI flags seem to have no effect | Something imported `src.config` rather than `config`. Keep the imports flat (§3). |
| Analyzer failed but the CSVs exist | Fix the cause, then `python tools/analyze.py` |

For any crash, the full traceback is in `output/run_log.txt`.

---

## 21. Extending the system

### Add a traditional model

1. Create `src/models/model_<name>.py` with `intrinsic_value(...) -> Result`. Return `Result.good(v, method=...)` or `Result.bad(code, detail)` on every path.
2. Add a `ModelSpec` to `ALL_MODELS` in [`model_registry.py`](src/model_registry.py). This sets the key, name, column, difference column, kind and description.
3. Add `"<key>": True` to `config.MODELS_ENABLED`.
4. Add the call in the valuation loop in [`pipeline.py`](src/pipeline.py) (`if "<key>" in enabled: row["<key>"] = guard(...)`).

The exporter, analyzer and web app read the registry, so they pick up the new model automatically.

### Add a machine-learning model

1. Create `src/models/model_<name>.py` exposing `KEY`, `NAME`, `COLUMN`, `build_estimator()`, `SPEC = {"key", "name", "build"}` and `intrinsic_value(store, company, fy)`.
2. Register it in `model_registry.ALL_MODELS` with `kind="ml"`, and in `pipeline.ML_MODULES`.

### Add a data source

1. Write a module in `src/sources/`. A statements provider returns `{fy: {field: value in rupees}}`, and a price provider returns a pandas Series of daily closes.
2. Add an entry to `PROVIDERS` in [`source_settings.py`](src/sources/source_settings.py): its key, label, what it supplies, and the `.env` key it needs (if any).
3. Register it in `data_hub.STATEMENTS` and/or `price_chain.FETCH`.

It then appears in Configuration → Data sources, where it can be reordered and switched on or off. The hub records which provider filled what in each year's `_notes`.

---

## 22. Glossary

- **Anchor price:** the in-FY mean price, used as a model input.
- **Benchmark price:** the close nearest 1 May after FY end, used only to score models.
- **Beta (β):** how sensitive a stock is to market moves.
- **CAPM:** Ke = Rf + β × ERP.
- **EBITDA:** earnings before interest, tax, depreciation and amortisation.
- **EV (enterprise value):** market cap + debt − cash.
- **FCFF:** free cash flow to the firm, available to both debt and equity holders.
- **Graham Number:** √(22.5 × EPS × BVPS), Benjamin Graham's defensive price ceiling.
- **LOYO:** leave-one-year-out cross-validation.
- **MAPE / MedAPE:** mean / median absolute percentage error.
- **Net debt:** total debt − cash.
- **ROCE:** EBIT ÷ (total assets − current liabilities).
- **Spearman ρ:** rank correlation.
- **Terminal value:** the value of all cash flows after the forecast horizon (Gordon growth model).
- **WACC:** weighted average cost of capital, the DCF discount rate.
- **Winsorisation:** clamping extreme values to a percentile band.
