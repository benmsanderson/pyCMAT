# pyCMAT

A Python port of the Climate Model Assessment Tool (CMAT) described in
[Fasullo et al. (2020, GMD)](https://doi.org/10.5194/gmd-13-3627-2020).

pyCMAT benchmarks climate model fidelity by computing area-weighted pattern
correlations between model output and observational/reanalysis datasets across
three timescales and three physical realms, producing a scalar overall score
comparable to published values in the paper.

---

## Status

| Component | Status |
|-----------|--------|
| Core scoring pipeline | **Working** |
| Local NetCDF scoring | **Working** |
| CMIP6 GCS scoring (Pangeo) | **Working** |
| CMIP6 disk cache | **Working** |
| Observational reference data (26 files) | **Working** |
| CLI: `score`, `fetch-obs`, `check-data`, `report` | **Working** |
| CESM2 historical validated | **0.846 overall** (paper: 0.86) |
| NorESM2-LM historical validated | **0.761 overall** (paper: 0.74, r2i1p1f1) |
| Color table plots (7 PNGs) | **Working** |
| HTML report output (7 pages) | **Working** |
| Bias map plots | In progress (Phase 4) |
| EOF/bias analysis | Not yet implemented |

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

### 1. Fetch observational reference data

Downloads CERES EBAF Ed4.2, GPCP CDR v2.3, and ERA5 fields for 2001-2020:

```bash
python run_cmat.py fetch-obs --source all \
    --year-start 2001 --year-end 2020 \
    --output data/obs
```

Requires:
- NASA Earthdata account (for CERES) — credentials in `~/.netrc`
- CDS API key (for ERA5) — credentials in `~/.cdsapirc`

### 2. Score a local model run

```bash
python run_cmat.py score \
    --data-dir /path/to/model/output \
    --obs-dir data/obs \
    --output output/my_run
```

Files in `--data-dir` are matched by filename stem, CF `standard_name`, or
a built-in alias table. Pass `--name-map '{"MYVAR": "pr"}'` for custom names.

### 3. Score a model run and compare against a CMIP6 reference

The CMIP6 benchmark is fetched from the Pangeo GCS mirror and cached locally
to `data/model_cache/`. Re-runs load from disk.

```bash
python run_cmat.py score \
    --data-dir /path/to/model/output \
    --benchmark-model CESM2 \
    --obs-dir data/obs \
    --output output/my_run_vs_cesm2
```

### 4. Score a CMIP6 model directly

```bash
python run_cmat.py score \
    --model CESM2 --experiment historical --member r1i1p1f1 \
    --obs-dir data/obs \
    --output output/CESM2
```

### 5. Check available data

```bash
python run_cmat.py check-data --obs-dir data/obs
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
python run_cmat.py report --scores-dir output --report-dir report
```

Output goes to `report/` (gitignored). Open `report/index.html` in a browser.

---

## Not Yet Implemented

- **Bias map plots** (`src/plots.py` `plot_bias_map()`): per-variable 3-panel
  maps (model mean / obs / bias) with zonal mean insets — requires cartopy (Phase 4)
- **EOF/bias analysis** (`src/eof_analysis.py`): bias PC decomposition
  analogous to Fig. 9 in Fasullo et al. (2020)

---

## Known Issues

### NorESM2-LM ensemble member

`rsus` is absent for r1i1p1f1 on the Pangeo GCS mirror; NorESM2-LM was
scored using r2i1p1f1. The paper likely used r1i1p1f1. To reproduce the
paper's member exactly, fetch `rsus` for r1i1p1f1 directly from ESGF.

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
