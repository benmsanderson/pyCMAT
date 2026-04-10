"""
eof_analysis.py — Bias EOF/PC analysis across a multi-model ensemble.

Computes empirical orthogonal functions of the model bias field (model - obs)
as described in Section 2.3 of Fasullo et al. (2020, GMD). The analysis uses
the covariance matrix of bias patterns across models and produces:
  - Leading EOF spatial patterns (as regression maps)
  - PC time series (one value per model)
  - Variance explained by each EOF

This reproduces Figures 6-9 in the paper for individual variables.
"""
import numpy as np
import xarray as xr


def compute_bias_eofs(
    bias_stack: xr.DataArray,
    n_eofs: int = 2,
    lat_dim: str = "lat",
    lon_dim: str = "lon",
    model_dim: str = "model",
) -> dict:
    """
    Principal component analysis of gridded bias patterns across models.

    Parameters
    ----------
    bias_stack : xr.DataArray
        Array of shape (model, lat, lon) containing the bias field
        (model - obs) for each model, already on the 1-degree target grid.
    n_eofs : int
        Number of leading EOFs to return (default 2, as in the paper).
    lat_dim, lon_dim, model_dim : str
        Dimension names.

    Returns
    -------
    dict with keys:
        'eofs'        : xr.DataArray (n_eofs, lat, lon) — spatial patterns
                        expressed as regression maps (same units as bias field)
        'pcs'         : xr.DataArray (n_eofs, model) — normalised PC values
        'variance_pct': np.ndarray (n_eofs,) — variance explained (percent)
    """
    raise NotImplementedError("compute_bias_eofs: implement with sklearn PCA")
