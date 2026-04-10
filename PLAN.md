# pyCMAT Development Plan

A Python port of the Climate Model Assessment Tool (CMAT v1) described in
Fasullo et al. (2020, GMD, https://doi.org/10.5194/gmd-13-3627-2020).

The tool benchmarks climate model fidelity by computing area-weighted pattern
correlations between model output and observational/reanalysis datasets across
three timescales (annual mean, seasonal contrast, ENSO teleconnections) and
three physical realms (energy budget, water cycle, dynamics).

---

## Primary Use Cases

1. **Score a local model run against observations** — the main development workflow.
   A local directory of NetCDF files (e.g., from a dev build or post-processed
   history files) is scored directly against the observational reference datasets.

   ```
   python run_cmat.py score --data-dir /path/to/model/output \
                            --output ./output/my_dev_run
   ```

2. **Compare a local run against a CMIP6 archived reference** — matching the
   original IDL `run1 vs run2` workflow. The local run is scored against obs,
   and its scores are compared to a CMIP6 model fetched from GCS.

   ```
   python run_cmat.py score --data-dir /path/to/model/output \
                            --benchmark-model CESM2 --benchmark-member r1i1p1f1 \
                            --output ./output/my_dev_vs_cesm2
   ```

3. **Score a CMIP6 model from GCS** — batch processing the full archive.

   ```
   python run_cmat.py score --model CESM2 --experiment historical \
                            --member r1i1p1f1 --output ./output/CESM2
   ```

4. **Generate repository HTML** — aggregate per-model score JSONs into
   sortable HTML index pages with color table summary plots.

---

## Repository Structure

```
pyCMAT/
  config.py              # paths, variable definitions, scoring weights
  src/
    data_loader.py       # unified data access: local NetCDF OR CMIP6 GCS
    derived_vars.py      # compute fs, rsnt, swcftoa, ep, zg500-eddy, etc.
    climatology.py       # annual mean, seasonal contrast, ENSO regression
    regrid.py            # regrid to 1-deg, land/ocean mask
    pattern_cor.py       # area-weighted pattern correlations
    scoring.py           # variable / realm / overall scores
    eof_analysis.py      # bias EOF/PC analysis (Fig. 9 in paper)
    plots.py             # color table summary + map/zonal mean bias plots
    html_output.py       # generate index.html pages
  data/
    obs/                 # observational/reanalysis reference fields (local cache)
    model/               # model data cache (NetCDF, gitignored)
  notebooks/
    01_data_access.ipynb   # CMIP6 cloud data exploration and subsetting
    02_test_scoring.ipynb  # end-to-end test with one model vs observations
  tests/
    test_scoring.py        # unit tests for scoring math
    test_derived_vars.py   # unit tests for derived variable computations
  PLAN.md
  requirements.txt
  README.md
```

---

## Development Phases

### Phase 1: Foundation (data I/O and regridding)
- [ ] Set up `config.py` with variable lists, realm assignments, scoring weights,
      and observed global-mean reference values used for sanity flags- [ ] Implement `src/data_loader.py`: unified interface for two backends:
      - **Local**: glob NetCDF files from a directory, infer variable from filename
        or CF standard_name; handle non-standard grids and file layouts
      - **CMIP6 GCS**: intake-esm catalog query, lazy Zarr loading
      Both backends return `xarray.Dataset` objects in a consistent form.
- [x] Implement `regrid.py` with three-tier backend strategy:
      - **Regular / Gaussian grids** (1D lat, lon): `xarray.interp()` via scipy
        (pip-only, matches IDL `congrid()` bilinear behaviour)
      - **Non-regular grids** (2D lat/lon, cubed-sphere `ncol`, tripolar ocean):
        `pyresample` KDTree (pip-installable); falls back to `scipy.griddata`;
        raises a descriptive error pointing to `ncremap` / `xesmf` if absent
      - **Conservative remapping** (opt-in `--method conservative`): `xesmf`
        (optional, requires `conda install -c conda-forge xesmf`)
- [x] Implement land/ocean masking via `regionmask` Natural Earth polygons
- [ ] Test CMIP6 data access via Pangeo intake-esm catalog (see Data section below)
- [ ] Download and cache observational reference fields (see Obs section below)

### Phase 2: Core diagnostics
- [ ] Implement `derived_vars.py` for all 16 scored variables and their component inputs
- [ ] Implement `climatology.py`: annual mean, JJA-DJF seasonal contrast,
      and Jul-Jun ENSO teleconnection regressions against Niño3.4
- [ ] Implement `pattern_cor.py`: area-weighted Pearson correlation
- [ ] Validate pattern correlations for CESM2 against published scores in Table 1
      of Fasullo et al. (2020) (CESM2 overall score ~0.81)

### Phase 3: Scoring and output
- [ ] Implement `scoring.py`: variable, realm, timescale, and overall scores
- [ ] Implement `eof_analysis.py`: bias PC/EOF decomposition across model ensemble
- [ ] Implement `plots.py`: color table summary heatmap, map and zonal mean bias plots
      with stippling for uncertainty
- [ ] Implement `html_output.py`: index pages sorted by overall/realm scores

### Phase 4: Validation
- [ ] Run full test case (CESM2 vs CESM2-WACCM, see below) and compare to paper
- [ ] Verify that the CESM1-LE spread in overall score reproduces ~0.010 std
      (used to establish the ~0.040 significance threshold between models)
- [ ] Expand to a broader CMIP6 subset and compare rank ordering to Table 1

---

## Scoring System

Scores are area-weighted pattern correlations $R_s$, scaled here as fractions
(0-1; multiplied by 100 in display). Per variable, the three timescales are
combined with a weighted average:

```
variable_score = (R_annual * 1.0 + R_seasonal * 1.0 + R_ENSO * 0.978) / 2.978
```

The ENSO weight (0.978, vs 1.0 for annual and seasonal) is set so that the
standard deviation of overall scores across the 40-member CESM1-LE is 0.010,
providing a yardstick: intermodel differences below ~0.040 (+/- 2 sigma) are
not statistically significant.

Realm scores are the arithmetic mean of variable scores within that realm.
Overall score is the arithmetic mean of the three realm scores.

### Variables scored (16 total)

| Realm    | Variable ID | Description                          |
|----------|-------------|--------------------------------------|
| Energy   | rsnt        | Net TOA shortwave (ASR)              |
| Energy   | rlut        | TOA outgoing longwave (OLR)          |
| Energy   | swcftoa     | SW cloud forcing                     |
| Energy   | lwcftoa     | LW cloud forcing                     |
| Energy   | fs          | Net surface energy flux (residual)   |
| Energy   | rtfs        | RT - Fs (column energy tendency)     |
| Water    | pr          | Precipitation                        |
| Water    | prw         | Precipitable water                   |
| Water    | hurs        | Near-surface relative humidity       |
| Water    | hfls        | Latent heat flux (evaporation)       |
| Water    | ep          | E-P (moisture divergence)            |
| Dynamics | psl         | Sea level pressure                   |
| Dynamics | sfcWind     | Near-surface wind speed              |
| Dynamics | zg500       | 500 hPa eddy geopotential height     |
| Dynamics | wap500      | 500 hPa vertical velocity            |
| Dynamics | hur500      | 500 hPa relative humidity            |

Excluded from scoring: `tasa` (mainly noise), `rsdt` (by definition = 1).
Note: `sfcWind` was absent from CMIP3; for CMIP3 comparisons the dynamics
realm score is computed from the remaining 4 dynamic variables only.

---

## Test Case: CMIP6 Google Cloud Mirror

### Access method

The Pangeo CMIP6 intake-esm catalog provides lazy Zarr access to most CMIP6
data hosted on Google Cloud Storage (GCS) — no download required for initial
exploration.

```python
import intake
catalog = intake.open_esm_datastore(
    "https://storage.googleapis.com/cmip6/pangeo-cmip6.json"
)
```

The catalog is queryable by `source_id`, `experiment_id`, `variable_id`,
`table_id`, and `member_id`. Fields can be loaded as `xarray.Dataset` objects
via Zarr with lazy evaluation, keeping memory usage low.

### Recommended minimal test case

Two CESM2-family models for initial end-to-end validation. CESM2 has
published scores in the paper, making it the primary validation target.

| Model        | experiment | member   | period    |
|--------------|------------|----------|-----------|
| CESM2        | historical | r1i1p1f1 | 1995-2014 |
| CESM2-WACCM  | historical | r1i1p1f1 | 1995-2014 |

### CMIP6 variables required from GCS

All from `table_id = Amon` (monthly atmospheric) unless noted.

| variable_id | table_id | Derived variable(s)           |
|-------------|----------|-------------------------------|
| rsdt        | Amon     | rsnt                          |
| rsut        | Amon     | rsnt, swcftoa                 |
| rsutcs      | Amon     | swcftoa                       |
| rlut        | Amon     | scored directly, lwcftoa      |
| rlutcs      | Amon     | lwcftoa                       |
| rsds        | Amon     | fs                            |
| rsus        | Amon     | fs                            |
| rlds        | Amon     | fs                            |
| rlus        | Amon     | fs                            |
| hfls        | Amon     | fs, ep                        |
| hfss        | Amon     | fs                            |
| pr          | Amon     | scored directly               |
| prw         | Amon     | scored directly               |
| hurs        | Amon     | scored directly               |
| psl         | Amon     | scored directly               |
| sfcWind     | Amon     | scored directly               |
| zg          | Amon     | zg500 (extract level, rm ZM)  |
| wap         | Amon     | wap500 (extract level)        |
| hur         | Amon     | hur500 (extract level)        |
| ts or tos   | Amon/Omon| Niño3.4 index for ENSO regs  |

Pressure-level fields (`zg`, `wap`, `hur`) may be in `table_id = Amon` with
a `plev19` or `plev8` coordinate, or in `CFmon`. Check catalog availability
per model before assuming `Amon`.

### Estimated data volume

At native resolution (~1-deg for CESM2) with 240 monthly time steps (1995-2014),
each `Amon` variable is roughly 50-100 MB. Twenty variables per model gives
approximately 1-2 GB per model. With streaming via Zarr, only the subset
needed for a given computation is pulled into memory.

---

## Observational Reference Datasets

These are obtained independently of the CMIP6 GCS mirror.

| Dataset        | Fields                            | Period    | Access                                         |
|----------------|-----------------------------------|-----------|------------------------------------------------|
| CERES EBAF 4.1 | rsut, rsutcs, rlut, rlutcs, rsdt  | 2001-2018 | https://ceres.larc.nasa.gov/data/               |
| ERA5           | prw, hurs, hfls, hfss, psl,       | 1979-2017 | Copernicus CDS (`cdsapi` Python package)       |
|                | sfcWind, zg500, wap500, hur500    |           |                                                |
| GPCP CDR v2.3  | pr                                | 1979-2016 | https://www.ncei.noaa.gov/products/gpcp        |
| ERA-Interim    | ep (E-P from moisture divergence) | 2001-2016 | Legacy; ERA5 moisture divergence preferred     |

For ENSO teleconnections, at least 20 years of Jul-Jun means are needed for
regression against Niño3.4 (area-averaged SSTA, 5S-5N, 170-120W).

### Observational uncertainty

The IDL tool uses pre-computed CESM1-LE spread fields to determine where
model-observation differences exceed internal variability. For the Python port,
two options:

1. Convert existing IDL `.sav` uncertainty files via `scipy.io.readsav`
   (quickest path if the original files are available)
2. Recompute from the CESM1-LE members available on CMIP6 GCS as
   `source_id = CESM2` large ensemble submissions

---

## Key Python Dependencies

```
# Core data
xarray>=2023.1
netCDF4
zarr
fsspec
gcsfs               # GCS access for CMIP6 cloud Zarr stores
intake-esm          # CMIP6 catalog queries

# Regridding and masking
xesmf               # conservative/bilinear regridding
regionmask          # land/ocean masking (Natural Earth or GRIB-based)

# Numerics
numpy
scipy               # readsav for IDL .sav migration, interpolation

# Analysis
scikit-learn        # PCA for EOF/bias analysis

# Visualization
matplotlib
cartopy             # map projections for bias plots

# Data access
cdsapi              # ERA5 download via Copernicus CDS

# HTML output (optional)
jinja2
```

---

## IDL-to-Python Translation Reference

| IDL function / pattern           | Python equivalent                              |
|----------------------------------|------------------------------------------------|
| `congrid()`                      | `xesmf.Regridder` (conservative) or `scipy.ndimage.zoom` |
| `rebin_bad()`                    | `xarray.coarsen()` with NaN-aware mean         |
| `anmean3d()`, `make_annual_cycle()` | `xarray.groupby('time.month').mean()`       |
| `mean_wgt()` / `calculate_wts()` | `numpy` cosine-latitude weighted mean          |
| `oceanonly()` / `landonly()`     | `regionmask` boolean masks                     |
| `spectrally_truncate()`          | `pyshtools` or `windspharm` (low priority;     |
|                                  | not used for any of the 16 scored variables)   |
| `fill_bad()`                     | `xarray.interpolate_na()`                      |
| `rms_2d()`                       | Custom `numpy` weighted RMS (trivial)           |
| `make_ncl_pat_cor()`             | Custom `numpy` area-weighted Pearson correlation |
|                                  | (IDL originally shells out to NCL for this)    |
| IDL `.sav` files                 | `scipy.io.readsav()` for legacy data migration |
| IDL fill value `1e36`            | `np.nan` throughout                            |
| `anmean3d(/djf)`, `anmean3d(/jja)` | `xarray.where(time.season == 'DJF').mean()`  |
| `ps` / `ps_process` (PostScript) | `matplotlib` + `cartopy`                       |

---

## Pattern Correlation Implementation Note

The area-weighted pattern correlation between simulated field $X$ and observed
field $Y$ over a global grid is:

$$R_s = \frac{\sum_i w_i (X_i - \bar{X})(Y_i - \bar{Y})}
            {\sqrt{\sum_i w_i (X_i - \bar{X})^2 \cdot \sum_i w_i (Y_i - \bar{Y})^2}}$$

where $w_i = \cos(\phi_i)$ (cosine of latitude) and overbars denote the
weighted global mean. NaN/missing values in either field are excluded from
both fields at the same grid points.

This replaces the IDL code's call to `make_ncl_pat_cor()`, which wrapped the
equivalent NCL built-in `pattern_cor()`.
