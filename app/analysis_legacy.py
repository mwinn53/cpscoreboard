"""Import the legacy analysis CSVs (CP-XI to CP-XIV) as historical round samples.

The old Python scraper wrote one CSV per round and division, named like
``CP-XIV Round 1 Middle School Division_scores_final.csv`` (``_prelim`` for
preliminary scores; older files have no suffix and count as final), plus a matching
``…_times_….csv`` with each team's 5-minute score history per image.

Score files have one row per team: ``TeamNumber``, ``State``, ``Division``,
``OverallPlace``, ``StatePlace``, ``PlayTime``, ``ScoredImages``,
``CurrentScore``/``TotalScore``, ``CiscoScore``, ``Adjust``, ``ChallengeScore``,
``TeamName`` and, per image, ``<image>-Found/-Remaining/-Penalties/-Score/-Time``.

Local grouping: the old files put a name on the district's teams. Other schools
are school abbreviations (``GTMS``, ``SIMS``…), and our own teams carry their team
names (``Tax Collectors V2``…), so a name that isn't an ``…MS`` abbreviation is an
EMS team.

Rows that don't parse (some files have shifted columns) are skipped and counted.
A file whose name says one round while its images say another (e.g. a "State Round"
file holding Round 2's images) is refused rather than filed under the wrong round.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime

from .analysis_store import (DISTRICT, EMS, FINAL, LEGACY, PRELIMINARY, ImageRow, Sample, TeamRow, parse_image_name,
                             roman, round_identity)
from .scraper import parse_hms

NAME_RE = re.compile(r"^CP-?([IVXLC]+|\d+)\s+(.+)\s+(Middle School|High School|Open|All Service|[A-Z]+JROTC|CAP)"
                     r" Division"
                     r"(?:_(scores|times2?)(?:_(final|prelim))?)?\.csv$", re.IGNORECASE)
TEAM_RE = re.compile(r"^\d{2}-\d{4}$")
SCHOOL_ABBR_RE = re.compile(r"^[A-Z]{1,5}MS$")
LABEL_KEYS = {"round 1": "r1", "round 2": "r2", "round 3": "r3", "state round": "state", "state": "state",
              "semi-finals": "sf", "semi-final round": "sf", "semifinal": "sf", "semifinals": "sf",
              "semi-final": "sf", "national finals": "nf"}


@dataclass
class ParsedName:
    season: int
    label: str
    division: str
    kind: str      # scores / times
    status: str    # preliminary / final


def parse_name(filename: str) -> ParsedName | None:
    m = NAME_RE.match(filename.strip())
    if not m:
        return None
    s = m.group(1)
    season = int(s) if s.isdigit() else roman(s)
    kind = "times" if (m.group(4) or "").startswith("times") else "scores"
    return ParsedName(season, m.group(2).strip(), m.group(3).strip(), kind,
                      PRELIMINARY if m.group(5) == "prelim" else FINAL)


def _num(v) -> float | None:
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return None


def _int(v) -> int | None:
    f = _num(v)
    return int(f) if f is not None else None


def _hms(v) -> int | None:
    text = (v or "").strip()
    if not text:
        return None
    if text.count(":") == 1:  # "5:38" (hours:minutes) in the per-image columns, "05:39" in older PlayTime
        text += ":00"
    return parse_hms(text)


def group_of(name: str) -> str:
    if not name:
        return ""
    return DISTRICT if SCHOOL_ABBR_RE.match(name) else EMS


@dataclass
class FileResult:
    filename: str
    message: str
    ok: bool = False
    skipped_rows: int = 0


@dataclass
class ImportResult:
    samples: list[Sample] = field(default_factory=list)
    files: list[FileResult] = field(default_factory=list)


def _read(data: bytes) -> list[dict]:
    text = data.decode("utf-8-sig", errors="replace")
    return list(csv.DictReader(io.StringIO(text)))


def parse_scores(data: bytes, division: str) -> tuple[list[TeamRow], list[ImageRow], int]:
    rows = _read(data)
    teams, images, skipped, seen = [], [], 0, set()
    for r in rows:
        number = (r.get("TeamNumber") or "").strip()
        current = _num(r.get("CurrentScore"))
        if r.get("Division") != division or not TEAM_RE.match(number) or current is None or number in seen:
            skipped += 1
            continue
        seen.add(number)
        name = (r.get("TeamName") or "").strip()
        code = (r.get("*Warn") or r.get("**") or "").strip()
        teams.append(TeamRow(
            team_number=number, location=(r.get("State") or "").strip(), tier=(r.get("Tier") or "").strip(),
            name=name, grp=group_of(name), images=_int(r.get("ScoredImages")), play_time=_hms(r.get("PlayTime")),
            ccs_score=current, challenge_1=_num(r.get("CiscoScore")), challenge_2=_num(r.get("ChallengeScore")),
            adjustment=_num(r.get("Adjust")), total=_num(r.get("TotalScore")), code=code,
            place_division=_int(r.get("OverallPlace")), place_state_division=_int(r.get("StatePlace"))))
        for key in r:
            if not key or not key.endswith("-Found"):
                continue
            full = key[:-len("-Found")]
            found = _int(r.get(f"{full}-Found"))
            score = _num(r.get(f"{full}-Score"))
            if found is None and score is None:
                continue  # image not attempted
            short, _, _ = parse_image_name(full)
            images.append(ImageRow(team_number=number, image=short, image_full=full, found=found,
                                   remaining=_int(r.get(f"{full}-Remaining")), penalties=_int(r.get(f"{full}-Penalties")),
                                   score=score, duration=_hms(r.get(f"{full}-Time")),
                                   code=(r.get(f"{full}-Warn") or r.get(f"{full}-**") or "").strip()))
    return teams, images, skipped


TOTAL = "Total"  # pseudo-image: a team's total at that time, when its per-image columns can't be trusted


def parse_times(data: bytes, season: int) -> tuple[list[tuple[str, str, datetime, float]], int]:
    """Timeline rows: Time (1900-MM-DD HH:MM:SS; the year is a placeholder), one column per image, Team.

    The old files were stitched together per team, so a team that attempted fewer
    images has its values shifted left under the wrong headers, with the team number
    earlier in the row. Rows that line up give per-image points; shifted rows give
    only the team's total (the sum of its values) as the ``Total`` pseudo-image.
    """
    text = data.decode("utf-8-sig", errors="replace")
    rows = list(csv.reader(io.StringIO(text)))
    if not rows or "Time" not in rows[0]:
        return [], len(rows)
    header = rows[0]
    t_col = header.index("Time")
    team_col = header.index("Team") if "Team" in header else len(header) - 1
    image_cols = [(i, parse_image_name(h)[0]) for i, h in enumerate(header) if "_cp" in h]
    out, skipped = [], 0
    for row in rows[1:]:
        teams = [i for i, v in enumerate(row) if TEAM_RE.match(v.strip())]
        if len(row) <= t_col or not teams:
            skipped += 1
            continue
        try:
            t = datetime.fromisoformat(row[t_col].strip())
        except ValueError:
            skipped += 1
            continue
        t = t.replace(year=2007 + season if t.month >= 8 else 2008 + season, tzinfo=UTC)  # CP-14: Oct 2021-Mar 2022
        team_at = teams[-1]
        team = row[team_at].strip()
        if team_at == team_col:
            for i, short in image_cols:
                v = _num(row[i]) if i < len(row) else None
                if v is not None:
                    out.append((team, short, t, v))
        else:
            values = [_num(v) for v in row[t_col + 1:team_at]]
            values = [v for v in values if v is not None]
            if values:
                out.append((team, TOTAL, t, sum(values)))
    return out, skipped


def import_files(files: list[tuple[str, bytes]], now: datetime | None = None) -> ImportResult:
    """Build samples from uploaded files (score files, each with its optional times file)."""
    result = ImportResult()
    times = {}
    for name, data in files:
        parsed = parse_name(name)
        if parsed and parsed.kind == "times":
            times.setdefault((parsed.season, parsed.label.lower(), parsed.division, parsed.status), (name, data))
    for name, data in files:
        parsed = parse_name(name)
        if parsed is None:
            result.files.append(FileResult(name, "skipped: the name isn't like "
                                           "'CP-XIV Round 1 Middle School Division_scores_final.csv'"))
            continue
        if parsed.kind == "times":
            continue
        teams, images, skipped = parse_scores(data, parsed.division)
        if not teams:
            result.files.append(FileResult(name, f"skipped: no {parsed.division} teams found", skipped_rows=skipped))
            continue
        season, round_key = round_identity({i.image_full for i in images}, [t.team_number for t in teams])
        named_key = LABEL_KEYS.get(parsed.label.lower())
        round_key = round_key or named_key or parsed.label.lower().replace(" ", "_")
        if named_key and named_key != round_key:
            result.files.append(FileResult(
                name, f"skipped: the name says {parsed.label}, but its images are from round '{round_key}' "
                      f"(a copy of another round?)", skipped_rows=skipped))
            continue
        timeline, t_skipped, t_note = [], 0, ""
        tfile = times.get((parsed.season, parsed.label.lower(), parsed.division, parsed.status))
        if tfile:
            timeline, t_skipped = parse_times(tfile[1], parsed.season)
            t_note = f"; {len(timeline)} timeline points from {tfile[0]}"
        result.samples.append(Sample(
            season=season or parsed.season, round_key=round_key, division=parsed.division, status=parsed.status,
            source=LEGACY, sampled_at=now or datetime.now(UTC), teams=teams, images=images, timeline=timeline,
            label=parsed.label.replace("Semi-Finals", "Semifinal").replace("Semi-Final Round", "Semifinal")))
        result.files.append(FileResult(name, f"{len(teams)} teams, {len(images)} image rows{t_note}", ok=True,
                                       skipped_rows=skipped + t_skipped))
    return result
