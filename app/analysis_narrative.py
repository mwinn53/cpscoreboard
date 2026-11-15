"""Narrative for the Analysis tab, written from the numbers.

The legacy R reports carried hand-written paragraphs ("The median score for the
state of Georgia is higher than the national median. However, the national median
intersects with the state IQR…"). Here the same kinds of statements are built from
each sample, so every round, season and comparison gets its own text, and a
statement only appears when the numbers support it. Coaches add interpretation
(rosters, grades, practice plans) in the notes.

Wording rules: "middle half" for the IQR, "outscored N%" for a percentile, and
"meaningful" only in the R report's sense (the other median falls outside the
middle half).
"""

from __future__ import annotations

from collections.abc import Sequence

from .posting import ordinal


# --- formatting ---

def num(v: float | None) -> str:
    if v is None:
        return "–"
    return f"{v:.0f}" if abs(v - round(v)) < 0.05 else f"{v:.1f}"


def pct(v: float | None) -> str:
    """A ratio (0–1) as a percent."""
    return "–" if v is None else f"{100 * v:.0f}%"


def share(v: float | None) -> str:
    """A percentile (0–100) as a percent."""
    return "–" if v is None else f"{v:.0f}%"


def minutes(v: float | None) -> str:
    if v is None:
        return "–"
    h, m = divmod(round(v), 60)
    return f"{m} min" if not h else f"{h} h {m:02d} min" if m else f"{h} h"


def listing(items: Sequence[str]) -> str:
    items = [i for i in items if i]
    if len(items) <= 2:
        return " and ".join(items)
    return ", ".join(items[:-1]) + ", and " + items[-1]


def plural(k: int, word: str, many: str | None = None) -> str:
    return f"{k} {word if k == 1 else (many or word + 's')}"


def corr(r: float) -> str:
    return f"{r + 0.0:.2f}".replace("-0.00", "0.00")


def strength(r: float | None) -> str:
    """How strong a correlation is, in words."""
    if r is None:
        return "no measurable"
    a = abs(r)
    size = "almost no" if a < 0.1 else "a weak" if a < 0.3 else "a moderate" if a < 0.5 else "a strong"
    return size if a < 0.1 else f"{size} {'positive' if r > 0 else 'negative'}"


def position(value: float, d) -> str:
    """Where a value sits in a distribution, in the box plot's terms."""
    if d.n < 4 or d.iqr is None:
        return "above the median" if value > (d.median or 0) else "at or below the median"
    if value > d.q3 + 1.5 * d.iqr:
        return "an upper outlier"
    if value < d.q1 - 1.5 * d.iqr:
        return "a lower outlier"
    if value > d.q3:
        return "in the top quarter"
    if value < d.q1:
        return "in the bottom quarter"
    return "in the middle half"


# --- a round ---

def round_narrative(r) -> dict[str, list[str]]:
    sections = {
        "overview": _overview(r), "scores": _scores(r), "time": _time(r), "density": _density(r),
        "attempts": _attempts(r), "images": _images(r), "challenge": _challenge(r), "progress": _progress(r),
    }
    sections["summary"] = _summary(r)
    return sections


def _overview(r) -> list[str]:
    nat, st, dist, ems = (r.counts[k] for k in ("national", "state", "district", "ems"))
    out = []
    s = f"{nat} {r.info.division} teams competed in {r.info.title}"
    if st:
        s += f", {st} of them from {r.state}"
        if dist:
            s += f"; {dist} of those are district teams ({pct(dist / st)} of {r.state}'s teams)"
    out.append(s + ".")
    if r.ems:
        ranked = sorted(r.ems, key=lambda res: res.team.place_state_division or 10**6)
        places = [ordinal(res.team.place_state_division) for res in ranked if res.team.place_state_division]
        lead = (f"Our {plural(len(r.ems), 'team')} ({listing([res.label for res in ranked])})"
                if len(r.ems) > 1 else f"Our team, {ranked[0].label},")
        if places:
            out.append(f"{lead} placed {listing(places)} in {r.state}, outscoring "
                       f"{listing([share(res.percentile) for res in ranked])} of the division.")
    else:
        out.append("None of our teams are in this sample.")
    in_state = [t for t, _, _ in r.state_table]
    top50 = 0
    for t in in_state:
        if t.place_division and t.place_division <= 50:
            top50 += 1
        else:
            break
    if top50 >= 2:
        out.append(f"The top {top50} {r.state} teams {'both' if top50 == 2 else 'all'} finished in the national "
                   "top 50.")
    elif in_state and in_state[0].place_division:
        out.append(f"{r.state}'s best team placed {ordinal(in_state[0].place_division)} nationally.")
    top3 = [t.location for t in r.teams[:3] if t.location]
    if len(top3) == 3:
        out.append(f"The top three teams are all from {top3[0]}." if len(set(top3)) == 1
                   else f"The top three teams came from {listing(top3)}.")
    if r.images:
        best = ", ".join(f"{i.name} {num(i.score.max)}" for i in r.images if i.score.n)
        out.append(f"The top score was {num(r.score['national'].max)} (best per image: {best}"
                   + (f"; challenge {num(r.challenge.max)}" if r.has_challenge else "") + ").")
        perfect = [f"{plural(i.perfect, 'team')} on {i.name}" for i in r.images if i.perfect]
        out.append(f"Teams that found everything: {listing(perfect)}." if perfect
                   else "No team found everything on any image.")
    return out


def _scores(r) -> list[str]:
    nat, st = r.score["national"], r.score["state"]
    out = []
    if nat.n:
        out.append(f"The national median was {num(nat.median)}, and the middle half of teams scored "
                   f"{num(nat.q1)}–{num(nat.q3)}.")
    if st.n and nat.median is not None:
        rel = "higher than" if st.median > nat.median else "lower than" if st.median < nat.median else "equal to"
        s = f"{r.state}'s median ({num(st.median)}) was {rel} the national median"
        if st.n > 1 and st.median != nat.median:
            inside = st.q1 <= nat.median <= st.q3
            s += (f", but the national median falls inside {r.state}'s middle half, so the difference isn't "
                  "meaningful" if inside else f", and the national median falls outside {r.state}'s middle half, "
                  "so the difference is meaningful")
        out.append(s + ".")
    if r.density and r.density.rank:
        out.append(f"{r.state} ranked {ordinal(r.density.rank)} of {len(r.density.states)} states and countries "
                   "by median score.")
    if r.ems and st.n >= 4:
        groups: dict[str, list[str]] = {}
        for res in r.ems:
            if res.team.location == r.state:
                groups.setdefault(position(res.team.score, st), []).append(res.label)
        parts = [f"{listing(v)} {'was' if len(v) == 1 else 'were'} {k}" for k, v in groups.items()]
        if parts:
            out.append(f"Among {r.state} teams, {listing(parts)}.")
    if r.ems and nat.median is not None:
        above = sum(1 for res in r.ems if res.team.score > nat.median)
        out.append("All of our teams scored above the national median." if above == len(r.ems)
                   else "None of our teams scored above the national median." if not above
                   else f"{above} of our {len(r.ems)} teams scored above the national median.")
    return out


def _time(r) -> list[str]:
    out = []
    pt, tm = r.play_time, r.time
    if pt.n:
        out.append(f"The median play time was {minutes(pt.median)}"
                   + (f"; {plural(r.over_limit, 'team')} went past the 6-hour limit." if r.over_limit
                      else ", and no team went past the 6-hour limit."))
    if tm and tm.above_median.n and tm.below_median.n:
        s = (f"Teams above the national median score played a median of {minutes(tm.above_median.median)}, "
             f"against {minutes(tm.below_median.median)} for the rest")
        if (tm.above_median.median or 0) >= 330:
            s += ": the stronger teams use nearly all of their six hours"
        out.append(s + ".")
    if tm and tm.r is not None:
        out.append(f"Among teams that attempted every image, play time had {strength(tm.r)} relationship with "
                   f"score (r = {corr(tm.r)})"
                   + (", so finishing early brought no clear advantage." if abs(tm.r) < 0.3 else "."))
    if tm and tm.ours_mean is not None:
        out.append(f"Our teams played a mean of {minutes(tm.ours_mean)}.")
    return out


def _density(r) -> list[str]:
    d = r.density
    if not d:
        return []
    out = [f"{len(d.states)} states and countries took part. The median state had {num(d.teams.median)} teams "
           f"(middle half {num(d.teams.q1)}–{num(d.teams.q3)})."]
    ours = next((s for s in d.states if s.state == r.state), None)
    if ours and d.teams.iqr is not None:
        if ours.n > d.teams.q3 + 1.5 * d.teams.iqr:
            out.append(f"{r.state}, with {ours.n} teams, is one of the outliers for size.")
        elif ours.n > d.teams.q3:
            out.append(f"{r.state}, with {ours.n} teams, is larger than most.")
    if d.r is not None:
        out.append(f"Teams per state and the state's median score had {strength(d.r)} relationship "
                   f"(r = {corr(d.r)})" + (", so more teams in a state doesn't by itself mean higher scores."
                                         if abs(d.r) < 0.3 else "."))
    if d.bands:
        lo, hi, med, k = max(d.bands, key=lambda b: b[2] or 0)
        out.append(f"States with {lo}–{hi} teams had the highest median of state medians ({num(med)}, "
                   f"{plural(k, 'state')}).")
    if ours and d.medians.n > 1:
        rel = "above" if ours.score.median > d.medians.median else "below" if ours.score.median < d.medians.median \
            else "equal to"
        inside = d.medians.q1 <= ours.score.median <= d.medians.q3
        out.append(f"{r.state}'s median ({num(ours.score.median)}) was {rel} the median state "
                   f"({num(d.medians.median)}), {'within' if inside else 'outside'} the middle half of states.")
    return out


def _attempts(r) -> list[str]:
    a = r.attempts
    if not a or a.most < 2:
        return []
    out = [f"{pct(a.all_share)} of teams attempted {'both' if a.most == 2 else f'all {a.most}'} images."]
    if a.fewer:
        s = f"{plural(a.fewer, 'team')} attempted fewer"
        if a.fewer_state:
            s += f", including {a.fewer_state} in {r.state}"
        if a.fewer_places:
            s += f"; they placed between {ordinal(a.fewer_places[0])} and {ordinal(a.fewer_places[1])}"
        out.append(s + ".")
        full, rest = a.by_count.get(a.most), [d for k, d in a.by_count.items() if k < a.most]
        rest_scores = [d.median for d in rest if d.median is not None]
        if full and rest_scores:
            out.append(f"Teams that attempted every image had a median score of {num(full.median)}; the best "
                       f"median among the rest was {num(max(rest_scores))}.")
    if r.ems:
        missing = [res.label for res in r.ems if r.images_attempted(res.team) < a.most]
        out.append("All of our teams attempted every image." if not missing
                   else f"{listing(missing)} attempted fewer than {a.most} images.")
    return out


def _images(r) -> list[str]:
    imgs = [i for i in r.images if i.completion.n]
    if not imgs:
        return []
    out = []
    if len(imgs) > 1:
        hard = min(imgs, key=lambda i: i.completion.median)
        easy = max(imgs, key=lambda i: i.completion.median)
        if pct(hard.completion.median) == pct(easy.completion.median):
            out.append(f"Every image had the same median completion ({pct(hard.completion.median)}).")
        else:
            out.append(f"By median completion, the hardest image was {hard.name} ({pct(hard.completion.median)}) "
                       f"and the easiest {easy.name} ({pct(easy.completion.median)}).")
    if not r.ems:
        return out
    for img in imgs:
        top = [res.label for res in r.ems if (res.completion.get(img.name) or 0) > (img.completion.q3 or 1)]
        above = sum(1 for res in r.ems if (res.completion.get(img.name) or 0) > (img.completion.median or 0))
        s = f"{img.name}: {above} of our {len(r.ems)} teams completed more than the national median"
        if top:
            s += f"; {listing(top)} {'was' if len(top) == 1 else 'were'} in the top quarter"
        out.append(s + ".")
    gaps = _image_gaps(r)
    if len(gaps) > 1:
        (b, bd), (w, wd) = gaps[0], gaps[-1]
        if wd >= 0:
            out.append(f"Our median completion beat the field's on every image: most on {b} ({_points(bd)}), "
                       f"least on {w} ({_points(wd)}).")
        elif bd < 0:
            out.append(f"Our median completion trailed the field's on every image: least on {b} ({_points(bd)}), "
                       f"most on {w} ({_points(wd)}).")
        else:
            out.append(f"Relative to the field, our teams were strongest on {b} ({_points(bd)} against the "
                       f"national median) and weakest on {w} ({_points(wd)}).")
    return out


def _points(delta: float) -> str:
    return f"{'+' if delta >= 0 else '−'}{abs(100 * delta):.0f} points"


def _image_gaps(r) -> list[tuple[str, float]]:
    """Per image, our median completion minus the field's, best first."""
    import statistics
    gaps = []
    for img in r.images:
        ours = [res.completion.get(img.name) for res in r.ems if res.completion.get(img.name) is not None]
        if ours and img.completion.median is not None:
            gaps.append((img.name, statistics.median(ours) - img.completion.median))
    return sorted(gaps, key=lambda g: -g[1])


def _challenge(r) -> list[str]:
    if not r.has_challenge or not r.challenge.n:
        return []
    c = r.challenge
    out = [f"The challenge (Cisco) median was {num(c.median)} (middle half {num(c.q1)}–{num(c.q3)}, best "
           f"{num(c.max)}); {r.challenge_attempted} of {c.n} teams scored on it."]
    ours = [f"{res.label} {num(res.team.challenge_1)} (outscored {share(res.challenge_percentile)})"
            for res in r.ems if res.team.challenge_1 is not None]
    if ours:
        out.append(f"Ours: {listing(ours)}.")
    return out


def _progress(r) -> list[str]:
    p = r.progress
    if not p:
        return []
    out = [f"From the {p.teams} teams with a 5-minute history, the median team reached half of its final score "
           f"after {minutes(p.half.median)}."]
    for res in r.ems:
        if not res.hourly:
            continue
        h = res.hourly
        s = (f"{res.label} outscored {share(h.get(1))} of the field after the first hour, {share(h.get(3))} at "
             f"three hours and {share(h.get(6))} at six")
        ahead = [k for k in sorted(h) if h[k] > 50]
        if len(ahead) == len(h):
            s += ", ahead of the median throughout"
        elif not ahead:
            s += ", behind the median throughout"
        elif ahead == list(range(ahead[0], 7)):
            s += f", passing the median by hour {ahead[0]}"
        if res.half_minutes is not None:
            s += f"; half of its final score came in {minutes(res.half_minutes)}"
        out.append(s + ".")
    return out


def _summary(r) -> list[str]:
    """The report's "In brief": the conclusions, as the R report's closing bullets."""
    out = []
    if r.ems:
        best = max(r.ems, key=lambda res: res.percentile)
        place = (f", {ordinal(best.team.place_state_division)} in {r.state}"
                 if best.team.place_state_division else "")
        out.append(f"Best result: {best.label}{place}, outscoring {share(best.percentile)} of the division.")
    nat, st = r.score["national"], r.score["state"]
    if st.n > 1 and nat.median is not None and st.median != nat.median:
        inside = st.q1 <= nat.median <= st.q3
        out.append(f"{r.state} scored {'higher' if st.median > nat.median else 'lower'} than the nation "
                   f"(median {num(st.median)} vs {num(nat.median)})"
                   + ("; not a meaningful difference." if inside else ", a meaningful difference."))
    gaps = _image_gaps(r)
    if gaps:
        strong = [g[0] for g in gaps if g[1] > 0.05]
        weak = [g[0] for g in gaps if g[1] < -0.05]
        if strong:
            out.append(f"Our teams were most competitive on {listing(strong)}.")
        if weak:
            out.append(f"Room to grow: {listing(weak)}, where our median completion trailed the field.")
    a = r.attempts
    if a and a.fewer and a.fewer_places and a.most > 1:
        out.append(f"Teams that skipped an image weren't competitive (the best of them placed "
                   f"{ordinal(a.fewer_places[0])}); attempting every image doesn't guarantee a high place, but it's "
                   "the price of entry.")
    if r.time and r.time.r is not None and abs(r.time.r) < 0.3:
        out.append("Finishing early brought no clear advantage; going past 6 hours costs points.")
    if r.density and r.density.r is not None and abs(r.density.r) < 0.3:
        out.append(f"The number of teams in a state had little to do with its scores (r = {corr(r.density.r)}).")
    if r.has_challenge and r.challenge.n:
        out.append(f"Challenge (Cisco): median {num(r.challenge.median)} of a best {num(r.challenge.max)}, so "
                   "there's room to gain on it.")
    return out


# --- context and comparisons ---

def change(a: float | None, b: float | None) -> str:
    if not a or b is None:
        return ""
    d = (b - a) / a
    return "unchanged" if abs(d) < 0.005 else f"{'up' if d > 0 else 'down'} {abs(100 * d):.0f}%"


def participation_context(current, previous=None, last_season=None) -> list[str]:
    """How this round's turnout compares with the season's previous round and the same round last season."""
    out = []
    last = last_season.short if last_season else ""
    for other, words in ((previous, f"from {previous.short if previous else ''}"),
                         (last_season, f"from the same round last season ({last})")):
        if other is None:
            continue
        nat = change(other.counts["national"], current.counts["national"])
        st = change(other.counts["state"], current.counts["state"])
        if nat:
            out.append(f"National participation was {nat} {words} ({other.counts['national']} → "
                       f"{current.counts['national']})" + (f"; {current.state} was {st} ({other.counts['state']} → "
                                                         f"{current.counts['state']})" if st else "") + ".")
    return out


def season_narrative(summaries: list) -> list[str]:
    """A season's rounds, in order."""
    if not summaries:
        return []
    first, last = summaries[0], summaries[-1]
    out = [f"CP-{first.info.season} has {plural(len(summaries), 'round')} sampled: "
           f"{listing([s.info.label for s in summaries])}."]
    if len(summaries) > 1:
        out.append(f"National participation went from {first.counts['national']} in {first.info.label} to "
                   f"{last.counts['national']} in {last.info.label}, and {first.state}'s from {first.counts['state']} "
                   f"to {last.counts['state']} (later rounds are by qualification).")
    teams: dict[str, list] = {}
    for s in summaries:
        for o in s.ours:
            teams.setdefault(o.team_number, []).append((s, o))
    for rows in teams.values():
        label = rows[-1][1].label
        if len(rows) == 1:
            s, o = rows[0]
            out.append(f"{label} competed in {s.info.label}, outscoring {share(o.percentile)} of the division.")
            continue
        pcts = [o.percentile for _, o in rows]
        best = max(rows, key=lambda x: x[1].percentile)
        trend = pcts[-1] - pcts[0]
        word = "rose" if trend > 5 else "fell" if trend < -5 else "held steady"
        out.append(f"{label} {word} from outscoring {share(pcts[0])} of the division in {rows[0][0].info.label} to "
                   f"{share(pcts[-1])} in {rows[-1][0].info.label} (best: {share(best[1].percentile)} in "
                   f"{best[0].info.label}).")
    return out


def history_narrative(summaries: list) -> list[str]:
    """Season over season (summaries in time order, one per round)."""
    if not summaries:
        return []
    seasons = sorted({s.info.season for s in summaries})
    out = [f"{plural(len(summaries), 'round')} sampled across {plural(len(seasons), 'season')} "
           f"(CP-{seasons[0]} to CP-{seasons[-1]})."]
    by_key: dict[str, list] = {}
    for s in summaries:
        by_key.setdefault(s.info.label, []).append(s)
    for label, rows in by_key.items():
        if len(rows) > 1:
            a, b = rows[0], rows[-1]
            out.append(f"{label}: national participation {change(a.counts['national'], b.counts['national'])} "
                       f"from CP-{a.info.season} to CP-{b.info.season} ({a.counts['national']} → "
                       f"{b.counts['national']}), {a.state} {change(a.counts['state'], b.counts['state'])} "
                       f"({a.counts['state']} → {b.counts['state']}).")
    with_ours = [s for s in summaries if s.ours]
    if with_ours:
        best = max(with_ours, key=lambda s: s.best_pct)
        top_half = sum(1 for s in with_ours if (s.median_pct or 0) > 50)
        out.append(f"Our median team outscored half the division in {top_half} of {len(with_ours)} rounds; our "
                   f"best single result was {share(best.best_pct)} in {best.short}.")
        per_season: dict[int, list[float]] = {}
        for s in with_ours:
            per_season.setdefault(s.info.season, []).append(s.median_pct)
        if len(per_season) > 1:
            import statistics
            first, last = min(per_season), max(per_season)
            a, b = statistics.median(per_season[first]), statistics.median(per_season[last])
            out.append(f"Season to season, our median team went from outscoring {share(a)} (CP-{first}) to "
                       f"{share(b)} (CP-{last}).")
    st = [s for s in summaries if s.state_median_pct is not None]
    if st:
        above = sum(1 for s in st if s.state_median_pct > 50)
        out.append(f"{st[0].state}'s median team was above the national median in {above} of {len(st)} rounds.")
    return out


def pair_narrative(a, b, matched: list) -> list[str]:
    """Two rounds side by side: ``a`` is the earlier (or the preliminary), ``b`` the later."""
    out = [f"{a.short} ({a.info.status}) against {b.short} ({b.info.status})."]
    nat = change(a.counts["national"], b.counts["national"])
    if nat and nat != "unchanged":
        out.append(f"National participation was {nat} ({a.counts['national']} → {b.counts['national']}).")
    med_a, med_b = a.median["national"], b.median["national"]
    if med_a is not None and med_b is not None:
        out.append(f"The national median went from {num(med_a)} to {num(med_b)}; scores aren't comparable across "
                   "rounds with different images, so the comparison below uses percentiles and completion.")
    if a.state_median_pct is not None and b.state_median_pct is not None:
        out.append(f"{a.state}'s median team outscored {share(a.state_median_pct)} of the division in the first and "
                   f"{share(b.state_median_pct)} in the second.")
    for oa, ob in matched:
        d = ob.percentile - oa.percentile
        word = "up" if d > 0.5 else "down" if d < -0.5 else "unchanged"
        s = f"{ob.label}: outscored {share(oa.percentile)} → {share(ob.percentile)} ({word}"
        s += f" {abs(d):.0f} points)" if word != "unchanged" else ")"
        if oa.place_state and ob.place_state and oa.place_state != ob.place_state:
            s += f"; {ordinal(oa.place_state)} → {ordinal(ob.place_state)} in {b.state}"
        out.append(s + ".")
    if a.ours and b.ours and not matched:
        out.append(f"Our median team outscored {share(a.median_pct)} of the division in the first and "
                   f"{share(b.median_pct)} in the second (different teams, so they're compared as a program).")
    return out
