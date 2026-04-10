"""
pattern_cor.py — Area-weighted pattern correlation between model and observed fields.

Replaces the IDL make_ncl_pat_cor() function, which wrapped the NCL built-in
pattern_cor(). The formula is the standard area-weighted Pearson correlation:

    Rs = sum_i[ w_i * (X_i - X_bar) * (Y_i - Y_bar) ]
         / sqrt( sum_i[w_i*(X_i-X_bar)^2] * sum_i[w_i*(Y_i-Y_bar)^2] )

where w_i = cos(lat_i) and overbars are weighted global means.
Grid points that are NaN in either field are excluded from both.
"""
import numpy as np
import xarray as xr


def pattern_cor(
    model: xr.DataArray,
    obs: xr.DataArray,
    lat_dim: str = "lat",
) -> float:
    """
    Area-weighted pattern correlation between two 2D fields.

    Parameters
    ----------
    model : xr.DataArray
        Simulated field on the 1-degree target grid (lat, lon).
    obs : xr.DataArray
        Observed/reference field on the same grid (lat, lon).
    lat_dim : str
        Name of the latitude dimension.

    Returns
    -------
    float in [-1, 1].  Returns NaN if fewer than 10 valid grid points.
    """
    # Cosine-latitude weights
    weights = np.cos(np.deg2rad(model[lat_dim]))
    weights = weights / weights.sum()  # normalise so weights sum to 1

    # Broadcast weights to 2D
    w2d = weights.broadcast_like(model)

    # Mask where either field is NaN
    valid = np.isfinite(model) & np.isfinite(obs)
    if int(valid.sum()) < 10:
        return float("nan")

    # Apply mask
    x = model.where(valid)
    y = obs.where(valid)
    w = w2d.where(valid)
    # Re-normalise weights over valid points
    w = w / w.sum()

    # Weighted means
    x_bar = (w * x).sum()
    y_bar = (w * y).sum()

    # Anomalies
    xp = x - x_bar
    yp = y - y_bar

    # Weighted covariance and variances
    cov = (w * xp * yp).sum()
    var_x = (w * xp ** 2).sum()
    var_y = (w * yp ** 2).sum()

    denom = float(np.sqrt(var_x * var_y))
    if denom == 0.0:
        return float("nan")

    return float(cov / denom)


def pattern_cor_all_timescales(
    model_annual: xr.DataArray,
    model_seasonal: xr.DataArray,
    model_enso: xr.DataArray,
    obs_annual: xr.DataArray,
    obs_seasonal: xr.DataArray,
    obs_enso: xr.DataArray,
) -> dict:
    """
    Compute pattern correlations for all three CMAT timescales.

    Returns
    -------
    dict with keys 'annual', 'seasonal', 'enso', each a float.
    """
    return {
        "annual":   pattern_cor(model_annual,   obs_annual),
        "seasonal": pattern_cor(model_seasonal, obs_seasonal),
        "enso":     pattern_cor(model_enso,     obs_enso),
    }
