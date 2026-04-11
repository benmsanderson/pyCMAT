"""
pipeline.py — End-to-end CMAT scoring pipeline.

Ties together data loading, derived variable computation, regridding,
climatology diagnostics, pattern correlations, and scoring.

Usage (programmatic)::

    from src.data_loader import CmatLoader
    from src.pipeline import run_scoring_pipeline

    loader = CmatLoader.from_cmip6("CESM2", "historical", "r1i1p1f1",
                                    year_range=(1995, 2014))
    results = run_scoring_pipeline(loader, obs_dir="data/obs")

The returned dict is JSON-serialisable and matches the structure expected
by `src/scoring.py:compute_scores()`.
"""
from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Optional

import numpy as np
import xarray as xr

from config import VARIABLES, REALM_VARS, NINO34_LAT, NINO34_LON
from src.derived_vars import (
    calc_rsnt, calc_swcftoa, calc_lwcftoa,
    calc_fs, calc_rtfs, calc_pr_mmday, calc_ep,
    calc_zg500, calc_wap500, calc_hur500,
)
from src.regrid import regrid_to_1deg, apply_land_mask, apply_ocean_mask, remove_zonal_mean
from src.climatology import annual_mean, seasonal_contrast, enso_teleconnection
from src.pattern_cor import pattern_cor
from src.scoring import compute_scores

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Variables that are scored over ocean only (land-masked before correlation)
# ---------------------------------------------------------------------------
_OCEAN_ONLY_VARS = {"fs", "rtfs"}

# Variables that are scored over land only
_LAND_ONLY_VARS: set = set()

# Variables scored as zonal eddies (zonal mean removed before correlation)
_EDDY_VARS = {"zg500"}

# ---------------------------------------------------------------------------
# Derived-variable computation dispatch table
# Maps CMAT variable name -> callable that accepts (loader, raw_fields) -> DataArray
# ---------------------------------------------------------------------------

def _derive(var: str, raw: dict) -> xr.DataArray:
    """Compute a CMAT variable from the dict of already-loaded raw fields."""
    if var == "rsnt":
        return calc_rsnt(raw["rsdt"], raw["rsut"])
    if var == "swcftoa":
        return calc_swcftoa(raw["rsut"], raw["rsutcs"])
    if var == "lwcftoa":
        return calc_lwcftoa(raw["rlut"], raw["rlutcs"])
    if var == "fs":
        return calc_fs(raw["rsds"], raw["rsus"], raw["rlds"], raw["rlus"],
                       raw["hfls"], raw["hfss"])
    if var == "rtfs":
        return calc_rtfs(raw["rsdt"], raw["rsut"], raw["rlut"],
                         raw["rsds"], raw["rsus"], raw["rlds"], raw["rlus"],
                         raw["hfls"], raw["hfss"])
    if var == "pr":
        return calc_pr_mmday(raw["pr"])
    if var == "ep":
        return calc_ep(raw["hfls"], raw["pr"])
    if var == "zg500":
        return calc_zg500(raw["zg"])
    if var == "wap500":
        return calc_wap500(raw["wap"])
    if var == "hur500":
        return calc_hur500(raw["hur"])
    # Direct pass-through (prw, hurs, psl, sfcWind, rlut)
    cmip6_name = VARIABLES[var].get("cmip6_var", var)
    return raw[cmip6_name].rename(var)


# ---------------------------------------------------------------------------
# Determine which raw CMIP6 fields are needed
# ---------------------------------------------------------------------------

def _required_raw_fields(scored_vars: list) -> set:
    """Return the set of raw CMIP6 variable names needed to compute scored_vars."""
    needed = set()
    for var in scored_vars:
        info = VARIABLES[var]
        if "derived_from" in info:
            needed.update(info["derived_from"])
        else:
            needed.add(info.get("cmip6_var", var))
    # SST is always needed for the ENSO Niño3.4 index
    needed.add("ts")
    return needed


# ---------------------------------------------------------------------------
# Observational field loader
# ---------------------------------------------------------------------------

def _load_obs(cmat_var: str, obs_dir: Path) -> Optional[xr.DataArray]:
    """
    Load an observational reference field for cmat_var from obs_dir.

    Expects files named  <cmat_var>.nc  or  <cmat_var>_obs.nc  (case-insensitive).
    Returns None if no file is found for that variable.
    """
    candidates = [
        obs_dir / f"{cmat_var}.nc",
        obs_dir / f"{cmat_var}_obs.nc",
        obs_dir / f"{cmat_var.lower()}.nc",
    ]
    for path in candidates:
        if path.exists():
            time_coder = xr.coders.CFDatetimeCoder(use_cftime=True)
            ds = xr.open_dataset(path, decode_times=time_coder)
            # Try the exact name first, then any data variable
            if cmat_var in ds:
                da = ds[cmat_var]
            else:
                da = next(iter(ds.data_vars.values()))
                da = da.rename(cmat_var)
            log.info("Loaded obs for %s from %s", cmat_var, path)
            return da
    log.warning("No obs file found for '%s' in %s — skipping", cmat_var, obs_dir)
    return None


# ---------------------------------------------------------------------------
# Per-variable climatology computation
# ---------------------------------------------------------------------------

def _compute_climatologies(
    da: xr.DataArray,
    sst_monthly: xr.DataArray,
) -> dict:
    """
    Return {'annual': DataArray, 'seasonal': DataArray, 'enso': DataArray}
    for a single regridded, masked variable field.
    """
    ann = annual_mean(da)
    seas = seasonal_contrast(da)
    try:
        enso = enso_teleconnection(da, sst_monthly)
    except (ValueError, Exception) as exc:
        log.warning("ENSO teleconnection failed: %s", exc)
        enso = None
    return {"annual": ann, "seasonal": seas, "enso": enso}


# ---------------------------------------------------------------------------
# Main pipeline entry point
# ---------------------------------------------------------------------------

def run_scoring_pipeline(
    loader,
    obs_dir: str | Path,
    scored_vars: Optional[list] = None,
    benchmark_loader=None,
) -> dict:
    """
    Run the full CMAT scoring pipeline.

    Parameters
    ----------
    loader : CmatLoader
        Primary model data loader.
    obs_dir : str or Path
        Directory containing observational reference NetCDF files.
    scored_vars : list of str or None
        Subset of CMAT variable names to score.  Defaults to all 16 variables.
    benchmark_loader : CmatLoader or None
        If provided, also score the benchmark model and include delta scores.

    Returns
    -------
    dict with keys:
        'pattern_correlations' : {varname: {'annual': R, 'seasonal': R, 'enso': R}}
        'scores'               : output of compute_scores() — variable/realm/overall
        'benchmark_scores'     : same structure for benchmark, or None
        'delta_scores'         : {varname: scored_var - benchmark_var}, or None
        'metadata'             : run info dict
    """
    obs_dir = Path(obs_dir)
    scored_vars = scored_vars or list(VARIABLES.keys())

    log.info("=== pyCMAT scoring pipeline ===")
    log.info("Variables to score: %s", scored_vars)

    # ------------------------------------------------------------------
    # Step 1: Determine and load raw CMIP6/model fields
    # ------------------------------------------------------------------
    raw_fields_needed = _required_raw_fields(scored_vars)
    log.info("Loading %d raw fields: %s", len(raw_fields_needed), sorted(raw_fields_needed))

    raw: dict[str, xr.DataArray] = {}
    load_errors: list[str] = []
    for field in sorted(raw_fields_needed):
        try:
            raw[field] = loader.load(field)
            log.info("  Loaded raw field: %s  shape=%s", field, dict(raw[field].sizes))
        except (KeyError, FileNotFoundError) as exc:
            log.warning("  MISSING raw field '%s': %s", field, exc)
            load_errors.append(field)

    # ------------------------------------------------------------------
    # Step 2: Compute derived variables and regrid to 1-degree
    # ------------------------------------------------------------------
    # SST is needed for ENSO; regrid it now
    sst_monthly_1deg: Optional[xr.DataArray] = None
    if "ts" in raw:
        log.info("Regridding SST for Niño3.4 index ...")
        sst_monthly_1deg = regrid_to_1deg(raw["ts"])

    model_fields: dict[str, xr.DataArray] = {}
    for var in scored_vars:
        info = VARIABLES[var]
        needed = set(info.get("derived_from", [info.get("cmip6_var", var)]))
        missing = needed - set(raw.keys())
        if missing:
            log.warning("Skipping '%s': raw field(s) missing: %s", var, missing)
            continue
        try:
            da = _derive(var, raw)
        except Exception as exc:
            log.warning("Failed to derive '%s': %s", var, exc)
            continue

        # Regrid to 1-degree target grid
        log.info("Regridding %s ...", var)
        try:
            da = regrid_to_1deg(da)
        except Exception as exc:
            log.warning("Regridding failed for '%s': %s", var, exc)
            continue

        # Apply domain mask
        if var in _OCEAN_ONLY_VARS:
            da = apply_land_mask(da)
        elif var in _LAND_ONLY_VARS:
            da = apply_ocean_mask(da)

        model_fields[var] = da
        log.info("  Derived+regridded: %s  shape=%s", var, dict(da.sizes))

    if not model_fields:
        raise RuntimeError("No model fields could be derived and regridded.")

    # ------------------------------------------------------------------
    # Step 3: Compute pattern correlations vs obs
    # ------------------------------------------------------------------
    pcors: dict[str, dict] = {}

    # Load obs SST for ENSO Niño3.4 index (ERA5 ts)
    obs_sst: Optional[xr.DataArray] = None
    _obs_ts = _load_obs("ts", obs_dir)
    if _obs_ts is not None:
        obs_sst = regrid_to_1deg(_obs_ts) if _needs_regrid(_obs_ts) else _obs_ts
        log.info("Loaded obs SST for ENSO index from %s", obs_dir / "ts.nc")

    for var, da in model_fields.items():
        obs_da = _load_obs(var, obs_dir)
        if obs_da is None:
            log.warning("No obs for '%s'; pattern correlations will be NaN", var)

        # Compute model climatologies
        model_clims = _compute_climatologies(da, sst_monthly_1deg)

        var_pcors: dict[str, float] = {}
        for timescale in ("annual", "seasonal", "enso"):
            m_clim = model_clims[timescale]
            if m_clim is None:
                var_pcors[timescale] = float("nan")
                continue

            if obs_da is not None:
                # Compute obs climatology on the same 1-deg grid
                obs_regridded = regrid_to_1deg(obs_da) if _needs_regrid(obs_da) else obs_da
                if var in _OCEAN_ONLY_VARS:
                    obs_regridded = apply_land_mask(obs_regridded)
                elif var in _LAND_ONLY_VARS:
                    obs_regridded = apply_ocean_mask(obs_regridded)
                if var in _EDDY_VARS:
                    obs_regridded = remove_zonal_mean(obs_regridded)
                obs_clims = _compute_obs_climatology(obs_regridded, obs_sst, timescale)
                r = pattern_cor(m_clim, obs_clims)
            else:
                r = float("nan")

            var_pcors[timescale] = r

        pcors[var] = var_pcors
        log.info("  Pattern cors for %s: annual=%.3f seasonal=%.3f enso=%.3f",
                 var,
                 var_pcors.get("annual", float("nan")),
                 var_pcors.get("seasonal", float("nan")),
                 var_pcors.get("enso", float("nan")))

    # ------------------------------------------------------------------
    # Step 4: Compute scores
    # ------------------------------------------------------------------
    scores = compute_scores(pcors)

    log.info("=== Score summary ===")
    log.info("  Realm scores: energy=%.3f  water=%.3f  dynamics=%.3f",
             scores["realm"].get("energy", float("nan")),
             scores["realm"].get("water", float("nan")),
             scores["realm"].get("dynamics", float("nan")))
    log.info("  Overall score: %.3f", scores["overall"])

    # ------------------------------------------------------------------
    # Step 5: Optionally score benchmark and compute deltas
    # ------------------------------------------------------------------
    benchmark_scores = None
    delta_scores = None
    if benchmark_loader is not None:
        log.info("=== Scoring benchmark model ===")
        benchmark_result = run_scoring_pipeline(
            benchmark_loader, obs_dir=obs_dir, scored_vars=scored_vars
        )
        benchmark_scores = benchmark_result["scores"]
        delta_scores = _compute_deltas(scores, benchmark_scores)

    # ------------------------------------------------------------------
    # Step 6: Assemble result dict
    # ------------------------------------------------------------------
    return {
        "pattern_correlations": pcors,
        "scores": scores,
        "benchmark_scores": benchmark_scores,
        "delta_scores": delta_scores,
        "metadata": {
            "scored_vars": scored_vars,
            "load_errors": load_errors,
            "n_vars_scored": len(pcors),
        },
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _needs_regrid(da: xr.DataArray) -> bool:
    """Return True if the DataArray is not already on the 1-degree target grid."""
    from config import TARGET_GRID
    return (da.sizes.get("lat", 0) != TARGET_GRID["nlat"] or
            da.sizes.get("lon", 0) != TARGET_GRID["nlon"])


def _compute_obs_climatology(
    obs: xr.DataArray,
    sst_monthly: Optional[xr.DataArray],
    timescale: str,
) -> xr.DataArray:
    """
    Compute the obs climatology for a given timescale.

    For obs fields that are already climatological (no time dim), return as-is.
    For obs with a time dimension, compute the appropriate diagnostic.
    """
    if "time" not in obs.dims:
        # Obs is already climatological (2D); use it for annual and seasonal
        if timescale == "enso":
            return obs  # Best-effort; ENSO obs should ideally be a regression map
        return obs

    if timescale == "annual":
        return annual_mean(obs)
    if timescale == "seasonal":
        return seasonal_contrast(obs)
    if timescale == "enso":
        if sst_monthly is None:
            return obs.isel(time=0) * float("nan")  # all-NaN placeholder
        try:
            return enso_teleconnection(obs, sst_monthly)
        except Exception as exc:
            log.warning("Obs ENSO teleconnection failed: %s", exc)
            return obs.isel(time=0) * float("nan")
    raise ValueError(f"Unknown timescale: {timescale}")


def _compute_deltas(scored: dict, benchmark: dict) -> dict:
    """
    Compute variable-level score improvements: scored - benchmark.
    Positive = improvement over benchmark.
    """
    s_vars = scored.get("variable", {})
    b_vars = benchmark.get("variable", {})
    deltas = {}
    for var in set(s_vars) | set(b_vars):
        s = s_vars.get(var, float("nan"))
        b = b_vars.get(var, float("nan"))
        if math.isfinite(s) and math.isfinite(b):
            deltas[var] = round(s - b, 4)
        else:
            deltas[var] = float("nan")
    return deltas
