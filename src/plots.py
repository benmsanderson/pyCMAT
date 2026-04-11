"""
plots.py — Visualization for pyCMAT.

Two main outputs:
  1. Color table summary — heatmap of scores for all models x variables/realms,
     matching Figures 2-4 in Fasullo et al. (2020).
  2. Bias maps — placeholder (requires cartopy, Phase 4).
"""
import os
import sys
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
from matplotlib.patches import Rectangle

# Ensure config is importable when called from any working directory
sys.path.insert(0, os.path.dirname(__file__))
from config import REALM_VARS

# ---------------------------------------------------------------------------
# Canonical variable display labels (matching IDL allvars2 names)
# ---------------------------------------------------------------------------
_VAR_LABELS = {
    "rsnt":    "SWNET_TOA",
    "rlut":    "LWNET_TOA",
    "swcftoa": "SW_CF",
    "lwcftoa": "LW_CF",
    "fs":      "Fs",
    "rtfs":    "RT-Fs",
    "pr":      "P",
    "prw":     "PRW",
    "hurs":    "RH_sfc",
    "hfls":    "LH",
    "ep":      "E-P",
    "psl":     "SLP",
    "sfcWind": "U_sfc",
    "zg500":   "Z500",
    "wap500":  "W500",
    "hur500":  "RH500",
}

# Realm label colors (energy=warm red, water=blue, dynamics=green)
_REALM_COLORS = {
    "energy":   "#CC2222",
    "water":    "#1155CC",
    "dynamics": "#226622",
}

# Summary-row colors (black for aggregate rows)
_SUMMARY_COLORS = {
    "OVERALL":  "black",
    "ENERGY":   _REALM_COLORS["energy"],
    "WATER":    _REALM_COLORS["water"],
    "DYNAMICS": _REALM_COLORS["dynamics"],
    "ANNUAL":   "black",
    "SEASONAL": "black",
    "ENSO":     "black",
}

# Colormap: score range 0.45-0.95, RdYlGn (red=low, green=high)
_CMAP    = plt.cm.RdYlGn
_SCORE_MIN = 0.45
_SCORE_MAX = 0.95


def _score_to_label(val: float) -> str:
    """Format a 0-1 score as a 2-digit integer string (matching IDL roundoff)."""
    if np.isnan(val):
        return "NA"
    x = min(100, round(val * 100))
    return str(x)


def _var_realm(varname: str) -> str | None:
    for realm, vlist in REALM_VARS.items():
        if varname in vlist:
            return realm
    return None


def plot_colortable(
    scores_dict: dict,
    output_path: str,
    sort_by: str = "overall",
    title: str | None = None,
) -> None:
    """
    Generate the CMAT color table summary figure (Figures 2-4 style).

    Parameters
    ----------
    scores_dict : dict
        {model_name: score_json} where score_json is the content of scores.json
        written by the 'score' command.  Only the 'scores' sub-dict is used.
    output_path : str
        File path for the PNG output.
    sort_by : str
        Column sort key: 'overall', 'energy', 'water', 'dynamics',
        'annual', 'seasonal', 'enso'.
    title : str or None
        Figure title; auto-generated if None.
    """
    model_names = list(scores_dict.keys())
    nrun = len(model_names)

    # Gather all variables that appear in at least one model
    all_vars: set[str] = set()
    for sd in scores_dict.values():
        all_vars.update(sd["scores"]["variable"].keys())

    # Sort variables by mean score across models, descending (best at top)
    def _var_mean(v):
        vals = [scores_dict[m]["scores"]["variable"].get(v, float("nan"))
                for m in model_names]
        finite = [x for x in vals if not np.isnan(x)]
        return np.mean(finite) if finite else 0.0

    all_vars_sorted = sorted(all_vars, key=_var_mean, reverse=True)
    nvar = len(all_vars_sorted)
    nrows = 7 + nvar   # 7 summary rows + one per variable

    # Sort models by chosen score key, ascending (worst left → best right)
    def _model_sort_score(m):
        s = scores_dict[m]["scores"]
        if sort_by == "overall":
            return s.get("overall", 0.0)
        if sort_by in ("energy", "water", "dynamics"):
            return s.get("realm", {}).get(sort_by, 0.0)
        return s.get("timescale", {}).get(sort_by, 0.0)

    model_order = sorted(model_names, key=_model_sort_score)

    # Build data matrix: shape (nrows, nrun)
    # Row indices: 0=Overall, 1=Energy, 2=Water, 3=Dynamics,
    #              4=Annual, 5=Seasonal, 6=ENSO, 7+= vars
    data = np.full((nrows, nrun), np.nan)
    for ci, m in enumerate(model_order):
        s = scores_dict[m]["scores"]
        data[0, ci] = s.get("overall", np.nan)
        data[1, ci] = s.get("realm", {}).get("energy",   np.nan)
        data[2, ci] = s.get("realm", {}).get("water",    np.nan)
        data[3, ci] = s.get("realm", {}).get("dynamics", np.nan)
        data[4, ci] = s.get("timescale", {}).get("annual",   np.nan)
        data[5, ci] = s.get("timescale", {}).get("seasonal", np.nan)
        data[6, ci] = s.get("timescale", {}).get("enso",     np.nan)
        for ri, v in enumerate(all_vars_sorted):
            data[7 + ri, ci] = s.get("variable", {}).get(v, np.nan)

    # Color norm
    norm = mcolors.Normalize(vmin=_SCORE_MIN, vmax=_SCORE_MAX)

    # Figure dimensions (inches): fixed cell size, margins for labels
    CELL_W = max(0.45, min(1.0, 6.0 / max(nrun, 1)))
    CELL_H = 0.33
    LEFT   = 1.6    # room for row labels
    RIGHT  = 0.9    # room for colorbar
    TOP    = 0.7
    BOT    = max(1.0, 0.15 * max(len(m) for m in model_order))  # rotated names

    fig_w = LEFT + nrun * CELL_W + RIGHT
    fig_h = TOP + nrows * CELL_H + BOT

    fig = plt.figure(figsize=(fig_w, fig_h))

    # Main axes: normalized coords
    ax_l = LEFT / fig_w
    ax_b = BOT / fig_h
    ax_w = (nrun * CELL_W) / fig_w
    ax_h = (nrows * CELL_H) / fig_h
    ax = fig.add_axes([ax_l, ax_b, ax_w, ax_h])

    # Draw color cells
    for ri in range(nrows):
        for ci in range(nrun):
            val = data[ri, ci]
            y_bottom = nrows - 1 - ri
            if np.isnan(val):
                color = "white"
            else:
                color = _CMAP(norm(np.clip(val, _SCORE_MIN, _SCORE_MAX)))
            rect = Rectangle((ci, y_bottom), 1, 1,
                              facecolor=color, edgecolor="0.85", linewidth=0.3)
            ax.add_patch(rect)
            label = _score_to_label(val)
            # Use dark text on light cells, light text on very dark cells
            txt_color = "black"
            if not np.isnan(val) and val < 0.52:
                txt_color = "white"
            ax.text(ci + 0.5, y_bottom + 0.5, label,
                    ha="center", va="center",
                    fontsize=7, color=txt_color,
                    fontweight="normal")

    # Separator lines
    # Heavy line between summary section (rows 0-6) and variable section
    ax.axhline(nrows - 7, color="black", linewidth=2.5)
    # Medium line: between "overall" row and realm rows
    ax.axhline(nrows - 1, color="black", linewidth=1.5)
    # Medium line: between realm rows (dynamics/annual boundary)
    ax.axhline(nrows - 4, color="black", linewidth=1.5)

    # Row labels on the left
    summary_labels = ["OVERALL", "ENERGY", "WATER", "DYNAMICS",
                      "ANNUAL", "SEASONAL", "ENSO"]
    var_labels = [_VAR_LABELS.get(v, v.upper()) for v in all_vars_sorted]
    all_labels = summary_labels + var_labels
    all_label_colors = [_SUMMARY_COLORS[lbl] for lbl in summary_labels]
    for v in all_vars_sorted:
        realm = _var_realm(v)
        all_label_colors.append(_REALM_COLORS.get(realm, "black"))

    for ri, (lbl, lcol) in enumerate(zip(all_labels, all_label_colors)):
        y_center = nrows - 0.5 - ri
        ax.text(-0.08, y_center, lbl, ha="right", va="center",
                fontsize=7.5, color=lcol,
                transform=ax.transData)

    # Column labels (model names, rotated 45°)
    for ci, m in enumerate(model_order):
        ax.text(ci + 0.5, -0.3, m,
                ha="right", va="top", fontsize=7, rotation=45,
                transform=ax.transData)

    ax.set_xlim(0, nrun)
    ax.set_ylim(0, nrows)
    ax.axis("off")

    # Figure title
    if title is None:
        suffix = f" (sorted by {sort_by.capitalize()})" if sort_by != "overall" else ""
        title = f"Model Performance Summary: Mean Pattern Correlation{suffix}"
    ax.set_title(title, fontsize=10, pad=6)

    # Colorbar
    cbar_l = (LEFT + nrun * CELL_W + 0.15) / fig_w
    cbar_b = BOT / fig_h + 0.02
    cbar_h = ax_h * 0.85
    cbar_w = 0.25 / fig_w
    cbar_ax = fig.add_axes([cbar_l, cbar_b, cbar_w, cbar_h])
    sm = plt.cm.ScalarMappable(cmap=_CMAP, norm=norm)
    sm.set_array([])
    cbar = fig.colorbar(sm, cax=cbar_ax)
    cbar.set_ticks([0.45, 0.55, 0.65, 0.75, 0.85, 0.95])
    cbar.set_ticklabels(["45", "55", "65", "75", "85", "95"], fontsize=7)
    cbar.ax.tick_params(labelsize=7)

    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Bias map stub (requires cartopy — Phase 4)
# ---------------------------------------------------------------------------

def plot_bias_map(
    model_field,
    obs_field,
    title: str,
    output_path: str,
    units: str = "",
    stipple_mask=None,
    hatch_mask=None,
) -> None:
    """
    Three-panel bias map: model mean, obs, and bias with zonal mean panels.
    Requires cartopy (not yet installed).
    """
    raise NotImplementedError(
        "plot_bias_map requires cartopy.  Install cartopy and implement in Phase 4."
    )


# ---------------------------------------------------------------------------
# Score distribution whisker plot stub
# ---------------------------------------------------------------------------

def plot_score_distributions(
    scores_by_archive: dict,
    variable_list: list,
    output_path: str,
) -> None:
    """
    Whisker plots of score distributions across CMIP archives (Figure 10 style).
    """
    raise NotImplementedError("plot_score_distributions: Phase 4")
