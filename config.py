"""
pyCMAT configuration: variable definitions, realm assignments, scoring weights,
observational dataset paths, and global-mean reference values used for
sanity-check flags.
"""
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths — override via environment variables or pass explicitly at runtime
# ---------------------------------------------------------------------------
ROOT_DIR = Path(__file__).parent
DATA_DIR = ROOT_DIR / "data"
OBS_DIR = DATA_DIR / "obs"
MODEL_CACHE_DIR = DATA_DIR / "model"
OUTPUT_DIR = ROOT_DIR / "output"

# ---------------------------------------------------------------------------
# Scoring weights
# The ENSO weight (0.978 vs 1.0) is chosen so that the standard deviation of
# overall scores across the 40-member CESM1-LE is 0.010, providing a yardstick:
# intermodel differences below ~0.040 (+/- 2 sigma) are not significant.
# ---------------------------------------------------------------------------
WT_ANNUAL = 1.0
WT_SEASONAL = 1.0
WT_ENSO = 0.978
WT_SUM = WT_ANNUAL + WT_SEASONAL + WT_ENSO  # 2.978

# ---------------------------------------------------------------------------
# Variable definitions
# Each entry: CMIP6 variable_id -> metadata dict
# ---------------------------------------------------------------------------
VARIABLES = {
    # --- Energy realm ---
    "rsnt": {
        "realm": "energy",
        "description": "Net TOA shortwave (ASR)",
        "units": "W m-2",
        # Derived from rsdt - rsut
        "derived_from": ["rsdt", "rsut"],
    },
    "rlut": {
        "realm": "energy",
        "description": "TOA outgoing longwave (OLR)",
        "units": "W m-2",
        "cmip6_var": "rlut",
    },
    "swcftoa": {
        "realm": "energy",
        "description": "SW cloud forcing at TOA",
        "units": "W m-2",
        # Derived: rsut - rsutcs  (all-sky minus clear-sky reflected SW)
        "derived_from": ["rsut", "rsutcs"],
    },
    "lwcftoa": {
        "realm": "energy",
        "description": "LW cloud forcing at TOA",
        "units": "W m-2",
        # Derived: rlutcs - rlut
        "derived_from": ["rlut", "rlutcs"],
    },
    "fs": {
        "realm": "energy",
        "description": "Net surface energy flux (residual method, ocean only)",
        "units": "W m-2",
        # Derived: rlns - rsns + hfls + hfss  (sign: positive into ocean)
        "derived_from": ["rsds", "rsus", "rlds", "rlus", "hfls", "hfss"],
    },
    "rtfs": {
        "realm": "energy",
        "description": "RT - Fs (column energy tendency proxy)",
        "units": "W m-2",
        "derived_from": ["rsdt", "rsut", "rlut", "rsds", "rsus", "rlds", "rlus", "hfls", "hfss"],
    },
    # --- Water realm ---
    "pr": {
        "realm": "water",
        "description": "Precipitation",
        "units": "mm day-1",
        "cmip6_var": "pr",
        "unit_scale": 86400.0,  # kg m-2 s-1 -> mm day-1
    },
    "prw": {
        "realm": "water",
        "description": "Precipitable water",
        "units": "mm",
        "cmip6_var": "prw",
    },
    "hurs": {
        "realm": "water",
        "description": "Near-surface relative humidity",
        "units": "%",
        "cmip6_var": "hurs",
    },
    "hfls": {
        "realm": "water",
        "description": "Latent heat flux (evaporation)",
        "units": "W m-2",
        "cmip6_var": "hfls",
    },
    "ep": {
        "realm": "water",
        "description": "E-P (evaporation minus precipitation)",
        "units": "mm day-1",
        # Derived: hfls / L_v * 86400 - pr * 86400
        "derived_from": ["hfls", "pr"],
    },
    # --- Dynamics realm ---
    "psl": {
        "realm": "dynamics",
        "description": "Sea level pressure",
        "units": "Pa",
        "cmip6_var": "psl",
    },
    "sfcWind": {
        "realm": "dynamics",
        "description": "Near-surface wind speed",
        "units": "m s-1",
        "cmip6_var": "sfcWind",
        # Note: absent from CMIP3; dynamics score omits this variable for CMIP3
        "cmip3_missing": True,
    },
    "zg500": {
        "realm": "dynamics",
        "description": "500 hPa eddy geopotential height (zonal mean removed)",
        "units": "m",
        # Extracted from 3D 'zg' field at 500 hPa, divided by g=9.80665
        "derived_from": ["zg"],
        "plev": 50000.0,  # Pa
    },
    "wap500": {
        "realm": "dynamics",
        "description": "500 hPa vertical velocity",
        "units": "Pa s-1",
        "derived_from": ["wap"],
        "plev": 50000.0,
    },
    "hur500": {
        "realm": "dynamics",
        "description": "500 hPa relative humidity",
        "units": "%",
        "derived_from": ["hur"],
        "plev": 50000.0,
    },
}

# ---------------------------------------------------------------------------
# Realm groupings (for realm-level scoring)
# ---------------------------------------------------------------------------
REALM_VARS = {
    "energy":   ["rsnt", "rlut", "swcftoa", "lwcftoa", "fs", "rtfs"],
    "water":    ["pr", "prw", "hurs", "hfls", "ep"],
    "dynamics": ["psl", "sfcWind", "zg500", "wap500", "hur500"],
}

# Variables excluded from scoring
EXCLUDED_VARS = ["tasa", "rsdt"]

# ---------------------------------------------------------------------------
# CMIP6 variables to fetch from GCS for each scored variable
# (union of all derived_from lists plus direct cmip6_var entries)
# ---------------------------------------------------------------------------
REQUIRED_CMIP6_VARS = [
    "rsdt", "rsut", "rsutcs",
    "rlut", "rlutcs",
    "rsds", "rsus", "rlds", "rlus",
    "hfls", "hfss",
    "pr", "prw", "hurs", "psl", "sfcWind",
    "zg", "wap", "hur",
    "ts",   # surface temperature for Nino3.4 index
]

# CMIP6 table for pressure-level fields (model-dependent; check catalog)
PLEV_TABLE_OPTIONS = ["Amon", "CFmon"]

# ---------------------------------------------------------------------------
# Target analysis period (model)
# ---------------------------------------------------------------------------
MODEL_PERIOD = ("1995", "2014")  # 20-year climatology

# ENSO teleconnection regression period (Jul-Jun annual means)
ENSO_PERIOD = ("1920", "1979")   # PI-era default; AMIP uses 1980-2014

# Nino3.4 region
NINO34_LAT = (-5.0, 5.0)
NINO34_LON = (190.0, 240.0)  # degrees East (170W-120W)

# ---------------------------------------------------------------------------
# Regridding target (all fields interpolated to this before scoring)
# ---------------------------------------------------------------------------
TARGET_GRID = {"nlon": 360, "nlat": 180}  # 1-degree

# Gravitational acceleration (for geopotential -> geopotential height)
GRAV = 9.80665  # m s-2

# Latent heat of vaporization (for E-P derived variable)
L_V = 2.5e6  # J kg-1

# ---------------------------------------------------------------------------
# Global-mean reference values for sanity-check flags
# (from observations/reanalyses, used to flag gross model errors)
# Source: CERES EBAF 4.1, ERA5
# ---------------------------------------------------------------------------
GLOBAL_MEAN_REF = {
    "rsnt":    241.1,   # W m-2  (net TOA SW)
    "rlut":    240.2,   # W m-2  (OLR)
    "swcftoa": -45.8,   # W m-2  (SW cloud forcing, negative = cooling)
    "lwcftoa":  28.0,   # W m-2  (LW cloud forcing)
    "hfls":     77.2,   # W m-2  (latent heat flux)
}

HEMISPHERE_DIFF_REF = {
    "rsnt":    0.2,     # NH - SH
    "rlut":    1.1,
    "swcftoa": 6.0,
    "lwcftoa": 0.5,
    "hfls":   -8.0,
    "tas":     1.9,
}

LAND_OCEAN_DIFF_REF = {
    "rsnt":    -38.1,   # land - ocean
    "rlut":    -11.3,
    "swcftoa":  17.0,
    "lwcftoa":  -3.9,
    "hfls":    -55.0,
    "tas":       7.3,
}

# ---------------------------------------------------------------------------
# Observational dataset configuration
# Keys correspond to CMAT variable names; values describe the obs source and
# the local cache filename expected under OBS_DIR.
# ---------------------------------------------------------------------------
OBS_SOURCES = {
    "rsnt": {
        "source": "CERES EBAF 4.1",
        "period": ("2001", "2018"),
        "file": "CERES41_rsnt_200101-201812.nc",
    },
    "rlut": {
        "source": "CERES EBAF 4.1",
        "period": ("2001", "2018"),
        "file": "CERES41_rlut_200101-201812.nc",
    },
    "swcftoa": {
        "source": "CERES EBAF 4.1",
        "period": ("2001", "2018"),
        "file": "CERES41_swcftoa_200101-201812.nc",
    },
    "lwcftoa": {
        "source": "CERES EBAF 4.1",
        "period": ("2001", "2018"),
        "file": "CERES41_lwcftoa_200101-201812.nc",
    },
    "fs": {
        "source": "CERES EBAF 4.1 / ERA-Interim residual",
        "period": ("2001", "2016"),
        "file": "CERES_ERAI_fs_200101-201612.nc",
    },
    "rtfs": {
        "source": "CERES EBAF 4.1 / ERA-Interim residual",
        "period": ("2001", "2016"),
        "file": "CERES_ERAI_rtfs_200101-201612.nc",
    },
    "pr": {
        "source": "GPCP CDR v2.3",
        "period": ("1979", "2016"),
        "file": "GPCP_CDR_pr_197901-201612.nc",
    },
    "prw": {
        "source": "ERA5",
        "period": ("1979", "2017"),
        "file": "ERA5_prw_197901-201712.nc",
    },
    "hurs": {
        "source": "ERA5",
        "period": ("1979", "2017"),
        "file": "ERA5_hurs_197901-201712.nc",
    },
    "hfls": {
        "source": "ERA5",
        "period": ("1979", "2017"),
        "file": "ERA5_hfls_197901-201712.nc",
    },
    "ep": {
        "source": "ERA-Interim (moisture divergence)",
        "period": ("2001", "2016"),
        "file": "ERAI_ep_200101-201612.nc",
    },
    "psl": {
        "source": "ERA5",
        "period": ("1979", "2017"),
        "file": "ERA5_psl_197901-201712.nc",
    },
    "sfcWind": {
        "source": "ERA5",
        "period": ("1979", "2017"),
        "file": "ERA5_sfcWind_197901-201712.nc",
    },
    "zg500": {
        "source": "ERA5",
        "period": ("1979", "2017"),
        "file": "ERA5_zg500_197901-201712.nc",
    },
    "wap500": {
        "source": "ERA5",
        "period": ("1979", "2018"),
        "file": "ERA5_wap500_197901-201812.nc",
    },
    "hur500": {
        "source": "ERA5",
        "period": ("1979", "2017"),
        "file": "ERA5_hur500_197901-201712.nc",
    },
}
