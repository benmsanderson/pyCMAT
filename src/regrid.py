"""
regrid.py — Regrid xarray DataArrays to the CMAT 1-degree target grid and
apply land/ocean masks.

All model and observational fields are regridded to a common 1-deg
(360 lon x 180 lat) grid before pattern correlations are computed, matching
the IDL congrid() approach but using conservative remapping via xesmf.
"""
import numpy as np
import xarray as xr

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def make_target_grid(nlon: int = 360, nlat: int = 180) -> xr.Dataset:
    """Return an xarray Dataset describing the CMAT 1-degree target grid."""
    lon = np.linspace(0.5, 359.5, nlon)
    lat = np.linspace(-89.5, 89.5, nlat)
    return xr.Dataset({"lat": lat, "lon": lon})


def regrid_to_1deg(da: xr.DataArray, method: str = "conservative") -> xr.DataArray:
    """
    Regrid a DataArray to the CMAT 1-degree target grid.

    Parameters
    ----------
    da : xr.DataArray
        Input field with 'lat' and 'lon' dimensions (any resolution).
    method : str
        xesmf regridding method. 'conservative' is preferred for flux fields;
        'bilinear' is acceptable for non-flux fields and faster.

    Returns
    -------
    xr.DataArray regridded to 360 x 180.
    """
    raise NotImplementedError("regrid_to_1deg: install xesmf and implement")


def get_land_mask(nlat: int = 180, nlon: int = 360) -> xr.DataArray:
    """
    Return a boolean DataArray (True = land) on the 1-degree target grid,
    using regionmask Natural Earth land polygons.
    """
    raise NotImplementedError("get_land_mask: install regionmask and implement")


def get_ocean_mask(nlat: int = 180, nlon: int = 360) -> xr.DataArray:
    """Return a boolean DataArray (True = ocean) on the 1-degree target grid."""
    raise NotImplementedError("get_ocean_mask: install regionmask and implement")


def remove_zonal_mean(da: xr.DataArray) -> xr.DataArray:
    """
    Remove the zonal mean from a 2D or 3D field, used for zg500 eddy
    geopotential (matching IDL behaviour for that variable).
    """
    return da - da.mean(dim="lon")
