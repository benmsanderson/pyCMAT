#!/usr/bin/env python3
"""
download_test_data.py — Download a minimal test set of CMIP6 fields from the
Pangeo GCS mirror for smoke-testing the pyCMAT scoring pipeline.

Why this script exists
----------------------
The upstream observational archives that ``src/obs_fetcher.py`` targets
(NASA Earthdata / CERES, Copernicus CDS / ERA5, NOAA PSL / GPCP) are not
reachable from every environment — notably, the cloud sandbox this repo is
developed in only permits outbound HTTPS to ``storage.googleapis.com`` and a
short allow-list of package mirrors. In that setting you cannot run
``fetch-obs``, so there is no way to exercise the pipeline end-to-end.

As a workaround, this script pulls a handful of monthly CMIP6 variables from
the Pangeo CMIP6 GCS mirror (which *is* reachable) and writes them as
compact NetCDF files in two directories:

    data/test/model/    — treated as the model-under-test (primary run)
    data/test/obs/      — treated as a *mock* observational reference

Because real obs endpoints are unreachable, the "obs" side is another CMIP6
model output (different source_id) trimmed to the same window. That is
obviously not a scientifically meaningful reference — it just lets the
scoring pipeline load, derive, regrid, and pattern-correlate real fields so
integration tests and smoke runs have something to chew on.

Usage
-----
    python scripts/download_test_data.py                         # defaults
    python scripts/download_test_data.py --year-start 2000 --year-end 2001
    python scripts/download_test_data.py --model-source CESM2 \
                                         --obs-source GFDL-CM4

Downloaded files are gitignored via ``data/test/`` in .gitignore.
"""
from __future__ import annotations

import argparse
import io
import logging
import os
import sys
from pathlib import Path

import pandas as pd
import requests
import xarray as xr

log = logging.getLogger("download_test_data")

PANGEO_CATALOG_JSON = "https://storage.googleapis.com/cmip6/pangeo-cmip6.json"
PANGEO_CATALOG_CSV = "https://storage.googleapis.com/cmip6/pangeo-cmip6.csv"

# Small, commonly-available monthly variables that exercise the CMAT pipeline
# without needing pressure-level fields or surface-radiation components.
DEFAULT_VARS = ("tas", "pr", "psl", "ts")


def _ensure_proxy_env() -> None:
    """Mirror uppercase proxy env vars to lowercase so aiohttp/gcsfs pick them up."""
    for upper, lower in (("HTTPS_PROXY", "https_proxy"),
                         ("HTTP_PROXY",  "http_proxy"),
                         ("NO_PROXY",    "no_proxy")):
        if upper in os.environ and lower not in os.environ:
            os.environ[lower] = os.environ[upper]


def _load_catalog(cache_path: Path) -> pd.DataFrame:
    """Fetch (and cache) the Pangeo CMIP6 catalog CSV."""
    if cache_path.exists():
        log.info("Using cached catalog: %s", cache_path)
        return pd.read_parquet(cache_path)

    log.info("Downloading Pangeo CMIP6 catalog from %s ...", PANGEO_CATALOG_CSV)
    r = requests.get(PANGEO_CATALOG_CSV, timeout=600)
    r.raise_for_status()
    log.info("  %.1f MB", len(r.content) / 1e6)
    df = pd.read_csv(io.BytesIO(r.content))
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(cache_path)
    log.info("  cached as %s (%d rows)", cache_path, len(df))
    return df


def _find_zstore(df: pd.DataFrame, source_id: str, variable_id: str,
                 experiment_id: str, member_id: str, table_id: str) -> str:
    sub = df[
        (df.source_id == source_id)
        & (df.experiment_id == experiment_id)
        & (df.member_id == member_id)
        & (df.table_id == table_id)
        & (df.variable_id == variable_id)
    ]
    if sub.empty:
        raise LookupError(
            f"No Pangeo CMIP6 entry for "
            f"{source_id}/{experiment_id}/{member_id}/{table_id}/{variable_id}"
        )
    # Prefer native grid ("gn") if available, else first match
    gn = sub[sub.grid_label == "gn"]
    row = (gn if not gn.empty else sub).iloc[0]
    return row.zstore


def _open_zarr(zstore: str) -> xr.Dataset:
    """Open a Pangeo CMIP6 zarr store over HTTPS via the ambient proxy.

    The gcsfs/grpc path triggers SSL handshake failures through
    MITM-inspecting proxies and wedges on minute-long retries. Plain HTTPS
    to ``storage.googleapis.com/<bucket>/<prefix>/`` is handled by
    fsspec's HTTPFileSystem (aiohttp under the hood) and honours
    ``HTTPS_PROXY`` when ``trust_env=True`` is passed.
    """
    import fsspec

    https_url = zstore.replace("gs://", "https://storage.googleapis.com/")
    if not https_url.endswith("/"):
        https_url += "/"
    mapper = fsspec.get_mapper(https_url, client_kwargs={"trust_env": True})
    return xr.open_zarr(mapper, consolidated=True, decode_times=True)


def _download_one(
    df: pd.DataFrame,
    source_id: str,
    variable_id: str,
    year_start: int,
    year_end: int,
    out_path: Path,
    experiment_id: str = "historical",
    member_id: str = "r1i1p1f1",
    table_id: str = "Amon",
) -> bool:
    """Fetch one (source, var) to NetCDF. Returns True on success."""
    if out_path.exists():
        size_mb = out_path.stat().st_size / 1e6
        log.info("  [skip] %s already exists (%.1f MB)", out_path.name, size_mb)
        return True

    try:
        zstore = _find_zstore(df, source_id, variable_id, experiment_id,
                              member_id, table_id)
    except LookupError as exc:
        log.warning("  %s", exc)
        return False

    log.info("  opening %s", zstore)
    try:
        ds = _open_zarr(zstore)
    except Exception as exc:  # noqa: BLE001
        log.error("  failed to open zarr store: %s", exc)
        return False

    if variable_id not in ds:
        log.error("  variable '%s' not in store; data_vars=%s",
                  variable_id, list(ds.data_vars))
        ds.close()
        return False

    da = ds[variable_id]
    # Temporal slice
    try:
        da = da.sel(time=slice(f"{year_start}-01-01", f"{year_end}-12-31"))
    except Exception as exc:  # noqa: BLE001
        log.warning("  time slice failed (%s); keeping full record", exc)

    n_time = da.sizes.get("time", 0)
    log.info("  loading %d months into memory ...", n_time)
    da = da.load()
    ds.close()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    encoding = {variable_id: {"zlib": True, "complevel": 4, "dtype": "float32"}}
    da.to_dataset(name=variable_id).to_netcdf(out_path, encoding=encoding)
    size_mb = out_path.stat().st_size / 1e6
    log.info("  wrote %s (%.1f MB)", out_path, size_mb)
    return True


def main() -> int:
    p = argparse.ArgumentParser(
        description="Download a minimal CMIP6 test set from Pangeo GCS.",
    )
    p.add_argument("--model-source", default="CESM2",
                   help="CMIP6 source_id used as the test model (default: CESM2)")
    p.add_argument("--obs-source", default="GFDL-CM4",
                   help="CMIP6 source_id used as MOCK observational reference "
                        "(default: GFDL-CM4). Real obs endpoints are unreachable "
                        "in this environment, so another model stands in.")
    p.add_argument("--variables", nargs="+", default=list(DEFAULT_VARS),
                   help=f"CMIP6 variable IDs to pull (default: {' '.join(DEFAULT_VARS)})")
    p.add_argument("--year-start", type=int, default=2000)
    p.add_argument("--year-end", type=int, default=2001,
                   help="Inclusive end year. Default keeps the download small (2 years).")
    p.add_argument("--experiment", default="historical")
    p.add_argument("--member", default="r1i1p1f1")
    p.add_argument("--table", default="Amon")
    p.add_argument("--out-dir", type=Path,
                   default=Path(__file__).parent.parent / "data" / "test",
                   help="Output root (model/ and obs/ subdirs created inside)")
    p.add_argument("--catalog-cache", type=Path,
                   default=Path(__file__).parent.parent / "data" / "test"
                   / "_pangeo_cmip6_catalog.parquet")
    p.add_argument("--verbose", "-v", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
        level=logging.DEBUG if args.verbose else logging.INFO,
    )

    _ensure_proxy_env()

    df = _load_catalog(args.catalog_cache)

    model_dir = args.out_dir / "model"
    obs_dir = args.out_dir / "obs"
    model_dir.mkdir(parents=True, exist_ok=True)
    obs_dir.mkdir(parents=True, exist_ok=True)

    log.info("=== Downloading test model: %s (%s %s %s) ===",
             args.model_source, args.experiment, args.member, args.table)
    model_ok: list[str] = []
    for var in args.variables:
        out = model_dir / f"{var}.nc"
        log.info("-> %s / %s", args.model_source, var)
        if _download_one(df, args.model_source, var, args.year_start, args.year_end,
                         out, args.experiment, args.member, args.table):
            model_ok.append(var)

    log.info("=== Downloading MOCK obs reference: %s ===", args.obs_source)
    obs_ok: list[str] = []
    for var in args.variables:
        out = obs_dir / f"{var}.nc"
        log.info("-> %s / %s", args.obs_source, var)
        if _download_one(df, args.obs_source, var, args.year_start, args.year_end,
                         out, args.experiment, args.member, args.table):
            obs_ok.append(var)

    log.info("")
    log.info("Done.")
    log.info("  Model (%s) variables written: %s", args.model_source, model_ok)
    log.info("  Obs   (%s) variables written: %s", args.obs_source, obs_ok)
    log.info("  Model dir: %s", model_dir)
    log.info("  Obs   dir: %s", obs_dir)

    if not model_ok or not obs_ok:
        log.error("At least one download failed.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
