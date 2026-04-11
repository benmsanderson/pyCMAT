"""
html_output.py — Generate CMAT HTML index pages.

Produces the same HTML repository output as the IDL make_repository() procedure:
  - index.html (sorted by overall score)
  - index_Energy.html, index_Water.html, index_Dynamics.html (sorted by realm)
  - index_Annual.html, index_Seasonal.html, index_ENSO.html (sorted by timescale)

Each page embeds the matching color table summary image and a sortable model
table with scores and letter grades.
"""
from __future__ import annotations

import datetime
import math
from pathlib import Path

# ---------------------------------------------------------------------------
# CMIP5 percentile thresholds for letter grades
# Source: IDL cmatv1.pro c5amthreshs / c5seasthreshs / c5ensothreshs arrays
# Thresholds = [A (p90), B (p75), C (p50), D (p25)]
# If score > threshold[i]: grade letter = GRADE_SCALE[i]
# If score < all thresholds: grade = E
# ---------------------------------------------------------------------------
_CMIP5_THRESHOLDS: dict[str, dict[str, list[float]]] = {
    "rsnt":    {"annual": [0.99, 0.99, 0.98, 0.98], "seasonal": [0.97, 0.97, 0.97, 0.97], "enso": [0.57, 0.44, 0.35, 0.25]},
    "rlut":    {"annual": [0.97, 0.95, 0.95, 0.94], "seasonal": [0.94, 0.93, 0.92, 0.89], "enso": [0.63, 0.61, 0.53, 0.41]},
    "swcftoa": {"annual": [0.82, 0.80, 0.75, 0.72], "seasonal": [-0.38, -0.39, -0.41, -0.42], "enso": [0.57, 0.44, 0.32, 0.24]},
    "lwcftoa": {"annual": [0.86, 0.84, 0.81, 0.77], "seasonal": [0.06, 0.04, 0.02, 0.00], "enso": [0.64, 0.59, 0.55, 0.40]},
    "fs":      {"annual": [0.96, 0.96, 0.95, 0.94], "seasonal": [0.90, 0.89, 0.87, 0.85], "enso": [0.59, 0.55, 0.46, 0.41]},
    "rtfs":    {"annual": [0.96, 0.96, 0.95, 0.94], "seasonal": [0.90, 0.89, 0.87, 0.85], "enso": [0.59, 0.55, 0.46, 0.41]},
    "pr":      {"annual": [0.84, 0.82, 0.79, 0.76], "seasonal": [0.81, 0.80, 0.76, 0.73], "enso": [0.73, 0.64, 0.57, 0.41]},
    "hurs":    {"annual": [0.99, 0.98, 0.98, 0.97], "seasonal": [0.97, 0.96, 0.95, 0.95], "enso": [0.84, 0.77, 0.72, 0.66]},
    "prw":     {"annual": [0.99, 0.98, 0.98, 0.97], "seasonal": [0.97, 0.96, 0.95, 0.95], "enso": [0.84, 0.77, 0.72, 0.66]},
    "hfls":    {"annual": [0.96, 0.96, 0.95, 0.94], "seasonal": [0.90, 0.89, 0.87, 0.85], "enso": [0.59, 0.55, 0.46, 0.41]},
    "ep":      {"annual": [0.96, 0.96, 0.95, 0.94], "seasonal": [0.90, 0.89, 0.87, 0.85], "enso": [0.59, 0.55, 0.46, 0.41]},
    "psl":     {"annual": [0.96, 0.96, 0.95, 0.94], "seasonal": [0.90, 0.89, 0.87, 0.85], "enso": [0.59, 0.55, 0.46, 0.41]},
    "sfcWind": {"annual": [0.96, 0.96, 0.95, 0.94], "seasonal": [0.90, 0.89, 0.87, 0.85], "enso": [0.59, 0.55, 0.46, 0.41]},
    "zg500":   {"annual": [0.96, 0.96, 0.95, 0.94], "seasonal": [0.90, 0.89, 0.87, 0.85], "enso": [0.59, 0.55, 0.46, 0.41]},
    "wap500":  {"annual": [0.96, 0.96, 0.95, 0.94], "seasonal": [0.90, 0.89, 0.87, 0.85], "enso": [0.59, 0.55, 0.46, 0.41]},
    "hur500":  {"annual": [0.96, 0.96, 0.95, 0.94], "seasonal": [0.90, 0.89, 0.87, 0.85], "enso": [0.59, 0.55, 0.46, 0.41]},
}

_GRADE_SCALE = ["A", "B", "C", "D", "E", "N/A"]


def _timescale_grade(score: float, thresholds: list[float]) -> int:
    """
    Return integer grade index 0-4 (A-E) from CMIP5 percentile thresholds.
    Grade = first index where score > threshold (thresholds in descending order).
    """
    if not math.isfinite(score):
        return 5  # N/A
    for i, t in enumerate(thresholds):
        if score > t:
            return i
    return 4  # E


def _variable_grade(var: str, pcors: dict) -> int:
    """Average grade across annual/seasonal/ENSO for one variable."""
    thresh = _CMIP5_THRESHOLDS.get(var)
    if thresh is None:
        return 5
    g_ann  = _timescale_grade(pcors.get("annual",   float("nan")), thresh["annual"])
    g_seas = _timescale_grade(pcors.get("seasonal", float("nan")), thresh["seasonal"])
    g_enso = _timescale_grade(pcors.get("enso",     float("nan")), thresh["enso"])
    grades = [g for g in (g_ann, g_seas, g_enso) if g < 5]
    if not grades:
        return 5
    return int(round(sum(grades) / len(grades)))


def _realm_grade(var_grades: dict[str, int], realm_vars: list[str]) -> int:
    """Mean grade across variables in a realm."""
    grades = [var_grades[v] for v in realm_vars if v in var_grades and var_grades[v] < 5]
    if not grades:
        return 5
    return int(round(sum(grades) / len(grades)))


def _fmt_score(val: float) -> str:
    """Format score as 2-decimal string (e.g. 0.85) for display."""
    if not math.isfinite(val):
        return "N/A"
    return f"{val:.2f}"


def _score_color(val: float) -> str:
    """Return a CSS background color for a score cell (low=red gradient, high=green)."""
    if not math.isfinite(val):
        return "#f0f0f0"
    # Map 0.45-0.95 → red → yellow → green
    t = max(0.0, min(1.0, (val - 0.45) / 0.50))
    r = int(200 * (1 - t) + 50 * t)
    g = int(80  * (1 - t) + 180 * t)
    b = int(80  * (1 - t) + 80  * t)
    return f"rgb({r},{g},{b})"


def _grade_color(grade_idx: int) -> str:
    """CSS color for a grade cell."""
    colors = {0: "#2d862d", 1: "#6db33f", 2: "#cccc00", 3: "#e07730", 4: "#cc2222", 5: "#aaaaaa"}
    return colors.get(grade_idx, "#aaaaaa")


# ---------------------------------------------------------------------------
# Page HTML template
# ---------------------------------------------------------------------------

_CSS = """
body {font-family: Arial, sans-serif; font-size: 13px; margin: 20px;}
h1   {font-size: 18px; margin-bottom: 4px;}
.subtitle {font-size: 14px; color: #444; margin-bottom: 8px;}
.nav a   {margin-right: 10px; text-decoration: none; color: #0645ad; font-size: 13px;}
.nav a.active {font-weight: bold; color: #222;}
.colortable {margin: 12px 0; border: 1px solid #ccc;}
table.models {border-collapse: collapse; margin-top: 12px; font-size: 12px;}
table.models th {background: #dde; padding: 5px 8px; border: 1px solid #aaa; white-space: nowrap;}
table.models td {padding: 4px 8px; border: 1px solid #ccc; white-space: nowrap;}
table.models tr:nth-child(even) td {background: #f8f8f8;}
.score-cell {text-align: center; font-weight: bold; color: #fff;}
.grade-cell {text-align: center; font-weight: bold; color: #fff; font-size: 11px;}
.note {color: #666; font-size: 11px;}
"""

_NAV_KEYS = [
    ("index",          "Overall"),
    ("index_Energy",   "Energy"),
    ("index_Water",    "Water"),
    ("index_Dynamics", "Dynamics"),
    ("index_Annual",   "Annual"),
    ("index_Seasonal", "Seasonal"),
    ("index_ENSO",     "ENSO"),
]


def _page_html(
    table_rows_html: str,
    image_filename: str,
    page_key: str,
    archive_label: str,
    sort_label: str,
    created: str,
) -> str:
    nav_links = " | ".join(
        f'<a href="{k}.html" class="{"active" if k == page_key else ""}">{label}</a>'
        for k, label in _NAV_KEYS
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>CMAT {archive_label} — {sort_label}</title>
<style>{_CSS}</style>
</head>
<body>
<h1>CMAT 1.0 {archive_label} Repository</h1>
<p class="subtitle">
  Climate Model Assessment Tool v1 &mdash; {archive_label} Archive<br>
  Created: {created}
</p>
<div class="nav">{nav_links}</div>
<hr>
<div>
  <img class="colortable" src="{image_filename}"
       alt="Color table summary sorted by {sort_label}"
       style="max-width:100%; height:auto;">
</div>
<p class="note">
  *Scoring is based on the mean of pattern correlations for the annual mean,
  seasonal contrast, and ENSO teleconnections.
  Sorted by <strong>{sort_label}</strong> score.
  Grades (A-E) are relative to the CMIP5 multi-model distribution.
</p>
<table class="models">
  <thead>
    <tr>
      <th>Model Run</th>
      <th>Overall</th>
      <th>Energy</th>
      <th>Water</th>
      <th>Dynamics</th>
      <th>Grade (O/E/W/D)</th>
      <th>Annual</th>
      <th>Seasonal</th>
      <th>ENSO</th>
    </tr>
  </thead>
  <tbody>
{table_rows_html}
  </tbody>
</table>
</body>
</html>
"""


def _build_table_rows(model_order: list[str], scores_dict: dict, var_grades: dict, link_detail: bool = True) -> str:
    """Build HTML table rows for the given model ordering."""
    rows = []
    from config import REALM_VARS
    energy_vars   = REALM_VARS["energy"]
    water_vars    = REALM_VARS["water"]
    dynamics_vars = REALM_VARS["dynamics"]

    for m in model_order:
        sd  = scores_dict[m]
        s   = sd["scores"]
        osc = s.get("overall", float("nan"))
        esc = s.get("realm", {}).get("energy",   float("nan"))
        wsc = s.get("realm", {}).get("water",    float("nan"))
        dsc = s.get("realm", {}).get("dynamics", float("nan"))
        asc = s.get("timescale", {}).get("annual",   float("nan"))
        ssc = s.get("timescale", {}).get("seasonal", float("nan"))
        nsc = s.get("timescale", {}).get("enso",     float("nan"))

        # Grades
        vg = var_grades.get(m, {})
        ogr = _grade_scale_letter(_realm_grade(vg, energy_vars + water_vars + dynamics_vars))
        egr = _grade_scale_letter(_realm_grade(vg, energy_vars))
        wgr = _grade_scale_letter(_realm_grade(vg, water_vars))
        dgr = _grade_scale_letter(_realm_grade(vg, dynamics_vars))

        # Metadata
        meta = sd.get("metadata", {})
        run_label = meta.get("run_label") or m
        experiment = meta.get("experiment", "")
        member     = meta.get("member", "")
        subtitle   = " ".join(filter(None, [experiment, member]))

        model_link = f'<a href="{m}.html">{run_label}</a>' if link_detail else run_label

        # Delta scores (improvements vs benchmark)
        deltas = sd.get("delta_scores") or {}
        improvements = [f"+{v}: {d:+.3f}" for v, d in deltas.items() if d >  0.05]
        degradations  = [f"-{v}: {d:+.3f}" for v, d in deltas.items() if d < -0.05]
        delta_html = ""
        if improvements:
            delta_html += f'<span style="color:green">Improves: {", ".join(improvements)}</span> '
        if degradations:
            delta_html += f'<span style="color:red">Degrades: {", ".join(degradations)}</span>'

        def sc(val, grade_letter=None):
            bg = _score_color(val)
            text = _fmt_score(val)
            return f'<td class="score-cell" style="background:{bg}">{text}</td>'

        def gc(letter):
            idx = _GRADE_SCALE.index(letter) if letter in _GRADE_SCALE else 5
            bg = _grade_color(idx)
            return f'<td class="grade-cell" style="background:{bg}">{letter}</td>'

        rows.append(
            f"  <tr>"
            f'<td><strong>{model_link}</strong>'
            + (f'<br><span class="note">{subtitle}</span>' if subtitle else "")
            + (f'<br><span class="note">{delta_html}</span>' if delta_html else "")
            + "</td>"
            + sc(osc) + sc(esc) + sc(wsc) + sc(dsc)
            + f'<td class="grade-cell">{ogr} / {egr} / {wgr} / {dgr}</td>'
            + sc(asc) + sc(ssc) + sc(nsc)
            + "</tr>"
        )
    return "\n".join(rows)


def _grade_scale_letter(idx: int) -> str:
    return _GRADE_SCALE[idx] if 0 <= idx < len(_GRADE_SCALE) else "N/A"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_index_pages(
    scores_dict: dict,
    output_dir: Path,
    archive_label: str = "CMIP6",
    image_dir: Path | None = None,
    scores_base_dir: Path | None = None,
) -> list[Path]:
    """
    Write all HTML index pages for a CMAT repository.

    Parameters
    ----------
    scores_dict : dict
        {model_name: score_json_content} where score_json_content is the full
        dict from scores.json (keys: pattern_correlations, scores, metadata, ...).
    output_dir : Path
        Directory to write HTML files into.
    archive_label : str
        Label used in page titles (e.g. 'CMIP6').
    image_dir : Path or None
        Directory where colortable PNG files live.  Defaults to output_dir.
    scores_base_dir : Path or None
        Root directory of per-model score output (e.g. 'output/').  Used to
        locate bias_maps subdirectories to copy into the report.  If None,
        bias map thumbnails are omitted from per-model pages.

    Returns
    -------
    list of Path objects for every HTML file written.
    """
    import sys
    import os
    import shutil
    sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if image_dir is None:
        image_dir = output_dir

    created = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    # Pre-compute per-variable grades for every model
    var_grades: dict[str, dict[str, int]] = {}
    for m, sd in scores_dict.items():
        pcors = sd.get("pattern_correlations", {})
        var_grades[m] = {v: _variable_grade(v, pcors.get(v, {})) for v in pcors}

    # ---------------------------------------------------------------------------
    # Copy bias maps into report dir and generate per-model detail pages
    # ---------------------------------------------------------------------------
    bias_maps_copied: dict[str, str] = {}  # model_name -> rel path from output_dir
    for m in scores_dict:
        bias_src: Path | None = None
        if scores_base_dir is not None:
            candidate = Path(scores_base_dir) / m / "bias_maps"
            if candidate.is_dir():
                bias_src = candidate
        if bias_src is not None:
            dest_dir = output_dir / "bias_maps" / m
            dest_dir.mkdir(parents=True, exist_ok=True)
            for png in bias_src.glob("*.png"):
                shutil.copy2(png, dest_dir / png.name)
            bias_maps_copied[m] = f"bias_maps/{m}"

        bias_rel = bias_maps_copied.get(m)  # None if no maps
        generate_model_page(
            model_name=m,
            score_data=scores_dict[m],
            output_dir=output_dir,
            bias_maps_rel_dir=bias_rel,
            archive_label=archive_label,
        )

    written: list[Path] = []
    # Re-collect per-model pages (already written above; track them)
    for m in scores_dict:
        p = output_dir / f"{m}.html"
        if p.exists():
            written.append(p)

    # Sort configurations for the 7 aggregate index pages
    pages = [
        ("index",          "Overall",  "overall"),
        ("index_Energy",   "Energy",   "energy"),
        ("index_Water",    "Water",    "water"),
        ("index_Dynamics", "Dynamics", "dynamics"),
        ("index_Annual",   "Annual",   "annual"),
        ("index_Seasonal", "Seasonal", "seasonal"),
        ("index_ENSO",     "ENSO",     "enso"),
    ]

    for page_key, sort_label, sort_by in pages:
        # Sort models by the chosen score, descending (best at top of table)
        def _sort_key(m, _sb=sort_by):
            s = scores_dict[m]["scores"]
            if _sb == "overall":
                return s.get("overall", 0.0)
            if _sb in ("energy", "water", "dynamics"):
                return s.get("realm", {}).get(_sb, 0.0)
            return s.get("timescale", {}).get(_sb, 0.0)

        model_order = sorted(scores_dict.keys(), key=_sort_key, reverse=True)

        table_html = _build_table_rows(model_order, scores_dict, var_grades)

        # Image filename (relative link, image lives in image_dir)
        img_name = f"colortable_summary_{sort_by}.png"
        # If image_dir != output_dir compute relative path
        try:
            img_rel = Path(image_dir / img_name).relative_to(output_dir)
        except ValueError:
            img_rel = Path(image_dir / img_name)

        page_html = _page_html(
            table_rows_html=table_html,
            image_filename=str(img_rel),
            page_key=page_key,
            archive_label=archive_label,
            sort_label=sort_label,
            created=created,
        )

        out_file = output_dir / f"{page_key}.html"
        out_file.write_text(page_html, encoding="utf-8")
        written.append(out_file)

    return written


# ---------------------------------------------------------------------------
# Per-model detail page
# ---------------------------------------------------------------------------

_VAR_LABELS = {
    "rsnt":    "SWNET_TOA",  "rlut":    "LWNET_TOA", "swcftoa": "SW_CF",
    "lwcftoa": "LW_CF",      "fs":      "Fs",         "rtfs":    "RT-Fs",
    "pr":      "P",          "prw":     "PRW",         "hurs":    "RH_sfc",
    "hfls":    "LH",         "ep":      "E-P",
    "psl":     "SLP",        "sfcWind": "U_sfc",       "zg500":   "Z500",
    "wap500":  "W500",       "hur500":  "RH500",
}

_REALM_ORDER = [
    ("energy",   ["rsnt", "rlut", "swcftoa", "lwcftoa", "fs", "rtfs"]),
    ("water",    ["pr", "prw", "hurs", "hfls", "ep"]),
    ("dynamics", ["psl", "sfcWind", "zg500", "wap500", "hur500"]),
]

_REALM_CSS_COLORS = {
    "energy":   "#882222",
    "water":    "#224488",
    "dynamics": "#226622",
}


def generate_model_page(
    model_name: str,
    score_data: dict,
    output_dir: Path,
    bias_maps_rel_dir: str | None = None,
    archive_label: str = "CMIP6",
) -> Path:
    """
    Write a per-model HTML detail page listing per-variable pattern correlations
    and bias map thumbnails.

    Parameters
    ----------
    model_name : str
        Display name / run label for the model.
    score_data : dict
        Content of that model's scores.json.
    output_dir : Path
        Directory to write the HTML file (same as the report dir).
    bias_maps_rel_dir : str or None
        Path to the directory containing bias map PNGs, relative to output_dir.
        E.g. 'bias_maps/CESM2'. If None, no images are shown.
    archive_label : str
        Archive label for the page title.
    """
    output_dir = Path(output_dir)
    meta        = score_data.get("metadata", {})
    pcors       = score_data.get("pattern_correlations", {})
    scores      = score_data.get("scores", {})
    experiment  = meta.get("experiment", "")
    member      = meta.get("member", "")
    year_range  = meta.get("year_range", [])
    subtitle    = " ".join(filter(None, [experiment, member] +
                                  ([f"{year_range[0]}-{year_range[1]}"] if year_range else [])))

    nav_links = " | ".join(
        f'<a href="{k}.html">{label}</a>'
        for k, label in _NAV_KEYS
    )

    rows_html = []
    for realm, var_list in _REALM_ORDER:
        rcol = _REALM_CSS_COLORS[realm]
        rows_html.append(
            f'<tr><td colspan="6" style="background:{rcol};color:#fff;'
            f'font-weight:bold;padding:3px 6px">'
            f'{realm.upper()}</td></tr>'
        )
        for var in var_list:
            vp = pcors.get(var, {})
            ann  = vp.get("annual",   float("nan"))
            seas = vp.get("seasonal", float("nan"))
            enso = vp.get("enso",     float("nan"))
            vscore = scores.get("variable", {}).get(var, float("nan"))

            grade_idx = _variable_grade(var, vp)
            grade_letter = _grade_scale_letter(grade_idx)
            grade_bg = _grade_color(grade_idx)

            # Bias map thumbnail cell
            if bias_maps_rel_dir:
                img_file = f"{bias_maps_rel_dir}/{var}_annual_bias.png"
                img_cell = f'<td style="text-align:center"><a href="{img_file}" target="_blank"><img src="{img_file}" style="height:60px;max-width:160px;vertical-align:middle" alt="{var} bias map" onerror="this.style.display=\'none\'"></a></td>'
            else:
                img_cell = "<td>—</td>"

            def sc(val):
                bg   = _score_color(val)
                text = _fmt_score(val)
                return f'<td style="text-align:center;background:{bg};color:#fff;font-weight:bold">{text}</td>'

            label = _VAR_LABELS.get(var, var.upper())
            rows_html.append(
                f"  <tr>"
                f'<td style="font-weight:bold">{label}</td>'
                + sc(ann) + sc(seas) + sc(enso) + sc(vscore)
                + f'<td style="text-align:center;background:{grade_bg};color:#fff;font-weight:bold">{grade_letter}</td>'
                + img_cell
                + "</tr>"
            )

    created = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    realm_scores = scores.get("realm") or {}
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>CMAT {archive_label} — {model_name}</title>
<style>{_CSS}
table.detail th {{background:#dde;padding:5px 8px;border:1px solid #aaa;}}
table.detail td {{padding:4px 6px;border:1px solid #ccc;}}
</style>
</head>
<body>
<h1>CMAT 1.0 {archive_label} — {model_name}</h1>
<p class="subtitle">{subtitle}<br>Created: {created}</p>
<div class="nav"><a href="index.html">&laquo; Back to index</a> | {nav_links}</div>
<hr>
<p>
  Overall: <strong>{_fmt_score(scores.get('overall', float('nan')))}</strong> &nbsp;
  Energy: <strong>{_fmt_score(realm_scores.get('energy', float('nan')))}</strong> &nbsp;
  Water: <strong>{_fmt_score(realm_scores.get('water', float('nan')))}</strong> &nbsp;
  Dynamics: <strong>{_fmt_score(realm_scores.get('dynamics', float('nan')))}</strong>
</p>
<table class="detail" style="border-collapse:collapse;font-size:12px">
  <thead>
    <tr>
      <th>Variable</th>
      <th>Annual R</th>
      <th>Seasonal R</th>
      <th>ENSO R</th>
      <th>Score</th>
      <th>Grade</th>
      <th>Annual Bias Map</th>
    </tr>
  </thead>
  <tbody>
{''.join(rows_html)}
  </tbody>
</table>
</body>
</html>
"""
    out_path = output_dir / f"{model_name}.html"
    out_path.write_text(html, encoding="utf-8")
    return out_path

