"""
derived_vars.py — Compute CMAT diagnostic variables from CMIP6 component fields.

Most CMAT variables are either direct CMIP6 outputs (e.g., rlut, psl) or
simple linear combinations of multiple outputs (e.g., fs from six surface
flux components). Unit conversions are also applied here.

All functions accept xarray DataArrays and return xarray DataArrays.
Missing values are represented as NaN (not the IDL fill value 1e36).
"""
import numpy as np
import xarray as xr
from config import GRAV, L_V


# ---------------------------------------------------------------------------
# Energy realm
# ---------------------------------------------------------------------------

def calc_rsnt(rsdt: xr.DataArray, rsut: xr.DataArray) -> xr.DataArray:
    """Net TOA shortwave (absorbed solar radiation): rsdt - rsut."""
    return (rsdt - rsut).rename("rsnt")


def calc_swcftoa(rsut: xr.DataArray, rsutcs: xr.DataArray) -> xr.DataArray:
    """
    SW cloud forcing at TOA: rsut - rsutcs.
    Sign convention: negative values indicate SW cooling by clouds.
    """
    return (rsut - rsutcs).rename("swcftoa")


def calc_lwcftoa(rlut: xr.DataArray, rlutcs: xr.DataArray) -> xr.DataArray:
    """
    LW cloud forcing at TOA: rlutcs - rlut.
    Sign convention: positive values indicate LW warming by clouds.
    """
    return (rlutcs - rlut).rename("lwcftoa")


def calc_fs(
    rsds: xr.DataArray,
    rsus: xr.DataArray,
    rlds: xr.DataArray,
    rlus: xr.DataArray,
    hfls: xr.DataArray,
    hfss: xr.DataArray,
) -> xr.DataArray:
    """
    Net surface energy flux (residual method, positive downward into surface).

    fs = (rlds - rlus) + (rsds - rsus) - hfls - hfss

    The IDL code applies this over ocean only for scoring; the masking is
    applied downstream in pattern_cor.py, not here.
    """
    lw_net = rlds - rlus   # net LW into surface (positive down)
    sw_net = rsds - rsus   # net SW into surface (positive down)
    return (lw_net + sw_net - hfls - hfss).rename("fs")


def calc_rtfs(
    rsdt: xr.DataArray,
    rsut: xr.DataArray,
    rlut: xr.DataArray,
    rsds: xr.DataArray,
    rsus: xr.DataArray,
    rlds: xr.DataArray,
    rlus: xr.DataArray,
    hfls: xr.DataArray,
    hfss: xr.DataArray,
) -> xr.DataArray:
    """
    Column energy imbalance: RT - Fs  (TOA net radiation minus surface net flux).
    Proxy for column energy tendency / atmospheric energy divergence.
    """
    rt = (rsdt - rsut) - rlut
    fs = calc_fs(rsds, rsus, rlds, rlus, hfls, hfss)
    return (rt - fs).rename("rtfs")


# ---------------------------------------------------------------------------
# Water realm
# ---------------------------------------------------------------------------

def calc_pr_mmday(pr: xr.DataArray) -> xr.DataArray:
    """Convert precipitation from kg m-2 s-1 to mm day-1."""
    return (pr * 86400.0).rename("pr")


def calc_ep(hfls: xr.DataArray, pr: xr.DataArray) -> xr.DataArray:
    """
    E-P: evaporation minus precipitation, in mm day-1.

    Evaporation is estimated from latent heat flux: E = hfls / L_v (kg m-2 s-1),
    then converted to mm day-1.  Precipitation is converted from kg m-2 s-1 to
    mm day-1.  Sign: positive where evaporation exceeds precipitation.
    """
    evap_mmday = (hfls / L_V) * 86400.0
    pr_mmday = pr * 86400.0
    return (evap_mmday - pr_mmday).rename("ep")


# ---------------------------------------------------------------------------
# Dynamics realm
# ---------------------------------------------------------------------------

def calc_zg500(zg: xr.DataArray) -> xr.DataArray:
    """
    Extract 500 hPa geopotential height (m) and remove the zonal mean.

    zg is in m2 s-2 (geopotential); divide by g to get geopotential height (m).
    The zonal mean is removed to isolate eddy structure, matching the IDL approach.
    """
    # Select 500 hPa level (coordinate may be in Pa or hPa; normalise)
    plev = zg["plev"] if "plev" in zg.coords else zg["lev"]
    if plev.values.max() < 2000:
        # Likely in hPa
        z500 = zg.sel(plev=500.0, method="nearest")
    else:
        # Likely in Pa
        z500 = zg.sel(plev=50000.0, method="nearest")

    z500_m = (z500 / GRAV).rename("zg500")
    # Remove zonal mean
    return (z500_m - z500_m.mean(dim="lon")).rename("zg500")


def calc_wap500(wap: xr.DataArray) -> xr.DataArray:
    """Extract 500 hPa vertical pressure velocity (Pa s-1)."""
    plev = wap["plev"] if "plev" in wap.coords else wap["lev"]
    if plev.values.max() < 2000:
        return wap.sel(plev=500.0, method="nearest").rename("wap500")
    return wap.sel(plev=50000.0, method="nearest").rename("wap500")


def calc_hur500(hur: xr.DataArray) -> xr.DataArray:
    """Extract 500 hPa relative humidity (%)."""
    plev = hur["plev"] if "plev" in hur.coords else hur["lev"]
    if plev.values.max() < 2000:
        return hur.sel(plev=500.0, method="nearest").rename("hur500")
    return hur.sel(plev=50000.0, method="nearest").rename("hur500")
