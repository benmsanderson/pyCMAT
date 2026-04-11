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
# Bias map (Phase 4) — requires cartopy
# ---------------------------------------------------------------------------

def _get_lat_lon(da):
    """Return (lat_name, lon_name) coordinate names for a DataArray."""
    for lat_cand in ("lat", "latitude"):
        for lon_cand in ("lon", "longitude"):
            if lat_cand in da.coords and lon_cand in da.coords:
                return lat_cand, lon_cand
    raise ValueError(f"Cannot find lat/lon coords in {list(da.coords)}")


def _norm_coords(da):
    """Rename latitude/longitude → lat/lon if needed; drop pressure level."""
    renames = {}
    if "latitude" in da.dims:
        renames["latitude"] = "lat"
    if "longitude" in da.dims:
        renames["longitude"] = "lon"
    if renames:
        da = da.rename(renames)
    # Drop any scalar pressure-level coordinate
    for c in list(da.coords):
        if c in ("level", "plev", "pressure") and da.coords[c].ndim == 0:
            da = da.drop_vars(c)
    return da


def _draw_map_panel(ax, data, cmap, norm, lat, lon, title_str, units, cbar_label):
    """Fill one geographic panel; return the mappable for the colorbar."""
    import cartopy.crs as ccrs
    import cartopy.feature as cfeature

    ax.set_global()
    ax.add_feature(cfeature.COASTLINE, linewidth=0.5, edgecolor="0.3")
    ax.add_feature(cfeature.BORDERS, linewidth=0.3, edgecolor="0.5")
    mesh = ax.pcolormesh(
        lon, lat, data,
        cmap=cmap, norm=norm,
        transform=ccrs.PlateCarree(),
        rasterized=True,
    )
    ax.set_title(title_str, fontsize=8, pad=3)
    return mesh


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
    Four-panel bias figure: obs climatology | model climatology | bias (model-obs)
    | zonal mean comparison (line plot).

    Parameters
    ----------
    model_field : xarray.DataArray
        Model field, (time, lat, lon) or (lat, lon). Time mean is taken automatically.
    obs_field : xarray.DataArray
        Observational field on the same or different grid.
    title : str
        Top-level figure title.
    output_path : str
        Output PNG path.
    units : str
        Physical units for colorbar labels.
    stipple_mask : np.ndarray or None
        2D boolean array (lat × lon on the model grid) — True where bias is
        statistically significant. Plotted as black dots on the bias panel.
    hatch_mask : np.ndarray or None
        Alternative significance mask plotted as hatching (not both).
    """
    import cartopy.crs as ccrs

    # --- Normalize coordinates -------------------------------------------------
    model_field = _norm_coords(model_field)
    obs_field   = _norm_coords(obs_field)

    # --- Time mean -------------------------------------------------------------
    if "time" in model_field.dims:
        model_m = model_field.mean("time").load()
    else:
        model_m = model_field.load()
    if "time" in obs_field.dims:
        obs_m = obs_field.mean("time").load()
    else:
        obs_m = obs_field.load()

    # --- Align on the model grid (obs may be at different resolution) ----------
    obs_m_rg = obs_m.interp(lat=model_m.lat, lon=model_m.lon, method="linear")
    bias = model_m - obs_m_rg

    lat = model_m.lat.values
    lon = model_m.lon.values

    # --- Color ranges ----------------------------------------------------------
    # Use the 3rd-97th percentile of combined obs+model to set the shared map range
    combined = np.concatenate([obs_m.values.ravel(), model_m.values.ravel()])
    finite   = combined[np.isfinite(combined)]
    vmin = float(np.percentile(finite, 3))
    vmax = float(np.percentile(finite, 97))

    bias_vals = bias.values.ravel()
    bias_finite = bias_vals[np.isfinite(bias_vals)]
    bmax = float(np.percentile(np.abs(bias_finite), 97)) if bias_finite.size else 1.0

    # Colormaps
    cmap_field = plt.cm.viridis
    cmap_bias  = plt.cm.RdBu_r
    norm_field = mcolors.Normalize(vmin=vmin, vmax=vmax)
    norm_bias  = mcolors.TwoSlopeNorm(vmin=-bmax, vcenter=0.0, vmax=bmax)

    proj = ccrs.Robinson()

    # --- Layout: 3 map panels + 1 zonal-mean panel ----------------------------
    fig = plt.figure(figsize=(16, 4.5))
    fig.suptitle(title, fontsize=11, y=1.01)

    # 3 geographic subplots + 1 line-plot
    axes_map = [
        fig.add_subplot(1, 4, 1, projection=proj),
        fig.add_subplot(1, 4, 2, projection=proj),
        fig.add_subplot(1, 4, 3, projection=proj),
    ]
    ax_zm = fig.add_subplot(1, 4, 4)

    # Panel 1: obs
    m1 = _draw_map_panel(
        axes_map[0], obs_m.values, cmap_field, norm_field,
        obs_m.lat.values, obs_m.lon.values,
        f"OBS ({units})", units, units,
    )
    # Panel 2: model
    _ = _draw_map_panel(
        axes_map[1], model_m.values, cmap_field, norm_field,
        lat, lon,
        f"Model ({units})", units, units,
    )
    # Panel 3: bias
    m3 = _draw_map_panel(
        axes_map[2], bias.values, cmap_bias, norm_bias,
        lat, lon,
        f"Bias: Model − OBS ({units})", units, units,
    )
    # Stippling / hatching on bias panel
    if stipple_mask is not None:
        import cartopy.crs as _ccrs
        yy, xx = np.where(stipple_mask)
        axes_map[2].scatter(
            lon[xx], lat[yy], s=0.5, c="k", alpha=0.4,
            transform=_ccrs.PlateCarree(), zorder=5,
        )
    elif hatch_mask is not None:
        pass  # reserved for future hatching implementation

    # Colorbars below maps 1+2 (shared) and map 3
    fig.colorbar(m1, ax=axes_map[:2], orientation="horizontal",
                  pad=0.03, fraction=0.04, label=units, shrink=0.9)
    fig.colorbar(m3, ax=axes_map[2], orientation="horizontal",
                  pad=0.03, fraction=0.04, label=units, shrink=0.9)

    # --- Panel 4: zonal mean --------------------------------------------------
    model_zm = model_m.mean("lon").values
    obs_zm   = obs_m.interp(lat=model_m.lat, method="linear").mean("lon").values
    lat_zm   = lat

    ax_zm.plot(obs_zm,   lat_zm, "b-",  linewidth=1.5, label="OBS")
    ax_zm.plot(model_zm, lat_zm, "r--", linewidth=1.5, label="Model")
    ax_zm.fill_betweenx(lat_zm, obs_zm, model_zm, alpha=0.15, color="gray")
    ax_zm.axvline(0, color="k", linewidth=0.5)
    ax_zm.set_ylim(-90, 90)
    ax_zm.set_yticks([-60, -30, 0, 30, 60])
    ax_zm.set_yticklabels(["60°S", "30°S", "0°", "30°N", "60°N"], fontsize=7)
    ax_zm.set_xlabel(units, fontsize=8)
    ax_zm.set_title("Zonal Mean", fontsize=8, pad=3)
    ax_zm.legend(fontsize=7, frameon=False)
    ax_zm.grid(True, linewidth=0.4, color="0.8")
    ax_zm.tick_params(labelsize=7)

    plt.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


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
