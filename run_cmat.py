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
import logging
from pathlib import Path

import click

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
@click.option("--model",      required=True,  help="CMIP6 source_id, e.g. CESM2")
@click.option("--experiment", default="historical", show_default=True,
              help="CMIP6 experiment_id")
@click.option("--member",     default="r1i1p1f1", show_default=True,
              help="CMIP6 member_id (ripf label)")
@click.option("--year-start", default=1995, show_default=True, type=int,
              help="Start year of analysis period (inclusive)")
@click.option("--year-end",   default=2014, show_default=True, type=int,
              help="End year of analysis period (inclusive)")
@click.option("--output",     required=True, type=click.Path(),
              help="Output directory for scores JSON and diagnostic plots")
@click.option("--obs-dir",    default=None, type=click.Path(exists=True),
              help="Override path to observational reference data")
@click.option("--no-plots",   is_flag=True, default=False,
              help="Skip generating diagnostic map plots (faster)")
@click.option("--clobber",    is_flag=True, default=False,
              help="Recompute even if cached results exist")
def score(
    model, experiment, member, year_start, year_end,
    output, obs_dir, no_plots, clobber
) -> None:
    """
    Compute CMAT scores for a single model simulation.

    Fetches data from the CMIP6 GCS mirror via intake-esm, computes the 16
    diagnostic variables across three timescales, runs pattern correlations
    against observations, and writes results as JSON + PNG figures.
    """
    output_path = Path(output)
    output_path.mkdir(parents=True, exist_ok=True)

    scores_file = output_path / "scores.json"
    if scores_file.exists() and not clobber:
        log.info("Scores file already exists: %s (use --clobber to recompute)", scores_file)
        return

    log.info("Scoring %s %s %s (%d-%d)", model, experiment, member, year_start, year_end)

    # Phase 1: load data  (to be implemented in src/data_loading.py)
    # Phase 2: compute derived variables  (src/derived_vars.py)
    # Phase 3: compute climatologies  (src/climatology.py)
    # Phase 4: regrid to 1-deg  (src/regrid.py)
    # Phase 5: pattern correlations  (src/pattern_cor.py)
    # Phase 6: compute scores  (src/scoring.py)
    # Phase 7: write JSON output
    # Phase 8: generate plots  (src/plots.py)

    raise NotImplementedError(
        "score command: data loading and scoring pipeline not yet implemented"
    )


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
@click.option("--datasets", default="all", show_default=True,
              help="Comma-separated list of datasets to fetch: "
                   "ceres,era5,gpcp,erai  or 'all'")
def fetch_obs(output, datasets) -> None:
    """
    Download observational reference datasets needed for scoring.

    CERES EBAF 4.1 is fetched from NASA CERES; ERA5 from Copernicus CDS
    (requires a ~/.cdsapirc credentials file); GPCP CDR from NOAA NCEI.
    """
    output_path = Path(output)
    output_path.mkdir(parents=True, exist_ok=True)

    to_fetch = [d.strip() for d in datasets.split(",")] if datasets != "all" \
               else ["ceres", "era5", "gpcp", "erai"]

    log.info("Will fetch: %s -> %s", to_fetch, output_path)

    raise NotImplementedError(
        "fetch-obs command: observational download not yet implemented"
    )


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
