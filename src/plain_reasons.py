# FILE: src/plain_reasons.py
"""
Plain-English translation of the data-sufficiency verdicts.

WHY THIS MODULE EXISTS

sufficiency.py already records, precisely, why each company failed. It writes
sentences like:

    only 2 of 5 financial years carry a complete set of required fundamentals
    (need 3) | 2021-22: eps, ocf, capex

That is exactly right for an auditor and useless for everybody else. Someone
who has never opened an annual report does not know what "ocf" is, does not
know why three years matters, and cannot tell from that line whether the
company is a bad company or simply a young one.

So this module takes the same verdict record and answers four questions in
ordinary words:

    1. What KIND of problem was it?      -> a named category, not a code
    2. What went wrong, in plain words?  -> two or three short sentences
    3. Which years did it affect?        -> readable financial-year labels
    4. What can the user do about it?    -> a concrete next step, or "nothing"

Nothing here changes a single number. The technical columns stay exactly where
they were, on the "Excluded Companies" sheet; these are additional sheets that
sit beside them.

CATEGORIES

Every rejected company lands in exactly one category, tested in this order,
most specific first:

    Nothing could be downloaded          the ticker never resolved, or the
                                        download itself failed
    Bank or lender                       the accounts are structured
                                        differently and operating-profit
                                        figures are simply not published
    Too new / recently listed            the missing years are the EARLIEST
                                        ones and the recent years are fine
    Not enough complete years            the ordinary case: gaps scattered
                                        through the accounts
    Not enough share-price history       accounts are fine, but there is no
                                        post-year price to score against

The ordering matters. A newly listed bank fails all four tests; calling it a
bank first is the honest answer, because relaxing the year threshold would
never rescue it.
"""

import config
import sufficiency
from fy_utils import fy_label

# ---------------------------------------------------------------- vocabulary

# Internal field name -> what an ordinary person would call it. Every field
# named in config.SUFFICIENCY_REQUIRED_FIELDS must appear here, otherwise the
# plain sheet quietly falls back to printing the raw name.
FIELD_WORDS = {
    "revenue": "total sales for the year",
    "ebit": "operating profit",
    "ebitda": "operating profit before depreciation is deducted",
    "net_income": "the final profit left after tax",
    "eps": "profit earned per share",
    "ocf": "cash the business actually generated",
    "capex": "money spent on factories, machines and equipment",
    "shares": "how many shares exist",
    "total_debt": "total borrowings",
    "cash": "cash held in the bank",
    "equity": "the shareholders' own money in the business",
    "price": "the share price during that year",
    "price_bench": "the share price a month after the year ended",
    "everything": "everything - not a single figure arrived",
}

# Sector words that mark a lender. Their published accounts do not carry the
# operating-profit lines these valuation methods are built on, so a number
# calculated for them would be meaningless rather than merely imprecise.
LENDER_HINTS = (
    "bank",
    "financ",
    "nbfc",
    "insur",
    "lend",
    "broker",
    "capital market",
    "asset management",
)

CAT_NO_DATA = "Nothing could be downloaded"
CAT_LENDER = "Bank or lender - these methods do not fit"
CAT_NEW = "Company is too new or listed too recently"
CAT_THIN = "Not enough complete years of accounts"
CAT_NO_PRICE = "Not enough share-price history"
CAT_OK = "No problem - this company was used"

CATEGORY_ORDER = [
    CAT_NO_DATA,
    CAT_LENDER,
    CAT_NEW,
    CAT_THIN,
    CAT_NO_PRICE,
    CAT_OK,
]

# What each category means, in one sentence, for the summary sheet.
CATEGORY_MEANING = {
    CAT_NO_DATA: (
        "The program could not find this company on the data service at all, "
        "so there was nothing to work with."
    ),
    CAT_LENDER: (
        "Banks, insurers and lending companies publish their accounts in a "
        "different shape, and these valuation methods cannot read that shape."
    ),
    CAT_NEW: (
        "The company simply has not existed, or has not been listed, for as "
        "many years as the calculation needs."
    ),
    CAT_THIN: (
        "The published accounts have gaps scattered through them, so too few "
        "years are complete enough to value."
    ),
    CAT_NO_PRICE: (
        "The accounts are fine, but there is no traded share price afterwards "
        "to compare the answer against, so the result could not be checked."
    ),
    CAT_OK: "This company had enough data and was valued normally.",
}


# ------------------------------------------------------------------ helpers


def humanise_field(name):
    """'ocf' -> 'cash the business actually generated'."""
    return FIELD_WORDS.get(name, name)


def humanise_fields(names, limit=None):
    """A readable list: 'total borrowings, cash held in the bank and 2 more'."""
    names = list(names or [])
    if not names:
        return ""
    shown = names if limit is None else names[:limit]
    words = [humanise_field(n) for n in shown]
    extra = len(names) - len(shown)
    if len(words) == 1:
        text = words[0]
    else:
        text = ", ".join(words[:-1]) + " and " + words[-1]
    if extra > 0:
        text += f", plus {extra} more"
    return text


def _required_count():
    try:
        return max(1, len(sufficiency.required_fields()))
    except Exception:
        return max(1, len(getattr(config, "SUFFICIENCY_REQUIRED_FIELDS", ())))


def _fy_years():
    return sorted(getattr(config, "FY_LIST", []))


def _is_blank_year(record, fy):
    """True when a year is not merely patchy but essentially empty."""
    missing = record.get("missing_by_fy", {}).get(fy) or []
    if "everything" in missing:
        return True
    return len(missing) >= max(1, int(round(0.7 * _required_count())))


def _blank_years(record):
    return [fy for fy in _fy_years() if _is_blank_year(record, fy)]


def _looks_like_lender(record):
    sector = (record.get("sector") or "").lower()
    if not any(hint in sector for hint in LENDER_HINTS):
        return False
    years = _fy_years()
    if not years:
        return False
    # Operating profit absent in EVERY year is the signature. One good year
    # would mean the data simply did not arrive, which is a different problem.
    missing_by_fy = record.get("missing_by_fy", {})
    hits = 0
    for fy in years:
        miss = missing_by_fy.get(fy) or []
        if "everything" in miss or "ebitda" in miss or "ebit" in miss:
            hits += 1
    return hits == len(years)


def _newly_listed(record):
    """Blank years are the earliest ones and at least one recent year is fine."""
    years = _fy_years()
    blanks = _blank_years(record)
    if not blanks or len(blanks) >= len(years):
        return False
    return blanks == years[: len(blanks)]


def _year_span(fys):
    """[2021, 2022] -> '2020-21 and 2021-22'."""
    labels = [str(fy_label(fy)) for fy in sorted(fys)]
    if not labels:
        return ""
    if len(labels) == 1:
        return labels[0]
    return ", ".join(labels[:-1]) + " and " + labels[-1]


def _all_missing_fields(record):
    """Every distinct field that went missing anywhere, most frequent first."""
    counts = {}
    for miss in (record.get("missing_by_fy") or {}).values():
        for field in miss:
            counts[field] = counts.get(field, 0) + 1
    return [f for f, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]


# --------------------------------------------------------------- classifier


def classify(record):
    """
    One verdict record -> a dict of plain-English strings.

    Keys: category, why, affected, missing, action.
    """
    total = record.get("total_fy") or len(_fy_years()) or 1
    have = record.get("complete_fy", 0)
    need = record.get("need_complete", 0)
    have_price = record.get("benchmark_fy", 0)
    need_price = record.get("need_benchmark", 0)
    blanks = _blank_years(record)
    fields = _all_missing_fields(record)

    if record.get("passes"):
        return {
            "category": CAT_OK,
            "why": (
                f"This company had {have} complete years out of {total}, which "
                f"met the requirement of {need}, so it was valued normally."
            ),
            "affected": _year_span(blanks) if blanks else "None",
            "missing": humanise_fields(fields, limit=4) or "Nothing important",
            "action": "Nothing to do.",
        }

    # 1. Nothing arrived at all.
    if any("nothing was fetched" in r for r in record.get("reasons", [])):
        return {
            "category": CAT_NO_DATA,
            "why": (
                "The program could not find this company on the data service. "
                "Usually the ticker symbol in your CSV file is wrong, or the "
                "company has been renamed, delisted or merged into another one."
            ),
            "affected": "Every year",
            "missing": "Everything - not a single figure arrived",
            "action": (
                "Check the ticker in your company list against the NSE or BSE "
                "website and correct it, then run again."
            ),
        }

    # 2. A lender. Test this before the year counts, because no threshold
    #    change would ever rescue it.
    if _looks_like_lender(record):
        return {
            "category": CAT_LENDER,
            "why": (
                "This is a bank or lending business. Banks do not publish the "
                "operating-profit figures these three valuation methods are "
                "built on, because lending money is their business rather than "
                "a cost. A number worked out for them would look convincing "
                "and mean nothing."
            ),
            "affected": "Every year",
            "missing": "Operating profit, in every year",
            "action": (
                "Nothing you can change here. Banks need their own valuation "
                "methods, which this program does not do."
            ),
        }

    # 3. Young company: the gaps are all at the start.
    if _newly_listed(record):
        return {
            "category": CAT_NEW,
            "why": (
                f"The company only has usable accounts for the more recent "
                f"years - {_year_span(blanks)} are empty because the business "
                f"was not listed, or not reporting, that far back. It needs "
                f"{need} complete years and has {have}."
            ),
            "affected": _year_span(blanks),
            "missing": humanise_fields(fields, limit=3),
            "action": (
                f"Lower 'complete years needed' to {max(1, have)} in Settings "
                f"if you are happy with a shorter history, or wait until the "
                f"company has reported for more years."
            ),
        }

    # 4. Accounts are fine, the price history is not.
    if have >= need and have_price < need_price:
        return {
            "category": CAT_NO_PRICE,
            "why": (
                f"The accounts for this company are good enough - {have} "
                f"complete years. What is missing is the share price after "
                f"each year ended, which is what the program checks its own "
                f"answer against. Only {have_price} of {total} years have "
                f"one, and {need_price} are needed."
            ),
            "affected": f"{total - have_price} of {total} years",
            "missing": "The share price used for comparison after the year ended",
            "action": (
                f"Lower 'years needing a comparison price' to {max(0, have_price)} "
                f"in Settings, or check that the ticker is the one the shares "
                f"actually trade under."
            ),
        }

    # 5. The ordinary case: scattered gaps.
    patchy = sorted((record.get("missing_by_fy") or {}).keys())
    return {
        "category": CAT_THIN,
        "why": (
            f"Only {have} of {total} years have every figure the calculation "
            f"needs, and {need} were required. The published accounts this "
            f"company filed have gaps in them, so those years could not be "
            f"used."
        ),
        "affected": (
            _year_span(patchy) if patchy else f"{total - have} of {total} years"
        ),
        "missing": humanise_fields(fields, limit=4),
        "action": (
            f"Either lower 'complete years needed' to {max(1, have)} in "
            f"Settings, or type the missing figures into "
            f"data/fundamentals_override.csv and run again."
        ),
    }


# ------------------------------------------------------------------- sheets

PLAIN_COLUMNS = [
    "Company name",
    "Sector",
    "Ticker",
    "Was it used in the report?",
    "Type of problem",
    "In plain words, what went wrong",
    "Which years were affected",
    "What exactly was missing",
    "What you can do about it",
]

YEAR_COLUMNS = [
    "Company name",
    "Financial year",
    "Was this year usable?",
    "Why this year could not be used",
    "What was missing, in plain words",
    "What was missing, technical names",
]

SUMMARY_COLUMNS = [
    "Type of problem",
    "How many companies",
    "What this means",
]


def _verdict_word(record):
    enforcing = (
        getattr(config, "SUFFICIENCY_ENABLED", True)
        and getattr(config, "SUFFICIENCY_MODE", "enforce") == "enforce"
    )
    if record.get("passes"):
        return "Yes - valued normally"
    return "No - left out" if enforcing else "Yes, but flagged as doubtful"


def plain_rows(records, include_passed=None):
    """One row per company: the human-readable twin of the Excluded sheet."""
    if include_passed is None:
        include_passed = getattr(config, "EXCLUSION_SHEET_INCLUDE_PASSED", False)

    rows = []
    for r in records or []:
        if r.get("passes") and not include_passed:
            continue
        info = classify(r)
        rows.append(
            {
                PLAIN_COLUMNS[0]: r.get("company", ""),
                PLAIN_COLUMNS[1]: r.get("sector", ""),
                PLAIN_COLUMNS[2]: r.get("ticker", ""),
                PLAIN_COLUMNS[3]: _verdict_word(r),
                PLAIN_COLUMNS[4]: info["category"],
                PLAIN_COLUMNS[5]: info["why"],
                PLAIN_COLUMNS[6]: info["affected"],
                PLAIN_COLUMNS[7]: info["missing"],
                PLAIN_COLUMNS[8]: info["action"],
            }
        )

    if not rows:
        rows.append(
            {
                PLAIN_COLUMNS[0]: "(none)",
                PLAIN_COLUMNS[3]: "Every company was used",
                PLAIN_COLUMNS[4]: CAT_OK,
                PLAIN_COLUMNS[5]: (
                    "Every company on your list had enough published data, so "
                    "nothing had to be left out of this run."
                ),
                **{c: "" for c in (PLAIN_COLUMNS[1], PLAIN_COLUMNS[2])},
                **{c: "" for c in PLAIN_COLUMNS[6:]},
            }
        )
    return rows


def year_rows(records, max_rows=5000):
    """
    One row per company-year that could not be used - for ANY company, whether
    it survived the gate or not. This is the answer to "why was that particular
    row of my spreadsheet left blank".
    """
    rows = []
    for r in records or []:
        company = r.get("company", "")
        for fy in sorted((r.get("missing_by_fy") or {}).keys()):
            missing = r["missing_by_fy"][fy] or []
            blank = "everything" in missing or _is_blank_year(r, fy)
            if blank:
                why = (
                    "No accounts were published, or none could be downloaded, "
                    "for this year at all."
                )
            else:
                why = (
                    f"{len(missing)} of the figures the calculation needs were "
                    f"not in the published accounts for this year."
                )
            rows.append(
                {
                    YEAR_COLUMNS[0]: company,
                    YEAR_COLUMNS[1]: fy_label(fy),
                    YEAR_COLUMNS[2]: "No",
                    YEAR_COLUMNS[3]: why,
                    YEAR_COLUMNS[4]: humanise_fields(missing, limit=6),
                    YEAR_COLUMNS[5]: ", ".join(missing),
                }
            )
            if len(rows) >= max_rows:
                return rows

    if not rows:
        rows.append(
            {
                YEAR_COLUMNS[0]: "(none)",
                YEAR_COLUMNS[1]: "",
                YEAR_COLUMNS[2]: "Yes",
                YEAR_COLUMNS[3]: "Every year of every company was complete.",
                YEAR_COLUMNS[4]: "",
                YEAR_COLUMNS[5]: "",
            }
        )
    return rows


def summary_rows(records, include_passed=None):
    """Counts per category, in a fixed order, with a one-line explanation."""
    if include_passed is None:
        include_passed = getattr(config, "EXCLUSION_SHEET_INCLUDE_PASSED", False)

    counts = {c: 0 for c in CATEGORY_ORDER}
    for r in records or []:
        if r.get("passes") and not include_passed:
            continue
        cat = classify(r)["category"]
        counts[cat] = counts.get(cat, 0) + 1

    return [
        {
            SUMMARY_COLUMNS[0]: cat,
            SUMMARY_COLUMNS[1]: counts.get(cat, 0),
            SUMMARY_COLUMNS[2]: CATEGORY_MEANING.get(cat, ""),
        }
        for cat in CATEGORY_ORDER
        if counts.get(cat, 0) or cat != CAT_OK
    ]
