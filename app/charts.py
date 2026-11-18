"""Server-rendered SVG step charts for the team history page (no chart library).

Snapshots are change-only, so a value holds until the next change: the line is a
step (horizontal, then vertical), carried on to the end of the round. History is
split into rounds wherever there's a long gap, and each chart covers one round.
Places use an inverted axis (1st at the top).

Each chart carries its points (in SVG units) in ``data-points`` so
static/charts.js can draw a crosshair and tooltip; a table on the page holds the
same values for anyone not using the chart.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, tzinfo
from html import escape

ROUND_GAP = timedelta(hours=12)
LONG_GAP = timedelta(days=7)   # rounds are weeks apart

W, H = 720, 220
LEFT, RIGHT, TOP, BOTTOM = 52, 16, 14, 30


@dataclass(frozen=True)
class Chart:
    svg: str


def split_rounds(times: Sequence[datetime], gap: timedelta = ROUND_GAP,
                 play_times: Sequence[int | None] | None = None) -> list[tuple[int, int]]:
    """Index ranges [start, end) of a team's rounds.

    With ``play_times``, a round starts where the team's play time resets (it only
    grows within a round, then holds until the next one), or after a gap of more than
    ``LONG_GAP`` (a team that didn't play a round). Quiet stretches inside a round
    don't split it: history is change-only, so a team whose places stop moving after
    it finishes can go a day or more without a row. Without play times (old callers),
    any gap longer than ``gap`` starts a new run.
    """
    runs, start = [], 0
    for i in range(1, len(times)):
        if play_times is not None:
            prev, cur = play_times[i - 1] or 0, play_times[i] or 0
            new = (prev > 0 and cur < prev) or times[i] - times[i - 1] > LONG_GAP
        else:
            new = times[i] - times[i - 1] > gap
        if new:
            runs.append((start, i))
            start = i
    if times:
        runs.append((start, len(times)))
    return runs


def _nice_step(span: float, target: int = 4) -> float:
    raw = span / max(target, 1)
    mag = 10 ** math.floor(math.log10(raw)) if raw > 0 else 1
    for m in (1, 2, 2.5, 5, 10):
        if raw <= m * mag:
            return m * mag
    return 10 * mag


def _y_ticks(lo: float, hi: float, integer: bool) -> list[float]:
    if hi <= lo:
        hi = lo + 1
    step = _nice_step(hi - lo)
    if integer:  # places: start exactly at the best place shown, then round numbers
        step = max(1, round(step))
        ticks = [lo] + [k * step for k in range(int(lo // step) + 1, int(math.ceil(hi / step)) + 1)
                        if k * step - lo >= step / 2]
        return ticks if ticks[-1] >= hi else ticks + [ticks[-1] + step]
    first = math.floor(lo / step) * step
    ticks, v = [], first
    while v <= hi + step * 1e-9:
        ticks.append(v)
        v += step
    if ticks[-1] < hi:
        ticks.append(ticks[-1] + step)
    return ticks


def _time_ticks(t0: datetime, t1: datetime, tz: tzinfo) -> list[datetime]:
    span = (t1 - t0).total_seconds()
    for hours in (0.25, 0.5, 1, 2, 3, 6, 12, 24, 48):
        if span / (hours * 3600) <= 7:
            break
    step = timedelta(hours=hours)
    local = t0.astimezone(tz)
    base = local.replace(minute=0, second=0, microsecond=0)
    ticks, t = [], base
    while t <= t1.astimezone(tz):
        if t >= local:
            ticks.append(t)
        t += step
    return ticks


def _clock(t: datetime) -> str:
    h = t.hour % 12 or 12
    return f"{h}:{t.minute:02d} {'AM' if t.hour < 12 else 'PM'}" if t.minute else f"{h} {'AM' if t.hour < 12 else 'PM'}"


def step_chart(points: Sequence[tuple[datetime, float]], end: datetime, *, tz: tzinfo, label: str,
               invert: bool = False, integer: bool = False,
               fmt: Callable[[float], str] = lambda v: f"{v:g}", width: int = W) -> Chart:
    """One series as a step line from the first point to ``end``.

    ``width`` is in SVG units: pick it near the width the chart is shown at, so text stays ~1:1.
    """
    W = width  # noqa: N806 (shadows the module default)
    t0, t1 = points[0][0], max(end, points[-1][0])
    if t1 <= t0:
        t1 = t0 + timedelta(minutes=1)
    values = [v for _, v in points]
    lo, hi = min(values), max(values)
    if invert:
        lo = max(1, lo)
    ticks = _y_ticks(0 if not invert and lo >= 0 and not integer else lo, hi, integer)
    if invert:
        ticks = [t for t in ticks if t >= 1] or [1]
    y_lo, y_hi = ticks[0], ticks[-1]
    if y_hi == y_lo:
        y_hi = y_lo + 1
    pw, ph = W - LEFT - RIGHT, H - TOP - BOTTOM

    def x(t: datetime) -> float:
        return LEFT + (t - t0).total_seconds() / (t1 - t0).total_seconds() * pw

    def y(v: float) -> float:
        frac = (v - y_lo) / (y_hi - y_lo)
        return TOP + (frac if invert else 1 - frac) * ph

    parts = [f'<svg class="chart" viewBox="0 0 {W} {H}" role="img" aria-label="{escape(label)}" '
             f'preserveAspectRatio="xMidYMid meet">']
    for v in ticks:  # recessive horizontal grid + y labels
        yy = y(v)
        parts.append(f'<line class="grid" x1="{LEFT}" x2="{W - RIGHT}" y1="{yy:.1f}" y2="{yy:.1f}"/>')
        parts.append(f'<text class="tick" x="{LEFT - 8}" y="{yy + 4:.1f}" text-anchor="end">{escape(fmt(v))}</text>')
    for t in _time_ticks(t0, t1, tz):
        xx = x(t)
        parts.append(f'<line class="axis" x1="{xx:.1f}" x2="{xx:.1f}" y1="{H - BOTTOM}" y2="{H - BOTTOM + 4}"/>')
        parts.append(f'<text class="tick" x="{xx:.1f}" y="{H - 8}" text-anchor="middle">{_clock(t)}</text>')
    parts.append(f'<line class="axis" x1="{LEFT}" x2="{W - RIGHT}" y1="{H - BOTTOM}" y2="{H - BOTTOM}"/>')

    d = [f"M{x(points[0][0]):.1f},{y(points[0][1]):.1f}"]
    for t, v in points[1:]:
        d.append(f"H{x(t):.1f}V{y(v):.1f}")
    d.append(f"H{x(t1):.1f}")
    parts.append(f'<path class="series" d="{"".join(d)}"/>')
    last_v = points[-1][1]
    parts.append(f'<circle class="end" cx="{x(t1):.1f}" cy="{y(last_v):.1f}" r="4"/>')
    label_y = y(last_v) - 8 if y(last_v) - 8 > TOP + 12 else y(last_v) + 18  # below the dot near the top
    parts.append(f'<text class="end-label" x="{min(x(t1), W - RIGHT) - 6:.1f}" y="{label_y:.1f}" '
                 f'text-anchor="end">{escape(fmt(last_v))}</text>')
    hover = [[round(x(t), 1), round(y(v), 1), f"{_clock(t.astimezone(tz))} · {fmt(v)}"] for t, v in points]
    parts.append("</svg>")
    svg = "".join(parts)
    return Chart(f'<div class="chart-wrap" data-points="{escape(json.dumps(hover))}" '
                 f'data-plot="{LEFT},{W - RIGHT},{TOP},{H - BOTTOM},{W},{H}">{svg}'
                 f'<div class="chart-tip" hidden></div></div>')


def short_image_name(name: str) -> str:
    """"Windows11_cp19_intro_r2_hsms" -> "Windows11"."""
    return name.split("_", 1)[0] or name


def multi_step_chart(series: Sequence[tuple[str, Sequence[tuple[datetime, float]]]], end: datetime, *,
                     tz: tzinfo, label: str, fmt: Callable[[float], str] = lambda v: f"{v:g}",
                     width: int = W) -> Chart:
    """Several series on one shared axis (image scores), each a step line in its categorical slot.

    The page shows a legend; each line also ends in a direct label (value), nudged apart
    so they don't overlap. The tooltip lists every series' value at the hovered time.
    """
    W = width  # noqa: N806
    series = [(n, list(p)) for n, p in series if p][:8]  # 8 categorical slots, never cycled
    if not series:
        return Chart("")
    t0 = min(p[0][0] for _, p in series)
    t1 = max([end] + [p[-1][0] for _, p in series])
    if t1 <= t0:
        t1 = t0 + timedelta(minutes=1)
    hi = max(v for _, p in series for _, v in p)
    ticks = _y_ticks(0, hi, False)
    y_lo, y_hi = ticks[0], ticks[-1] if ticks[-1] > ticks[0] else ticks[0] + 1
    pw, ph = W - LEFT - RIGHT - 40, H - TOP - BOTTOM  # room on the right for end labels

    def x(t: datetime) -> float:
        return LEFT + (t - t0).total_seconds() / (t1 - t0).total_seconds() * pw

    def y(v: float) -> float:
        return TOP + (1 - (v - y_lo) / (y_hi - y_lo)) * ph

    parts = [f'<svg class="chart" viewBox="0 0 {W} {H}" role="img" aria-label="{escape(label)}" '
             f'preserveAspectRatio="xMidYMid meet">']
    for v in ticks:
        yy = y(v)
        parts.append(f'<line class="grid" x1="{LEFT}" x2="{LEFT + pw}" y1="{yy:.1f}" y2="{yy:.1f}"/>')
        parts.append(f'<text class="tick" x="{LEFT - 8}" y="{yy + 4:.1f}" text-anchor="end">{escape(fmt(v))}</text>')
    for t in _time_ticks(t0, t1, tz):
        xx = x(t)
        parts.append(f'<line class="axis" x1="{xx:.1f}" x2="{xx:.1f}" y1="{H - BOTTOM}" y2="{H - BOTTOM + 4}"/>')
        parts.append(f'<text class="tick" x="{xx:.1f}" y="{H - 8}" text-anchor="middle">{_clock(t)}</text>')
    parts.append(f'<line class="axis" x1="{LEFT}" x2="{LEFT + pw}" y1="{H - BOTTOM}" y2="{H - BOTTOM}"/>')

    ends = []
    for i, (_, pts) in enumerate(series, start=1):
        d = [f"M{x(pts[0][0]):.1f},{y(pts[0][1]):.1f}"] + [f"H{x(t):.1f}V{y(v):.1f}" for t, v in pts[1:]]
        d.append(f"H{x(t1):.1f}")
        parts.append(f'<path class="series s{i}" d="{"".join(d)}"/>')
        ends.append([y(pts[-1][1]), i, pts[-1][1]])
    ends.sort()
    for k in range(1, len(ends)):  # keep end labels at least 13 units apart
        ends[k][0] = max(ends[k][0], ends[k - 1][0] + 13)
    for ly, i, v in ends:
        cy = y(v)
        parts.append(f'<circle class="end s{i}" cx="{x(t1):.1f}" cy="{cy:.1f}" r="4"/>')
        parts.append(f'<text class="end-label" x="{x(t1) + 8:.1f}" y="{ly + 4:.1f}">{escape(fmt(v))}</text>')
    parts.append("</svg>")

    times = sorted({t for _, p in series for t, _ in p})
    hover = []
    for t in times:  # each series' value at t (held from its last change), or "–" before it starts
        vals = []
        for name, pts in series:
            cur = None
            for pt, pv in pts:
                if pt > t:
                    break
                cur = pv
            vals.append(f"{short_image_name(name)} {fmt(cur) if cur is not None else '–'}")
        hover.append([round(x(t), 1), None, f"{_clock(t.astimezone(tz))} · " + " · ".join(vals)])
    return Chart(f'<div class="chart-wrap" data-points="{escape(json.dumps(hover))}" '
                 f'data-plot="{LEFT},{LEFT + pw},{TOP},{H - BOTTOM},{W},{H}">{"".join(parts)}'
                 f'<div class="chart-tip" hidden></div></div>')


def sparkline(points: Sequence[tuple[datetime, float]], end: datetime, *, invert: bool = False,
              label: str = "", width: int = 120, height: int = 28) -> str:
    """A tiny step line with an end dot and no axes, for the scoreboard's expanded rows."""
    if not points:
        return ""
    t0, t1 = points[0][0], max(end, points[-1][0])
    if t1 <= t0:
        t1 = t0 + timedelta(minutes=1)
    values = [v for _, v in points]
    lo, hi = min(values), max(values)
    if hi == lo:
        lo, hi = lo - 1, hi + 1
    pad = 4

    def x(t: datetime) -> float:
        return pad + (t - t0).total_seconds() / (t1 - t0).total_seconds() * (width - 2 * pad)

    def y(v: float) -> float:
        frac = (v - lo) / (hi - lo)
        return pad + (frac if invert else 1 - frac) * (height - 2 * pad)

    d = [f"M{x(points[0][0]):.1f},{y(points[0][1]):.1f}"] + [f"H{x(t):.1f}V{y(v):.1f}" for t, v in points[1:]]
    d.append(f"H{x(t1):.1f}")
    return (f'<svg class="spark" viewBox="0 0 {width} {height}" width="{width}" height="{height}" role="img" '
            f'aria-label="{escape(label)}"><path class="series" d="{"".join(d)}"/>'
            f'<circle class="end" cx="{x(t1):.1f}" cy="{y(points[-1][1]):.1f}" r="3"/></svg>')
