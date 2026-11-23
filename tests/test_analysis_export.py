"""Print or save as PDF (#69): the export bar on the three analysis pages and the print layout."""

from pathlib import Path

from test_analysis import _synthetic
from test_auth import make_admin, site  # noqa: F401 (fixture)

CSS = Path(__file__).resolve().parents[1] / "app" / "static" / "style.css"


def test_export_bar_and_print_notes(site):  # noqa: F811
    admin = make_admin(site)
    analysis = admin.app.state.analysis
    one = analysis.save(_synthetic())
    two = analysis.save(_synthetic(round_key="r2", shift=10))
    page = admin.get(f"/analysis/reports/{one.id}").text
    assert '<p class="export-bar js-only" data-filename="' in page and "Print or save as PDF" in page
    assert '<h2 id="notes" class="no-print">' in page and "notes-print" not in page   # no notes: not printed
    admin.post(f"/analysis/reports/{one.id}", data={"label": "", "notes": "Practice <Server> hardening.",
                                                   "round_key": "r1", "status": "final"})
    page = admin.get(f"/analysis/reports/{one.id}").text
    assert '<div class="print-only notes-print">Practice &lt;Server&gt; hardening.</div>' in page
    season = admin.get("/analysis/seasons/19?division=Middle%20School").text
    assert 'data-filename="CP-19 season - Middle School"' in season
    compare = admin.get(f"/analysis/compare?a={two.id}&b={one.id}").text
    assert 'data-filename="' in compare and " vs " in compare.split('data-filename="')[1].split('"')[0]


def test_print_layout_is_light_and_hides_controls():
    css = CSS.read_text(encoding="utf-8")
    assert "@media (prefers-color-scheme: dark)" not in css          # dark mode is screen-only
    printing = css.split("@media print {")[1]
    for sel in ("main form", ".report-tools", ".export-bar", ".zoom-controls", "details.choices", ".topbar .nav"):
        assert sel in printing
