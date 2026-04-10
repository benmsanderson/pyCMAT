"""
obs_fetcher.py — Download and pre-process observational reference datasets
for pyCMAT scoring.

Three sources are supported, covering all 16 CMAT scored variables:

  CERES EBAF Ed4.2 (NASA ASDC / Earthdata)
    Variables: rsnt, rlut, swcftoa, lwcftoa, + surface radiation for fs/rtfs
    Auth: free NASA Earthdata account; token stored in ~/.netrc or passed as
          EARTHDATA_TOKEN env var.
    Format: monthly mean NetCDF at 1-degree on the original CERES grid.

  GPCP CDR v2.3 (NOAA PSL)
    Variables: pr (mm day-1)
    Auth: none (open HTTP)
    Format: single global monthly file.

  ERA5 (Copernicus CDS)
    Variables: prw, hurs, hfls, hfss (for ep/fs/rtfs), psl, sfcWind,
               ts (Nino3.4 SST), zg/wap/hur at 500 hPa
    Auth: requires ~/.cdsapirc  (free CDS account; see
          https://cds.climate.copernicus.eu/how-to-api)
    Format: single-level and pressure-level monthly means via cdsapi.

All fetchers write pre-processed climatology files (time-mean over the obs
period) to obs_dir/<cmat_var>.nc in a format that pipeline.py understands
directly (2D lat x lon DataArrays, or time-resolved for ENSO).
"""
from __future__ import annotations

import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Optional

import numpy as np
import xarray as xr

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# CERES EBAF Ed4.2
# ---------------------------------------------------------------------------
# CERES EBAF Ed4.2 is distributed as a single combined NetCDF covering the
# full mission (March 2000 - present).  We use earthaccess to search and
# download via NASA Earthdata (~/.netrc or EARTHDATA_TOKEN env var).
#
# Concept IDs (short_names) on CMR:
#   TOA monthly: CERES_EBAF-TOA_Ed4.2
#   SFC monthly: CERES_EBAF-SFC_Ed4.2

# Variable names inside CERES EBAF NetCDF files -> CMAT variable names
_CERES_TOA_MAP = {
    "toa_sw_all_mon":      ("rsut",    "TOA outgoing SW all-sky monthly mean"),
    "toa_sw_clr_c_mon":    ("rsutcs",  "TOA outgoing SW clear-sky"),
    "toa_lw_all_mon":      ("rlut",    "TOA outgoing LW all-sky monthly mean"),
    "toa_lw_clr_c_mon":    ("rlutcs",  "TOA outgoing LW clear-sky"),
    "solar_mon":           ("rsdt",    "TOA incident SW"),
}

_CERES_SFC_MAP = {
    "sfc_sw_down_all_mon": ("rsds",  "Surface downwelling SW all-sky"),
    "sfc_sw_up_all_mon":   ("rsus",  "Surface upwelling SW all-sky"),
    "sfc_lw_down_all_mon": ("rlds",  "Surface downwelling LW all-sky"),
    "sfc_lw_up_all_mon":   ("rlus",  "Surface upwelling LW all-sky"),
}


def fetch_ceres(
    obs_dir: Path,
    start_year: int = 2001,
    end_year: int = 2022,
    earthdata_token: Optional[str] = None,
) -> list[str]:
    """
    Download CERES EBAF Ed4.2 TOA and Surface data and derive CMAT obs fields.

    Uses earthaccess to search CMR and download via ~/.netrc or
    EARTHDATA_TOKEN env var.

    Writes to obs_dir:
      rsnt.nc, rlut.nc, swcftoa.nc, lwcftoa.nc
      rsdt.nc, rsut.nc, rsutcs.nc, rlutcs.nc   (intermediates, also kept)
      rsds.nc, rsus.nc, rlds.nc, rlus.nc        (surface; needed for fs/rtfs)
    """
    try:
        import earthaccess
    except ImportError as e:
        raise ImportError(
            "earthaccess is required to download CERES data.\n"
            "Run: pip install earthaccess"
        ) from e

    # Auth: earthaccess reads ~/.netrc automatically
    if earthdata_token:
        os.environ["EARTHDATA_TOKEN"] = earthdata_token
    earthaccess.login(strategy="netrc", persist=False)

    written = []
    with tempfile.TemporaryDirectory() as tmpdir:
        # CERES_EBAF (Edition4.2) is a combined TOA+SFC file — one download
        # covers both TOA and surface variables.
        log.info("Searching CMR for CERES_EBAF Edition4.2 ...")
        results = earthaccess.search_data(
            short_name="CERES_EBAF",
            version="Edition4.2",
            temporal=(f"{start_year}-01-01", f"{end_year}-12-31"),
            count=200,
        )
        if not results:
            # Try without version constraint (picks any available edition)
            log.info("Retrying CERES_EBAF without version constraint ...")
            results = earthaccess.search_data(
                short_name="CERES_EBAF",
                temporal=(f"{start_year}-01-01", f"{end_year}-12-31"),
                count=200,
            )
        if not results:
            log.error(
                "No CMR results for CERES_EBAF; check Earthdata auth (~/.netrc) "
                "and date range. Skipping CERES."
            )
            return written

        log.info("Downloading %d CERES granule(s) ...", len(results))
        files = earthaccess.download(results, local_path=tmpdir)
        if not files:
            log.error("CERES download returned no files; check Earthdata auth.")
            return written

        ds = xr.open_mfdataset(sorted(files), combine="by_coords")
        if "time" in ds.dims:
            ds = ds.sel(time=slice(str(start_year), str(end_year)))

        # Process both TOA and surface variables from the combined file
        written += _process_ceres_toa(ds, obs_dir)
        written += _process_ceres_sfc(ds, obs_dir)

    return written


def _process_ceres_toa(ds: xr.Dataset, obs_dir: Path) -> list[str]:
    """Derive CMAT TOA radiation obs fields from a CERES EBAF-TOA dataset."""
    # Rename CERES long lat/lon names
    rename = {}
    for d in ds.dims:
        if "lat" in d.lower():
            rename[d] = "lat"
        elif "lon" in d.lower():
            rename[d] = "lon"
    ds = ds.rename(rename)

    written = []
    raw = {}
    for ceres_name, (cmat_name, _) in _CERES_TOA_MAP.items():
        if ceres_name in ds:
            da = ds[ceres_name].rename(cmat_name)
            raw[cmat_name] = da
            # Write intermediate field
            _write_clim(da, obs_dir / f"{cmat_name}.nc")
            written.append(cmat_name)

    # Derive scored variables
    if "rsdt" in raw and "rsut" in raw:
        rsnt = (raw["rsdt"] - raw["rsut"]).rename("rsnt")
        _write_clim(rsnt, obs_dir / "rsnt.nc")
        written.append("rsnt")

    if "rsut" in raw and "rsutcs" in raw:
        swcf = (raw["rsut"] - raw["rsutcs"]).rename("swcftoa")
        _write_clim(swcf, obs_dir / "swcftoa.nc")
        written.append("swcftoa")

    if "rlut" in raw and "rlutcs" in raw:
        lwcf = (raw["rlutcs"] - raw["rlut"]).rename("lwcftoa")
        _write_clim(lwcf, obs_dir / "lwcftoa.nc")
        written.append("lwcftoa")

    return written


def _process_ceres_sfc(ds: xr.Dataset, obs_dir: Path) -> list[str]:
    """Write surface radiation obs fields from CERES EBAF-SFC dataset."""
    rename = {}
    for d in ds.dims:
        if "lat" in d.lower():
            rename[d] = "lat"
        elif "lon" in d.lower():
            rename[d] = "lon"
    ds = ds.rename(rename)

    written = []
    for ceres_name, (cmat_name, _) in _CERES_SFC_MAP.items():
        if ceres_name in ds:
            da = ds[ceres_name].rename(cmat_name)
            _write_clim(da, obs_dir / f"{cmat_name}.nc")
            written.append(cmat_name)
    return written


# ---------------------------------------------------------------------------
# GPCP CDR v2.3 (NOAA PSL — open access, no auth)
# ---------------------------------------------------------------------------
# Monthly mean precipitation, 2.5-degree, 1979-present.
# Single file updated regularly at NOAA PSL.
_GPCP_URL = "https://downloads.psl.noaa.gov/Datasets/gpcp/precip.mon.mean.nc"


def fetch_gpcp(
    obs_dir: Path,
    start_year: int = 1979,
    end_year: int = 2020,
) -> list[str]:
    """
    Download GPCP CDR v2.3 monthly precipitation and write obs/pr.nc.

    The NOAA PSL copy is a single file (~60 MB) with monthly means from
    1979 to near-present at 2.5-degree resolution.

    Returns list of written file paths.
    """
    try:
        import requests
    except ImportError as e:
        raise ImportError("pip install requests") from e

    dest = obs_dir / "_gpcp_monthly.nc"
    log.info("Downloading GPCP from NOAA PSL ...")
    with requests.Session() as sess:
        log.info("Downloading %s ...", _GPCP_URL)
        r = sess.get(_GPCP_URL, stream=True, timeout=180)
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                f.write(chunk)
        log.info("  -> %s (%d MB)", dest.name, dest.stat().st_size >> 20)
    ok = dest.exists() and dest.stat().st_size > 1000
    if not ok:
        raise RuntimeError(f"GPCP download failed from {_GPCP_URL}")

    # Open and process — GPCP uses a non-standard calendar; decode time manually
    ds = xr.open_dataset(dest, decode_times=False)
    # NOAA PSL GPCP variable is 'precip' in mm/day already
    pr = ds["precip"].astype("float32").rename("pr")

    # Build a proper time axis from the months dimension
    import pandas as pd
    n_months = pr.sizes["time"]
    # Reference is 1979-01 (GPCP starts Jan 1979)
    time_index = pd.date_range("1979-01", periods=n_months, freq="MS")
    pr = pr.assign_coords(time=time_index)

    # Rename if needed
    rename = {}
    for d in pr.dims:
        dl = d.lower()
        if "lat" in dl and d != "lat":
            rename[d] = "lat"
        elif "lon" in dl and d != "lon":
            rename[d] = "lon"
    if rename:
        pr = pr.rename(rename)

    # Normalise lon to 0-360 if -180 to 180
    if float(pr.lon.min()) < 0:
        pr = pr.assign_coords(lon=(pr.lon % 360)).sortby("lon")

    # Slice to requested period
    pr = pr.sel(time=slice(str(start_year), str(end_year)))

    out_path = obs_dir / "pr.nc"
    _write_clim(pr, out_path)
    dest.unlink(missing_ok=True)  # remove raw download
    log.info("GPCP written to %s", out_path)
    return ["pr"]


# ---------------------------------------------------------------------------
# ERA5 via CDS API
# ---------------------------------------------------------------------------
# Requires ~/.cdsapirc with valid CDS credentials.
# See: https://cds.climate.copernicus.eu/how-to-api
#
# Variable mappings from ERA5 short names / CDS names -> CMAT names.
_ERA5_SINGLE_LEVEL_VARS = {
    # CDS parameter name                  : (era5_short, cmat_var, factor, offset)
    "mean_sea_level_pressure"             : ("msl",  "psl",     1.0,    0.0),
    "10m_wind_speed"                      : ("si10", "sfcWind", 1.0,    0.0),
    "total_column_water_vapour"           : ("tcwv", "prw",     1.0,    0.0),
    "2m_dewpoint_temperature"             : ("d2m",  "_d2m",    1.0, -273.15),  # intermediate
    "2m_temperature"                      : ("t2m",  "_t2m",    1.0, -273.15),  # intermediate
    "surface_latent_heat_flux"            : ("slhf", "hfls",   -1.0/3600.0, 0.0),  # J/m2/hr -> W/m2, sign flip
    "surface_sensible_heat_flux"          : ("sshf", "hfss",   -1.0/3600.0, 0.0),
    "skin_temperature"                    : ("skt",  "ts",      1.0,    0.0),
}

_ERA5_PRESSURE_LEVEL_VARS = {
    # CDS parameter name                  : (era5_short, cmat_var)
    "geopotential"                        : ("z",   "zg"),   # /g -> zg in m
    "vertical_velocity"                   : ("w",   "wap"),
    "relative_humidity"                   : ("r",   "hur"),
}

_ERA5_TARGET_PRESSURE_LEVELS = ["500"]  # hPa


def _extract_nc_from_cds_zip(zip_path: Path, tmpdir: str) -> Path:
    """If ``zip_path`` is a CDS zip archive, extract NetCDF file(s) inside it.

    cdsapi >= 0.7 with the new CDS endpoint downloads data as a zip archive
    and saves it as-is to the requested output path even when the extension
    is ``.nc``.  This helper detects that situation, extracts all NetCDF
    files, and either:

    * returns the single extracted `.nc` path directly, OR
    * merges multiple `.nc` files into one combined file and returns its path.

    Returns ``zip_path`` unchanged if the file is already a plain NetCDF.
    """
    import zipfile

    if not zipfile.is_zipfile(zip_path):
        return zip_path  # already a plain NetCDF or GRIB

    with zipfile.ZipFile(zip_path, "r") as zf:
        names = zf.namelist()
        nc_names = [n for n in names if n.lower().endswith(".nc")]
        if not nc_names:
            # Check for GRIB as a fallback hint
            grib_names = [n for n in names if n.lower().endswith((".grib", ".grb", ".grb2"))]
            hint = (
                " Zip contains GRIB files; install cfgrib and retry."
                if grib_names else ""
            )
            raise ValueError(
                f"CDS download is a zip but contains no .nc files. "
                f"Contents: {names}.{hint}"
            )
        zf.extractall(tmpdir)
        log.info("Extracted %d NetCDF file(s) from CDS zip: %s", len(nc_names), nc_names)

        if len(nc_names) == 1:
            return Path(tmpdir) / nc_names[0]

        # Multiple NC files: merge into a single dataset file so callers
        # can use a single xr.open_dataset call.
        merged_path = Path(tmpdir) / "era5_merged.nc"
        parts = [xr.open_dataset(Path(tmpdir) / n, engine="netcdf4") for n in nc_names]
        merged = xr.merge(parts, compat="override")
        for ds in parts:
            ds.close()
        merged.to_netcdf(merged_path)
        merged.close()
        log.info("Merged %d NC files -> %s", len(nc_names), merged_path.name)
        return merged_path


def fetch_era5(
    obs_dir: Path,
    start_year: int = 1979,
    end_year: int = 2020,
) -> list[str]:
    """
    Download ERA5 monthly mean fields via cdsapi and write CMAT obs files.

    Requires ~/.cdsapirc:
        url: https://cds.climate.copernicus.eu/api/v2
        key: <UID>:<API_KEY>

    Downloads two requests:
      1. Single-level monthly means for surface/atmospheric vars
      2. Pressure-level monthly means at 500 hPa for 3D vars

    Returns list of written CMAT variable names.
    """
    try:
        import cdsapi
    except ImportError as e:
        raise ImportError(
            "cdsapi is not installed. Run: pip install cdsapi\n"
            "Also create ~/.cdsapirc with your CDS credentials:\n"
            "  url: https://cds.climate.copernicus.eu/api\n"
            "  key: <your-personal-access-token>"
        ) from e

    client = cdsapi.Client(quiet=True)
    written = []
    years = [str(y) for y in range(start_year, end_year + 1)]
    months = [f"{m:02d}" for m in range(1, 13)]

    with tempfile.TemporaryDirectory() as tmpdir:
        # cdsapi >= 0.7 with the new CDS endpoint saves the raw zip archive
        # to the requested output path (it does not auto-extract).  We
        # download without an extension and call _extract_nc_from_cds_zip
        # to resolve the actual NetCDF path before processing.

        # Common request parameters for both old (format) and new
        # (data_format) CDS API versions.  We intentionally omit
        # "download_format" so the server uses its default (usually a zip
        # archive); _extract_nc_from_cds_zip handles that transparently.
        _fmt = {"format": "netcdf"}

        # --- Single-level request ---
        sl_raw = Path(tmpdir) / "era5_sl_raw"
        sl_vars = list(_ERA5_SINGLE_LEVEL_VARS.keys())
        log.info("Requesting ERA5 single-level monthly means (%d-%d) ...",
                 start_year, end_year)
        client.retrieve(
            "reanalysis-era5-single-levels-monthly-means",
            {
                "product_type": "monthly_averaged_reanalysis",
                "variable": sl_vars,
                "year": years,
                "month": months,
                "time": "00:00",
                **_fmt,
            },
            str(sl_raw),
        )
        sl_path = _extract_nc_from_cds_zip(sl_raw, tmpdir)
        written += _process_era5_single(sl_path, obs_dir)

        # --- Pressure-level request ---
        pl_raw = Path(tmpdir) / "era5_pl_raw"
        pl_vars = list(_ERA5_PRESSURE_LEVEL_VARS.keys())
        log.info("Requesting ERA5 pressure-level monthly means at 500 hPa ...")
        client.retrieve(
            "reanalysis-era5-pressure-levels-monthly-means",
            {
                "product_type": "monthly_averaged_reanalysis",
                "variable": pl_vars,
                "pressure_level": _ERA5_TARGET_PRESSURE_LEVELS,
                "year": years,
                "month": months,
                "time": "00:00",
                **_fmt,
            },
            str(pl_raw),
        )
        pl_path = _extract_nc_from_cds_zip(pl_raw, tmpdir)
        written += _process_era5_pressure(pl_path, obs_dir)

    return written


def _process_era5_single(nc_path: Path, obs_dir: Path) -> list[str]:
    """Post-process ERA5 single-level download and write per-variable obs files."""
    from config import GRAV

    ds = xr.open_dataset(nc_path)
    ds = _rename_latlon(ds)
    written = []

    # Track intermediates for derived fields
    intermediates = {}

    for cds_name, (era5_short, cmat_name, factor, offset) in _ERA5_SINGLE_LEVEL_VARS.items():
        # ERA5 NetCDF variables use short names
        var = None
        for candidate in (era5_short, cds_name, cds_name.replace(" ", "_")):
            if candidate in ds:
                var = candidate
                break
        if var is None:
            log.warning("ERA5 single-level: variable not found for '%s'", cds_name)
            continue

        da = ds[var].astype("float32")
        da = da * factor + offset
        da.name = cmat_name

        if cmat_name.startswith("_"):
            # Intermediate: store for derived computation
            intermediates[cmat_name] = da
        else:
            _write_clim(da, obs_dir / f"{cmat_name}.nc")
            written.append(cmat_name)
            log.info("ERA5: wrote %s", cmat_name)

    # Derive near-surface relative humidity from T and Td (Magnus formula)
    if "_t2m" in intermediates and "_d2m" in intermediates:
        t2m = intermediates["_t2m"]   # degC
        d2m = intermediates["_d2m"]   # degC
        # RH = 100 * exp(17.625 * Td / (243.04 + Td)) / exp(17.625 * T / (243.04 + T))
        import numpy as _np
        rh = 100.0 * _np.exp(17.625 * d2m / (243.04 + d2m)) / \
             _np.exp(17.625 * t2m / (243.04 + t2m))
        rh = rh.clip(0, 100).rename("hurs")
        _write_clim(rh, obs_dir / "hurs.nc")
        written.append("hurs")
        log.info("ERA5: derived and wrote hurs")

    return written


def _process_era5_pressure(nc_path: Path, obs_dir: Path) -> list[str]:
    """Post-process ERA5 pressure-level download for 500-hPa variables."""
    from config import GRAV

    ds = xr.open_dataset(nc_path)
    ds = _rename_latlon(ds)

    # Rename plev dim if needed
    for d in ds.dims:
        if d.lower() in ("level", "pressure_level", "lev"):
            ds = ds.rename({d: "plev"})
            break

    written = []
    for cds_name, (era5_short, cmat_name) in _ERA5_PRESSURE_LEVEL_VARS.items():
        var = None
        for candidate in (era5_short, cds_name):
            if candidate in ds:
                var = candidate
                break
        if var is None:
            log.warning("ERA5 pressure-level: variable not found for '%s'", cds_name)
            continue

        da = ds[var].astype("float32")

        # Select 500 hPa (plev may be in hPa or Pa)
        plev_vals = da["plev"].values if "plev" in da.coords else da.coords.get("level", None)
        if plev_vals is not None and float(plev_vals.max()) > 2000:
            da500 = da.sel(plev=50000.0, method="nearest")
        else:
            da500 = da.sel(plev=500.0, method="nearest")

        # Unit conversions
        if cmat_name == "zg":
            # ERA5 geopotential (m2/s2) -> geopotential height (m)
            da500 = (da500 / GRAV).rename("zg500")
            cmat_name = "zg500"
        elif cmat_name == "wap":
            da500 = da500.rename("wap500")
            cmat_name = "wap500"
        elif cmat_name == "hur":
            da500 = da500.rename("hur500")
            cmat_name = "hur500"

        _write_clim(da500, obs_dir / f"{cmat_name}.nc")
        written.append(cmat_name)
        log.info("ERA5: wrote %s", cmat_name)

    return written


# ---------------------------------------------------------------------------
# Derived obs variables (computed from already-fetched CERES + ERA5 fields)
# ---------------------------------------------------------------------------

def derive_obs_fs_rtfs(obs_dir: Path) -> list[str]:
    """
    Derive fs and rtfs obs climatologies from CERES surface + ERA5 flux fields.

    All component files must already exist in obs_dir.
    Components may be on different grids (e.g., CERES 1-degree vs ERA5 0.25-
    degree). We regrid everything to a shared 1-degree grid before computing.
    """
    from src.derived_vars import calc_fs, calc_rtfs

    needed_fs = ["rsds", "rsus", "rlds", "rlus", "hfls", "hfss"]
    needed_extra = ["rsdt", "rsut", "rlut"]

    if not all((obs_dir / f"{v}.nc").exists() for v in needed_fs):
        log.warning("Cannot derive obs fs: missing component files in %s", obs_dir)
        return []

    # Target grid: 1-degree resolution matching CERES
    import numpy as np
    target_lat = np.linspace(-89.5, 89.5, 180)
    target_lon = np.linspace(0.5, 359.5, 360)

    def _load_regrid(name):
        """Load obs file and regrid to 1-degree if needed."""
        ds = xr.open_dataset(obs_dir / f"{name}.nc")
        da = ds[name] if name in ds else next(iter(ds.data_vars.values())).rename(name)
        ds.close()
        # Take the annual mean of the time series to get 2D for spatial checks
        # but keep time dimension if present for broadcasting
        da = da.squeeze(drop=True) if "time" not in da.dims else da
        if "time" in da.dims:
            da = da.mean("time", keep_attrs=True)
        # Check if regridding is needed (not 1-degree already)
        needs_regrid = (len(da.lat) != 180 or len(da.lon) != 360)
        if needs_regrid:
            da = da.interp(lat=target_lat, lon=target_lon, method="linear",
                           kwargs={"fill_value": "extrapolate"})
        return da.rename(name)

    comp = {v: _load_regrid(v) for v in needed_fs}
    fs = calc_fs(**comp)
    _write_clim(fs, obs_dir / "fs.nc")
    log.info("Derived obs fs")

    written = ["fs"]

    if all((obs_dir / f"{v}.nc").exists() for v in needed_extra):
        extra = {v: _load_regrid(v) for v in needed_extra}
        rtfs = calc_rtfs(extra["rsdt"], extra["rsut"], extra["rlut"], **comp)
        _write_clim(rtfs, obs_dir / "rtfs.nc")
        written.append("rtfs")
        log.info("Derived obs rtfs")

    # ep = E - P from hfls + pr
    if (obs_dir / "hfls.nc").exists() and (obs_dir / "pr.nc").exists():
        from src.derived_vars import calc_ep
        hfls = _load_regrid("hfls")
        pr_raw = _load_regrid("pr")
        # pr obs is already in mm/day; calc_ep expects kg/m2/s -> convert back
        pr_kgs = pr_raw / 86400.0
        ep = calc_ep(hfls, pr_kgs)
        _write_clim(ep, obs_dir / "ep.nc")
        written.append("ep")
        log.info("Derived obs ep")

    return written


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _rename_latlon(ds: xr.Dataset) -> xr.Dataset:
    """Rename non-standard coordinate names to the pyCMAT conventions.

    New CDS API (cdsapi >= 0.7) uses ``valid_time`` / ``latitude`` /
    ``longitude`` instead of the older ``time`` / ``lat`` / ``lon``.
    """
    rename = {}
    for d in list(ds.dims) + list(ds.coords):
        dl = d.lower()
        if dl in ("latitude", "nav_lat") and "lat" not in ds.dims:
            rename[d] = "lat"
        elif dl in ("longitude", "nav_lon") and "lon" not in ds.dims:
            rename[d] = "lon"
        elif dl == "valid_time" and "time" not in ds.dims:
            rename[d] = "time"
    if rename:
        ds = ds.rename(rename)
    # Normalise lon to 0-360
    if "lon" in ds.coords and float(ds.lon.min()) < 0:
        ds = ds.assign_coords(lon=(ds.lon % 360)).sortby("lon")
    return ds


def _write_clim(da: xr.DataArray, path: Path) -> None:
    """
    Write a DataArray to NetCDF.

    If the array has a time dimension, write the full time series (for
    ENSO / trend analyses).  Otherwise write the 2D climatological mean.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    # If time-resolved, keep as is; compute the mean only for 2D obs
    if "time" not in da.dims:
        out = da
    else:
        # Keep full time series — pipeline.py computes climatologies internally
        out = da

    # Ensure consistent lat ordering (south-to-north)
    if "lat" in out.dims and float(out.lat.values[0]) > float(out.lat.values[-1]):
        out = out.isel(lat=slice(None, None, -1))

    encoding = {da.name: {"dtype": "float32", "zlib": True, "complevel": 4}}
    out.to_dataset(name=da.name).to_netcdf(path, encoding={da.name: encoding.get(da.name, {})})
    log.debug("Wrote %s", path)
