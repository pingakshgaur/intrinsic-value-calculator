"""
Cost-of-capital helpers shared by the Residual Income model and the Hybrid.

WHY A SEPARATE BETA

Yahoo's beta for an Indian scrip is a single raw regression slope, often
measured against a non-Indian benchmark, and simply absent for many small
caps (in which case yf_source substitutes DEFAULT_BETA). Fed straight into
CAPM it is the noisiest input in the whole valuation chain.

The adjusted beta used here is a shrinkage estimate:

    beta_adj = w x beta_company + (1 - w) x beta_sector

    beta_sector = median company beta in the same sector (needs at least
                  BETA_MIN_SECTOR_PEERS companies, else 1.0, the market)

This is the Vasicek idea - pull a noisy individual estimate toward a more
reliable group mean - with the sector standing in for the prior. With w = 0.67
and beta_sector = 1.0 it reduces exactly to the Blume adjustment most data
vendors publish. A company whose beta Yahoo did not supply carries no
information of its own, so it takes the sector figure outright.

The original DCF model is deliberately left on the raw beta. It is the
baseline the hybrid is measured against, and changing it would move the
goalposts of that comparison.
"""

import statistics

import config

_SECTOR_BETA = {}


def build_sector_betas(universe):
    """-> {sector: median beta}. Companies on the default beta are skipped,
    because a substituted 1.0 is an absence of data, not an observation."""
    buckets = {}
    for rec in universe.values():
        b = rec["data"].get("beta")
        if b is None or b == config.DEFAULT_BETA:
            continue
        buckets.setdefault(rec["sector"], []).append(b)

    need = getattr(config, "BETA_MIN_SECTOR_PEERS", 2)
    out = {s: statistics.median(v) for s, v in buckets.items() if len(v) >= need}
    _SECTOR_BETA.clear()
    _SECTOR_BETA.update(out)
    return out


def adjusted_beta(rec):
    """-> (beta_adj, note). rec is one universe entry."""
    sector_beta = _SECTOR_BETA.get(rec["sector"], 1.0)
    raw = rec["data"].get("beta")
    if raw is None or raw == config.DEFAULT_BETA:
        return sector_beta, f"sector beta {sector_beta:.2f} (company beta unavailable)"
    w = getattr(config, "BETA_SHRINK_WEIGHT", 0.67)
    b = w * raw + (1 - w) * sector_beta
    return b, f"adjusted beta {b:.2f} (raw {raw:.2f}, sector {sector_beta:.2f})"


def cost_of_equity(beta):
    return config.RISK_FREE_RATE + beta * config.EQUITY_RISK_PREMIUM
