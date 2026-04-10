"""
plots.py — Visualization for pyCMAT.

Two main outputs:
  1. Color table summary — heatmap of scores for all models x variables/realms,
     matching Figures 2-4 in Fasullo et al. (2020).
  2. Bias maps — 2D map plots with zonal mean panels for individual variables,
     matching Figure 1 in the paper. Stippling and hatching indicate regions
     where differences exceed internal variability or observational uncertainty.
"""
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors


# ---------------------------------------------------------------------------
# Color table summary (Figures 2-4)
# ---------------------------------------------------------------------------

def plot_colortable(
    scores: dict,
    model_names: list,
    output_path: str,
    sort_by: str = "overall",
    title: str = "Model Performance Summary: Mean Pattern Correlation",
) -> None:
    """
    Generate the CMAT color table summary figure.

    Parameters
    ----------
    scores : dict
        {model_name: {'overall': float, 'realm': {...}, 'variable': {...}, ...}}
        as returned by scoring.compute_scores().
    model_names : list of str
        Model names to display on x-axis.
    output_path : str
        Path (PNG) to save the figure.
    sort_by : str
        Score key to sort models by: 'overall', 'energy', 'water', 'dynamics'.
    title : str
        Figure title.
    """
    raise NotImplementedError("plot_colortable: implement with matplotlib")


# ---------------------------------------------------------------------------
# Bias map (Figure 1 style)
# ---------------------------------------------------------------------------

def plot_bias_map(
    model_field: "xr.DataArray",
    obs_field: "xr.DataArray",
    title: str,
    output_path: str,
    units: str = "",
    stipple_mask: "xr.DataArray | None" = None,
    hatch_mask: "xr.DataArray | None" = None,
) -> None:
    """
    Three-panel bias map: (top) model annual mean, (middle) obs, (bottom) bias.
    A zonal mean panel is appended to the right of each row.

    Parameters
    ----------
    model_field, obs_field : xr.DataArray
        Annual mean fields on the 1-degree grid.
    stipple_mask : xr.DataArray or None
        Boolean mask (True = stipple) where |bias| > 2 * internal variability.
    hatch_mask : xr.DataArray or None
        Boolean mask (True = hatch) where |bias| > variability + obs uncertainty.
    """
    raise NotImplementedError("plot_bias_map: implement with cartopy")


# ---------------------------------------------------------------------------
# Whisker/box plot (Figure 10)
# ---------------------------------------------------------------------------

def plot_score_distributions(
    scores_by_archive: dict,
    variable_list: list,
    output_path: str,
) -> None:
    """
    Whisker plots of score distributions across CMIP archives (Figure 10).

    Parameters
    ----------
    scores_by_archive : dict
        {'CMIP3': [...], 'CMIP5': [...], 'CMIP6': [...]}
        Each value is a list of score dicts from scoring.compute_scores().
    variable_list : list of str
        Variables to include (subset of the 16 scored variables).
    """
    raise NotImplementedError("plot_score_distributions: implement with matplotlib")
