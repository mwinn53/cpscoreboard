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

from .analysis import describe
from .analysis_stats import p_text
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


def possessive(name: str) -> str:
    return f"{name}'" if name.endswith("s") else f"{name}'s"


def signed(v: float) -> str:
    return f"{'+' if v > 0 else '−' if v < 0 else ''}{num(abs(v))}"


def group_sentence(t, who_a: str, who_b: str) -> str:
    """Two groups in words: the medians, the chance one beats the other, the interval, and whether it's significant."""
    rel = "higher than" if t.median_a > t.median_b else "lower than" if t.median_a < t.median_b else "the same as"
    s = f"{possessive(t.a)} median ({num(t.median_a)}) was {rel} {possessive(t.b)} ({num(t.median_b)})."
    if t.mw is None:
        return s
    lo, hi = t.mw.prob_sup_ci
    s += (f" A random {who_a} outscored a random {who_b} {pct(t.mw.prob_sup)} of the time (95% CI "
          f"{pct(lo)}–{pct(hi)})")
    if t.diff:
        d, dlo, dhi = t.diff
        s += f", and the difference in medians was {signed(d)} points (95% CI {signed(dlo)} to {signed(dhi)})"
    s += (f". That's a statistically significant difference (Mann–Whitney, {p_text(t.mw.p)})." if t.mw.significant
          else f". That's within what chance alone produces ({p_text(t.mw.p)}), so it isn't a significant difference.")
    return s


def corr(r: float) -> str:
    return f"{r + 0.0:.2f}".replace("-0.00", "0.00")


HOURS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six"}


def hours(n: int) -> str:
    return HOURS.get(n, str(n))


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
        "reach": _reach(r), "relative": _relative(r), "penalties": _penalties(r),
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
                   + (f"; Cisco {num(r.challenge.max)}" if r.has_challenge else "") + ").")
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
    t = r.tests.get("state")
    if t:
        out.append(group_sentence(t, f"{r.state} team", "team from elsewhere"))
    elif st.n and nat.median is not None:
        rel = "higher than" if st.median > nat.median else "lower than" if st.median < nat.median else "equal to"
        out.append(f"{r.state}'s median ({num(st.median)}) was {rel} the national median; there are too few "
                   f"{r.state} teams to test the difference.")
    t = r.tests.get("district")
    if t:
        out.append(group_sentence(t, "district team", f"other {r.state} team"))
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
                   + (f"; {plural(r.over_limit, 'team')} went past the {r.limit // 60}-hour limit." if r.over_limit
                      else f", and no team went past the {r.limit // 60}-hour limit."))
    if tm and tm.above_median.n and tm.below_median.n:
        s = (f"Teams above the national median score played a median of {minutes(tm.above_median.median)}, "
             f"against {minutes(tm.below_median.median)} for the rest")
        if (tm.above_median.median or 0) >= r.limit - 30:
            s += f": the stronger teams use nearly all of their {hours(r.limit // 60)} hours"
        out.append(s + ".")
    if tm and tm.test is not None:
        out.append(f"Among teams that attempted every image, play time had {strength(tm.r)} rank correlation with "
                   f"score (ρ = {corr(tm.r)}, {p_text(tm.test.p)})"
                   + (", so finishing early brought no clear advantage." if not tm.test.significant or abs(tm.r) < 0.1
                      else ": teams that used more of their time tended to score higher." if tm.r > 0
                      else ": teams that finished sooner tended to score higher."))
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
    if d.test is not None:
        out.append(f"Teams per state and the state's median score had {strength(d.r)} rank correlation "
                   f"(ρ = {corr(d.r)}, {p_text(d.test.p)})"
                   + (", so more teams in a state doesn't by itself mean higher scores." if not d.test.significant
                      else "."))
    if d.bands:
        best = max(d.bands, key=lambda b: b[2] or 0)
        lo, hi, med, k = best
        s = (f"States with {lo}–{hi} teams had the highest median of state medians ({num(med)}, "
             f"{plural(k, 'state')})")
        if best is d.bands[0]:
            s += ", but a state with only a few teams has a median that's mostly the luck of who entered, so read it loosely"
        out.append(s + ".")
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


def approx(v: float) -> str:
    """An estimate, to the whole point."""
    return f"{v:.0f}"


def _items(k: int) -> str:
    return plural(k, "item")


def _diff(v: float) -> str:
    """A signed difference in percentile points, with a real minus sign."""
    return f"{v:+.0f}".replace("-", "−")


def _pts(v: float) -> str:
    return f"{num(v)} point{'' if v == 1 else 's'}"


NOTABLE = 5   # percentile points: a family's median difference worth a sentence (or a significant test)


def _reach(r) -> list[str]:
    """Points within reach (#76): the cheapest points, and what each team's next step would have taken."""
    f = r.focus
    if not f or not f.gaps:
        return []
    out = []
    c = f.cheapest
    if c:
        name, items, points, teams = c
        n = len(f.gaps)
        who = ("our team" if n == 1 else "both our teams" if teams == n == 2 else f"all {n} of our teams"
               if teams == n else f"{teams} of our {n} teams")
        if items:
            out.append(f"The most points within reach were on {name}: {who} found a median {_items(items)} fewer "
                       f"than the field's top quarter there (≈ {approx(points)} points).")
        else:
            out.append(f"The most points within reach were on {name}, in penalties: ≈ {approx(points)} points for {who}.")
    for g in f.gaps:
        t = next((t for t in g.targets if t.plan), None)
        if t is None:
            continue
        steps = listing([f"{what} on {img} (≈ +{approx(pts)})" for img, what, pts in t.plan])
        if t.reachable:
            out.append(f"{g.label} was {_pts(t.gap)} from {t.label}: {steps} would have covered it.")
        else:
            out.append(f"{g.label} was {_pts(t.gap)} from {t.label}, more than the top quarter's items "
                       f"would have added ({steps}).")
    return out


def _relative(r) -> list[str]:
    """Strengths and weaknesses (#75): images far from each team's overall result."""
    rel = r.focus.relative if r.focus else None
    if not rel:
        return []
    flagged = rel.flagged()
    if not flagged:
        return [f"No image was more than {rel.threshold:.0f} percentile points from any of our teams' overall "
                "results: no clear weak spot this round."]
    out = []
    for team in dict.fromkeys(t for t, _, _ in flagged):
        mine = [(img, gap) for t, img, gap in flagged if t == team]
        weak = [f"{img} ({_diff(gap)})" for img, gap in mine if gap < 0]
        strong = [f"{img} ({_diff(gap)})" for img, gap in mine if gap > 0]
        parts = []
        if weak:
            parts.append(f"weaker on {listing(weak)}")
        if strong:
            parts.append(f"stronger on {listing(strong)}")
        out.append(f"Against its overall result, {team} was {' and '.join(parts)}.")
    return out


def _penalties(r) -> list[str]:
    """Penalties (#78): where our rate was higher than the field's, and the points they cost."""
    rows = r.focus.penalties if r.focus else []
    if not rows:
        return []
    lost = sum(x.ours_lost for x in rows)
    higher = [x for x in rows if x.higher]
    out = []
    if not any(x.ours_with for x in rows):
        out.append("None of our teams took a penalty.")
    elif lost >= 1:
        out.append(f"Penalties cost our teams about {approx(lost)} points together.")
    for x in higher:
        s = (f"On {x.image}, {x.ours_with} of our {x.ours_n} teams took a penalty, against "
             f"{share(100 * x.field_share)} of the field")
        if x.p is not None:
            s += (f": a significant difference (Fisher's exact test, {p_text(x.p)})" if x.p < 0.05
                  else f" (with so few of our teams, not a significant difference: {p_text(x.p)})")
        out.append(s + ".")
    return out


def _challenge(r) -> list[str]:
    if not r.has_challenge or not r.challenge.n:
        return []
    c = r.challenge
    out = [f"The Cisco Networking Challenge (quiz + Packet Tracer) median was {num(c.median)} (middle half "
           f"{num(c.q1)}–{num(c.q3)}, best {num(c.max)}); {r.challenge_attempted} of {c.n} teams scored on it."]
    split = [t for t in r.teams if t.challenge_2 is not None and t.challenge_2 > 0]
    if split:
        quiz = describe(t.challenge_1 for t in r.teams if t.challenge_1 is not None)
        pt = describe(t.challenge_2 for t in r.teams if t.challenge_2 is not None)
        out.append(f"Median quiz {num(quiz.median)} (best {num(quiz.max)}), median Packet Tracer {num(pt.median)} "
                   f"(best {num(pt.max)}).")
    ours = [f"{res.label} {num(res.team.cisco)}"
            + (f" (quiz {num(res.team.challenge_1)}, Packet Tracer {num(res.team.challenge_2)})"
               if res.team.challenge_2 is not None and split else "")
            + f", outscoring {share(res.challenge_percentile)}"
            for res in r.ems if res.team.cisco is not None]
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
        last = max(h)
        mid = max(2, last // 2)
        s = (f"{res.label} outscored {share(h.get(1))} of the field after the first hour, {share(h.get(mid))} at "
             f"{hours(mid)} hours and {share(h.get(last))} at {hours(last)}")
        ahead = [k for k in sorted(h) if h[k] > 50]
        if len(ahead) == len(h):
            s += ", ahead of the median throughout"
        elif not ahead:
            s += ", behind the median throughout"
        elif ahead == list(range(ahead[0], last + 1)):
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
    t = r.tests.get("state")
    if t and t.mw and t.median_a != t.median_b:
        out.append(f"{r.state} scored {'higher' if t.median_a > t.median_b else 'lower'} than the rest of the division "
                   f"(median {num(t.median_a)} vs {num(t.median_b)}): "
                   + (f"a statistically significant difference ({p_text(t.mw.p)})." if t.mw.significant
                      else f"not a statistically significant difference ({p_text(t.mw.p)})."))
    gaps = _image_gaps(r)
    if gaps:
        strong = [g[0] for g in gaps if g[1] > 0.05]
        weak = [g[0] for g in gaps if g[1] < -0.05]
        if strong:
            out.append(f"Our teams were most competitive on {listing(strong)}.")
        if weak:
            out.append(f"Room to grow: {listing(weak)}, where our median completion trailed the field.")
    c = r.focus.cheapest if r.focus else None
    if c and c[1]:
        out.append(f"Most points within reach: {c[0]}, where our teams found a median {_items(c[1])} fewer than the "
                   f"field's top quarter (≈ {approx(c[2])} points).")
    pen = [x for x in (r.focus.penalties if r.focus else []) if x.higher and x.p is not None and x.p < 0.05]
    if pen:
        out.append(f"Watch the penalties on {listing([x.image for x in pen])}: our teams took them more often than "
                   "the field.")
    a = r.attempts
    if a and a.fewer and a.fewer_places and a.most > 1:
        out.append(f"Teams that skipped an image weren't competitive (the best of them placed "
                   f"{ordinal(a.fewer_places[0])}); attempting every image doesn't guarantee a high place, but it's "
                   "the price of entry.")
    if r.time and r.time.test is not None and (not r.time.test.significant or abs(r.time.r) < 0.1):
        out.append(f"Finishing early brought no clear advantage; going past {r.limit // 60} hours costs points.")
    elif r.time and r.time.test is not None and r.time.r > 0:
        out.append(f"Teams that used more of their {r.limit // 60} hours scored higher (ρ = {corr(r.time.r)}, "
                   f"{p_text(r.time.test.p)}): finishing early leaves points on the table.")
    if r.density and r.density.test is not None and not r.density.test.significant:
        out.append(f"The number of teams in a state had no significant relation to its scores "
                   f"(ρ = {corr(r.density.r)}, {p_text(r.density.test.p)}).")
    if r.has_challenge and r.challenge.n:
        out.append(f"Cisco: median {num(r.challenge.median)} of a best {num(r.challenge.max)}, so "
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


def program_narrative(p, sums: list) -> list[str]:
    """Our teams as a program across rounds: are they above the median team, and is it trending?"""
    out = []
    if p is None or not p.n:
        return out
    s = (f"Across {plural(p.n, 'team-round')}, our teams outscored half the division {p.above} times; the median "
         f"team-round outscored {share(p.median_pct)} of the division")
    if p.ci:
        s += f" (95% CI {share(p.ci[0])}–{share(p.ci[1])})"
    if p.test:
        where = "above" if p.median_pct > 50 else "below"
        s += (f". That's significantly {where} the median team (Wilcoxon signed-rank, {p_text(p.test.p)})."
              if p.test.significant else f". That's not significantly different from the median team ({p_text(p.test.p)}).")
    else:
        s += "; too few team-rounds to test."
    out.append(s)
    if p.trend:
        direction = "upward" if p.trend.r > 0 else "downward"
        out.append("Round to round, our median team's percentile shows "
                   + (f"a significant {direction} trend" if p.trend.significant else "no significant trend")
                   + f" (Kendall's τ = {corr(p.trend.r)}, {p_text(p.trend.p)}, {plural(p.trend.n, 'round')})"
                   + ("; later rounds have smaller, qualified fields, which pulls percentiles down." if p.trend.significant
                      and p.trend.r < 0 else "."))
    if p.state_test and sums:
        state = sums[0].state
        out.append(f"{state}'s median team was above the national median team in "
                   f"{sum(1 for s in sums if (s.state_median_pct or 0) > 50)} of {p.state_test.n} rounds; "
                   + ("a significant pattern" if p.state_test.significant else "not a significant pattern")
                   + f" ({p_text(p.state_test.p)}).")
    return out


def strength_narrative(rows: list) -> list[str]:
    """Image families against our overall results, over the rounds (#75): exploratory, so effects first."""
    rows = [f for f in rows if f.n >= 2]
    if not rows:
        return []

    def sentence(f, word: str) -> str:
        weak = f.median < 0
        rounds = f.rounds_below if weak else f.rounds - f.rounds_below
        s = (f"Relative to our overall results, {f.family} was our {word} image family: "
             f"{'below' if weak else 'above'} in {rounds} of {plural(f.rounds, 'round')}, a median "
             f"{_diff(f.median)} percentile points per team-round")
        if f.test and f.p_holm is not None:
            s += (f" (Wilcoxon signed-rank, Holm-adjusted {p_text(f.p_holm)}: "
                  + ("a consistent pattern)" if f.p_holm < 0.05 else "could be chance)"))
        else:
            s += " (too few team-rounds to test)"
        return s + "."

    def notable(f) -> bool:
        return abs(f.median) >= NOTABLE or (f.p_holm is not None and f.p_holm < 0.05)

    out = []
    weakest, strongest = rows[0], rows[-1]   # sorted by median gap
    if weakest.median < 0 and notable(weakest):
        out.append(sentence(weakest, "weakest"))
    if strongest is not weakest and strongest.median > 0 and notable(strongest):
        out.append(sentence(strongest, "strongest"))
    if not out:
        out.append("No image family stood out against our overall results across these rounds.")
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
