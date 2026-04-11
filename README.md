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
| CLI: `score`, `fetch-obs`, `check-data` | **Working** |
| CESM2 historical validated | **0.746 overall** (target ~0.81) |
| Diagnostic plots | Not yet implemented |
| HTML report output | Not yet implemented |
| EOF/bias analysis | Not yet implemented |
| CLI: `report` | Stub only |

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

Current CESM2 historical result: **0.746 overall** (target ~0.81, Fasullo et al. 2020 Table 1).
The gap is concentrated in `fs`, `rtfs`, and `ep` which have near-zero or negative seasonal/ENSO correlations — see Known Issues below.

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
python run_cmat.py report     [stub] Generate HTML report

python run_cmat.py score --help    # see all options
python run_cmat.py fetch-obs --help
```

---

## Not Yet Implemented

- **Diagnostic plots** (`src/plots.py`): color table heatmap, per-variable
  map and zonal mean bias plots with stippling
- **HTML report** (`src/html_output.py`): sortable multi-model index pages
- **EOF/bias analysis** (`src/eof_analysis.py`): bias PC decomposition
  analogous to Fig. 9 in Fasullo et al. (2020)
- **`report` command**: aggregate multiple `scores.json` files into HTML

---

## Known Issues

### Score gap vs Fasullo et al. 2020

CESM2 historical scores 0.746 vs the paper's ~0.81. The gap is driven by
three variables whose seasonal and/or ENSO correlations are near-zero or negative:

| Variable | Annual R | Seasonal R | ENSO R | Score |
|----------|----------|------------|--------|-------|
| `fs`     | 0.805    | -0.213     | -0.170 | 0.143 |
| `rtfs`   | 0.920    | -0.066     | -0.055 | 0.269 |
| `ep`     | 0.913    | 0.060      | 0.034  | 0.338 |

The annual correlations are now physically reasonable. The sub-annual
correlations are likely poor because the obs for these variables are derived
residuals (CERES surface radiation minus ERA5 turbulent fluxes), and the
seasonal/ENSO signals in that residual do not match the model well. The paper
may use a different obs source or a different derivation for these variables.

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
