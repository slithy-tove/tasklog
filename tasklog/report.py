"""The `report` command: sums time blocks, with optional filters and "sweeps".

Terminology:
  filter  narrows which blocks count (-d, -dr, -l, -t, -p).
  sweep   groups the counted time by a dimension (-sd, -sl, -sp, -st).
          Sweeps can be combined; the output is one row per combination.

With no sweeps, the report prints one number: the total of all matching time.

Blocks that cross midnight are split at day boundaries, so each day's share is
counted on the correct day, both for -sd and for -d/-dr filtering.
"""
from collections import defaultdict
from datetime import datetime, time, timedelta
from typing import Dict, Iterator, List, Optional, Tuple

from .errors import TasklogError
from .lookup import projects_by_path, resolve_id
from .store import Entity
from .timeparse import parse_day

SWEEP_ORDER = ("date", "label", "project", "task")


def fmt_duration(td: timedelta) -> str:
    """Format as H:MM:SS (hours are not capped at 24)."""
    total = int(td.total_seconds())
    hours, rem = divmod(total, 3600)
    minutes, seconds = divmod(rem, 60)
    return f"{hours}:{minutes:02d}:{seconds:02d}"


def split_by_day(start: datetime, end: datetime) -> Iterator[Tuple]:
    """Yield (day, piece_start, piece_end) for each calendar day the block touches."""
    cur = start
    while cur < end:
        next_midnight = datetime.combine(cur.date() + timedelta(days=1), time(0))
        piece_end = min(end, next_midnight)
        yield cur.date(), cur, piece_end
        cur = piece_end


def project_key(parent: str, filters: Optional[List[str]]) -> Optional[str]:
    """Decide which project group a task's time belongs to.

    No -p filters: the task's own project (or "(root)").
    With -p filters: the matching filter. If the task sits in a subproject of
    that filter, the next level down is used, so `-p project1 -sp` shows the
    direct tasks of project1 and each subproject as its own row.
    Returns None when the task matches none of the filters.
    """
    if filters is None:
        return parent or "(root)"
    matches = [f for f in filters if parent == f or parent.startswith(f + ".")]
    if not matches:
        return None
    best = max(matches, key=len)          # the most specific filter wins
    if parent == best:
        return best
    next_level = parent[len(best) + 1:].split(".")[0]
    return f"{best}.{next_level}"


def _normalize_project(text: str, entities: Dict[str, Entity]) -> str:
    """Accept 'project1.sub' or '/project1.sub' (a leading slash is optional)."""
    path = text.strip().strip("/").strip(".")
    if path not in projects_by_path(entities):
        raise TasklogError(f"no project named '{text}'")
    return path


def _print_table(headers: List[str], rows: List[List[str]]) -> None:
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))
    line = "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers))
    print(line)
    print("  ".join("-" * w for w in widths))
    for row in rows:
        # Right-align the TIME column (last); left-align the rest.
        cells = [c.ljust(widths[i]) if i < len(row) - 1 else c.rjust(widths[i])
                 for i, c in enumerate(row)]
        print("  ".join(cells))


def run(store, args) -> None:
    """Entry point for `tasklog report`. `args` is the parsed argparse namespace."""
    entities = store.load_entities()

    # ----- filters -----
    days = None                                       # None means "all days"
    if args.date:
        days = {parse_day(d) for d in args.date}
    if args.date_range:
        first, last = (parse_day(x) for x in args.date_range)
        if last < first:
            raise TasklogError("the second date of -dr must not be before the first")
        days = {first + timedelta(n) for n in range((last - first).days + 1)}

    label_set = {x.strip().lower() for x in args.label} if args.label else None
    task_ids = {resolve_id(entities, t).id for t in args.task} if args.task else None
    project_filters = [_normalize_project(p, entities) for p in args.project] if args.project else None

    # ----- gather blocks, including a running timer counted up to now -----
    blocks = list(store.iter_blocks())
    state = store.load_state()
    active = state.get("active")
    if active:
        blocks.append({
            "id": active["id"],
            "start": datetime.fromisoformat(active["start"]),
            "end": datetime.now(),
        })

    # ----- sweeps, in the fixed order used for output columns -----
    flags = {"date": args.sweep_date, "label": args.sweep_label,
             "project": args.sweep_project, "task": args.sweep_task}
    sweeps = [name for name in SWEEP_ORDER if flags[name]]

    totals: Dict[tuple, timedelta] = defaultdict(lambda: timedelta(0))

    # With only -sd and explicit days, show every requested day, even zero-time ones.
    if sweeps == ["date"] and days:
        for d in days:
            totals[(d.isoformat(),)] = timedelta(0)

    for blk in blocks:
        ent = entities.get(blk["id"])
        if ent is None:
            continue
        if task_ids is not None and ent.id not in task_ids:
            continue
        if label_set is not None and ent.label.lower() not in label_set:
            continue
        proj = project_key(ent.parent, project_filters)
        if proj is None:
            continue

        for day, piece_start, piece_end in split_by_day(blk["start"], blk["end"]):
            if days is not None and day not in days:
                continue
            values = {
                "date": day.isoformat(),
                "label": ent.label,
                "project": proj,
                "task": f"{ent.name} [{ent.id}]",
            }
            key = tuple(values[s] for s in sweeps)
            totals[key] += piece_end - piece_start

    # ----- output -----
    if not sweeps:
        print(fmt_duration(sum(totals.values(), timedelta(0))))
        return

    if not totals:
        print("No time recorded for these filters.")
        return

    rows = [list(key) + [fmt_duration(value)] for key, value in sorted(totals.items())]
    if len(totals) > 1:
        grand = sum(totals.values(), timedelta(0))
        rows.append(["TOTAL"] + [""] * (len(sweeps) - 1) + [fmt_duration(grand)])
    headers = [s.upper() for s in sweeps] + ["TIME"]
    _print_table(headers, rows)
