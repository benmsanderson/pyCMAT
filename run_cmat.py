#!/usr/bin/env python3
"""
run_cmat.py — Command-line interface for pyCMAT.

Primary usage:
  python run_cmat.py score  --model CESM2 --experiment historical \\
                            --member r1i1p1f1 --output ./output/CESM2

  python run_cmat.py report --scores-dir ./output --archive CMIP6

Run `python run_cmat.py --help` or `python run_cmat.py <command> --help`
for full option details.
"""
import sys
import json
import math
import logging
from pathlib import Path

import click


def _json_default(obj):
    """JSON serialiser that converts NaN/Inf to null."""
    if isinstance(obj, float) and not math.isfinite(obj):
        return None
    raise TypeError(f"Object of type {type(obj)} is not JSON serialisable")

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    level=logging.INFO,
)
log = logging.getLogger("pycmat")


# ---------------------------------------------------------------------------
# CLI root
# ---------------------------------------------------------------------------
@click.group()
@click.option("--verbose", "-v", is_flag=True, default=False,
              help="Enable DEBUG logging.")
def cli(verbose: bool) -> None:
    """pyCMAT — Climate Model Assessment Tool (Python)."""
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)


# ---------------------------------------------------------------------------
# score  — run diagnostics for a single model simulation
# ---------------------------------------------------------------------------
@cli.command()
# --- Data source: local directory (takes priority if provided) ---
@click.option("--data-dir",   default=None, type=click.Path(exists=True),
              help="Local directory of NetCDF files to score. "
                   "Mutually exclusive with --model/--experiment/--member.")
@click.option("--name-map",   default=None, type=str,
              help="JSON string mapping local variable names to CMIP6 names, "
                   'e.g. \'{"TMQ": "prw", "LHFLX": "hfls"}\'. '
                   "Only needed if auto-detection fails.")
# --- Data source: CMIP6 GCS ---
@click.option("--model",      default=None,
              help="CMIP6 source_id for GCS access, e.g. CESM2. "
                   "Required if --data-dir is not provided.")
@click.option("--experiment", default="historical", show_default=True,
              help="CMIP6 experiment_id")
@click.option("--member",     default="r1i1p1f1", show_default=True,
              help="CMIP6 member_id (ripf label)")
# --- Optional: benchmark/reference model from CMIP6 GCS for comparison ---
@click.option("--benchmark-model",  default=None,
              help="CMIP6 source_id to use as the reference/benchmark run "
                   "(fetched from GCS). Produces a side-by-side improvement/degradation report.")
@click.option("--benchmark-member", default="r1i1p1f1", show_default=True,
              help="Member ID for the benchmark CMIP6 model.")
# --- Common options ---
@click.option("--year-start", default=1995, show_default=True, type=int,
              help="Start year of analysis period (inclusive)")
@click.option("--year-end",   default=2014, show_default=True, type=int,
              help="End year of analysis period (inclusive)")
@click.option("--output",     required=True, type=click.Path(),
              help="Output directory for scores JSON and diagnostic plots")
@click.option("--obs-dir",    default=None, type=click.Path(exists=True),
              help="Override path to observational reference data "
                   "(default: data/obs/ relative to repo root)")
@click.option("--no-plots",   is_flag=True, default=False,
              help="Skip generating diagnostic map plots (faster for batch runs)")
@click.option("--clobber",    is_flag=True, default=False,
              help="Recompute even if cached results exist")
@click.option("--cache-dir",  default=None, type=click.Path(),
              help="Override the default GCS download cache location "
                   "(default: data/model_cache/, or $PYCMAT_CACHE_DIR). "
                   "Fields are saved under <cache-dir>/<model>/<experiment>/<member>/")
@click.option("--no-cache",   is_flag=True, default=False,
              help="Disable local caching of CMIP6 GCS downloads (always re-streams from GCS)")
def score(
    data_dir, name_map, model, experiment, member,
    benchmark_model, benchmark_member,
    year_start, year_end, output, obs_dir, no_plots, clobber, cache_dir, no_cache
) -> None:
    """
    Compute CMAT scores for a single model simulation.

    \b
    Data source (choose one):
      --data-dir   Score a local directory of NetCDF files (dev runs, post-
                   processed history files, any format auto-detected).
      --model      Fetch from the CMIP6 GCS mirror via intake-esm.

    \b
    Optionally compare against a CMIP6 reference:
      --benchmark-model CESM2   Fetch the benchmark from GCS and report
                                improvements/degradations vs. the scored run.

    Results are written as scores.json plus PNG diagnostic plots.
    """
    if data_dir is None and model is None:
        raise click.UsageError(
            "Provide either --data-dir (local NetCDF) or --model (CMIP6 GCS)."
        )
    if data_dir is not None and model is not None:
        raise click.UsageError(
            "--data-dir and --model are mutually exclusive."
        )

    output_path = Path(output)
    output_path.mkdir(parents=True, exist_ok=True)

    scores_file = output_path / "scores.json"
    if scores_file.exists() and not clobber:
        log.info("Scores file already exists: %s (use --clobber to recompute)", scores_file)
        return

    year_range = (year_start, year_end)

    # Build the primary data loader
    from src.data_loader import CmatLoader
    if data_dir is not None:
        extra_map = json.loads(name_map) if name_map else None
        run_label = Path(data_dir).name
        log.info("Scoring local run: %s (%d-%d)", data_dir, *year_range)
        loader = CmatLoader.from_local(data_dir, year_range=year_range, name_map=extra_map)
    else:
        run_label = f"{model}_{member}"
        log.info("Scoring CMIP6: %s %s %s (%d-%d)", model, experiment, member, *year_range)
        resolved_cache = None if no_cache else (cache_dir or "default")
        loader = CmatLoader.from_cmip6(model, experiment, member, year_range=year_range,
                                       cache_dir=resolved_cache)

    # Optionally build a benchmark loader for comparison
    benchmark_loader = None
    if benchmark_model:
        log.info("Benchmark: CMIP6 %s %s (%d-%d)", benchmark_model, benchmark_member, *year_range)
        resolved_cache = None if no_cache else (cache_dir or "default")
        benchmark_loader = CmatLoader.from_cmip6(
            benchmark_model, experiment, benchmark_member, year_range=year_range,
            cache_dir=resolved_cache
        )

    # Resolve observational data directory
    if obs_dir is None:
        from config import OBS_DIR
        obs_dir = str(OBS_DIR)

    from src.pipeline import run_scoring_pipeline
    results = run_scoring_pipeline(
        loader,
        obs_dir=obs_dir,
        benchmark_loader=benchmark_loader,
    )

    # Write scores.json
    with open(scores_file, "w") as fh:
        json.dump(results, fh, indent=2, default=_json_default)
    log.info("Scores written to %s", scores_file)

    # Summary to stdout
    s = results["scores"]
    click.echo(f"\n{'='*50}")
    click.echo(f"  Run: {run_label}")
    click.echo(f"  Period: {year_start}-{year_end}")
    click.echo(f"{'='*50}")
    click.echo(f"  Energy:   {s['realm'].get('energy',  float('nan')):.3f}")
    click.echo(f"  Water:    {s['realm'].get('water',   float('nan')):.3f}")
    click.echo(f"  Dynamics: {s['realm'].get('dynamics',float('nan')):.3f}")
    click.echo(f"{'='*50}")
    click.echo(f"  OVERALL:  {s['overall']:.3f}")
    click.echo(f"{'='*50}")

    if results["delta_scores"]:
        click.echo("\n  Variable-level deltas vs benchmark (positive = improvement):")
        for var, delta in sorted(results["delta_scores"].items()):
            sign = "+" if delta > 0 else ""
            click.echo(f"    {var:12s}  {sign}{delta:.4f}")


# ---------------------------------------------------------------------------
# report  — aggregate scores from multiple runs into HTML output
# ---------------------------------------------------------------------------
@cli.command()
@click.option("--scores-dir", required=True, type=click.Path(exists=True),
              help="Directory containing per-model score JSON files")
@click.option("--archive",    default="CMIP6", show_default=True,
              help="Archive label shown in HTML pages (e.g. CMIP6, CMIP5)")
@click.option("--output",     required=True, type=click.Path(),
              help="Output directory for HTML index pages and summary plots")
def report(scores_dir, archive, output) -> None:
    """
    Aggregate per-model scores into CMAT HTML report pages.

    Reads score JSON files written by the 'score' command, generates the
    color table summary figure, and writes index.html pages sorted by
    overall and realm scores.
    """
    output_path = Path(output)
    output_path.mkdir(parents=True, exist_ok=True)

    scores_path = Path(scores_dir)
    score_files = sorted(scores_path.rglob("scores.json"))

    if not score_files:
        log.error("No scores.json files found in %s", scores_dir)
        sys.exit(1)

    log.info("Found %d model score files", len(score_files))

    # Load all scores
    all_scores = {}
    for f in score_files:
        model_name = f.parent.name
        with open(f) as fh:
            all_scores[model_name] = json.load(fh)

    # Phase: generate color table summary plot  (src/plots.py)
    # Phase: generate HTML index pages  (src/html_output.py)

    raise NotImplementedError(
        "report command: plots and HTML generation not yet implemented"
    )


# ---------------------------------------------------------------------------
# fetch-obs  — download observational reference datasets
# ---------------------------------------------------------------------------
@cli.command("fetch-obs")
@click.option("--output", required=True, type=click.Path(),
              help="Directory to cache observational reference files")
@click.option("--source", "sources",
              type=click.Choice(["ceres", "gpcp", "era5", "all"], case_sensitive=False),
              multiple=True, default=("all",), show_default=True,
              help="Which sources to fetch. Repeat flag for multiple: "
                   "--source ceres --source gpcp")
@click.option("--year-start", default=2001, show_default=True, type=int,
              help="Start year for obs period")
@click.option("--year-end", default=2022, show_default=True, type=int,
              help="End year for obs period")
@click.option("--earthdata-token", default=None, envvar="EARTHDATA_TOKEN",
              help="NASA Earthdata bearer token for CERES download. "
                   "Falls back to ~/.netrc (machine urs.earthdata.nasa.gov). "
                   "Also reads EARTHDATA_TOKEN env var.")
def fetch_obs(output, sources, year_start, year_end, earthdata_token) -> None:
    """
    Download observational reference datasets needed for CMAT scoring.

    \b
    Sources:
      ceres   CERES EBAF Ed4.2 (NASA Earthdata, free account required)
              -> rsnt, rlut, swcftoa, lwcftoa; surface radiation for fs/rtfs
      gpcp    GPCP CDR v2.3 (NOAA PSL, no auth required)
              -> pr
      era5    ERA5 monthly means (Copernicus CDS, requires ~/.cdsapirc)
              -> prw, hurs, hfls, psl, sfcWind, ts, zg500, wap500, hur500

    \b
    After fetching CERES + ERA5, derived obs fields (fs, rtfs, ep) are
    computed automatically from the component files.

    \b
    Auth setup:
      CERES:  https://urs.earthdata.nasa.gov  (free; add urs.earthdata.nasa.gov
              to ~/.netrc or export EARTHDATA_TOKEN=<token>)
      ERA5:   https://cds.climate.copernicus.eu/how-to-api  (free; creates
              ~/.cdsapirc with your personal access token)
    """
    from src.obs_fetcher import (
        fetch_ceres, fetch_gpcp, fetch_era5, derive_obs_fs_rtfs
    )

    output_path = Path(output)
    output_path.mkdir(parents=True, exist_ok=True)

    to_fetch = set(sources)
    if "all" in to_fetch:
        to_fetch = {"ceres", "gpcp", "era5"}

    written_all = []

    if "ceres" in to_fetch:
        click.echo("Fetching CERES EBAF Ed4.2 (TOA + Surface) ...")
        try:
            written = fetch_ceres(
                output_path,
                start_year=year_start,
                end_year=year_end,
                earthdata_token=earthdata_token,
            )
            written_all += written
            click.echo(f"  CERES: wrote {written}")
        except Exception as exc:
            log.error("CERES fetch failed: %s", exc)
            click.echo(f"  CERES FAILED: {exc}", err=True)

    if "gpcp" in to_fetch:
        click.echo("Fetching GPCP CDR v2.3 (precipitation) ...")
        try:
            written = fetch_gpcp(
                output_path,
                start_year=year_start,
                end_year=year_end,
            )
            written_all += written
            click.echo(f"  GPCP: wrote {written}")
        except Exception as exc:
            log.error("GPCP fetch failed: %s", exc)
            click.echo(f"  GPCP FAILED: {exc}", err=True)

    if "era5" in to_fetch:
        click.echo("Fetching ERA5 monthly means via CDS API ...")
        try:
            written = fetch_era5(
                output_path,
                start_year=year_start,
                end_year=year_end,
            )
            written_all += written
            click.echo(f"  ERA5: wrote {written}")
        except Exception as exc:
            log.error("ERA5 fetch failed: %s", exc)
            click.echo(f"  ERA5 FAILED: {exc}", err=True)

    # Derive composite obs (fs, rtfs, ep) from downloaded components
    if {"ceres", "era5"} & to_fetch:
        click.echo("Deriving composite obs fields (fs, rtfs, ep) ...")
        try:
            derived = derive_obs_fs_rtfs(output_path)
            written_all += derived
            click.echo(f"  Derived: {derived}")
        except Exception as exc:
            log.warning("Derived obs computation failed: %s", exc)

    click.echo(f"\nDone. {len(written_all)} obs variables in {output_path}:")
    for v in sorted(set(written_all)):
        path = output_path / f"{v}.nc"
        size_mb = path.stat().st_size >> 20 if path.exists() else 0
        click.echo(f"  {v:12s}  {size_mb} MB")


# ---------------------------------------------------------------------------
# check-data  — verify CMIP6 GCS catalog availability for a model
# ---------------------------------------------------------------------------
@cli.command("check-data")
@click.option("--model",      required=True)
@click.option("--experiment", default="historical", show_default=True)
@click.option("--member",     default="r1i1p1f1", show_default=True)
def check_data(model, experiment, member) -> None:
    """
    Check CMIP6 GCS catalog availability for all required variables.

    Queries the Pangeo intake-esm catalog and reports which of the required
    CMIP6 variables are available for the specified model/experiment/member,
    and which are missing or only available at non-standard table_ids.
    """
    try:
        import intake
    except ImportError:
        log.error("intake-esm is not installed. Run: pip install intake-esm gcsfs")
        sys.exit(1)

    log.info("Checking CMIP6 GCS availability: %s %s %s", model, experiment, member)

    catalog = intake.open_esm_datastore(
        "https://storage.googleapis.com/cmip6/pangeo-cmip6.json"
    )

    from config import REQUIRED_CMIP6_VARS, PLEV_TABLE_OPTIONS

    found = []
    missing = []

    for var in REQUIRED_CMIP6_VARS:
        subset = catalog.search(
            source_id=model,
            experiment_id=experiment,
            member_id=member,
            variable_id=var,
        )
        if len(subset.df) > 0:
            tables = subset.df["table_id"].unique().tolist()
            found.append((var, tables))
            log.info("  FOUND   %-12s  tables: %s", var, tables)
        else:
            missing.append(var)
            log.warning("  MISSING %-12s", var)

    click.echo(f"\n{len(found)}/{len(REQUIRED_CMIP6_VARS)} required variables found")
    if missing:
        click.echo(f"Missing: {missing}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    cli()
