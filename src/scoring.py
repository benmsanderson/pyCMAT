"""
scoring.py — Compute CMAT variable, realm, timescale, and overall scores.

Score hierarchy:
  pattern correlations (R_s per variable per timescale)
    -> variable score (weighted mean across 3 timescales)
    -> realm score (arithmetic mean of variable scores within realm)
    -> overall score (arithmetic mean of 3 realm scores)

The ENSO timescale weight (0.978 vs 1.0 for annual and seasonal) is set so
that the std of overall scores across the 40-member CESM1-LE is ~0.010.
Intermodel differences below ~0.040 (+/-2 sigma) are not statistically
significant.
"""
import math
import numpy as np
from config import WT_ANNUAL, WT_SEASONAL, WT_ENSO, WT_SUM, REALM_VARS


# ---------------------------------------------------------------------------
# Variable score
# ---------------------------------------------------------------------------

def variable_score(r_annual: float, r_seasonal: float, r_enso: float) -> float:
    """
    Weighted mean of the three timescale pattern correlations for one variable.

    NaN timescale values are skipped (weight excluded from denominator) to
    handle missing teleconnection data gracefully -- matching the IDL behaviour
    of setting wt3=0 when the ENSO file is missing.
    """
    pairs = [
        (r_annual,   WT_ANNUAL),
        (r_seasonal, WT_SEASONAL),
        (r_enso,     WT_ENSO),
    ]
    numerator = 0.0
    denominator = 0.0
    for r, w in pairs:
        if math.isfinite(r):
            numerator += r * w
            denominator += w
    if denominator == 0.0:
        return float("nan")
    return numerator / denominator


# ---------------------------------------------------------------------------
# Realm and overall scores
# ---------------------------------------------------------------------------

def realm_score(var_scores: dict, realm: str) -> float:
    """
    Arithmetic mean of variable scores within a realm.

    Parameters
    ----------
    var_scores : dict
        {variable_name: score_float} for all variables.
    realm : str
        One of 'energy', 'water', 'dynamics'.
    """
    scores = [
        var_scores[v]
        for v in REALM_VARS[realm]
        if v in var_scores and math.isfinite(var_scores[v])
    ]
    if not scores:
        return float("nan")
    return float(np.mean(scores))


def overall_score(realm_scores: dict) -> float:
    """Arithmetic mean of the three realm scores."""
    scores = [s for s in realm_scores.values() if math.isfinite(s)]
    if not scores:
        return float("nan")
    return float(np.mean(scores))


def timescale_score(var_scores_by_timescale: dict, timescale: str) -> float:
    """
    Mean of a single-timescale pattern correlation across all variables.

    Parameters
    ----------
    var_scores_by_timescale : dict
        {variable_name: {'annual': R, 'seasonal': R, 'enso': R}}
    timescale : str
        One of 'annual', 'seasonal', 'enso'.
    """
    scores = [
        d[timescale]
        for d in var_scores_by_timescale.values()
        if timescale in d and math.isfinite(d[timescale])
    ]
    if not scores:
        return float("nan")
    return float(np.mean(scores))


# ---------------------------------------------------------------------------
# Main scoring entry point
# ---------------------------------------------------------------------------

def compute_scores(pcors: dict) -> dict:
    """
    Compute the full CMAT score hierarchy from a dict of pattern correlations.

    Parameters
    ----------
    pcors : dict
        {variable_name: {'annual': R, 'seasonal': R, 'enso': R}}

    Returns
    -------
    dict with keys:
        'variable'  : {varname: float}
        'realm'     : {'energy': float, 'water': float, 'dynamics': float}
        'timescale' : {'annual': float, 'seasonal': float, 'enso': float}
        'overall'   : float
    """
    var_scores = {
        v: variable_score(
            pcors[v].get("annual",   float("nan")),
            pcors[v].get("seasonal", float("nan")),
            pcors[v].get("enso",     float("nan")),
        )
        for v in pcors
    }

    realm_scores = {
        r: realm_score(var_scores, r)
        for r in ("energy", "water", "dynamics")
    }

    ts_scores = {
        t: timescale_score(pcors, t)
        for t in ("annual", "seasonal", "enso")
    }

    return {
        "variable":  var_scores,
        "realm":     realm_scores,
        "timescale": ts_scores,
        "overall":   overall_score(realm_scores),
    }
