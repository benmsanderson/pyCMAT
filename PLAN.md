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

   ```bash
   python run_cmat.py score --data-dir /path/to/model/output \
                            --obs-dir data/obs --output ./output/my_dev_run
   ```

2. **Compare a local run against a CMIP6 archived reference** — matching the
   original IDL `run1 vs run2` workflow. CMIP6 fields auto-cache to
   `data/model_cache/` on first download; subsequent calls are instant.

   ```bash
   python run_cmat.py score --data-dir /path/to/model/output \
                            --benchmark-model CESM2 \
                            --obs-dir data/obs --output ./output/my_dev_vs_cesm2
   ```

3. **Score a CMIP6 model from GCS** — first run downloads + caches; re-runs are fast.

   ```bash
   python run_cmat.py score --model CESM2 --experiment historical \
                            --member r1i1p1f1 --obs-dir data/obs --output ./output/CESM2
   ```

4. **Generate repository HTML** — aggregate per-model score JSONs into
   sortable HTML index pages with color table summary plots.

### Cache behaviour

CMIP6 fields are streamed from the Pangeo GCS mirror (`gs://cmip6/`) and
written to `data/model_cache/<model>/<experiment>/<member>/<var>.nc`.
Subsequent runs load from disk, reducing scoring time from ~1 hour to ~30 seconds.

Override the location with `--cache-dir <path>` or `PYCMAT_CACHE_DIR` env var.
Disable with `--no-cache`.

---

## Repository Structure

```
pyCMAT/
  config.py              # paths, variable definitions, scoring weights
  run_cmat.py            # CLI entry point (score, fetch-obs, check-data, report)
  src/
    data_loader.py       # unified data access: local NetCDF OR CMIP6 GCS (with disk cache)
    derived_vars.py      # compute fs, rsnt, swcftoa, ep, zg500-eddy, etc.
    climatology.py       # annual mean, seasonal contrast, ENSO regression
    regrid.py            # regrid to 1-deg, land/ocean mask
    pattern_cor.py       # area-weighted pattern correlations
    scoring.py           # variable / realm / overall scores
    pipeline.py          # end-to-end orchestration
    obs_fetcher.py       # download CERES, GPCP, ERA5 observation files
    eof_analysis.py      # bias EOF/PC analysis — stub, Phase 3
    plots.py             # color table + map/zonal mean bias plots — stub, Phase 3
    html_output.py       # generate index.html pages — stub, Phase 3
  data/
    obs/                 # observational reference fields (gitignored)
    model_cache/         # downloaded CMIP6 NetCDF files (gitignored)
  output/                # per-model scores.json and plots
  tests/
    test_scoring.py
    test_derived_vars.py
  PLAN.md
  requirements.txt
  README.md
```

---

## Development Phases

### Phase 1: Foundation — COMPLETE
- [x] `config.py`: variable list, realm assignments, scoring weights, paths
- [x] `data_loader.py`: local NetCDF + CMIP6 GCS backends; disk cache for GCS
- [x] `derived_vars.py`: all 16 scored variables and component fields
- [x] `climatology.py`: annual mean, JJA-DJF, Jul-Jun ENSO regression
- [x] `regrid.py`: 3-tier regridding (xarray.interp / pyresample / griddata);
      land/ocean masks via regionmask
- [x] `pattern_cor.py`: area-weighted Pearson correlation
- [x] `scoring.py`: variable, realm, and overall scores
- [x] `pipeline.py`: end-to-end orchestration
- [x] `run_cmat.py`: CLI — `score`, `fetch-obs`, `check-data` commands working;
      `report` stub

### Phase 2: Observations + CMIP6 validation — COMPLETE
- [x] `obs_fetcher.py`: CERES EBAF Ed4.2 (earthaccess), GPCP CDR v2.3 (NOAA PSL),
      ERA5 (cdsapi) — all 26 obs files present in `data/obs/`
- [x] Fix ERA5 new CDS API differences: zip extraction, `valid_time`→`time` rename,
      0.25° grid regrid before arithmetic
- [x] Fix CMIP6 GCS access: `token="anon"` for anonymous Pangeo bucket reads
- [x] Fix intake-esm extra dimensions (`member_id`, `dcpp_init_year`) — squeezed out
- [x] Fix ENSO time alignment: normalize mid-month vs start-of-month timestamps
- [x] Fix obs ENSO: use ERA5 `ts` (not model SST) as Niño3.4 source for obs regression
- [x] CESM2 historical scoring run complete — 0.746 overall
- [x] Fix `zg500` obs: zonal mean was not removed from obs before correlation
      (model had eddy = z - zonal_mean; obs was raw). Fix: added `_EDDY_VARS`
      set in `pipeline.py`, `remove_zonal_mean()` applied to obs for `zg500`.
      Result: annual R 0.110 → 0.926, variable score 0.315 → 0.874.
- [x] Fix ERA5 `hfls`/`hfss` unit factor: ERA5 monthly slhf/sshf are
      J m-2 day-1 (daily accumulated), not J m-2 hr-1. Factor corrected from
      `-1/3600` to `-1/86400` in `obs_fetcher.py`. Stored files corrected
      in-place; `ep`, `fs`, `rtfs` re-derived from corrected fields.
      Result: `fs` annual R 0.128 → 0.805; `ep` annual R 0.466 → 0.913.

### Phase 3: Output and visualisation — COMPLETE (bias maps pending)
- [x] `plots.py`: color table heatmap (7 PNG summary plots) — `plot_colortable()`
- [ ] `plots.py`: per-variable map and zonal mean bias plots — `plot_bias_map()` (stub; Phase 4)
- [x] `html_output.py`: 7 HTML index pages (overall, energy, water, dynamics, annual, seasonal, ENSO)
      with CSS color-coded score cells, letter grades (A-E from CMIP5 percentile thresholds),
      and nav bar linking all views
- [ ] `eof_analysis.py`: bias PC/EOF decomposition across ensemble
- [x] `report` CLI command: aggregates per-model `scores.json` files into 7 PNGs + 7 HTML pages

### Phase 4: Validation — IN PROGRESS
- [x] CESM2 historical overall score: **0.846** vs paper's 0.86 (gap = 0.014) — VALIDATED
      All three bug fixes applied: `zg500` eddy (0.315→0.874), `hfls`/`hfss` units
      (-1/3600→-1/86400), `fs`/`rtfs`/`ep` time series (monthly series preserved).
      Energy 0.858, Water 0.836, Dynamics 0.845.
- [x] NorESM2-LM historical overall score: **0.761** vs paper's 0.74 — VALIDATED
      Used r2i1p1f1 (r1i1p1f1 missing `rsus` on Pangeo GCS). ENSO scores lower
      than CESM2 (0.213 gap) driven by rsnt, swcftoa, fs; expected for NorESM2-LM
      ENSO physics. Overall score slightly above paper value.
- [ ] Implement `plot_bias_map()` with cartopy (Phase 4 current work)
- [ ] Score additional CMIP6 models to validate rank ordering vs Table 1
- [ ] Optionally fetch NorESM2-LM r1i1p1f1 `rsus` from ESGF to match paper's member

---

## Scoring System

Per variable, the three timescales are combined:

```
variable_score = (R_annual + R_seasonal + 0.978 * R_ENSO) / 2.978
```

The ENSO weight (0.978) is calibrated so that the std of overall scores across
the 40-member CESM1-LE is 0.010 (significance threshold ~0.040).

Realm scores = mean of variable scores within realm.
Overall score = mean of three realm scores.

### Variables scored (16 total)

| Realm    | Variable | Description                         |
|----------|----------|-------------------------------------|
| Energy   | rsnt     | Net TOA shortwave (ASR)             |
| Energy   | rlut     | TOA outgoing longwave (OLR)         |
| Energy   | swcftoa  | SW cloud forcing                    |
| Energy   | lwcftoa  | LW cloud forcing                    |
| Energy   | fs       | Net surface energy flux (residual)  |
| Energy   | rtfs     | RT minus Fs (column energy balance) |
| Water    | pr       | Precipitation                       |
| Water    | prw      | Precipitable water                  |
| Water    | hurs     | Near-surface relative humidity      |
| Water    | hfls     | Latent heat flux                    |
| Water    | ep       | E-P (moisture divergence)           |
| Dynamics | psl      | Sea level pressure                  |
| Dynamics | sfcWind  | Near-surface wind speed             |
| Dynamics | zg500    | 500 hPa eddy geopotential height    |
| Dynamics | wap500   | 500 hPa vertical velocity           |
| Dynamics | hur500   | 500 hPa relative humidity           |

---

## Observational Reference Datasets

All fetched via `python run_cmat.py fetch-obs --source all --year-start 2001 --year-end 2020`.

| Source         | Variables                                                   |
|----------------|-------------------------------------------------------------|
| CERES EBAF Ed4.2 | rsut, rsutcs, rlut, rlutcs, rsdt, rsds, rsus, rlds, rlus |
| GPCP CDR v2.3  | pr                                                          |
| ERA5 (CDS API) | prw, hurs, hfls, hfss, psl, sfcWind, ts, zg500, wap500, hur500 |
| Derived        | rsnt, swcftoa, lwcftoa, fs, rtfs, ep                        |

**ERA5 CDS API notes**: cdsapi 0.7.7 downloads results as a zip (not auto-extracted);
time dim is `valid_time`; coordinates are `latitude`/`longitude`. All handled
in `obs_fetcher.py`.

---

## Known Issues / Decisions

- **NorESM2-LM ensemble member**: `rsus` is absent for r1i1p1f1 on the Pangeo
  GCS mirror; we used r2i1p1f1. To match the paper's member exactly, fetch
  `rsus` for r1i1p1f1 from ESGF directly.
- **`sfcWind`**: CMIP6 provides `sfcWind` (scalar speed); ERA5 obs derived
  from `si10` (10m wind speed, already scalar) — should match.
- **Period mismatch**: model 1995-2014 vs obs 2001-2020. Spatial correlations
  are robust to this, but a 2001-2014 overlap would be stricter.

### Fixed bugs (kept for reference)

- **`zg500` eddy**: FIXED. Zonal mean now removed from obs before correlation,
  matching the model-side treatment in `calc_zg500()`. Score: 0.315 → 0.874.
- **ERA5 `hfls`/`hfss` units**: FIXED. Factor was `-1/3600` (J/m²/hr → W/m²);
  correct factor is `-1/86400` (J/m²/day → W/m²) for ERA5 monthly mean
  accumulations. `fs`, `rtfs`, `ep` re-derived in-place after correction.
- **`fs`/`rtfs`/`ep` time series**: FIXED. `obs_fetcher.derive_obs_fs_rtfs()`
  was returning 2D time-mean fields; rewritten to keep full monthly series
  and align timestamps with `_normalize_time()` + `xr.align(join="inner")`.
  `fs` seasonal R: -0.213 → 0.984. Overall CESM2 score: 0.746 → 0.846.
