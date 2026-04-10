"""
html_output.py — Generate CMAT HTML index pages.

Produces the same HTML repository output as the IDL make_repository() procedure:
  - index.html (sorted by overall score)
  - index_Energy.html, index_Water.html, index_Dynamics.html (sorted by realm)
  - index_Annual.html, index_Seasonal.html, index_ENSO.html

Each page embeds the color table summary image and a sortable model table
with scores, grades, flags, improvements, and degradations.
"""
from pathlib import Path
from jinja2 import Environment, FileSystemLoader


# ---------------------------------------------------------------------------
# Grade scale (matching IDL: 0=A, 1=B, 2=C, 3=D, 4=E, 5=N/A)
# Thresholds are CMIP5 percentile-based; same as IDL c5*thresh arrays
# ---------------------------------------------------------------------------
GRADE_SCALE = ["A", "B", "C", "D", "E", "N/A"]


def score_to_grade(score: float, thresholds: list) -> str:
    """
    Convert a numeric score to a letter grade using precomputed thresholds.

    Parameters
    ----------
    score : float
        Pattern correlation score (0-1 scale).
    thresholds : list of float
        Descending percentile thresholds [p90, p75, p50, p25].
        Grade = index of first threshold the score exceeds.
    """
    for i, t in enumerate(thresholds):
        if score >= t:
            return GRADE_SCALE[i]
    return GRADE_SCALE[len(thresholds)]


def generate_index_pages(
    scores: dict,
    model_runs: list,
    output_dir: Path,
    archive_label: str = "CMIP6",
    template_dir: Path | None = None,
) -> None:
    """
    Write all HTML index pages for a CMAT run.

    Parameters
    ----------
    scores : dict
        {model_name: score_dict} as returned by scoring.compute_scores().
    model_runs : list of dict
        Each dict has keys: 'run', 'benchmark_run', 'notes', 'flags',
        'improvements', 'degradations'.
    output_dir : Path
        Directory where HTML files are written.
    archive_label : str
        Label shown in page titles (e.g. 'CMIP6').
    template_dir : Path or None
        Directory containing Jinja2 templates. Defaults to src/templates/.
    """
    raise NotImplementedError("generate_index_pages: implement with Jinja2")
