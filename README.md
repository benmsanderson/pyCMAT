# pyCMAT

A Python port of the Climate Model Assessment Tool (CMAT) described in
[Fasullo et al. (2020, GMD)](https://doi.org/10.5194/gmd-13-3627-2020).

pyCMAT benchmarks climate model fidelity by computing area-weighted pattern
correlations between model output and observational/reanalysis datasets across
three timescales and three physical realms, producing a scalar overall score
comparable to published values in the paper.

---

## Installation

```bash
git clone https://github.com/benmsanderson/pyCMAT.git
cd pyCMAT
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

---

## Quick Start

### 1. Fetch observational reference data (if needed)

Downloads CERES EBAF Ed4.2, GPCP CDR v2.3, and ERA5 fields for 2001-2020:

```bash
python run_cmat.py fetch-obs --source all \
    --year-start 2001 --year-end 2020 \
    --output data/obs
```

Requires:
- NASA Earthdata account (for CERES) — credentials in `~/.netrc`
- CDS API key (for ERA5) — credentials in `~/.cdsapirc`

**Skip this step if you already have an obs directory.** If your group
maintains a shared processed-obs folder, point `--obs-dir` directly at it:

```bash
python run_cmat.py score \
    --data-dir /path/to/model/output \
    --obs-dir /projects/NS9188K/CMATobs \
    --output output/my_run
```

Run `python run_cmat.py check-data --model NorESM2-LM` to verify all required
CMIP6 variables are available in the Pangeo catalog for a given model.

### 2. Score a local model run

```bash
python run_cmat.py score \
    --data-dir /path/to/model/output \
    --obs-dir /datalake/NS16000B/CMATobs \
    --output output/my_run
```

Files in `--data-dir` are matched by filename stem, CF `standard_name`, or
a built-in alias table. Pass `--name-map '{"MYVAR": "pr"}'` for custom names.

Add `--bias-maps` to generate annual-mean bias map PNGs alongside scores:

```bash
python run_cmat.py score \
    --data-dir /path/to/model/output \
    --obs-dir /datalake/NS16000B/CMATobs \
    --output output/my_run \
    --bias-maps
```

### 4. Score a NorESM development run directly

Point `--noresm-case` at a NorESM case output directory and pyCMAT reads the
raw `atm/hist/*.cam.h0.YYYY-MM.nc` files directly — no pre-processing or
variable renaming required.  The CAM→CMIP6 name mapping, surface-flux
derivations, and time-coordinate fix are all handled automatically.

```bash
python run_cmat.py score \
    --noresm-case /projects/NS9560K/noresm/cases/MyCaseName \
    --year-start 1950 --year-end 1969 \
    --obs-dir /datalake/NS16000B/CMATobs \
    --output output/MyCaseName
```

Optionally specify a non-default history stream with `--noresm-stream`
(default: `cam.h0`):

```bash
python run_cmat.py score \
    --noresm-case /projects/NS9560K/noresm/cases/MyCaseName \
    --noresm-stream cam.h0 \
    --year-start 1950 --year-end 1969 \
    --obs-dir /datalake/NS16000B/CMATobs --output output/MyCaseName
```

Historical, piControl, and other experiment types all work — CMAT scores
spatial *patterns*, not absolute values, so the forcing level does not
affect the method.

The CMIP6 benchmark is fetched from the Pangeo GCS mirror and cached locally
to `data/model_cache/`. Re-runs load from disk.

```bash
python run_cmat.py score \
    --data-dir /path/to/model/output \
    --benchmark-model CESM2 \
    --obs-dir /datalake/NS16000B/CMATobs \
    --output output/my_run_vs_cesm2
```

### 5. Score a CMIP6 model directly (pull from Google/PanGEO CMIP6 mirror)

```bash
python run_cmat.py score \
    --model CESM2 --experiment historical --member r1i1p1f1 \
    --obs-dir data/obs \
    --output output/CESM2
```

### 6. Check CMIP6 catalog availability

```bash
python run_cmat.py check-data --model NorESM2-LM
```

---

## Output

Results are written to `<output>/scores.json`:

```json
{
  "pattern_correlations": {
    "rsnt": {"annual": 0.994, "seasonal": 0.994, "enso": 0.639},
    "rlut": {"annual": 0.988, "seasonal": 0.956, "enso": 0.823},
    ...
  },
  "scores": {
    "variable": {"rsnt": 0.877, "rlut": 0.923, "zg500": 0.874, ...},
    "realm":    {"energy": 0.658, "water": 0.734, "dynamics": 0.845},
    "overall":  0.746
  },
  "metadata": {
    "model": "CESM2", "experiment": "historical",
    "member": "r1i1p1f1", "year_range": [1995, 2014]
  }
}
```

Validated results vs Fasullo et al. 2020 Table 1:

| Model | Score | Paper |
|-------|-------|-------|
| CESM2 (r1i1p1f1) | **0.846** | 0.86 |
| NorESM2-LM (r2i1p1f1) | **0.761** | 0.74 |

---

## Variables Scored (16)

| Realm    | Variable  | Description                          | Obs source        |
|----------|-----------|--------------------------------------|-------------------|
| Energy   | `rsnt`    | Net TOA shortwave (ASR)              | CERES EBAF        |
| Energy   | `rlut`    | TOA outgoing longwave (OLR)          | CERES EBAF        |
| Energy   | `swcftoa` | SW cloud forcing                     | CERES EBAF        |
| Energy   | `lwcftoa` | LW cloud forcing                     | CERES EBAF        |
| Energy   | `fs`      | Net surface energy flux              | CERES + ERA5      |
| Energy   | `rtfs`    | RT minus Fs (column energy balance)  | CERES + ERA5      |
| Water    | `pr`      | Precipitation                        | GPCP CDR v2.3     |
| Water    | `prw`     | Precipitable water                   | ERA5              |
| Water    | `hurs`    | Near-surface relative humidity       | ERA5              |
| Water    | `hfls`    | Latent heat flux                     | ERA5              |
| Water    | `ep`      | E-P (evaporation minus precip)       | ERA5 + GPCP       |
| Dynamics | `psl`     | Sea level pressure                   | ERA5              |
| Dynamics | `sfcWind` | Near-surface wind speed              | ERA5              |
| Dynamics | `zg500`   | 500 hPa eddy geopotential height     | ERA5              |
| Dynamics | `wap500`  | 500 hPa vertical velocity            | ERA5              |
| Dynamics | `hur500`  | 500 hPa relative humidity            | ERA5              |

---

## Scoring Method

Per variable, pattern correlations across three timescales are combined:

```
variable_score = (R_annual + R_seasonal + 0.978 × R_ENSO) / 2.978
```

- **Annual mean**: time-mean climatology
- **Seasonal contrast**: JJA minus DJF mean
- **ENSO teleconnection**: OLS regression of Jul-Jun annual anomalies against
  the Niño3.4 SST index (5S-5N, 170-120W)

The ENSO weight (0.978) is calibrated so the std of overall scores across the
40-member CESM1-LE is 0.010, giving a ~0.040 significance threshold between models.

Realm scores = mean of variable scores within that realm.
Overall score = mean of the three realm scores.

---

## CMIP6 Disk Cache

CMIP6 fields downloaded from GCS are saved to `data/model_cache/` by default:

```
data/model_cache/
  CESM2/historical/r1i1p1f1/
    pr.nc
    ts.nc
    ...
```

Override location: `--cache-dir /path/to/cache` or `PYCMAT_CACHE_DIR=/path python run_cmat.py ...`

Disable caching: `--no-cache`

---

## CLI Reference

```
python run_cmat.py score      Score a model against observations
python run_cmat.py fetch-obs  Download observational reference data
python run_cmat.py check-data Check which obs/model files are available
python run_cmat.py report     Generate color table PNGs + HTML index pages

python run_cmat.py score --help    # see all options
python run_cmat.py fetch-obs --help
```

### 6. Generate HTML report

After scoring one or more models, aggregate their `scores.json` files into 7
HTML index pages (overall, energy, water, dynamics, annual, seasonal, ENSO)
plus 7 matching color table PNG heatmaps:

```bash
python run_cmat.py report --scores-dir output --output report
```

Output goes to `report/` (gitignored). Open `report/index.html` in a browser.
Model names in the index pages are links to per-model detail pages that include
bias map thumbnails (if `--bias-maps` was used when scoring).

---

## Not Yet Implemented

Both remaining stubs are ensemble-level analyses that require scores from many
models to be meaningful. They are not needed for single-model scoring.

- **EOF/bias PC decomposition** (`src/eof_analysis.py`): PCA of the bias
  field stacked across models, analogous to Figs. 6-9 in Fasullo et al. (2020).
  Requires `sklearn` and a collection of per-model bias arrays.
- **Score distribution plots** (`src/plots.py` `plot_score_distributions()`):
  whisker plots of score spread across CMIP archives (Fig. 10 style).

---

## Preparing Local Model Data

The `score --data-dir` path accepts a directory of monthly-mean NetCDF files
(one variable per file is simplest, but multi-variable files work too).
Files are matched to scored variables in this priority order:

1. **Filename stem** — e.g. `pr.nc` or `precipitation.nc`
2. **CF `standard_name` attribute** — e.g. `precipitation_flux`
3. **Built-in alias table** — common alternative names (e.g. `PRECT` -> `pr`)
4. **`--name-map` JSON override** — anything else

### NorESM / CAM history files

For NorESM development runs the easiest path is the dedicated
`--noresm-case` backend (see [Quick Start §3](#3-score-a-noresm-development-run-directly)).
It discovers `atm/hist/*.cam.h0.*.nc` files automatically and handles all
of the following mappings internally — no shell pre-processing needed:

| CAM h0 variable | CMIP6 variable | Notes |
|-----------------|----------------|-------|
| `PRECC + PRECL` | `pr` | multiplied by 1000 (m s⁻¹ → kg m⁻² s⁻¹) |
| `TMQ` | `prw` | — |
| `LHFLX` | `hfls` | — |
| `SHFLX` | `hfss` | — |
| `FLUT` | `rlut` | — |
| `FLUTC` | `rlutcs` | — |
| `FSUTOA` | `rsut` | — |
| `FSNTOAC` | `rsutcs` | — |
| `SOLIN` | `rsdt` | — |
| `FSDS` | `rsds` | — |
| `FSDS − FSNS` | `rsus` | derived from net SW |
| `FLDS` | `rlds` | — |
| `FLDS + FLNS` | `rlus` | derived from net LW |
| `RELHUM` (lowest σ level) | `hurs` | near-surface RH |
| `Z3` | `zg` | full 3-D field |
| `OMEGA` | `wap` | full 3-D field |
| `RELHUM` | `hur` | full 3-D field |
| `PSL` | `psl` | — |
| `U10` | `sfcWind` | — |
| `TS` | `ts` | Niño3.4 SST index |

The time coordinate is also corrected automatically: CAM writes each
 monthly-mean record with a timestamp at the start of the *following* month;
pyCMAT shifts it back using `time_bnds` so that seasonal labels and
year-range slicing are correct.

If you prefer to pre-process the history files yourself, use `--data-dir`
with a `--name-map` override instead:

```bash
python run_cmat.py score \
    --data-dir /path/to/cam/output \
    --name-map '{"PRECT": "pr", "TMQ": "prw", "LHFLX": "hfls", "SHFLX": "hfss"}' \
    --obs-dir data/obs \
    --output output/my_cam_run
```

### Required variables

To score all 16 CMAT variables, provide these raw fields. pyCMAT derives
`rsnt`, `swcftoa`, `lwcftoa`, `fs`, `rtfs`, and `ep` automatically; you do
not need to pre-derive them.

| CMIP6 name | Feeds scored variable(s) |
|------------|---------------------------|
| `rsdt` | rsnt, swcftoa |
| `rsut` | rsnt, swcftoa |
| `rsutcs` | swcftoa |
| `rlut` | rlut, lwcftoa |
| `rlutcs` | lwcftoa |
| `rsds` | fs, rtfs |
| `rsus` | fs, rtfs |
| `rlds` | fs, rtfs |
| `rlus` | fs, rtfs |
| `hfls` | fs, rtfs, ep, hfls |
| `hfss` | fs, rtfs |
| `pr` | pr, ep |
| `prw` | prw |
| `hurs` | hurs |
| `psl` | psl |
| `sfcWind` | sfcWind |
| `zg` (with `plev`, needs 500 hPa) | zg500 |
| `wap` (with `plev`, needs 500 hPa) | wap500 |
| `hur` (with `plev`, needs 500 hPa) | hur500 |
| `ts` or `tos` | Nino3.4 index for ENSO regression |

Missing variables are skipped gracefully — you get NaN scores for those
variables, but the rest score normally.

### File naming

The simplest layout names each file by CMIP6 variable:

```
my_run/
  pr.nc         prw.nc       hurs.nc       psl.nc      sfcWind.nc
  rlut.nc       rsdt.nc      rsut.nc       rsutcs.nc   rlutcs.nc
  rsds.nc       rsus.nc      rlds.nc       rlus.nc
  hfls.nc       hfss.nc
  zg.nc         wap.nc       hur.nc
  ts.nc
```

For models using different internal names, add `--name-map`:

```bash
python run_cmat.py score \
    --data-dir /path/to/cam/output \
    --name-map '{"TMQ": "prw", "LHFLX": "hfls", "SHFLX": "hfss"}' \
    --obs-dir data/obs \
    --output output/my_cam_run
```

### Time dimension

- Must have a CF-compliant `time` coordinate with **monthly** frequency
- Standard and `cftime` calendars both work
- Minimum useful period: 10 years (needed for stable ENSO regression)
- Recommended: 20 years matching the obs period (2001-2020) or the
  standard CMIP6 historical end (1995-2014)
- Use `--year-start` / `--year-end` to subset the time axis before scoring

### Grid

pyCMAT regrids everything to 1 degree x 1 degree before computing pattern
correlations. Any grid is accepted:

- **Regular lat/lon grids** (1D lat/lon arrays): fast interpolation via
  `xarray.interp`
- **Unstructured or 2D-coordinate grids** (cubed-sphere, tripolar, `ncol`):
  regridded via `pyresample` KDTree

Pressure-level fields (`zg`, `wap`, `hur`) must include a `plev` coordinate
in **Pascals** (50000 Pa is extracted for the 500 hPa level automatically).

### Units

pyCMAT assumes CMIP6-standard SI units. Common pitfalls:

| Variable | Expected | Common non-standard form |
|----------|----------|--------------------------|
| `pr` | kg m-2 s-1 | mm day-1 (divide by 86400) |
| `psl` | Pa | hPa (multiply by 100) |
| `zg` | m | dam or gpm (multiply by 10) |
| `hfls`, `hfss` | W m-2 | ERA5 J m-2 accumulations (divide by 86400) |
| `rsds`, `rsus`, etc. | W m-2 | ERA5 J m-2 accumulations (divide by 86400) |

### Minimal post-processing example (CESM/CAM)

If you need to pre-process CESM `.cam.h0.` files into the `--data-dir`
format rather than using `--noresm-case`, extract and rename with xarray:

```python
import xarray as xr

ds = xr.open_mfdataset('case.cam.h0.1995-*.nc', combine='by_coords')

# Map CAM names to CMIP6 names
cam_to_cmip6 = {
    'FSNTOA': 'rsdt',   # net TOA SW (clear label differs from CMIP6 convention)
    'FLUT':   'rlut',
    'PRECT':  'pr',
    'TMQ':    'prw',
    'PSL':    'psl',
    'LHFLX':  'hfls',
    'SHFLX':  'hfss',
}
ds_out = ds[list(cam_to_cmip6)].rename(cam_to_cmip6)
ds_out.sel(time=slice('1995', '2014')).to_netcdf('my_run/atm_vars.nc')
```

Or save individual per-variable files and let pyCMAT match by stem:

```python
for cam_name, cmip6_name in cam_to_cmip6.items():
    ds[[cam_name]].rename({cam_name: cmip6_name}).to_netcdf(f'my_run/{cmip6_name}.nc')
```

---


## Status

| Component | Status |
|-----------|--------|
| Core scoring pipeline | **Working** |
| Local NetCDF scoring | **Working** |
| NorESM case scoring (raw h0 files) | **Working** |
| CMIP6 GCS scoring (Pangeo) | **Working** |
| CMIP6 disk cache | **Working** |
| Observational reference data (26 files) | **Working** |
| CLI: `score`, `fetch-obs`, `check-data`, `report` | **Working** |
| CESM2 historical validated | **0.846 overall** (paper: 0.86) |
| NorESM2-LM historical validated | **0.761 overall** (paper: 0.74, r2i1p1f1) |
| Color table plots (7 PNGs) | **Working** |
| HTML report output (7 pages) | **Working** |
| Bias map plots | **Working** |
| EOF/bias PC decomposition | Not yet implemented (needs ensemble of models) |
| Score distribution whisker plots | Not yet implemented (needs ensemble of models) |
---
## Known Issues

### NorESM2-LM ensemble member

`rsus` is absent for r1i1p1f1 on the Pangeo GCS mirror; NorESM2-LM was
scored using r2i1p1f1. The paper likely used r1i1p1f1. To reproduce the
paper's member exactly, fetch `rsus` for r1i1p1f1 directly from ESGF.
Note: this only affects the CMIP6 GCS backend — the `--noresm-case` backend
reads `rsus` directly from the h0 files (derived as `FSDS − FSNS`).

### Period mismatch

Model period 1995-2014 vs obs period 2001-2020. Pattern correlations are
spatial so the mismatch affects the climatological state but not the
correlation method. A 2001-2014 overlap period would be stricter.

---

## Data Directory Layout

```
data/
  obs/             # observational reference NetCDF files (gitignored)
  model_cache/     # cached CMIP6 downloads (gitignored)
output/
  CESM2/
    scores.json
```

Both `data/obs/` and `data/model_cache/` are excluded from version control.
Re-fetch obs with `fetch-obs`; the model cache re-populates automatically on
the first `score` run for each model.

---

## Reference

Fasullo, J. T.: Evaluating simulated climate patterns from the CMIP archives using satellite and reanalysis datasets using the Climate Model Assessment Tool (CMATv1), Geosci. Model Dev., 13, 3627–3642, https://doi.org/10.5194/gmd-13-3627-2020, 2020.
