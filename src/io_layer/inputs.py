# FILE: src/io_layer/inputs.py
"""Input readers. Tolerant of ragged rows; reports problems with line numbers."""

import csv
import io

# Positional fallback when the file has no header row at all.
POSITIONAL = ["company name", "sector name", "market cap", "ticker"]

HEADER_WORDS = {
    "company",
    "company name",
    "name",
    "sector",
    "sector name",
    "cap",
    "market cap",
    "ticker",
    "symbol",
}


def _sniff(sample: str) -> str:
    """
    Pick the delimiter by counting candidates in the first populated line.

    A copy-paste out of a spreadsheet, and Excel on some locales, both produce
    TAB-separated files with a .csv extension. csv.DictReader defaults to a
    comma, parses each such line as a single field, finds no 'company name'
    column and skips every row - the file then looks empty rather than
    misdelimited, which is a confusing way to fail.
    """
    for line in sample.splitlines():
        if not line.strip():
            continue
        counts = {d: line.count(d) for d in (",", "\t", ";", "|")}
        best = max(counts, key=counts.get)
        return best if counts[best] > 0 else ","
    return ","


def _has_header(first_row) -> bool:
    return any((c or "").strip().lower() in HEADER_WORDS for c in first_row)


def read_csv_input(path):
    companies, problems = [], []

    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        text = fh.read()

    delim = _sniff(text)

    probe = [
        r
        for r in csv.reader(io.StringIO(text), delimiter=delim)
        if any((c or "").strip() for c in r)
    ]
    if not probe:
        raise ValueError(f"No usable rows in {path}")

    if _has_header(probe[0]):
        reader = csv.DictReader(
            io.StringIO(text), delimiter=delim, restkey="_extra", restval=""
        )
        if not reader.fieldnames:
            raise ValueError(f"{path} has no header row")
        norm = {k: (k or "").strip().lower() for k in reader.fieldnames}
    else:
        problems.append(
            f"  no header row detected; columns read positionally as "
            f"{', '.join(POSITIONAL)}"
        )
        reader = csv.DictReader(
            io.StringIO(text),
            fieldnames=POSITIONAL,
            delimiter=delim,
            restkey="_extra",
            restval="",
        )
        norm = {k: k for k in POSITIONAL}

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
                f"delimiters than the header. Quote any field containing the "
                f'delimiter, e.g. "Emami, Ltd".'
            )

        name = row.get("company name") or row.get("company") or row.get("name") or ""
        if not name:
            if any(row.get(k) for k in row if k != "_extra"):
                problems.append(f"  line {line_no}: no company name; skipped")
            continue

        companies.append(
            {
                "name": name,
                "sector": row.get("sector name") or row.get("sector") or "Unclassified",
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
