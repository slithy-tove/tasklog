"""Long-form help text, printed by `tasklog help [TOPIC]`.

Short per-command help comes from argparse (`tasklog COMMAND -h`). These longer
topics explain the concepts. To edit the wording, change the strings below.
"""
from .errors import TasklogError

OVERVIEW = """\
tasklog: an offline, on-demand time tracker. It runs only when you call it,
with no background process, and needs no network.

Concepts
  Projects   Folders that can hold projects and tasks. Projects nest with dots:
             work.client1.website
  Tasks      Things you track time against. Each task has a six-character ID.
  Pointer    The "current project", like a working directory. Change it with cd.
  Label      One optional tag per task (default: None). Used for grouping in reports.

Commands
  tasklog cd [PROJECT]            Move the pointer. No argument goes to root.
  tasklog ls                      List projects and tasks here, with IDs and labels.
  tasklog create -p NAME          Create a project here.       (--project)
  tasklog create -t NAME          Create a task here.          (--task)
  tasklog ID start                Start tracking a task.
  tasklog ID stop                 Stop tracking that task.
  tasklog ID manual START END     Add a finished time block.
  tasklog ID label LABEL          Set the label ("none" clears it).
  tasklog ID desc                 Edit the long description in your editor.
  tasklog ID rename NEW_NAME      Rename a task or project.
  tasklog ID delete [-y]          Delete a task (with its time) or an empty project.
  tasklog report ...              Totals, filters and sweeps. See: tasklog help report
  tasklog help [TOPIC]            Detailed help. Topics: ids, dates, report, storage, cd

Shorthand and long forms are both accepted, for example -p and --project.
Run "tasklog COMMAND -h" for the options of one command.
"""

IDS = """\
Task IDs
  IDs are six random lowercase letters or digits, generated when you create an
  item and checked against existing IDs so they never repeat.

  You can type any unique prefix. If "3f" matches only one task, "3f" is enough:
      tasklog 3f start
  An exact match always wins. If a prefix matches several tasks, tasklog lists
  them and asks for more characters.
"""

DATES = """\
Dates and times
  Times, for `ID manual START END`:
    17:00:00                  today at 17:00:00 (seconds optional, 17:00 also works)
    2026-10-17::17:00:00      an explicit date and time
    today::17:00:00           today, with the given time
    yesterday::17:00:00       yesterday, with the given time
    now                       the current moment

  Days, for `report -d` and `report -dr`:
    2026-10-17, today, yesterday
    "::" and anything after it is ignored here, so today::17:00:00 also works.

  All times are your computer's local time.

  Manual blocks may not overlap time that is already recorded, including a
  running timer. An overlapping request is rejected with the conflicting block.
"""

REPORT = """\
report: totals with filters and sweeps

  Filters narrow which time counts:
    -d, --date DAY [DAY ...]       one or more single days
    -dr, --date-range FROM TO      an inclusive range; cannot be combined with -d
    -l, --label LABEL [...]        tasks with any of these labels
    -t, --task ID [ID ...]         specific tasks (partial IDs accepted)
    -p, --project PROJ [...]       projects, including their subprojects

  Sweeps group the counted time. They can be combined:
    -sd, --sweep-date              one row per day
    -sl, --sweep-label             one row per label
    -sp, --sweep-project           one row per project (the next level below any -p filter)
    -st, --sweep-task              one row per task

  Without sweeps, the report prints one number: the total of the matching time.

  Examples
    tasklog report -d today yesterday -l billing     total for two days, billing label
    tasklog report -p work -sl                       work, split by label
    tasklog report -dr 2026-10-15::today -p work.site -sd
                                                     work.site, one row per day

  Days with no time show as 0 when you use -sd on a day list or range.
  A block that crosses midnight is split between the two days.
  The running timer, if any, counts up to the present moment.
"""

STORAGE = """\
Where your data lives
  Default folder: ~/.tasklog. Set TASKLOG_HOME to use another folder.

  index.jsonl    Project and task headers only: small, read on every command.
  blocks.jsonl   Finished time blocks, appended one line at a time.
  state.json     The pointer and the running timer.
  desc/ID.txt    Long descriptions, read only by `ID desc`.

  Recording time only appends to blocks.jsonl, so it stays fast as history grows.
  The index is rewritten in full when you create items or change labels.
  Everything is plain text, so you can inspect or back it up with normal tools.
"""

CD = """\
cd: moving the pointer
  tasklog cd work            into project "work", relative to where you are
  tasklog cd work.client1    several levels at once
  tasklog cd ..              up one level
  tasklog cd /work           absolute path, from root
  tasklog cd                 back to root

  Every level must already exist. Commands that take a project, such as
  `create`, work relative to the pointer.
"""

TOPICS = {
    "ids": IDS,
    "dates": DATES,
    "report": REPORT,
    "storage": STORAGE,
    "cd": CD,
}


def topic(name=None) -> str:
    """Return the text for a help topic, or the overview when no topic is given."""
    if not name:
        return OVERVIEW
    if name not in TOPICS:
        available = ", ".join(sorted(TOPICS))
        raise TasklogError(f"no help topic '{name}'. Available topics: {available}")
    return TOPICS[name]
