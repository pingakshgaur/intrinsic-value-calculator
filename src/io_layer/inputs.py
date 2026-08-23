# FILE: src/io_layer/inputs.py
"""Input readers. Tolerant of ragged rows; reports problems with line numbers."""

import csv


def read_csv_input(path):
    companies, problems = [], []

    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, restkey="_extra", restval="")
        if not reader.fieldnames:
            raise ValueError(f"{path} has no header row")
        norm = {k: (k or "").strip().lower() for k in reader.fieldnames}

        for raw in reader:
            line_no = reader.line_num
            row = {}
            for k, v in raw.items():
                key = norm.get(k, k if isinstance(k, str) else "_extra")
                if isinstance(v, list):
                    v = ",".join(str(x) for x in v)
                row[key] = (v or "").strip() if v is not None else ""

            if row.get("_extra"):
                problems.append(
                    f"  line {line_no}: extra field(s) {row['_extra']!r} - more "
                    f"commas than the header. Quote any field containing a "
                    f'comma, e.g. "Emami, Ltd".'
                )

            name = (
                row.get("company name") or row.get("company") or row.get("name") or ""
            )
            if not name:
                if any(row.get(k) for k in row if k != "_extra"):
                    problems.append(f"  line {line_no}: no company name; skipped")
                continue

            companies.append(
                {
                    "name": name,
                    "sector": row.get("sector name")
                    or row.get("sector")
                    or "Unclassified",
                    "cap": row.get("market cap") or row.get("cap") or "",
                    "ticker": row.get("ticker") or None,
                }
            )

    if problems:
        print(f"[input] {len(problems)} issue(s) in {path}:")
        for p in problems:
            print(p)
        print()
    if not companies:
        raise ValueError(f"No usable rows in {path}")
    print(f"[input] loaded {len(companies)} companies from {path}\n")
    return companies


def read_terminal_input():
    print("\nEnter companies as:  Company Name, Sector Name, Cap [, TICKER]")
    print("Press ENTER on an empty line when done.\n")
    companies = []
    while True:
        try:
            line = input("> ").strip()
        except EOFError:
            break
        if not line:
            break
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 2:
            print("   Need at least 'Name, Sector'. Try again.")
            continue
        companies.append(
            {
                "name": parts[0],
                "sector": parts[1],
                "cap": parts[2] if len(parts) > 2 else "",
                "ticker": parts[3] if len(parts) > 3 else None,
            }
        )
    return companies
