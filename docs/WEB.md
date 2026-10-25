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
| `Alt+1`–`7` | Go to a page |
| `Ctrl+\` | Collapse or expand the sidebar |
| `?` | Glossary |
| `↑ ↓` / `Enter` | Move between rows / open one, in grids |

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
