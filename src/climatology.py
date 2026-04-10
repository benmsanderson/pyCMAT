"""
climatology.py — Compute the three CMAT diagnostic timescales from monthly data.

Timescales:
  1. Annual mean climatology
  2. Seasonal contrast (JJA - DJF)
  3. ENSO teleconnection (linear regression of Jul-Jun annual means against
     the Niño3.4 SST anomaly index)

All functions accept xarray DataArrays with a 'time' dimension encoded as
cftime or numpy datetime64 objects and return 2D (lat x lon) DataArrays.
"""
import numpy as np
import xarray as xr
from config import NINO34_LAT, NINO34_LON


# ---------------------------------------------------------------------------
# Annual and seasonal means
# ---------------------------------------------------------------------------

def annual_mean(da: xr.DataArray) -> xr.DataArray:
    """Time-mean of all months (climatological annual mean)."""
    return da.mean(dim="time")


def seasonal_contrast(da: xr.DataArray) -> xr.DataArray:
    """
    JJA minus DJF seasonal contrast.

    Computes the mean over June-July-August months minus the mean over
    December-January-February months, averaged over all years in the record.
    """
    jja = da.sel(time=da.time.dt.season == "JJA").mean(dim="time")
    djf = da.sel(time=da.time.dt.season == "DJF").mean(dim="time")
    return (jja - djf).rename(da.name)


# ---------------------------------------------------------------------------
# ENSO teleconnection
# ---------------------------------------------------------------------------

def nino34_index(sst: xr.DataArray) -> xr.DataArray:
    """
    Compute the Niño3.4 SST anomaly index (area-weighted mean over
    5S-5N, 170W-120W / 190E-240E), as Jul-Jun annual means.

    Parameters
    ----------
    sst : xr.DataArray
        Monthly SST or surface temperature (lat, lon, time).

    Returns
    -------
    xr.DataArray of annual (Jul-Jun) Niño3.4 anomalies.
    """
    lat_s, lat_n = NINO34_LAT
    lon_w, lon_e = NINO34_LON

    # Subset to Niño3.4 region
    region = sst.sel(lat=slice(lat_s, lat_n), lon=slice(lon_w, lon_e))

    # Area-weighted mean
    weights = np.cos(np.deg2rad(region.lat))
    nino34_monthly = region.weighted(weights).mean(dim=("lat", "lon"))

    # Remove monthly climatology to get anomalies
    clim = nino34_monthly.groupby("time.month").mean()
    nino34_anom = nino34_monthly.groupby("time.month") - clim

    # Resample to Jul-Jun annual means
    return _juljun_annual_mean(nino34_anom)


def enso_teleconnection(
    da: xr.DataArray, sst: xr.DataArray
) -> xr.DataArray:
    """
    Compute the ENSO teleconnection pattern: linear regression of Jul-Jun
    annual mean anomalies of 'da' against the Niño3.4 SST anomaly index.

    The regression slope has units of [da units] / K and represents the
    expected change per 1 K of Niño3.4 warming.

    Parameters
    ----------
    da : xr.DataArray
        Monthly climate field (time, lat, lon).
    sst : xr.DataArray
        Monthly SST/surface temperature used to derive Niño3.4 index.

    Returns
    -------
    xr.DataArray (lat, lon) of regression slopes.
    """
    # Annual (Jul-Jun) means of both fields over overlapping period
    da_annual = _juljun_annual_mean(da)
    nino = nino34_index(sst)

    # Align time axes
    da_annual, nino = xr.align(da_annual, nino, join="inner")

    if len(da_annual.time) < 5:
        raise ValueError(
            f"Fewer than 5 overlapping Jul-Jun years for ENSO regression "
            f"(got {len(da_annual.time)}). Check period overlap."
        )

    # Remove time mean (anomalies)
    da_anom = da_annual - da_annual.mean(dim="time")
    nino_anom = nino - nino.mean(dim="time")

    # OLS slope: cov(X,Y) / var(X) applied pointwise via dot product
    nino_var = float((nino_anom ** 2).sum(dim="time"))
    slope = (da_anom * nino_anom).sum(dim="time") / nino_var

    return slope.rename(da.name)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _juljun_annual_mean(da: xr.DataArray) -> xr.DataArray:
    """
    Resample monthly data into Jul-Jun annual means.

    Each year label corresponds to the July that starts the 12-month window
    (i.e., year Y covers Jul-Y through Jun-(Y+1)).
    """
    # Shift time so July becomes month 1 of a fiscal year, then resample
    # xarray's resample with offset handles this cleanly
    return da.resample(time="YS-JUL").mean(dim="time")
