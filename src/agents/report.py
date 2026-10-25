"""
Run outputs: Markdown note, JSON for machines, a self-contained HTML
dashboard. Each run writes a dated folder under <state>/reports/ and
refreshes <state>/latest/, which is what the cloud workflow publishes.
"""

import datetime as dt
import html
import json
import shutil

DISCLAIMER = (
    "Research output generated automatically from public data. Labels describe the "
    "price against an estimated value; they are not recommendations to buy or sell."
)


def _m(v, pct=False):
    if v is None or v == "":
        return "n/a"
    if pct:
        return f"{v:+.1%}"
    return f"{v:,.2f}"


# ============================================================ markdown
def markdown(verdicts, meta):
    out = [f"# Market Intelligence Report - {meta['started'][:16].replace('T', ' ')}", ""]
    out.append(f"Run #{meta['run_id']} ({meta['mode']}), {meta['companies']} companies, "
               f"{meta['seconds']}s. {meta['llm_mode']}; {meta['llm']['calls']} LLM calls.")
    out += ["", f"> {DISCLAIMER}", "", "## Summary", ""]
    out.append("| Company | Label | Price | Expected value | Upside | Buy-below | Confidence | Red flags |")
    out.append("|---|---|---:|---:|---:|---:|---:|---:|")
    for v in verdicts:
        out.append(
            f"| {v['company']} | {v['label']} | {_m(v['price'])} | {_m(v['expected_value'])} | "
            f"{_m(v.get('upside'), True)} | {_m(v.get('buy_below'))} | {v['confidence']:.0f} | "
            f"{len(v['red_flags'])} |"
        )
    changes = [(v["company"], c) for v in verdicts for c in v.get("changes", []) if not c.startswith("first")]
    if changes:
        out += ["", "## What changed since the last run", ""]
        out += [f"- **{n}**: {c}" for n, c in changes]

    for v in verdicts:
        s = v.get("summary", {})
        out += ["", f"## {v['company']} ({v.get('ticker', '')})", ""]
        out.append(f"**{s.get('headline') or v['label']}**")
        out += ["", s.get("note", ""), ""]
        for p in s.get("key_points", []):
            out.append(f"- {p['text']}")
        if s.get("watch_next"):
            out.append("")
            out.append("Watch next: " + "; ".join(s["watch_next"]))
        out += ["", "### Valuation waterfall", "", "| Step | Value | Note |", "|---|---:|---|"]
        for w in v.get("waterfall", []):
            out.append(f"| {w['step']} | {_m(w['value'])} | {w['note']} |")
        out += ["", f"Cost of equity {v['cost_of_equity']:.2%} (CAPM {v['cost_of_equity_capm']:.2%} + premia: "
                + ", ".join(f"{k} {p:.2%}" for k, p in v['premia'].items() if p) + ")."]
        out.append(f"Growth {v['growth']:.2%} (base {v['growth_base']:.2%}; tilts "
                   + ", ".join(f"{k} {t:+.2%}" for k, t in v['growth_tilts'].items() if t) + f"), terminal {v['growth_terminal']:.2%}.")
        out.append(f"Quality multiplier {v['quality_multiplier']:.3f}; governance haircut {v['governance_haircut']:.0%}.")
        if v["red_flags"]:
            out += ["", "### Red flags", ""] + [f"- {f}" for f in v["red_flags"]]
        out += ["", "### Research leads", "", "| Lead | Score | Confidence | Summary |", "|---|---:|---:|---|"]
        for r in v["leads"]:
            out.append(f"| {r['name']} | {r['score']:+.2f} | {r['confidence']:.2f} | {r['summary'][:220]} |")
        for side in ("bull_case", "bear_case"):
            c = v.get(side)
            if c:
                out += ["", f"### {side.replace('_', ' ').title()}", "", c.get("thesis", "")]
                if c.get("invalidated_if"):
                    out.append(f"\n_Wrong if:_ {c['invalidated_if']}")
    if meta.get("feed_problems"):
        out += ["", "## Data-source problems", ""] + [f"- {p}" for p in meta["feed_problems"]]
    out += ["", "---", DISCLAIMER, ""]
    return "\n".join(out)


# ============================================================ html
CSS = """
:root{--bg:#f7f7f5;--card:#fff;--ink:#1d1d1b;--muted:#6b6b66;--line:#e4e3de;
--good:#1f7a4d;--bad:#b3261e;--warn:#9a6700;--accent:#3a5ccc}
@media (prefers-color-scheme:dark){:root{--bg:#141413;--card:#1f1f1d;--ink:#ecebe6;
--muted:#a3a29b;--line:#34332f;--good:#5cc28f;--bad:#f2867c;--warn:#e3b341;--accent:#8ea8ff}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:15px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
main{max-width:1100px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:22px;margin:0 0 4px}h2{font-size:18px;margin:28px 0 8px}h3{font-size:15px;margin:18px 0 6px}
.muted{color:var(--muted)}.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;margin:12px 0}
table{width:100%;border-collapse:collapse;font-size:14px}th,td{padding:7px 8px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{color:var(--muted);font-weight:600}td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}
.wrap{overflow-x:auto}.pill{display:inline-block;padding:2px 8px;border-radius:99px;font-size:12px;font-weight:600;border:1px solid currentColor}
.good{color:var(--good)}.bad{color:var(--bad)}.warn{color:var(--warn)}
details{border-top:1px solid var(--line);padding:8px 0}summary{cursor:pointer;font-weight:600}
a{color:var(--accent)}ul{padding-left:20px}.note{font-size:13px}
"""


def _cls(label):
    if label in ("Deep value", "Undervalued"):
        return "good"
    if label in ("Overvalued", "Avoid - red flags"):
        return "bad"
    return "warn"


def _e(x):
    return html.escape(str(x if x is not None else ""))


def dashboard(verdicts, meta):
    rows = []
    for i, v in enumerate(verdicts):
        rows.append(
            f"<tr><td><a href='#c{i}'>{_e(v['company'])}</a><div class='muted note'>{_e(v.get('sector'))}</div></td>"
            f"<td><span class='pill {_cls(v['label'])}'>{_e(v['label'])}</span></td>"
            f"<td class=n>{_m(v['price'])}</td><td class=n>{_m(v['expected_value'])}</td>"
            f"<td class=n>{_m(v.get('upside'), True)}</td><td class=n>{_m(v.get('buy_below'))}</td>"
            f"<td class=n>{v['confidence']:.0f}</td><td class=n>{len(v['red_flags'])}</td></tr>"
        )
    cards = []
    for i, v in enumerate(verdicts):
        s = v.get("summary", {})
        wf = "".join(f"<tr><td>{_e(w['step'])}</td><td class=n>{_m(w['value'])}</td><td class='muted'>{_e(w['note'])}</td></tr>"
                     for w in v.get("waterfall", []))
        leads = "".join(
            f"<tr><td>{_e(r['name'])}</td><td class='n {'good' if r['score'] > 0.05 else 'bad' if r['score'] < -0.05 else ''}'>"
            f"{r['score']:+.2f}</td><td class=n>{r['confidence']:.2f}</td><td class=note>{_e(r['summary'][:260])}</td></tr>"
            for r in v["leads"]
        )
        flags = "".join(f"<li class=bad>{_e(f)}</li>" for f in v["red_flags"]) or "<li class=muted>none</li>"
        changes = "".join(f"<li>{_e(c)}</li>" for c in v.get("changes", []))
        analysts = []
        for a in v.get("analysts", []):
            ev = "".join(
                f"<li class=note>{_e(e['source'])}: "
                + (f"<a href='{_e(e['url'])}' rel=noopener target=_blank>{_e(e['title'][:120])}</a>" if e.get("url") else _e(e["title"][:120]))
                + f" <span class=muted>{_e(e.get('date'))}</span></li>"
                for e in a["evidence"]
            )
            badge = "" if a["validated"] else " <span class='pill warn'>not validated</span>"
            analysts.append(
                f"<details><summary>{_e(a['agent'].replace('_', ' ').title())} "
                f"<span class=muted>{a['score']:+.2f} / conf {a['confidence']:.2f}{' / LLM' if a['used_llm'] else ''}</span>{badge}</summary>"
                f"<p>{_e(a['summary'])}</p>"
                + ("<ul>" + "".join(f"<li class=bad>{_e(f)}</li>" for f in a["flags"]) + "</ul>" if a["flags"] else "")
                + ("<ul>" + "".join(f"<li class=muted>{_e(n)}</li>" for n in a["notes"]) + "</ul>" if a["notes"] else "")
                + (f"<ul>{ev}</ul>" if ev else "") + "</details>"
            )
        cases = ""
        for side in ("bull_case", "bear_case"):
            c = v.get(side) or {}
            if c:
                cases += (f"<h3>{side.replace('_', ' ').title()}</h3><p>{_e(c.get('thesis'))}</p>"
                          + (f"<p class='muted note'>Wrong if: {_e(c['invalidated_if'])}</p>" if c.get("invalidated_if") else ""))
        cards.append(
            f"<section class=card id=c{i}><h2>{_e(v['company'])} <span class=muted>{_e(v.get('ticker'))}</span></h2>"
            f"<p><b>{_e(s.get('headline') or v['label'])}</b></p><p>{_e(s.get('note'))}</p>"
            + ("<p class=note>Watch next: " + _e("; ".join(s.get("watch_next", []))) + "</p>" if s.get("watch_next") else "")
            + (f"<h3>Changes since last run</h3><ul>{changes}</ul>" if changes else "")
            + f"<h3>Red flags</h3><ul>{flags}</ul>"
            f"<h3>Valuation waterfall</h3><div class=wrap><table>{wf}</table></div>"
            f"<p class='muted note'>Cost of equity {v['cost_of_equity']:.2%} (CAPM {v['cost_of_equity_capm']:.2%}); "
            f"growth {v['growth']:.2%} fading to {v['growth_terminal']:.2%}; quality x{v['quality_multiplier']:.3f}; "
            f"haircut {v['governance_haircut']:.0%}; scenario odds bull {v['probabilities']['bull']:.0%} / "
            f"base {v['probabilities']['base']:.0%} / bear {v['probabilities']['bear']:.0%}.</p>"
            f"<h3>Research leads</h3><div class=wrap><table><tr><th>Lead</th><th class=n>Score</th><th class=n>Conf.</th><th>Summary</th></tr>{leads}</table></div>"
            f"{cases}<h3>All analysts</h3>{''.join(analysts)}</section>"
        )
    probs = "".join(f"<li>{_e(p)}</li>" for p in meta.get("feed_problems", []))
    return (
        "<!doctype html><html lang=en><head><meta charset=utf-8>"
        "<meta name=viewport content='width=device-width,initial-scale=1'>"
        f"<title>Market Intelligence</title><style>{CSS}</style></head><body><main>"
        f"<h1>Market Intelligence</h1><p class=muted>Run #{meta['run_id']} ({meta['mode']}) - "
        f"{_e(meta['started'][:16].replace('T', ' '))} - {meta['companies']} companies - {_e(meta['llm_mode'])}</p>"
        f"<p class='muted note'>{_e(DISCLAIMER)}</p>"
        "<div class='card wrap'><table><tr><th>Company</th><th>Label</th><th class=n>Price</th>"
        "<th class=n>Expected value</th><th class=n>Upside</th><th class=n>Buy-below</th>"
        f"<th class=n>Conf.</th><th class=n>Flags</th></tr>{''.join(rows)}</table></div>"
        + "".join(cards)
        + (f"<h2>Data-source problems</h2><ul class='muted note'>{probs}</ul>" if probs else "")
        + "</main></body></html>"
    )


# ============================================================ write
def write_all(verdicts, meta, state):
    stamp = dt.datetime.now().strftime("%Y-%m-%d_%H%M")
    folder = state / "reports" / f"{stamp}_{meta['mode']}"
    folder.mkdir(parents=True, exist_ok=True)
    payload = {"meta": meta, "verdicts": verdicts}
    files = {
        "report.md": markdown(verdicts, meta),
        "verdicts.json": json.dumps(payload, indent=1, default=str),
        "dashboard.html": dashboard(verdicts, meta),
    }
    for name, text in files.items():
        (folder / name).write_text(text, encoding="utf-8")
    latest = state / "latest"
    if latest.exists():
        shutil.rmtree(latest, ignore_errors=True)
    shutil.copytree(folder, latest)

    # keep the newest N runs; the blackboard keeps the long history compactly
    from agents import settings as S

    keep = int(S.num("run.keep_reports", 60))
    runs = sorted((p for p in (state / "reports").iterdir() if p.is_dir()), key=lambda p: p.name)
    for old in runs[:-keep] if keep > 0 else []:
        shutil.rmtree(old, ignore_errors=True)
    return [folder / n for n in files] + [latest / "dashboard.html"]
