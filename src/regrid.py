"""
regrid.py — Regrid xarray DataArrays to the CMAT 1-degree target grid and
apply land/ocean masks.

All model and observational fields are regridded to a common 1-deg
(360 lon x 180 lat) grid before pattern correlations are computed.  This
matches what the original IDL tool did (congrid() bilinear resampling).

Grid-type detection
-------------------
The module inspects each incoming DataArray and routes to the appropriate
backend:

  Regular lat/lon or Gaussian grid (1D lat, 1D lon coords)
    -> xarray.DataArray.interp() via scipy  [default; pip-only]

  Non-regular grid (2D lat/lon, cubed-sphere ncol dim, tripolar ocean, etc.)
    -> pyresample KDTree nearest-neighbour or bilinear  [pip-installable]
    -> falls back to scipy.interpolate.griddata if pyresample absent
    -> raises a clear error if neither is available, pointing to ncremap/xesmf

  Conservative remapping (explicit opt-in)
    -> xesmf  [optional; requires conda install of ESMF]
"""
from __future__ import annotations

import logging
import numpy as np
import xarray as xr
from config import TARGET_GRID

log = logging.getLogger(__name__)

# Pre-build target coordinate arrays once
_TARGET_LAT = np.linspace(-89.5, 89.5, TARGET_GRID["nlat"])
_TARGET_LON = np.linspace(0.5, 359.5, TARGET_GRID["nlon"])
_TARGET_LON_2D, _TARGET_LAT_2D = np.meshgrid(_TARGET_LON, _TARGET_LAT)


# ---------------------------------------------------------------------------
# Grid-type detection
# ---------------------------------------------------------------------------

def detect_grid_type(da: xr.DataArray) -> str:
    """
    Classify the horizontal grid of a DataArray.

    Returns
    -------
    str: one of
      'regular'      — 1D lat and lon coordinates (standard rectilinear /
                       Gaussian; xarray.interp works directly)
      'curvilinear'  — 2D lat and lon arrays (tripolar ocean grids,
                       rotated-pole grids)
      'unstructured' — single horizontal dimension (ncol for CAM-SE/EAM,
                       cell/node for ICON/FESOM)
    """
    # Check for unstructured: a single horizontal dim that is not lat or lon.
    # CAM-SE uses 'ncol' (physics grid) or 'ncol_d' (dynamics grid); other
    # models use 'cell', 'node', etc.  Match any dim that starts with 'ncol'
    # or equals a known unstructured dim name.
    _UNSTRUCT_EXACT = {"cell", "cells", "node", "nodes", "npoints", "gridcell"}
    for dim in da.dims:
        dl = dim.lower()
        if dl.startswith("ncol") or dl in _UNSTRUCT_EXACT:
            return "unstructured"

    lat_coord = _find_coord(da, ("lat", "latitude", "nav_lat", "y"))
    lon_coord = _find_coord(da, ("lon", "longitude", "nav_lon", "x"))

    if lat_coord is None or lon_coord is None:
        raise ValueError(
            f"Cannot identify lat/lon coordinates in DataArray '{da.name}'. "
            f"Dims: {da.dims}, Coords: {list(da.coords)}"
        )

    lat_vals = da[lat_coord]
    if lat_vals.ndim == 2:
        return "curvilinear"
    return "regular"


def _find_coord(da: xr.DataArray, candidates: tuple) -> str | None:
    """Return the first coordinate name from candidates that exists in da."""
    for c in candidates:
        if c in da.coords or c in da.dims:
            return c
        # Case-insensitive search
        for coord in list(da.coords) + list(da.dims):
            if coord.lower() == c.lower():
                return coord
    return None


# ---------------------------------------------------------------------------
# Main public entry point
# ---------------------------------------------------------------------------

def regrid_to_1deg(
    da: xr.DataArray,
    method: str = "linear",
) -> xr.DataArray:
    """
    Regrid a DataArray to the CMAT 1-degree target grid (360 x 180).

    Automatically selects the appropriate backend based on the input grid type.

    Parameters
    ----------
    da : xr.DataArray
        Input field (any horizontal resolution / grid type).
        Time and plev dimensions are handled transparently.
    method : str
        'linear'       — bilinear interpolation (default; matches IDL congrid)
        'nearest'      — nearest-neighbour (faster; useful for masks)
        'conservative' — conservative remapping via xesmf (requires conda ESMF)

    Returns
    -------
    xr.DataArray with dims (..., lat, lon) on the 1-degree target grid.
    """
    if method == "conservative":
        return _regrid_xesmf(da)

    grid_type = detect_grid_type(da)
    log.debug("Regridding '%s': grid_type=%s method=%s", da.name, grid_type, method)

    if grid_type == "regular":
        return _regrid_regular(da, method)
    elif grid_type in ("curvilinear", "unstructured"):
        return _regrid_nonregular(da, method)
    else:
        raise ValueError(f"Unknown grid type: {grid_type}")


# ---------------------------------------------------------------------------
# Backend: regular grids — xarray.interp (scipy)
# ---------------------------------------------------------------------------

def _regrid_regular(da: xr.DataArray, method: str = "linear") -> xr.DataArray:
    """Bilinear interpolation for regular/Gaussian grids via xarray.interp."""
    # Normalise longitude to 0-360
    da = _normalise_lon(da)

    # Rename non-standard coords to lat/lon so interp can find them
    rename = {}
    for c in list(da.dims) + list(da.coords):
        if c.lower() in ("latitude", "nav_lat") and c != "lat":
            rename[c] = "lat"
        elif c.lower() in ("longitude", "nav_lon") and c != "lon":
            rename[c] = "lon"
    if rename:
        da = da.rename(rename)

    return da.interp(
        lat=_TARGET_LAT,
        lon=_TARGET_LON,
        method=method,
        kwargs={"fill_value": None},  # allow edge extrapolation
    )


# ---------------------------------------------------------------------------
# Backend: non-regular grids — pyresample (pip) or scipy.griddata (fallback)
# ---------------------------------------------------------------------------

def _regrid_nonregular(da: xr.DataArray, method: str = "linear") -> xr.DataArray:
    """
    Regrid curvilinear or unstructured grids to the 1-degree target.

    Tries pyresample first (faster, pip-installable).  Falls back to
    scipy.interpolate.griddata.  Raises a descriptive error if neither
    can handle the data.
    """
    try:
        return _regrid_pyresample(da, method)
    except ImportError:
        log.warning(
            "pyresample not available; falling back to scipy.griddata "
            "(slower). Install pyresample for better performance: "
            "pip install pyresample"
        )
    return _regrid_griddata(da)


def _regrid_pyresample(da: xr.DataArray, method: str = "linear") -> xr.DataArray:
    """Pyresample-based regridding for non-regular grids."""
    try:
        import pyresample as pr
    except ImportError as e:
        raise ImportError("pyresample not installed") from e

    # Extract source lat/lon as flat arrays
    src_lat, src_lon = _extract_latlon_arrays(da)

    source_def = pr.geometry.SwathDefinition(
        lons=src_lon.ravel(), lats=src_lat.ravel()
    )
    target_def = pr.geometry.GridDefinition(
        lons=_TARGET_LON_2D, lats=_TARGET_LAT_2D
    )

    pr_method = "bilinear" if method == "linear" else "nearest"

    # Process each non-spatial slice (time, plev) separately
    def _resample_slice(arr_2d):
        result = pr.kd_tree.resample_nearest(
            source_def,
            arr_2d.ravel(),
            target_def,
            radius_of_influence=500_000,  # 500 km search radius
            fill_value=np.nan,
        )
        return result

    return _apply_over_slices(da, _resample_slice)


def _regrid_griddata(da: xr.DataArray) -> xr.DataArray:
    """scipy.interpolate.griddata fallback for non-regular grids."""
    from scipy.interpolate import griddata

    src_lat, src_lon = _extract_latlon_arrays(da)
    points = np.column_stack([src_lat.ravel(), src_lon.ravel()])
    target_points = np.column_stack([
        _TARGET_LAT_2D.ravel(), _TARGET_LON_2D.ravel()
    ])

    def _interp_slice(arr_2d):
        return griddata(
            points, arr_2d.ravel(), target_points, method="linear"
        ).reshape(TARGET_GRID["nlat"], TARGET_GRID["nlon"])

    return _apply_over_slices(da, _interp_slice)


# ---------------------------------------------------------------------------
# Backend: conservative (optional xesmf)
# ---------------------------------------------------------------------------

def _regrid_xesmf(da: xr.DataArray) -> xr.DataArray:
    """Conservative remapping via xesmf (requires conda install of ESMF)."""
    try:
        import xesmf as xe
    except ImportError as e:
        raise ImportError(
            "xesmf is required for conservative regridding.\n"
            "It is NOT pip-installable — install via conda:\n"
            "  conda install -c conda-forge xesmf\n"
            "Alternatively omit --method conservative to use bilinear "
            "interpolation (the default, matching IDL congrid behaviour)."
        ) from e

    target_ds = xr.Dataset({"lat": _("lat", _TARGET_LAT),
                            "lon": _("lon", _TARGET_LON)})
    regridder = xe.Regridder(da, target_ds, method="conservative", periodic=True)
    return regridder(da)


# ---------------------------------------------------------------------------
# Land / ocean masks
# ---------------------------------------------------------------------------

def get_land_mask() -> xr.DataArray:
    """
    Boolean mask (True = land) on the 1-degree target grid,
    built from regionmask Natural Earth 110m land polygons.
    """
    try:
        import regionmask
    except ImportError as e:
        raise ImportError(
            "regionmask is required for land/ocean masking. "
            "Run: pip install regionmask"
        ) from e

    land = regionmask.defined_regions.natural_earth_v5_0_0.land_110
    mask_ds = xr.Dataset(
        {"lat": _("lat", _TARGET_LAT), "lon": _("lon", _TARGET_LON)}
    )
    mask = land.mask(mask_ds)
    # regionmask: 0 = land, NaN = ocean
    return (mask == 0).rename("land_mask")


def get_ocean_mask() -> xr.DataArray:
    """Boolean mask (True = ocean) on the 1-degree target grid."""
    return (~get_land_mask()).rename("ocean_mask")


def apply_land_mask(da: xr.DataArray) -> xr.DataArray:
    """Set land grid points to NaN — keep ocean only."""
    return da.where(get_ocean_mask())


def apply_ocean_mask(da: xr.DataArray) -> xr.DataArray:
    """Set ocean grid points to NaN — keep land only."""
    return da.where(get_land_mask())


def remove_zonal_mean(da: xr.DataArray) -> xr.DataArray:
    """
    Remove the zonal mean, used for zg500 eddy geopotential
    (matching the IDL approach for that variable).
    """
    return da - da.mean(dim="lon")


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _normalise_lon(da: xr.DataArray) -> xr.DataArray:
    """Convert longitude coordinate to 0–360 if it runs –180 to 180."""
    lon_name = _find_coord(da, ("lon", "longitude", "nav_lon"))
    if lon_name and float(da[lon_name].values.min()) < 0:
        da = da.assign_coords({lon_name: da[lon_name] % 360}).sortby(lon_name)
    return da


def _extract_latlon_arrays(
    da: xr.DataArray,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Extract 2D lat/lon arrays from a DataArray regardless of whether they are
    stored as 1D coordinates, 2D coordinate variables, or auxiliary coords.
    Returns (lat_2d, lon_2d) as numpy arrays.
    """
    lat_name = _find_coord(da, ("lat", "latitude", "nav_lat", "y"))
    lon_name = _find_coord(da, ("lon", "longitude", "nav_lon", "x"))

    if lat_name is None or lon_name is None:
        raise ValueError(
            f"Cannot locate lat/lon in '{da.name}'. "
            f"Coords: {list(da.coords)}"
        )

    lat = da[lat_name].values
    lon = da[lon_name].values % 360  # normalise to 0-360

    # For regular grids, lat and lon are 1D axes of different lengths (nlat, nlon).
    # Broadcast them to 2D so pyresample / griddata receive consistent (N,) arrays.
    # For unstructured grids (SE/CAM-SE, cubed-sphere), lat and lon are paired 1D
    # arrays of the same length (ncol) — do NOT meshgrid; pass them as-is.
    if lat.ndim == 1 and lon.ndim == 1 and lat.shape != lon.shape:
        lon, lat = np.meshgrid(lon, lat)

    return lat, lon


def _apply_over_slices(
    da: xr.DataArray,
    func,  # function(2d_numpy_array) -> 2d_numpy_array on target grid
) -> xr.DataArray:
    """
    Apply func to each 2D horizontal slice of da (iterating over time and plev
    if present) and reassemble into a DataArray on the target grid.
    """
    # Identify the horizontal dims to stack
    non_horiz = [d for d in da.dims
                 if d.lower() not in ("lat", "latitude", "lon", "longitude",
                                      "nav_lat", "nav_lon", "x", "y")
                 and not d.lower().startswith("ncol")
                 and d.lower() not in ("cell", "cells", "node", "nodes",
                                       "npoints", "gridcell")]
    # Stack all non-horizontal dims into a single 'sample' dim for iteration
    if non_horiz:
        stacked = da.stack(sample=non_horiz)
    else:
        stacked = da.expand_dims("sample")

    results = []
    for i in range(stacked.sizes["sample"]):
        sl = stacked.isel(sample=i).values
        results.append(func(sl))

    out_data = np.stack(results, axis=0).reshape(
        [stacked.sizes["sample"]] + [TARGET_GRID["nlat"], TARGET_GRID["nlon"]]
    )

    # Build output DataArray with target lat/lon coords
    out = xr.DataArray(
        out_data,
        dims=["sample", "lat", "lon"],
        coords={
            "sample": stacked.coords["sample"] if "sample" in stacked.coords else np.arange(len(results)),
            "lat": _("lat", _TARGET_LAT),
            "lon": _("lon", _TARGET_LON),
        },
        name=da.name,
        attrs=da.attrs,
    )

    # Unstack sample back to original non-horizontal dims, then enforce
    # the canonical dim order (non-horiz dims first, then lat, lon).
    # xarray.unstack() does not guarantee to restore the original dim order,
    # so we always transpose explicitly.
    if non_horiz:
        out = out.unstack("sample")

    out = out.transpose(*non_horiz, "lat", "lon")

    return out


def _(name: str, data) -> xr.Variable:
    """Convenience: build a named xr.Variable from a numpy array."""
    return xr.Variable(name, data)
