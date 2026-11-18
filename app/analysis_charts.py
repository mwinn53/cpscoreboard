"""Server-rendered SVG charts for the Analysis tab (no chart library), after the R report's plots.

Every chart follows the same rules as the team charts (app/charts.py): thin marks,
a recessive grid, light and dark through CSS variables, and a table on the page
with the same numbers. Highlighting is consistent across charts:

* **our teams**: categorical slot 2 (orange), drawn last and a little larger;
* **district teams**: slot 1 (blue), filled;
* **other teams in the state**: slot 1, hollow;
* **everyone else**: neutral gray.

Marks carry a ``data-tip`` that static/analysis_charts.js shows on hover or tap; the
progress chart uses the crosshair from static/charts.js instead.

Interactive charts (#65), all in static/analysis_charts.js over this SVG:

* team marks carry ``data-team``, so a team picked in any chart, table or the search
  box is highlighted in every chart;
* legend entries with a ``toggle`` (a CSS selector inside the card) show or hide a
  series; team-group entries (``group``) show or hide that group's dots page-wide;
* charts in ``ZOOMABLE`` carry ``data-zoom`` and ``data-x`` (the x domain and its SVG
  range): a brushed range is re-rendered by the server (``zoomed_chart``) with its own
  ticks and bins.
"""

from __future__ import annotations

import json
import math
import zlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from html import escape

from .analysis import Describe, RoundReport, describe
from .analysis_store import DISTRICT, EMS, TeamRow
from .charts import _nice_step, _y_ticks

W = 720
LEFT, RIGHT, TOP, BOTTOM = 48, 16, 26, 34
OVER = 120                        # time axes run 2 hours past the limit; longer (bad rows in old files) piles into the last bin
HALF = 480                        # charts shown in half-width cards


@dataclass(frozen=True)
class Item:
    label: str
    cls: str      # legend class: ours / district / state / other / band / median / s1…
    shape: str = "dot"
    toggle: str = ""   # CSS selector, inside the chart card, of the marks this entry shows or hides
    group: str = ""    # a team group whose dots this entry shows or hides on the whole page


def legend(items: Sequence[Item]) -> str:
    out = []
    for i in items:
        key = f'<span class="key {escape(i.shape)} {escape(i.cls)}"></span>{escape(i.label)}'
        if i.toggle:
            out.append(f'<li><button type="button" class="legend-toggle" data-toggle="{escape(i.toggle)}" '
                       f'aria-pressed="true">{key}</button></li>')
        elif i.group:
            out.append(f'<li><button type="button" class="legend-toggle" data-group="{escape(i.group)}" '
                       f'aria-pressed="true">{key}</button></li>')
        else:
            out.append(f"<li>{key}</li>")
    return f'<ul class="legend">{"".join(out)}</ul>'


TEAM_LEGEND = [Item("Our teams", "ours", group="ours"), Item("District teams", "district", group="district"),
               Item("Other {state} teams", "state", group="state"), Item("Everyone else", "other", group="other")]


def team_legend(state: str, *, others: bool = True, toggles: bool = True) -> str:
    """The team groups; with ``toggles``, each entry shows or hides that group's dots (not bars) on the page."""
    items = [Item(i.label.replace("{state}", state), i.cls, group=i.group if toggles else "") for i in TEAM_LEGEND]
    return legend(items if others else items[:3])


class Scale:
    def __init__(self, d0: float, d1: float, r0: float, r1: float):
        self.d0, self.d1, self.r0, self.r1 = d0, d1 if d1 != d0 else d0 + 1, r0, r1

    def __call__(self, v: float) -> float:
        return self.r0 + (v - self.d0) / (self.d1 - self.d0) * (self.r1 - self.r0)


def ticks(lo: float, hi: float) -> list[float]:
    return _y_ticks(lo, hi, False)


def num(v: float | None) -> str:
    if v is None:
        return "–"
    return f"{v:.0f}" if abs(v - round(v)) < 0.05 else f"{v:.1f}"


def pct(v: float | None) -> str:
    return "–" if v is None else f"{100 * v:.0f}%"


def jitter(key: str) -> float:
    """A stable offset in [-1, 1] per team, so dots don't move between page loads."""
    return (zlib.crc32(key.encode()) % 10007) / 10007 * 2 - 1


def team_class(t: TeamRow, state: str) -> str:
    if t.grp == EMS:
        return "ours"
    if t.grp == DISTRICT:
        return "district"
    return "state" if t.location == state else "other"


def team_tip(t: TeamRow, extra: str = "") -> str:
    name = f" {t.name}" if t.name else ""
    place = f" · {t.location} {t.place_state_division}" if t.place_state_division else f" · {t.location}"
    return f"{t.team_number}{name}{place} · {num(t.score)}{extra}"


_ORDER = {"other": 0, "state": 1, "district": 2, "ours": 3}


def _svg(width: int, height: int, label: str, body: list[str], attrs: str = "") -> str:
    return (f'<div class="chart-wrap" data-tips{attrs}><svg class="chart" viewBox="0 0 {width} {height}" role="img" '
            f'aria-label="{escape(label)}" preserveAspectRatio="xMidYMid meet">{"".join(body)}</svg>'
            f'<div class="chart-tip" hidden></div></div>')


def _y_axis(parts: list[str], tick_values: list[float], y: Scale, x0: float, x1: float,
            fmt: Callable[[float], str] = num, title: str = "") -> None:
    for v in tick_values:
        yy = y(v)
        parts.append(f'<line class="grid" x1="{x0}" x2="{x1}" y1="{yy:.1f}" y2="{yy:.1f}"/>')
        parts.append(f'<text class="tick" x="{x0 - 6}" y="{yy + 4:.1f}" text-anchor="end">{escape(fmt(v))}</text>')
    if title:
        parts.append(f'<text class="axis-title" x="4" y="12">{escape(title)}</text>')


def _x_ticks(parts: list[str], tick_values: list[float], x: Scale, y0: float,
             fmt: Callable[[float], str] = num, title: str = "", width: int = W) -> None:
    for v in tick_values:
        xx = x(v)
        parts.append(f'<line class="axis" x1="{xx:.1f}" x2="{xx:.1f}" y1="{y0}" y2="{y0 + 4}"/>')
        parts.append(f'<text class="tick" x="{xx:.1f}" y="{y0 + 16}" text-anchor="middle">{escape(fmt(v))}</text>')
    if title:
        parts.append(f'<text class="axis-title" x="{width - RIGHT}" y="{y0 + 30}" text-anchor="end">'
                     f'{escape(title)}</text>')


def _ref_h(parts: list[str], value: float, y: Scale, x0: float, x1: float, text: str, left: bool = False) -> None:
    yy = y(value)
    parts.append(f'<line class="ref" x1="{x0}" x2="{x1}" y1="{yy:.1f}" y2="{yy:.1f}"/>')
    if left:
        parts.append(f'<text class="ref-label" x="{x0 + 4}" y="{yy + 14:.1f}">{escape(text)}</text>')
    else:
        parts.append(f'<text class="ref-label" x="{x1 - 2}" y="{yy - 4:.1f}" text-anchor="end">{escape(text)}</text>')


def _ref_v(parts: list[str], value: float, x: Scale, y0: float, y1: float, text: str) -> None:
    xx = x(value)
    parts.append(f'<line class="ref" x1="{xx:.1f}" x2="{xx:.1f}" y1="{y0}" y2="{y1}"/>')
    parts.append(f'<text class="ref-label" x="{xx + 4:.1f}" y="{y0 + 10}">{escape(text)}</text>')


def _vbox(parts: list[str], cx: float, half: float, d: Describe, values, y: Scale, cls: str = "") -> None:
    """A vertical box plot: box = middle half, line = median, whiskers to 1.5 × IQR."""
    if d.n == 0:
        return
    lo, hi = d.whiskers(values)
    parts.append(f'<line class="whisker" x1="{cx:.1f}" x2="{cx:.1f}" y1="{y(hi):.1f}" y2="{y(d.q3):.1f}"/>')
    parts.append(f'<line class="whisker" x1="{cx:.1f}" x2="{cx:.1f}" y1="{y(d.q1):.1f}" y2="{y(lo):.1f}"/>')
    top, bottom = y(d.q3), y(d.q1)
    parts.append(f'<rect class="box {cls}" x="{cx - half:.1f}" y="{top:.1f}" width="{2 * half:.1f}" '
                 f'height="{max(bottom - top, 1):.1f}" rx="2"/>')
    parts.append(f'<line class="med" x1="{cx - half:.1f}" x2="{cx + half:.1f}" y1="{y(d.median):.1f}" '
                 f'y2="{y(d.median):.1f}"/>')
    for v in values:  # outliers beyond the whiskers
        if v is not None and (v > hi or v < lo):
            parts.append(f'<circle class="outlier" cx="{cx:.1f}" cy="{y(v):.1f}" r="2"/>')


def _hbox(parts: list[str], cy: float, half: float, d: Describe, values, x: Scale, cls: str = "") -> None:
    if d.n == 0:
        return
    lo, hi = d.whiskers(values)
    parts.append(f'<line class="whisker" x1="{x(lo):.1f}" x2="{x(d.q1):.1f}" y1="{cy:.1f}" y2="{cy:.1f}"/>')
    parts.append(f'<line class="whisker" x1="{x(d.q3):.1f}" x2="{x(hi):.1f}" y1="{cy:.1f}" y2="{cy:.1f}"/>')
    parts.append(f'<rect class="box {cls}" x="{x(d.q1):.1f}" y="{cy - half:.1f}" '
                 f'width="{max(x(d.q3) - x(d.q1), 1):.1f}" height="{2 * half:.1f}" rx="2"/>')
    parts.append(f'<line class="med" x1="{x(d.median):.1f}" x2="{x(d.median):.1f}" y1="{cy - half:.1f}" '
                 f'y2="{cy + half:.1f}"/>')


def _dot(parts: list[str], cx: float, cy: float, cls: str, tip: str | None, team: str = "") -> None:
    r = 5 if cls == "ours" else 4 if "big" in cls else 3.5 if cls in ("district", "state") else 2.5
    t = f' data-tip="{escape(tip)}"' if tip else ""
    t += f' data-team="{escape(team)}"' if team else ""
    parts.append(f'<circle class="dot {cls}" cx="{cx:.1f}" cy="{cy:.1f}" r="{r}"{t}/>')


def _bar(parts: list[str], x0: float, x1: float, y0: float, y1: float, cls: str, top: bool) -> None:
    """A bar segment; the top segment gets rounded data-end corners."""
    w, h = max(x1 - x0, 1), y0 - y1
    if h <= 0:
        return
    if top and h > 3:
        r = min(3, w / 2)
        parts.append(f'<path class="bar {cls}" d="M{x0:.1f},{y0:.1f}V{y1 + r:.1f}Q{x0:.1f},{y1:.1f} {x0 + r:.1f},'
                     f'{y1:.1f}H{x1 - r:.1f}Q{x1:.1f},{y1:.1f} {x1:.1f},{y1 + r:.1f}V{y0:.1f}Z"/>')
    else:
        parts.append(f'<rect class="bar {cls}" x="{x0:.1f}" y="{y1:.1f}" width="{w:.1f}" height="{h:.1f}"/>')


# --- round report charts ---

def state_boxes(r: RoundReport, width: int = W) -> str:
    """Score by state: one box per state, highest median first; ours highlighted; national median dashed."""
    d = r.density
    if not d:
        return ""
    states = d.states
    many = len(states) > 18
    h = 280 if many else 240
    bottom = 46 if many else BOTTOM
    lo = min(min(s.values) for s in states)
    hi = max(max(s.values) for s in states)
    tv = ticks(min(0, lo), hi)
    y = Scale(tv[0], tv[-1], h - bottom, TOP)
    step = (width - LEFT - RIGHT) / len(states)
    parts: list[str] = []
    _y_axis(parts, tv, y, LEFT, width - RIGHT)
    for i, s in enumerate(states):
        cx = LEFT + step * (i + 0.5)
        hl = "hl" if s.state == r.state else ""
        _vbox(parts, cx, max(min(step * 0.32, 14), 2), s.score, s.values, y, hl + (" few" if s.n < 5 else ""))
        label = escape(s.state)
        if many:
            parts.append(f'<text class="tick {hl}" transform="translate({cx + 3:.1f},{h - bottom + 8}) rotate(-60)" '
                         f'text-anchor="end">{label}</text>')
        else:
            parts.append(f'<text class="tick {hl}" x="{cx:.1f}" y="{h - bottom + 16}" text-anchor="middle">'
                         f'{label}</text>')
        tip = (f"{s.state} · {s.n} team{'s' if s.n != 1 else ''} · median {num(s.score.median)}"
               + (f" · middle half {num(s.score.q1)}–{num(s.score.q3)}" if s.n > 1 else "")
               + (" · few teams: an unreliable median" if s.n < 5 else ""))
        parts.append(f'<rect class="hit" x="{LEFT + step * i:.1f}" y="{TOP}" width="{step:.1f}" '
                     f'height="{h - bottom - TOP}" data-tip="{escape(tip)}"/>')
    parts.append(f'<line class="axis" x1="{LEFT}" x2="{width - RIGHT}" y1="{h - bottom}" y2="{h - bottom}"/>')
    if r.score["national"].median is not None:
        _ref_h(parts, r.score["national"].median, y, LEFT, width - RIGHT,
               f"national median {num(r.score['national'].median)}")
    return _svg(width, h, f"Score by state, {len(states)} states, highest median first", parts)


def group_strips(r: RoundReport, width: int = W) -> str:
    """Where teams landed: the nation and the state as box plots with every team as a dot."""
    rows = [("Nationally", r.teams), (r.state, [t for t in r.teams if t.location == r.state])]
    rows = [(name, teams) for name, teams in rows if teams]
    if not rows:
        return ""
    left, row_h = 92, 64
    h = TOP + row_h * len(rows) + BOTTOM
    hi = max(t.score for t in r.teams)
    tv = ticks(min(0, min(t.score for t in r.teams)), hi)
    x = Scale(tv[0], tv[-1], left, width - RIGHT)
    parts: list[str] = []
    for v in tv:
        parts.append(f'<line class="grid" x1="{x(v):.1f}" x2="{x(v):.1f}" y1="{TOP}" y2="{h - BOTTOM}"/>')
    for k, (name, teams) in enumerate(rows):
        cy = TOP + row_h * (k + 0.5)
        values = [t.score for t in teams]
        d = describe(values)
        _hbox(parts, cy, 11, d, values, x, "hl" if k else "")
        parts.append(f'<text class="row-label" x="{left - 10}" y="{cy + 4:.1f}" text-anchor="end">'
                     f'{escape(name)}</text>')
        parts.append(f'<text class="tick" x="{left - 10}" y="{cy + 18:.1f}" text-anchor="end">'
                     f'{d.n} teams</text>')
        for t in sorted(teams, key=lambda t: _ORDER[team_class(t, r.state)]):
            cls = team_class(t, r.state)
            if k == 0 and cls in ("state",):
                cls = "other"
            _dot(parts, x(t.score), cy + jitter(t.team_number) * 22, cls,
                 team_tip(t) if cls != "other" or k else None, t.team_number)
    parts.append(f'<line class="axis" x1="{left}" x2="{width - RIGHT}" y1="{h - BOTTOM}" y2="{h - BOTTOM}"/>')
    _x_ticks(parts, tv, x, h - BOTTOM, title="score", width=width)
    return _svg(width, h, f"Scores nationally and in {r.state}, every team a dot", parts)


def histogram(r: RoundReport, value: Callable[[TeamRow], float | None], *, bin_size: float, label: str,
              x_title: str, refs: Sequence[tuple[float, str]] = (), fmt: Callable[[float], str] = num,
              width: int = W, height: int = 220, start: float | None = None,
              x_tick_values: Sequence[float] | None = None, stop: float | None = None, zoom: str = "") -> str:
    """Counts per bin, stacked: our teams, then the state's, then everyone else. With ``stop``, only values from
    ``start`` to ``stop`` (a zoomed range)."""
    vals = [(value(t), team_class(t, r.state)) for t in r.teams]
    vals = [(v, c) for v, c in vals if v is not None]
    if stop is not None:
        vals = [(v, c) for v, c in vals if (start is None or v >= start) and v <= stop]
    if not vals:
        return ""
    lo = start if start is not None else (min(v for v, _ in vals) // bin_size) * bin_size
    if stop is not None:
        n_bins = max(int(math.ceil((stop - lo) / bin_size - 1e-9)), 1)
    else:
        n_bins = int((max(v for v, _ in vals) - lo) // bin_size) + 1
    counts = [{"ours": 0, "state": 0, "other": 0} for _ in range(n_bins)]
    for v, c in vals:
        b = min(int((v - lo) // bin_size), n_bins - 1)
        counts[b]["ours" if c == "ours" else "state" if c in ("state", "district") else "other"] += 1
    top_count = max(sum(c.values()) for c in counts)
    yv = ticks(0, top_count)
    y = Scale(0, yv[-1], height - BOTTOM, TOP)
    x = Scale(lo, lo + n_bins * bin_size, LEFT, width - RIGHT)
    parts: list[str] = []
    _y_axis(parts, [v for v in yv if v == int(v)], y, LEFT, width - RIGHT, title="teams")
    for b, c in enumerate(counts):
        x0, x1 = x(lo + b * bin_size) + 1, x(lo + (b + 1) * bin_size) - 1
        base = 0
        segs = [(k, c[k]) for k in ("other", "state", "ours") if c[k]]
        for i, (k, n) in enumerate(segs):
            _bar(parts, x0, x1, y(base) - (1 if base else 0), y(base + n), k, i == len(segs) - 1)
            base += n
        if base:
            tip = (f"{fmt(lo + b * bin_size)}–{fmt(lo + (b + 1) * bin_size)}: {base} teams"
                   + (f" ({c['state']} {r.state}" + (f", {c['ours']} ours" if c["ours"] else "") + ")"
                      if c["state"] or c["ours"] else ""))
            parts.append(f'<rect class="hit" x="{x0 - 1:.1f}" y="{TOP}" width="{x1 - x0 + 2:.1f}" '
                         f'height="{height - BOTTOM - TOP}" data-tip="{escape(tip)}"/>')
    parts.append(f'<line class="axis" x1="{LEFT}" x2="{width - RIGHT}" y1="{height - BOTTOM}" '
                 f'y2="{height - BOTTOM}"/>')
    xt = [v for v in (x_tick_values or ticks(lo, lo + n_bins * bin_size)) if lo <= v <= lo + n_bins * bin_size]
    _x_ticks(parts, xt, x, height - BOTTOM, fmt, x_title, width)
    for v, text in refs:
        if lo <= v <= lo + n_bins * bin_size:
            _ref_v(parts, v, x, TOP, height - BOTTOM, text)
    attrs = _zoom_attrs(zoom, lo, lo + n_bins * bin_size, LEFT, width - RIGHT, stop is not None)
    return _svg(width, height, label, parts, attrs)


def _zoom_attrs(name: str, d0: float, d1: float, r0: float, r1: float, zoomed: bool) -> str:
    """Marks a zoomable chart: its name, and its x domain against the SVG range (for the brush)."""
    if not name:
        return ""
    return (f' data-zoom="{escape(name)}" data-x="{d0:g},{d1:g},{r0:.1f},{r1:.1f}"'
            + (" data-zoomed" if zoomed else ""))


def heatmap(r: RoundReport, width: int = W, height: int = 260) -> str:
    """Score against play time: shaded cells count teams (15 minutes × a score band); ours as dots."""
    cap = r.limit + OVER
    pts = [(min(t.play_time / 60, cap - 1), t.score, t) for t in r.teams if t.play_time]
    if len(pts) < 5:
        return ""
    xmax = cap
    sv = ticks(min(0, min(p[1] for p in pts)), max(p[1] for p in pts))
    ybin = (sv[1] - sv[0]) / 4 if len(sv) > 1 else 10
    xbin = 15
    cells: dict[tuple[int, int], int] = {}
    for m, s, _ in pts:
        key = (int(m // xbin), int((s - sv[0]) // ybin))
        cells[key] = cells.get(key, 0) + 1
    most = max(cells.values())
    x = Scale(0, xmax, LEFT, width - RIGHT)
    y = Scale(sv[0], sv[-1], height - BOTTOM, TOP)
    parts: list[str] = []
    _y_axis(parts, sv, y, LEFT, width - RIGHT, title="score")
    for (i, j), n in cells.items():
        x0, x1 = x(i * xbin), x((i + 1) * xbin)
        y1, y0 = y(sv[0] + (j + 1) * ybin), y(sv[0] + j * ybin)
        tip = f"{i * xbin}–{(i + 1) * xbin} min, score {num(sv[0] + j * ybin)}–{num(sv[0] + (j + 1) * ybin)}: {n} teams"
        parts.append(f'<rect class="cell" x="{x0 + 0.5:.1f}" y="{y1 + 0.5:.1f}" width="{x1 - x0 - 1:.1f}" '
                     f'height="{max(y0 - y1 - 1, 1):.1f}" style="fill-opacity:{0.12 + 0.88 * n / most:.2f}" '
                     f'data-tip="{escape(tip)}"/>')
    for m, s, t in pts:
        if t.grp == EMS:
            _dot(parts, x(m), y(s), "ours", team_tip(t, f" · {m:.0f} min"), t.team_number)
    parts.append(f'<line class="axis" x1="{LEFT}" x2="{width - RIGHT}" y1="{height - BOTTOM}" '
                 f'y2="{height - BOTTOM}"/>')
    _x_ticks(parts, list(range(0, int(xmax) + 1, 60)), x, height - BOTTOM, lambda v: f"{v / 60:.0f} h",
             "play time", width)
    _ref_v(parts, r.limit, x, TOP, height - BOTTOM, f"{r.limit // 60}-hour limit")
    return _svg(width, height, "Score against play time: teams per 15 minutes and score band", parts)


def density_scatter(r: RoundReport, width: int = W, height: int = 260) -> str:
    """Teams per state against the state's median score."""
    d = r.density
    if not d:
        return ""
    xv = ticks(0, max(s.n for s in d.states))
    yv = ticks(min(0, min(s.score.median for s in d.states)), max(s.score.median for s in d.states))
    x = Scale(0, xv[-1], LEFT, width - RIGHT)
    y = Scale(yv[0], yv[-1], height - BOTTOM, TOP)
    parts: list[str] = []
    _y_axis(parts, yv, y, LEFT, width - RIGHT, title="median score")
    biggest = max(d.states, key=lambda s: s.n).state
    best = d.states[0].state
    labels = []
    for s in sorted(d.states, key=lambda s: s.state == r.state):
        cls = "district" if s.state == r.state else "other big"
        tip = f"{s.state} · {s.n} teams · median {num(s.score.median)}"
        _dot(parts, x(s.n), y(s.score.median), cls, tip)
        if s.state in (r.state, biggest, best):
            labels.append(s)
    for s in labels:
        parts.append(f'<text class="point-label" x="{x(s.n) + 7:.1f}" y="{y(s.score.median) - 6:.1f}">'
                     f'{escape(s.state)} ({s.n})</text>')
    if r.score["national"].median is not None:
        _ref_h(parts, r.score["national"].median, y, LEFT, width - RIGHT,
               f"national median {num(r.score['national'].median)}")
    parts.append(f'<line class="axis" x1="{LEFT}" x2="{width - RIGHT}" y1="{height - BOTTOM}" '
                 f'y2="{height - BOTTOM}"/>')
    _x_ticks(parts, xv, x, height - BOTTOM, title="teams in the state", width=width)
    return _svg(width, height, "Teams per state against the state's median score", parts)


def column_boxes(r: RoundReport, columns: Sequence[tuple[str, list[tuple[TeamRow, float]]]], *, label: str,
                 y_title: str, fmt: Callable[[float], str] = num, y_max: float | None = None,
                 tip_fmt: Callable[[float], str] | None = None, width: int = W, height: int = 260) -> str:
    """A box per column with the state's and our teams as dots (scores by images attempted; completion)."""
    columns = [(name, rows) for name, rows in columns if rows]
    if not columns:
        return ""
    allv = [v for _, rows in columns for _, v in rows]
    yv = ticks(min(0, min(allv)), y_max if y_max is not None else max(allv))
    y = Scale(yv[0], yv[-1], height - BOTTOM, TOP)
    step = (width - LEFT - RIGHT) / len(columns)
    parts: list[str] = []
    _y_axis(parts, yv, y, LEFT, width - RIGHT, fmt, y_title)
    for i, (name, rows) in enumerate(columns):
        cx = LEFT + step * (i + 0.5)
        values = [v for _, v in rows]
        d = describe(values)
        _vbox(parts, cx, min(step * 0.22, 40), d, values, y)
        parts.append(f'<text class="tick" x="{cx:.1f}" y="{height - BOTTOM + 16}" text-anchor="middle">'
                     f'{escape(name)}</text>')
        parts.append(f'<text class="tick" x="{cx:.1f}" y="{height - BOTTOM + 29}" text-anchor="middle">'
                     f'{d.n} teams</text>')
        tip = f"{name} · {d.n} teams · median {fmt(d.median)}" + (
            f" · middle half {fmt(d.q1)}–{fmt(d.q3)}" if d.n > 1 else "")
        parts.append(f'<rect class="hit" x="{LEFT + step * i:.1f}" y="{TOP}" width="{step:.1f}" '
                     f'height="{height - BOTTOM - TOP}" data-tip="{escape(tip)}"/>')
        spread = min(step * 0.3, 60)
        for t, v in sorted(rows, key=lambda tv: _ORDER[team_class(tv[0], r.state)]):
            cls = team_class(t, r.state)
            if cls == "other":
                continue
            _dot(parts, cx + jitter(t.team_number + name) * spread, y(v), cls,
                 team_tip(t, f" · {name} {(tip_fmt or fmt)(v)}"), t.team_number)
    parts.append(f'<line class="axis" x1="{LEFT}" x2="{width - RIGHT}" y1="{height - BOTTOM}" '
                 f'y2="{height - BOTTOM}"/>')
    return _svg(width, height, label, parts)


def attempts_boxes(r: RoundReport, width: int = W) -> str:
    if not r.attempts or len(r.attempts.by_count) < 2:
        return ""
    cols: dict[int, list] = {}
    for t in r.teams:
        cols.setdefault(r.images_attempted(t), []).append((t, t.score))
    return column_boxes(r, [(f"{k} image{'s' if k != 1 else ''}", cols[k]) for k in sorted(cols)],
                        label="Score by number of images attempted", y_title="score", width=width)


def completion_boxes(r: RoundReport, width: int = W) -> str:
    cols = []
    for img in r.images:
        rows = [(t, r.completion(t.team_number, img.name)) for t in r.teams
                if img.name in r.by_team.get(t.team_number, {})]
        cols.append((img.name, [(t, c) for t, c in rows if c is not None]))
    return column_boxes(r, cols, label="Completion per image (found ÷ items)", y_title="completion",
                        fmt=lambda v: f"{100 * v:.0f}%", y_max=1.0, width=width)


def finds_bars(r: RoundReport, image: str, width: int = 360) -> str:
    """How many teams found each number of items on one image."""
    total = r.totals.get(image)
    if not total:
        return ""

    def found(t: TeamRow) -> float | None:
        row = r.by_team.get(t.team_number, {}).get(image)
        return row.found if row and row.found is not None else None
    return histogram(r, found, bin_size=1, label=f"Items found on {image}", x_title="items found",
                     width=width, height=190, start=0)


def _clock(v: float) -> str:
    v = int(round(v))
    return f"{v // 60} h" if v % 60 == 0 else f"{v // 60}:{v % 60:02d}"


def progress_chart(r: RoundReport, width: int = W, height: int = 260,
                   window: tuple[float, float] | None = None) -> str:
    """The field's (and the top quarter's) median and middle half by minutes since each team's start, with our
    teams' lines; ``window`` (minutes) zooms in."""
    p = r.progress
    if not p:
        return ""
    pc = r.pace
    lo, hi = window or (0, p.limit)
    ks = [k for k, m in enumerate(p.minutes) if lo <= m <= hi]
    if len(ks) < 2:
        return ""

    def pick(seq):
        return [seq[k] for k in ks]
    mins, q1, med, q3 = pick(p.minutes), pick(p.q1), pick(p.median), pick(p.q3)
    ours = [(team, pick(series)) for team, series in p.ours[:7]]
    top = (pick(pc.q1), pick(pc.median), pick(pc.q3)) if pc else None
    vals = [v for v in q3 if v is not None] + [v for _, s in ours for v in s]
    if top:
        vals += [v for v in top[2] if v is not None]
    yv = ticks(0, max(vals) if vals else 1)
    first, end = mins[0], mins[-1]
    x = Scale(first, end, LEFT, width - RIGHT - 70)
    y = Scale(0, yv[-1], height - BOTTOM, TOP)
    parts: list[str] = []
    _y_axis(parts, yv, y, LEFT, width - RIGHT - 70, title="score")

    def area(lows, highs, cls):
        band = [(m, a, b) for m, a, b in zip(mins, lows, highs) if a is not None]
        if band:
            d = "M" + " L".join(f"{x(m):.1f},{y(b):.1f}" for m, _, b in band)
            d += " L" + " L".join(f"{x(m):.1f},{y(a):.1f}" for m, a, _ in reversed(band)) + " Z"
            parts.append(f'<path class="{cls}" d="{d}"/>')

    def line(values, cls, extra=""):
        pts = [(m, v) for m, v in zip(mins, values) if v is not None]
        if pts:
            parts.append(f'<path class="{cls}"{extra} d="M' + " L".join(f"{x(m):.1f},{y(v):.1f}" for m, v in pts)
                         + '"/>')
    area(q1, q3, "band")
    line(med, "median-line")
    if top:
        area(top[0], top[2], "band top")
        line(top[1], "top-line")
    ends = []
    for i, (team, series) in enumerate(ours, start=2):
        slot = f"s{i}"
        line(series, f"series {slot}", f' data-team="{escape(team)}"')
        ends.append([y(series[-1]), slot, team, series[-1]])
    ends.sort()
    for k in range(1, len(ends)):
        ends[k][0] = max(ends[k][0], ends[k - 1][0] + 13)
    for ly, slot, team, v in ends:
        parts.append(f'<circle class="end {slot}" cx="{x(end):.1f}" cy="{y(v):.1f}" r="4" '
                     f'data-team="{escape(team)}"/>')
        parts.append(f'<text class="end-label {slot}" x="{x(end) + 8:.1f}" y="{ly + 4:.1f}" '
                     f'data-team="{escape(team)}">{escape(team)}</text>')
    parts.append(f'<line class="axis" x1="{LEFT}" x2="{x(end):.1f}" y1="{height - BOTTOM}" '
                 f'y2="{height - BOTTOM}"/>')
    span = end - first
    step = 60 if span > 240 else 30 if span > 90 else 15 if span > 30 else 5
    _x_ticks(parts, list(range(int(math.ceil(first / step)) * step, int(end) + 1, step)), x, height - BOTTOM,
             _clock, "", width)
    hover = []
    for k, m in enumerate(mins):
        bits = [f"median {num(med[k])} (middle half {num(q1[k])}–{num(q3[k])})"]
        if top:
            bits.append(f"top quarter {num(top[1][k])} ({num(top[0][k])}–{num(top[2][k])})")
        bits += [f"{team} {num(s[k])}" for team, s in ours]
        hover.append([round(x(m), 1), None, f"{m // 60}:{m % 60:02d} · " + " · ".join(bits)])
    svg = (f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" aria-label="Score by time since each '
           f'team started: the field and our teams" preserveAspectRatio="xMidYMid meet">{"".join(parts)}</svg>')
    zoom = _zoom_attrs("progress", first, end, LEFT, x(end), window is not None)
    return (f'<div class="chart-wrap" data-points="{escape(json.dumps(hover))}" '
            f'data-plot="{LEFT},{x(end):.1f},{TOP},{height - BOTTOM},{width},{height}"{zoom}>{svg}'
            f'<div class="chart-tip" hidden></div></div>')


def progress_legend(r: RoundReport) -> str:
    if not r.progress:
        return ""
    items = [Item("Field median", "median", "line", ".median-line"),
             Item("Field middle half", "band", "area", ".band:not(.top)")]
    if r.pace:
        items += [Item("Top quarter median", "top", "line", ".top-line"),
                  Item("Top quarter middle half", "top-band", "area", ".band.top")]
    items += [Item(team, f"s{i}", "line", f".series.s{i}, .end.s{i}, .end-label.s{i}")
              for i, (team, _) in enumerate(r.progress.ours[:7], start=2)]
    return legend(items)


def advance_chart(r: RoundReport, width: int = W) -> str:
    """The projected State Round points each of our teams needs (median and likely range), per target, with
    the team's own projected score. Marked ``data-projection`` so interactive charts (#65) can toggle it."""
    a = r.advance
    if not a or a.stage != "projection" or not a.projections:
        return ""
    rows = [(p, n, slot) for p in a.projections for n, slot in ((p.semis, "s1"), (p.award, "s3")) if n]
    hi = max([n.hi for _, n, _ in rows] + [p.expected for p in a.projections] + [1.0])
    xv = ticks(0, hi)
    left, row = 110, 22
    height = TOP + row * len(rows) + 8 * len(a.projections) + BOTTOM
    x = Scale(0, xv[-1], left, width - RIGHT)
    parts: list[str] = []
    for v in xv:
        parts.append(f'<line class="grid" x1="{x(v):.1f}" x2="{x(v):.1f}" y1="{TOP - 6}" y2="{height - BOTTOM}"/>')
    y = TOP
    for p in a.projections:
        first = True
        for q, n, slot in rows:
            if q is not p:
                continue
            cy = y + row / 2
            if first:
                parts.append(f'<text class="tick" x="{left - 8}" y="{cy + 4:.1f}" text-anchor="end">'
                             f'{escape(p.team.team_number)}</text>')
            tip = (f"{p.team.team_number}: {n.label} needs ≈ {num(n.median)} State Round points "
                   f"(likely {num(n.lo)}–{num(n.hi)}), {100 * n.chance:.0f}% chance")
            team = escape(p.team.team_number)
            parts.append(f'<rect class="need {slot}" x="{x(n.lo):.1f}" y="{cy - 5:.1f}" '
                         f'width="{max(x(n.hi) - x(n.lo), 2):.1f}" height="10" rx="3" data-tip="{escape(tip)}" '
                         f'data-team="{team}"/>')
            parts.append(f'<line class="need-med {slot}" x1="{x(n.median):.1f}" x2="{x(n.median):.1f}" '
                         f'y1="{cy - 8:.1f}" y2="{cy + 8:.1f}"/>')
            if first:
                parts.append(f'<circle class="dot expected" cx="{x(p.expected):.1f}" cy="{cy:.1f}" r="4.5" '
                             f'data-team="{team}" data-tip="{escape(f"{p.team.team_number}: projected State Round score ≈ {num(p.expected)}")}"/>')
            first = False
            y += row
        y += 8
    parts.append(f'<line class="axis" x1="{left}" x2="{width - RIGHT}" y1="{height - BOTTOM}" y2="{height - BOTTOM}"/>')
    _x_ticks(parts, xv, x, height - BOTTOM, title="State Round points", width=width)
    svg = _svg(width, height, "State Round points our teams need, projected", parts)
    return svg.replace('<div class="chart-wrap" data-tips>', '<div class="chart-wrap" data-tips data-projection>', 1)


def advance_legend(r: RoundReport) -> str:
    a = r.advance
    if not a or a.stage != "projection":
        return ""
    items = [Item("Needed for the Semifinals", "s1", "area", ".need.s1, .need-med.s1")]
    if any(p.award for p in a.projections):
        items.append(Item(f"Needed for a top-3 {r.state} award", "s3", "area", ".need.s3, .need-med.s3"))
    items.append(Item("Projected State Round score", "expected", toggle=".dot.expected"))
    return legend(items)


def _hours(v: float) -> str:
    return f"{v / 60:.0f} h" if v % 60 == 0 else f"{v / 60:.2f} h"


def score_hist(r: RoundReport, window: tuple[float, float] | None = None) -> str:
    nat = r.score["national"]
    refs = [(nat.median, f"national median {num(nat.median)}")] if nat.median is not None else []
    if window:
        lo, hi = window
        step = _nice_step(hi - lo, 24)
        return histogram(r, lambda t: t.score, bin_size=step, label="Score distribution (zoomed)", x_title="score",
                         refs=refs, width=HALF, start=math.floor(lo / step) * step, stop=hi, zoom="score_hist")
    top = max((t.score for t in r.teams), default=0)
    return histogram(r, lambda t: t.score, bin_size=_nice_step(top or 10, 24), label="Score distribution",
                     x_title="score", refs=refs, width=HALF, zoom="score_hist")


def time_hist(r: RoundReport, window: tuple[float, float] | None = None) -> str:
    cap = r.limit + OVER

    def minutes(t: TeamRow) -> float | None:
        return min(t.play_time / 60, cap - 1) if t.play_time else None
    refs = [(r.limit, f"{r.limit // 60}-hour limit")]
    if window:
        lo, hi = window
        step = 5 if hi - lo <= 120 else 15
        lo = math.floor(lo / step) * step
        tick = 60 if hi - lo > 240 else 30 if hi - lo > 90 else 15
        return histogram(r, minutes, bin_size=step, label="Play time distribution (zoomed)", x_title="play time",
                         refs=refs, fmt=_clock, start=lo, stop=hi, width=HALF, zoom="time_hist",
                         x_tick_values=list(range(int(math.ceil(lo / tick)) * tick, int(hi) + 1, tick)))
    return histogram(r, minutes, bin_size=15, label="Play time distribution", x_title="play time", refs=refs,
                     fmt=_hours, start=0, width=HALF, zoom="time_hist",
                     x_tick_values=list(range(0, cap + 1, 60 if r.limit <= 240 else 120)))


def zoomed_chart(r: RoundReport, name: str, lo: float, hi: float) -> str:
    """One zoomable chart re-rendered for an x range (the brush in static/analysis_charts.js)."""
    if name not in ZOOMABLE or not hi > lo:
        return ""
    return ZOOMABLE[name](r, window=(lo, hi))


def round_charts(r: RoundReport) -> dict[str, str]:
    charts = {
        "state_boxes": state_boxes(r),
        "strips": group_strips(r),
        "score_hist": score_hist(r),
        "time_hist": time_hist(r),
        "heatmap": heatmap(r),
        "density": density_scatter(r),
        "attempts": attempts_boxes(r, HALF),
        "completion": completion_boxes(r, HALF),
        "progress": progress_chart(r),
        "advance": advance_chart(r),
    }
    for img in r.images:
        charts[f"finds:{img.name}"] = finds_bars(r, img.name)
    return charts


ZOOMABLE: dict[str, Callable[..., str]] = {"progress": progress_chart, "score_hist": score_hist,
                                           "time_hist": time_hist}


# --- comparisons ---

def percentile_lines(categories: Sequence[str], series: Sequence[tuple[str, Sequence[float | None]]], *,
                     label: str, width: int = W, height: int = 240, slots: Sequence[str] | None = None,
                     y_title: str = "outscored") -> str:
    """Percentiles (0–100) across rounds: one line per series, a marker per round, gaps where missing."""
    if not categories or not series:
        return ""
    yv = [0, 25, 50, 75, 100]
    y = Scale(0, 100, height - BOTTOM - 10, TOP)
    n = len(categories)
    step = (width - LEFT - RIGHT - 90) / max(n, 1)
    x0 = LEFT

    def x(i: int) -> float:
        return x0 + step * (i + 0.5)
    parts: list[str] = []
    _y_axis(parts, yv, y, LEFT, width - RIGHT - 90, lambda v: f"{v:.0f}%", y_title)
    _ref_h(parts, 50, y, LEFT, width - RIGHT - 90, "half the division", left=True)
    many = n > 8
    for i, c in enumerate(categories):
        if many:
            parts.append(f'<text class="tick" transform="translate({x(i) + 3:.1f},{height - BOTTOM}) rotate(-35)" '
                         f'text-anchor="end">{escape(c)}</text>')
        else:
            parts.append(f'<text class="tick" x="{x(i):.1f}" y="{height - BOTTOM + 8}" text-anchor="middle">'
                         f'{escape(c)}</text>')
    ends = []
    for k, (name, values) in enumerate(series[:8]):
        slot = slots[k] if slots else f"s{k + 1}"
        runs, cur = [], []
        for i, v in enumerate(values):
            if v is None:
                if cur:
                    runs.append(cur)
                cur = []
            else:
                cur.append((x(i), y(v)))
        if cur:
            runs.append(cur)
        for run in runs:
            if len(run) > 1:
                parts.append(f'<path class="series {slot}" d="M' + " L".join(f"{a:.1f},{b:.1f}" for a, b in run)
                             + '"/>')
        for i, v in enumerate(values):
            if v is not None:
                parts.append(f'<circle class="end {slot}" cx="{x(i):.1f}" cy="{y(v):.1f}" r="4.5" '
                             f'data-tip="{escape(f"{name} · {categories[i]} · outscored {v:.0f}%")}"/>')
        last = next(((i, v) for i, v in reversed(list(enumerate(values))) if v is not None), None)
        if last:
            ends.append([y(last[1]), name, slot])
    ends.sort()
    for k in range(1, len(ends)):
        ends[k][0] = max(ends[k][0], ends[k - 1][0] + 15)
    for ly, name, slot in ends:  # direct labels, each with its line's color key; a click shows or hides the line
        parts.append(f'<g class="label-toggle" data-series="{slot}" role="button" tabindex="0" aria-pressed="true" '
                     f'aria-label="Show or hide {escape(name)}">')
        parts.append(f'<rect class="key-mark {slot}" x="{width - RIGHT - 86}" y="{ly - 1.5:.1f}" width="10" '
                     'height="3" rx="1.5"/>')
        parts.append(f'<text class="end-label" x="{width - RIGHT - 72}" y="{ly + 4:.1f}">{escape(name[:14])}</text>')
        parts.append(f'<rect class="hit" x="{width - RIGHT - 88}" y="{ly - 8:.1f}" width="88" height="15"/></g>')
    return _svg(width, height + (40 if many else 0), label, parts)
