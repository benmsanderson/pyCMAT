"""
data_loader.py — Unified data access layer for pyCMAT.

Supports three backends, all returning xarray DataArrays with consistent
coordinate names (lat, lon, time, plev where applicable):

  1. Local NetCDF backend
     Loads monthly model output from a local directory.  Files can be:
       - One file per variable: pr_195001-201412.nc
       - All variables in one file: model_Amon_1995-2014.nc
       - CESM history file layout: casename.cam.h0.YYYY-MM.nc
     Variable discovery uses CF standard_name attributes, then falls back
     to a configurable name mapping.

  2. CMIP6 GCS backend
     Queries the Pangeo intake-esm catalog and streams data lazily via Zarr.
     Named CMIP6 variables are returned directly; no local download required
     unless explicitly requested.

  3. NorESM case backend
     Reads raw NorESM CAM ``atm/hist/*.cam.h0.YYYY-MM.nc`` history files
     directly from a case output directory, handling the CAM→CMIP6 variable
     name mapping and computing derived surface fields (rsus, rlus, pr)
     that are not written as direct outputs.

Usage
-----
# Local directory
loader = CmatLoader.from_local("/path/to/model/output", year_range=(1995, 2014))

# CMIP6 GCS
loader = CmatLoader.from_cmip6("CESM2", experiment="historical",
                                member="r1i1p1f1", year_range=(1995, 2014))

# NorESM case directory (atm/hist/*.cam.h0.*.nc discovered automatically)
loader = CmatLoader.from_noresm_case("/projects/.../MyCaseName",
                                      year_range=(1950, 1969))

# Load a specific variable (returns xr.DataArray)
pr = loader.load("pr")
zg = loader.load("zg")   # full 3D field; extract level in derived_vars.py
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Sequence

import numpy as np
import xarray as xr

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# CF standard_name -> CMAT/CMIP6 variable_id mapping
# Used to identify variables in local files that don't follow CMIP6 naming.
# ---------------------------------------------------------------------------
CF_STANDARD_NAME_MAP = {
    "precipitation_flux": "pr",
    "atmosphere_mass_content_of_water_vapor": "prw",
    "relative_humidity": "hur",    # disambiguate by level downstream
    "surface_air_pressure": "ps",
    "air_pressure_at_mean_sea_level": "psl",
    "surface_upward_latent_heat_flux": "hfls",
    "surface_upward_sensible_heat_flux": "hfss",
    "toa_outgoing_longwave_flux": "rlut",
    "toa_outgoing_shortwave_flux": "rsut",
    "toa_incoming_shortwave_flux": "rsdt",
    "surface_downwelling_shortwave_flux_in_air": "rsds",
    "surface_upwelling_shortwave_flux_in_air": "rsus",
    "surface_downwelling_longwave_flux_in_air": "rlds",
    "surface_upwelling_longwave_flux_in_air": "rlus",
    "wind_speed": "sfcWind",
    "geopotential": "zg",
    "lagrangian_tendency_of_air_pressure": "wap",
    "near_surface_relative_humidity": "hurs",
    "sea_surface_temperature": "ts",
    "surface_temperature": "ts",
}

# Common non-CF variable name aliases used in CESM history files and others
ALIAS_MAP = {
    # CESM CAM names -> CMIP6 names
    "PRECC": None,    # convective precip - not directly usable alone
    "PRECL": None,    # large-scale precip - combine with PRECC for pr
    "TMQ": "prw",
    "LHFLX": "hfls",
    "SHFLX": "hfss",
    "FLUT": "rlut",
    "FLUTC": "rlutcs",
    "FSNTOA": "rsnt",  # net SW at TOA  (already derived)
    "FSUTOA": "rsut",
    "FSUTOAC": "rsutcs",
    "SOLIN": "rsdt",
    "Z3": "zg",
    "OMEGA": "wap",
    "RELHUM": "hur",
    "PSL": "psl",
    "U10": "sfcWind",
    "TS": "ts",
    "FSDS": "rsds",
    "FSUS": "rsus",
    "FLDS": "rlds",
    "FLUS": "rlus",
}

# NorESM/CAM h0 -> CMIP6 name map for variables that have a direct 1-to-1
# correspondence.  Derived/computed fields (pr, rsus, rlus, hurs) are handled
# separately in _load_noresm().
NORESM_ALIAS_MAP: dict[str, str] = {
    "TMQ":     "prw",
    "LHFLX":   "hfls",
    "SHFLX":   "hfss",
    "FLUT":    "rlut",
    "FLUTC":   "rlutcs",
    "FSNTOA":  "rsnt",    # net SW at TOA (== rsdt - rsut, already derived in CAM)
    "FSUTOA":  "rsut",
    "FSNTOAC": "rsutcs",  # clear-sky net SW TOA; rsutcs = SOLIN - FSNTOAC
    "SOLIN":   "rsdt",
    "Z3":      "zg",
    "OMEGA":   "wap",
    "RELHUM":  "hur",
    "PSL":     "psl",
    "U10":     "sfcWind",
    "TS":      "ts",
    "FSDS":    "rsds",
    "FLDS":    "rlds",
    # Fields derived from NorESM output that happen to equal their CMIP6 name:
    # rsus = FSDS - FSNS  (handled in _load_noresm)
    # rlus = FLDS + FLNS  (handled in _load_noresm)
    # pr   = (PRECC+PRECL)*1000  (handled in _load_noresm)
    # hurs = RELHUM at lowest level  (handled in _load_noresm)
}


class CmatLoader:
    """
    Unified loader that provides a consistent xr.DataArray for any CMAT variable,
    regardless of the data source (local files or CMIP6 GCS).
    """

    def __init__(self, backend: str, year_range: tuple[int, int] = (1995, 2014)):
        self.backend = backend           # 'local', 'cmip6', or 'noresm'
        self.year_range = year_range
        self._catalog = None            # intake-esm catalog (cmip6 backend)
        self._local_dir: Path | None = None
        self._local_ds_cache: dict[str, xr.Dataset] = {}
        # CMIP6 identifiers (cmip6 backend)
        self.source_id: str | None = None
        self.experiment_id: str | None = None
        self.member_id: str | None = None
        # Optional local disk cache for GCS downloads
        self._cache_dir: Path | None = None
        # NorESM case backend
        self._noresm_ds: xr.Dataset | None = None   # lazy multi-file dataset
        self.case_name: str | None = None

    # ------------------------------------------------------------------
    # Constructors
    # ------------------------------------------------------------------

    @classmethod
    def from_local(
        cls,
        data_dir: str | Path,
        year_range: tuple[int, int] = (1995, 2014),
        name_map: dict | None = None,
    ) -> "CmatLoader":
        """
        Create a loader backed by a local directory of NetCDF files.

        Parameters
        ----------
        data_dir : str or Path
            Directory containing monthly NetCDF files.
        year_range : (start_year, end_year)
            Inclusive year range to extract after loading.
        name_map : dict or None
            Optional {local_varname: cmip6_varname} overrides, applied on top
            of the built-in CF standard_name and alias mappings.
        """
        loader = cls(backend="local", year_range=year_range)
        loader._local_dir = Path(data_dir)
        if not loader._local_dir.is_dir():
            raise FileNotFoundError(f"data_dir does not exist: {data_dir}")
        if name_map:
            ALIAS_MAP.update(name_map)
        log.info("Local loader initialised: %s (%d-%d)", data_dir, *year_range)
        return loader

    @classmethod
    def from_noresm_case(
        cls,
        case_dir: str | Path,
        year_range: tuple[int, int] = (1995, 2014),
        stream: str = "cam.h0",
    ) -> "CmatLoader":
        """
        Create a loader backed by a NorESM case directory containing raw CAM
        history files (``atm/hist/<casename>.<stream>.YYYY-MM.nc``).

        The full multi-year time series is opened lazily with
        ``xr.open_mfdataset``; only the files whose year falls within
        ``year_range`` are loaded.  CAM variable names are mapped to their
        CMIP6 equivalents automatically; computed fields that are not direct
        CAM outputs (``pr``, ``rsus``, ``rlus``, ``hurs``) are derived on the
        fly inside ``_load_noresm()``.

        Parameters
        ----------
        case_dir : str or Path
            Root NorESM case output directory, e.g.
            ``/projects/NS9560K/noresm/cases/MyCaseName``.
            The loader automatically descends into ``atm/hist/``.
        year_range : (start_year, end_year)
            Inclusive year range to extract from the history files.
        stream : str
            CAM history stream to read (default ``cam.h0`` = monthly mean).
        """
        import glob

        case_dir = Path(case_dir)
        hist_dir = case_dir / "atm" / "hist"
        if not hist_dir.is_dir():
            raise FileNotFoundError(
                f"Expected NorESM history directory not found: {hist_dir}\n"
                "Check that the case directory contains atm/hist/."
            )

        y0, y1 = year_range
        pattern = str(hist_dir / f"*.{stream}.*.nc")
        all_files = sorted(glob.glob(pattern))
        if not all_files:
            raise FileNotFoundError(
                f"No files matching '{pattern}' found under {hist_dir}"
            )

        # Filter to the requested year range by parsing YYYY-MM from filename.
        # Filenames look like: <casename>.<stream>.YYYY-MM.nc
        def _file_year(path: str) -> int:
            stem = Path(path).stem          # e.g. Case.cam.h0.1950-01
            yyyymm = stem.rsplit(".", 1)[-1]  # e.g. 1950-01
            return int(yyyymm.split("-")[0])

        files = [f for f in all_files if y0 <= _file_year(f) <= y1]
        if not files:
            raise FileNotFoundError(
                f"No {stream} files for years {y0}-{y1} found in {hist_dir}. "
                f"Available range: {_file_year(all_files[0])}-{_file_year(all_files[-1])}"
            )

        log.info(
            "NorESM case loader: %s, stream=%s, %d-%d (%d files)",
            case_dir.name, stream, y0, y1, len(files),
        )

        # Determine case name from first file
        case_name = Path(files[0]).name.split(f".{stream}.")[0]

        # Open all monthly files as a single lazy dataset.
        # Use only the variables we actually need to keep memory footprint small.
        _NEEDED_CAM_VARS = [
            "PRECC", "PRECL",          # -> pr
            "TMQ",                      # -> prw
            "LHFLX", "SHFLX",          # -> hfls, hfss
            "FLUT", "FLUTC",            # -> rlut, rlutcs
            "FSNTOA", "FSUTOA",         # -> rsnt, rsut
            "FSNTOAC",                  # -> rsutcs  (via SOLIN - FSNTOAC)
            "SOLIN",                    # -> rsdt
            "FSDS", "FSNS",             # -> rsds, rsus (rsus = FSDS - FSNS)
            "FLDS", "FLNS",             # -> rlds, rlus (rlus = FLDS + FLNS)
            "Z3", "OMEGA", "RELHUM",    # -> zg, wap, hur  (3-D)
            "PSL", "U10", "TS",         # -> psl, sfcWind, ts
        ]

        time_coder = xr.coders.CFDatetimeCoder(use_cftime=True)
        ds = xr.open_mfdataset(
            files,
            combine="by_coords",
            data_vars="minimal",
            coords="minimal",
            compat="override",
            decode_times=time_coder,
            chunks={"time": 12},    # one year per chunk
        )

        # Fix CAM's end-of-period time convention: CAM writes the time stamp at
        # the first instant of the NEXT month (e.g. the Jan 1950 monthly mean has
        # time = 1950-02-01 00:00).  Use the lower bound from time_bnds (= the
        # first day of the averaging month) as the canonical time coordinate so
        # that year-based slicing works correctly and season labels match data.
        if "time_bnds" in ds.coords or "time_bnds" in ds:
            t0 = ds["time_bnds"].isel(nbnd=0)
            ds = ds.assign_coords(time=t0.drop_vars("time", errors="ignore"))
            log.debug("NorESM time coordinate fixed using time_bnds lower bound")
        else:
            log.warning(
                "time_bnds not found in NorESM dataset; time stamps may be off by one month"
            )

        # Drop variables we won't use to save memory
        keep = [v for v in _NEEDED_CAM_VARS if v in ds]
        missing = [v for v in _NEEDED_CAM_VARS if v not in ds]
        if missing:
            log.warning("NorESM h0 is missing expected CAM variables: %s", missing)
        ds = ds[keep]

        loader = cls(backend="noresm", year_range=year_range)
        loader._noresm_ds = ds
        loader.case_name = case_name
        return loader

    @classmethod
    def from_cmip6(
        cls,
        source_id: str,
        experiment_id: str = "historical",
        member_id: str = "r1i1p1f1",
        year_range: tuple[int, int] = (1995, 2014),
        catalog_url: str = "https://storage.googleapis.com/cmip6/pangeo-cmip6.json",
        cache_dir: str | Path | None = "default",
    ) -> "CmatLoader":
        """
        Create a loader backed by the Pangeo CMIP6 GCS intake-esm catalog.

        Parameters
        ----------
        source_id : str
            CMIP6 model name, e.g. 'CESM2'.
        experiment_id : str
            CMIP6 experiment, e.g. 'historical'.
        member_id : str
            CMIP6 ripf label, e.g. 'r1i1p1f1'.
        year_range : (start_year, end_year)
            Inclusive year range to extract after loading.
        catalog_url : str
            URL of the intake-esm JSON catalog descriptor.
        cache_dir : str, Path, or None
            Root directory for local NetCDF caching.  Downloaded fields are
            saved under ``<cache_dir>/<source_id>/<experiment_id>/<member_id>/``
            and reused on subsequent runs, skipping the GCS download.
            Defaults to ``data/model_cache/`` (or ``$PYCMAT_CACHE_DIR`` if set).
            Pass ``None`` to disable caching entirely.
        """
        try:
            import intake
        except ImportError as e:
            raise ImportError(
                "intake-esm is required for CMIP6 GCS access. "
                "Run: pip install intake-esm gcsfs ipython"
            ) from e

        # The Pangeo CMIP6 bucket is public (requester-pays exempt for reads).
        # Tell gcsfs to use anonymous access so it doesn't try ADC credentials.
        try:
            import fsspec
            fsspec.config.conf["gcs"] = {"token": "anon"}
        except (ImportError, Exception):
            pass

        # Resolve default cache location from config / env var
        if cache_dir == "default":
            from config import MODEL_CACHE_DIR
            cache_dir = MODEL_CACHE_DIR

        loader = cls(backend="cmip6", year_range=year_range)
        loader.source_id = source_id
        loader.experiment_id = experiment_id
        loader.member_id = member_id
        if cache_dir is not None:
            loader._cache_dir = Path(cache_dir) / source_id / experiment_id / member_id
            loader._cache_dir.mkdir(parents=True, exist_ok=True)
            log.info("Model cache dir: %s", loader._cache_dir)
        log.info("Opening intake-esm catalog: %s", catalog_url)
        loader._catalog = intake.open_esm_datastore(catalog_url)
        log.info("CMIP6 loader initialised: %s %s %s (%d-%d)",
                 source_id, experiment_id, member_id, *year_range)
        return loader

    # ------------------------------------------------------------------
    # Public load interface
    # ------------------------------------------------------------------

    def load(self, cmat_var: str) -> xr.DataArray:
        """
        Load a variable and return it as an xr.DataArray with standardised
        coordinate names (lat, lon, time; plev if 3D) sliced to year_range.

        Parameters
        ----------
        cmat_var : str
            CMAT/CMIP6 variable name, e.g. 'pr', 'zg', 'rlut'.

        Returns
        -------
        xr.DataArray with dims (time, lat, lon) or (time, plev, lat, lon).
        """
        if self.backend == "local":
            da = self._load_local(cmat_var)
        elif self.backend == "cmip6":
            da = self._load_cmip6(cmat_var)
        elif self.backend == "noresm":
            da = self._load_noresm(cmat_var)
        else:
            raise ValueError(f"Unknown backend: {self.backend}")

        da = self._standardise_coords(da)
        da = self._slice_years(da)
        return da

    # ------------------------------------------------------------------
    # NorESM case backend
    # ------------------------------------------------------------------

    def _load_noresm(self, cmat_var: str) -> xr.DataArray:
        """
        Return a CMAT variable from the NorESM multi-file dataset.

        Direct aliases are resolved via NORESM_ALIAS_MAP.  Four variables
        require on-the-fly computation because they are not CAM h0 outputs:

        ============  ==========================================
        CMAT var      Derivation from CAM h0 fields
        ============  ==========================================
        pr            (PRECC + PRECL) * 1000  [m s-1 → kg m-2 s-1]
        rsus          FSDS - FSNS  [net SW at surface]
        rlus          FLDS + FLNS  [net LW at surface, FLNS is upward]
        hurs          RELHUM at the lowest model level (~surface)
        ============  ==========================================
        """
        ds = self._noresm_ds

        # --- Derived fields not present as direct CAM outputs ---
        if cmat_var == "pr":
            # PRECC + PRECL are in m s-1; multiply by 1000 to get kg m-2 s-1
            return ((ds["PRECC"] + ds["PRECL"]) * 1000.0).rename("pr")

        if cmat_var == "rsus":
            # FSNS = rsds - rsus (net SW into surface, positive down)
            # => rsus = FSDS - FSNS
            return (ds["FSDS"] - ds["FSNS"]).rename("rsus")

        if cmat_var == "rlus":
            # FLNS = rlus - rlds (net LW leaving surface, positive upward)
            # => rlus = FLDS + FLNS
            return (ds["FLDS"] + ds["FLNS"]).rename("rlus")

        if cmat_var == "hurs":
            # Near-surface relative humidity: use lowest CAM sigma level.
            # RELHUM has vertical dim 'lev'; isel(lev=-1) is the
            # bottom-most level (~992 hPa on f19).
            rh_sfc = (
                ds["RELHUM"]
                .isel(lev=-1)
                .drop_vars(["lev", "ilev"], errors="ignore")
            )
            return rh_sfc.rename("hurs")

        # --- Direct 1-to-1 alias look-up ---
        for cam_name, cmip6_name in NORESM_ALIAS_MAP.items():
            if cmip6_name == cmat_var and cam_name in ds:
                log.debug("NorESM: %s -> %s", cam_name, cmat_var)
                return ds[cam_name].rename(cmat_var)

        raise KeyError(
            f"Variable '{cmat_var}' not available from the NorESM case backend.\n"
            f"Available direct aliases: {list(NORESM_ALIAS_MAP.values())}\n"
            f"Computed fields: pr, rsus, rlus, hurs"
        )

    # ------------------------------------------------------------------
    # Local backend
    # ------------------------------------------------------------------

    def _load_local(self, cmat_var: str) -> xr.DataArray:
        """
        Search the local directory for a file containing cmat_var.

        Search order:
          1. File whose stem matches the variable name (case-insensitive)
          2. Any NetCDF file containing a variable whose CF standard_name maps
             to cmat_var
          3. Any NetCDF file containing a variable whose name matches an alias
             in ALIAS_MAP
          4. A single NetCDF file in the directory (assumed to contain everything)
        """
        nc_files = sorted(self._local_dir.glob("*.nc")) + \
                   sorted(self._local_dir.glob("**/*.nc"))

        if not nc_files:
            raise FileNotFoundError(
                f"No .nc files found under {self._local_dir}"
            )

        # 1. Stem match
        for f in nc_files:
            if cmat_var.lower() in f.stem.lower():
                ds = self._open_and_cache(f)
                if cmat_var in ds:
                    return ds[cmat_var]

        # 2 & 3. Scan all files for matching variables
        for f in nc_files:
            ds = self._open_and_cache(f)
            # CF standard_name scan
            for vname, var in ds.data_vars.items():
                std = var.attrs.get("standard_name", "")
                if CF_STANDARD_NAME_MAP.get(std) == cmat_var:
                    log.debug("Found %s in %s as '%s' (CF standard_name)", cmat_var, f.name, vname)
                    return ds[vname].rename(cmat_var)
            # Alias scan
            for alias, mapped in ALIAS_MAP.items():
                if mapped == cmat_var and alias in ds:
                    log.debug("Found %s in %s as alias '%s'", cmat_var, f.name, alias)
                    return ds[alias].rename(cmat_var)

        raise KeyError(
            f"Variable '{cmat_var}' not found in any file under {self._local_dir}. "
            f"Add an entry to ALIAS_MAP or use a --name-map override."
        )

    def _open_and_cache(self, path: Path) -> xr.Dataset:
        key = str(path)
        if key not in self._local_ds_cache:
            log.debug("Opening %s", path)
            time_coder = xr.coders.CFDatetimeCoder(use_cftime=True)
            self._local_ds_cache[key] = xr.open_dataset(
                path, chunks="auto", decode_times=time_coder
            )
        return self._local_ds_cache[key]

    # ------------------------------------------------------------------
    # CMIP6 GCS backend
    # ------------------------------------------------------------------

    def _load_cmip6(self, cmat_var: str) -> xr.DataArray:
        """Query intake-esm catalog and return the requested variable as DataArray.

        If a ``cache_dir`` was provided at construction time, the downloaded
        field is saved as ``<cache_dir>/<var>.nc`` and reloaded from disk on
        subsequent calls, avoiding repeated GCS traffic.
        """
        # --- cache hit ---
        if self._cache_dir is not None:
            cached = self._cache_dir / f"{cmat_var}.nc"
            if cached.exists():
                log.info("Cache hit for %s: loading from %s", cmat_var, cached)
                time_coder = xr.coders.CFDatetimeCoder(use_cftime=True)
                ds = xr.open_dataset(cached, chunks="auto", decode_times=time_coder)
                return ds[cmat_var]
        subset = self._catalog.search(
            source_id=self.source_id,
            experiment_id=self.experiment_id,
            member_id=self.member_id,
            variable_id=cmat_var,
            table_id="Amon",
        )

        if len(subset.df) == 0:
            # Try pressure-level tables for 3D fields
            subset = self._catalog.search(
                source_id=self.source_id,
                experiment_id=self.experiment_id,
                member_id=self.member_id,
                variable_id=cmat_var,
            )

        if len(subset.df) == 0:
            raise KeyError(
                f"Variable '{cmat_var}' not found in CMIP6 catalog for "
                f"{self.source_id} {self.experiment_id} {self.member_id}"
            )

        # Prefer Amon if multiple tables available
        if "Amon" in subset.df["table_id"].values:
            subset = subset.search(table_id="Amon")

        log.info("Loading %s from CMIP6 GCS (%s %s %s)",
                 cmat_var, self.source_id, self.experiment_id, self.member_id)

        _time_coder = xr.coders.CFDatetimeCoder(use_cftime=True)

        dsets = subset.to_dataset_dict(
            xarray_open_kwargs={"chunks": "auto", "decode_times": _time_coder,
                                "storage_options": {"token": "anon"}},
            progressbar=False,
        )
        # to_dataset_dict returns {key: Dataset}; pick first entry
        ds = next(iter(dsets.values()))
        da = ds[cmat_var]
        # intake-esm adds member_id / dcpp_init_year dimensions of size 1;
        # squeeze them out so downstream code sees (time, [plev,] lat, lon).
        extra_dims = [d for d in da.dims if d not in ("time", "lat", "lon", "lev",
                                                       "plev", "level", "latitude",
                                                       "longitude", "pressure_level")]
        if extra_dims:
            da = da.isel({d: 0 for d in extra_dims}).drop_vars(extra_dims, errors="ignore")

        # --- cache write ---
        if self._cache_dir is not None:
            cached = self._cache_dir / f"{cmat_var}.nc"
            log.info("Caching %s to %s ...", cmat_var, cached)
            enc = {cmat_var: {"dtype": "float32", "zlib": True, "complevel": 4}}
            da.compute().to_dataset(name=cmat_var).to_netcdf(cached, encoding=enc)
            log.info("Cached %s (%s)", cmat_var, cached)

        return da

    # ------------------------------------------------------------------
    # Coordinate standardisation helpers
    # ------------------------------------------------------------------

    def _standardise_coords(self, da: xr.DataArray) -> xr.DataArray:
        """Rename non-standard coordinate names to lat/lon/time/plev."""
        rename = {}
        for dim in da.dims:
            dl = dim.lower()
            if dl in ("latitude", "nav_lat", "lat_0"):
                rename[dim] = "lat"
            elif dl in ("longitude", "nav_lon", "lon_0"):
                rename[dim] = "lon"
            elif dl in ("lev", "level", "pressure", "pressure_level", "plev"):
                rename[dim] = "plev"
        if rename:
            da = da.rename(rename)
        # Ensure lat increases south to north
        if "lat" in da.dims and da.lat.values[0] > da.lat.values[-1]:
            da = da.isel(lat=slice(None, None, -1))
        return da

    def _slice_years(self, da: xr.DataArray) -> xr.DataArray:
        """Subset to the configured year_range (inclusive)."""
        y0, y1 = self.year_range
        return da.sel(time=slice(str(y0), str(y1)))
