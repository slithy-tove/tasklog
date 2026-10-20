"""Implementations of the commands. Each takes (store, args) and prints its result.

Business rules worth knowing:
  * Only one timer runs at a time. `ID start` on a second task stops the first one at
    that same instant, like timewarrior does.
  * `ID stop` only stops the task you name, so a typo cannot stop the wrong timer.
  * Names are unique among siblings (a project and a task cannot share a name in one place).
  * The keyword ACTIVE can be used wherever a task ID is expected.
  * Projects accept info, desc, rename and delete. Time-tracking verbs (start, stop,
    manual, label) work on tasks only; a project's time is the sum of the tasks inside it.
"""
import os
import shlex
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from typing import Iterable, List, Optional, Tuple

from .errors import TasklogError
from .lookup import display_path, join_path, projects_by_path, resolve_id, resolve_project, validate_name
from .report import _print_table, fmt_duration, run as run_report
from .store import DEFAULT_LABEL, Entity
from .timeparse import parse_datetime


def _now() -> datetime:
    return datetime.now().replace(microsecond=0)


def _resolve(store, entities, text: str, kind: Optional[str] = None) -> Entity:
    """Resolve an ID, partial ID, or ACTIVE using the current state of the timer.

    kind=None accepts tasks and projects; kind="task" accepts tasks only.
    """
    active = store.load_state().get("active")
    return resolve_id(entities, text, kind, active["id"] if active else None)


def _task_only(store, entities, text: str, action: str) -> Entity:
    """Resolve an ID that must refer to a task, with a helpful message for projects."""
    entity = _resolve(store, entities, text)
    if entity.kind != "task":
        raise TasklogError(f"'{entity.name}' is a project; {action} needs a task. "
                           f"Use a task inside the project instead")
    return entity


def _inside(entities: dict, project: Entity) -> List[Entity]:
    """Every project and task below `project`, at any depth."""
    return [e for e in entities.values()
            if e.parent == project.path or e.parent.startswith(project.path + "/")]


def normalize_label(text: str) -> str:
    """Trim a label; empty or 'none' (any case) means the default label."""
    label = text.strip()
    if not label or label.lower() == "none":
        return DEFAULT_LABEL
    return label


def _find_overlap(store, state: dict, start: datetime, end: datetime):
    """Return the first existing block (finished or running) that overlaps [start, end), or None."""
    for blk in store.iter_blocks():
        if start < blk["end"] and end > blk["start"]:
            return blk
    active = state.get("active")
    if active:
        running_start = datetime.fromisoformat(active["start"])
        now = datetime.now()
        if start < now and end > running_start:
            return {"id": active["id"], "start": running_start, "end": now}
    return None


def _close_active(store, state: dict, end: datetime) -> str:
    """Stop the running timer at `end`, record the block, and return the stopped task's ID."""
    active = state["active"]
    start = datetime.fromisoformat(active["start"])
    if end > start:
        store.append_block(active["id"], start, end)
    state["active"] = None
    return active["id"]


# ----- navigation -----

def cmd_cd(store, args) -> None:
    entities = store.load_entities()
    state = store.load_state()
    target = args.project or ""
    new_path = resolve_project(entities, state.get("cwd", ""), target) if target else ""
    state["cwd"] = new_path
    store.save_state(state)
    print(f"Now in {display_path(new_path)}")


def cmd_ls(store, args) -> None:
    entities = store.load_entities()
    cwd = store.load_state().get("cwd", "")
    if cwd and cwd not in projects_by_path(entities):
        raise TasklogError(f"current project '{cwd}' no longer exists; run 'tasklog cd' to return to root")

    children = [e for e in entities.values() if e.parent == cwd]
    # Projects first, then tasks; each group alphabetical.
    children.sort(key=lambda e: (e.kind != "project", e.name.lower()))

    print(display_path(cwd))
    if not children:
        print("  (nothing here yet)")
        return
    print(f"  {'ID':<8}{'TYPE':<10}{'LABEL':<16}NAME")
    for e in children:
        label = e.label if e.kind == "task" else ""
        name = e.name if e.kind == "task" else f"{e.name}/"
        print(f"  {e.id:<8}{e.kind:<10}{label:<16}{name}")


def cmd_create(store, args) -> None:
    entities = store.load_entities()
    cwd = store.load_state().get("cwd", "")
    kind = "project" if args.project is not None else "task"
    name = validate_name(args.project if kind == "project" else args.task)
    if args.label is not None and kind == "project":
        raise TasklogError("labels apply to tasks only; remove -l or create a task")
    label = normalize_label(args.label) if args.label is not None else DEFAULT_LABEL

    if any(e.parent == cwd and e.name == name for e in entities.values()):
        raise TasklogError(f"'{name}' already exists in {display_path(cwd)}")

    entity = Entity(
        id=store.new_id(entities),
        kind=kind,
        parent=cwd,
        name=name,
        label=label,
        created=_now().isoformat(timespec="seconds"),
    )
    entities[entity.id] = entity
    store.save_entities(entities)
    print(f"Created {kind} '{name}' [{entity.id}] in {display_path(cwd)}")


# ----- tracking (ID VERB ...) -----

def cmd_start(store, args) -> None:
    entities = store.load_entities()
    task = _task_only(store, entities, args.id, "tracking time")
    state = store.load_state()
    now = _now()

    active = state.get("active")
    if active:
        if active["id"] == task.id:
            raise TasklogError(f"'{task.name}' is already being tracked")
        previous = entities.get(active["id"])
        _close_active(store, state, now)
        prev_name = previous.name if previous else active["id"]
        print(f"Stopped '{prev_name}' to switch tasks")

    state["active"] = {"id": task.id, "start": now.isoformat(timespec="seconds")}
    store.save_state(state)
    print(f"Started tracking '{task.name}' [{task.id}] at {now.strftime('%H:%M:%S')}")


def cmd_stop(store, args) -> None:
    entities = store.load_entities()
    task = _task_only(store, entities, args.id, "tracking time")
    state = store.load_state()
    active = state.get("active")
    if not active:
        raise TasklogError("nothing is being tracked right now")
    if active["id"] != task.id:
        running = entities.get(active["id"])
        running_name = running.name if running else active["id"]
        raise TasklogError(f"'{task.name}' is not running; '{running_name}' is")

    now = _now()
    start = datetime.fromisoformat(active["start"])
    _close_active(store, state, now)
    store.save_state(state)
    print(f"Stopped '{task.name}' after {fmt_duration(now - start)}")


def cmd_manual(store, args) -> None:
    entities = store.load_entities()
    task = _task_only(store, entities, args.id, "adding time")
    start = parse_datetime(args.start_time)
    end = parse_datetime(args.end_time)
    if end <= start:
        raise TasklogError("END must be after START")
    overlap = _find_overlap(store, store.load_state(), start, end)
    if overlap:
        other = entities.get(overlap["id"])
        other_name = other.name if other else overlap["id"]
        raise TasklogError(
            f"overlaps existing time for '{other_name}' "
            f"({overlap['start'].strftime('%Y-%m-%d %H:%M')} to {overlap['end'].strftime('%Y-%m-%d %H:%M')})")
    store.append_block(task.id, start, end)
    print(f"Added {fmt_duration(end - start)} to '{task.name}' "
          f"({start.isoformat(sep=' ', timespec='minutes')} to {end.isoformat(sep=' ', timespec='minutes')})")


def cmd_label(store, args) -> None:
    entities = store.load_entities()
    task = _task_only(store, entities, args.id, "setting a label")
    label = normalize_label(args.label)   # "none" clears the label
    task.label = label
    entities[task.id] = task
    store.save_entities(entities)
    print(f"Label of '{task.name}' set to {label}")


# ----- details -----

def _block_rows(store, entities: dict, state: dict, task_ids: Iterable[str]) -> List[Tuple]:
    """(task, start, end, running) for every block of the given tasks, oldest first."""
    wanted = set(task_ids)
    rows = [(entities[b["id"]], b["start"], b["end"], False)
            for b in sorted((b for b in store.iter_blocks() if b["id"] in wanted),
                            key=lambda b: b["start"])
            if b["id"] in entities]
    active = state.get("active")
    if active and active["id"] in wanted and active["id"] in entities:
        rows.append((entities[active["id"]], datetime.fromisoformat(active["start"]), _now(), True))
    return rows


def _print_block_table(rows: List[Tuple], with_task: bool) -> None:
    headers = ["START", "END", "DURATION"] + (["TASK"] if with_task else [])
    table = []
    for task, start, end, running in rows:
        line = [start.strftime("%Y-%m-%d %H:%M:%S"),
                end.strftime("%Y-%m-%d %H:%M:%S") + (" (running)" if running else ""),
                fmt_duration(end - start)]
        if with_task:
            line.append(f"{task.name} [{task.id}]")
        table.append(line)
    _print_table(headers, table)


def cmd_info(store, args) -> None:
    """Details for a task, or a summary for a project covering everything inside it.

    The description is not shown; use `ID desc` for it.
    """
    entities = store.load_entities()
    item = _resolve(store, entities, args.id)
    state = store.load_state()
    active = state.get("active")
    now_running_id = active["id"] if active else None

    if item.kind == "task":
        rows = _block_rows(store, entities, state, [item.id])
        running = now_running_id == item.id
        total = sum((end - start for _, start, end, _ in rows), timedelta(0))
        print(f"Task:     {item.name} [{item.id}]")
        print(f"Project:  {display_path(item.parent)}")
        print(f"Label:    {item.label}")
        print(f"Created:  {item.created}")
        print(f"Status:   {'running' if running else 'stopped'}")
        print(f"Total:    {fmt_duration(total)}")
        print(f"Blocks:   {len(rows)}")
        if rows:
            print()
            _print_block_table(rows, with_task=False)
        return

    # Project: everything below it, at any depth.
    members = _inside(entities, item)
    task_ids = [e.id for e in members if e.kind == "task"]
    rows = _block_rows(store, entities, state, task_ids)
    total = sum((end - start for _, start, end, _ in rows), timedelta(0))
    n_tasks = len(task_ids)
    n_projects = len(members) - n_tasks
    running = now_running_id in task_ids

    print(f"Project:  {item.name} [{item.id}]")
    print(f"Path:     {display_path(item.path)}")
    print(f"Contents: {n_tasks} task(s), {n_projects} subproject(s)")
    print(f"Created:  {item.created}")
    print(f"Status:   {'a task inside is running' if running else 'nothing running'}")
    print(f"Total:    {fmt_duration(total)}")
    print(f"Blocks:   {len(rows)}")
    if rows:
        print()
        _print_block_table(rows, with_task=True)


def cmd_desc(store, args) -> None:
    entities = store.load_entities()
    item = _resolve(store, entities, args.id, kind=None)
    store.desc_dir.mkdir(parents=True, exist_ok=True)
    path = store.desc_path(item.id)
    path.touch(exist_ok=True)

    editor = _pick_editor()
    result = subprocess.run([*shlex.split(editor), str(path)])
    if result.returncode != 0:
        raise TasklogError(f"editor '{editor}' exited with status {result.returncode}; description not confirmed")
    print(f"Description of '{item.name}' saved ({path})")


def _pick_editor() -> str:
    """$VISUAL, then $EDITOR, then vim (falling back to vi if vim is not installed)."""
    for var in ("VISUAL", "EDITOR"):
        if os.environ.get(var):
            return os.environ[var]
    if os.name == "nt":
        return "notepad"
    for candidate in ("vim", "vi"):
        if shutil.which(candidate):
            return candidate
    raise TasklogError("no editor found; set the EDITOR environment variable")


# ----- reporting -----

def cmd_report(store, args) -> None:
    run_report(store, args)


# ----- editing items (ID rename / ID delete) -----

def _relocate_project(store, entities: dict, project: Entity, new_parent: str, new_name: str) -> None:
    """Give a project a new parent and/or name, and update everything that lives inside it.

    Items inside store their parent as a path string, so their paths are rewritten.
    If the pointer is inside the project, it follows the project.
    """
    old_path = project.path
    new_path = join_path(new_parent, new_name)
    for e in entities.values():
        if e.id != project.id and (e.parent == old_path or e.parent.startswith(old_path + "/")):
            e.parent = new_path + e.parent[len(old_path):]
    project.parent = new_parent
    project.name = new_name

    state = store.load_state()
    cwd = state.get("cwd", "")
    if cwd == old_path or cwd.startswith(old_path + "/"):
        state["cwd"] = new_path + cwd[len(old_path):]
        store.save_state(state)


def cmd_rename(store, args) -> None:
    """Rename a task or project. Renaming a project also updates every path below it."""
    entities = store.load_entities()
    entity = _resolve(store, entities, args.id, kind=None)
    new_name = validate_name(args.new_name)
    if any(e.parent == entity.parent and e.name == new_name and e.id != entity.id
           for e in entities.values()):
        raise TasklogError(f"'{new_name}' already exists in {display_path(entity.parent)}")

    old_name = entity.name
    if entity.kind == "project":
        _relocate_project(store, entities, entity, entity.parent, new_name)
    else:
        entity.name = new_name
    entities[entity.id] = entity
    store.save_entities(entities)
    print(f"Renamed {entity.kind} '{old_name}' to '{new_name}' [{entity.id}]")


def cmd_move(store, args) -> None:
    """Move a task or project into another project.

    The destination is a project path, resolved like `cd` (relative to the pointer,
    a leading '/' from root, '..' for the parent). A project cannot move into itself.
    """
    entities = store.load_entities()
    item = _resolve(store, entities, args.id, kind=None)
    state = store.load_state()
    dest = resolve_project(entities, state.get("cwd", ""), args.destination)

    if dest == item.parent:
        raise TasklogError(f"'{item.name}' is already in {display_path(dest)}")
    if item.kind == "project" and (dest == item.path or dest.startswith(item.path + "/")):
        raise TasklogError(f"cannot move project '{item.name}' into itself")
    if any(e.parent == dest and e.name == item.name and e.id != item.id for e in entities.values()):
        raise TasklogError(f"'{item.name}' already exists in {display_path(dest)}")

    if item.kind == "project":
        _relocate_project(store, entities, item, dest, item.name)
    else:
        item.parent = dest
    entities[item.id] = item
    store.save_entities(entities)
    print(f"Moved {item.kind} '{item.name}' [{item.id}] to {display_path(dest)}")


def cmd_delete(store, args) -> None:
    """Delete a task (with its time blocks) or an empty project. Descriptions are removed too."""
    entities = store.load_entities()
    entity = _resolve(store, entities, args.id, kind=None)
    state = store.load_state()

    if entity.kind == "project":
        inside = _inside(entities, entity)
        if inside:
            raise TasklogError(f"project '{entity.name}' still contains {len(inside)} item(s); "
                               f"delete those first")
        detail = ""
    else:
        blocks = sum(1 for b in store.iter_blocks() if b["id"] == entity.id)
        detail = f" and its {blocks} time block(s)"

    if not args.yes:
        if not sys.stdin.isatty():
            raise TasklogError("refusing to delete without confirmation; add -y or --yes")
        answer = input(f"Delete {entity.kind} '{entity.name}' [{entity.id}]{detail}? [y/N] ")
        if answer.strip().lower() not in ("y", "yes"):
            print("Cancelled.")
            return

    # A running timer on a deleted task is discarded, not recorded.
    active = state.get("active")
    if active and active["id"] == entity.id:
        state["active"] = None
    # If the pointer is inside a deleted project, move it up to that project's parent.
    if entity.kind == "project":
        cwd = state.get("cwd", "")
        if cwd == entity.path or cwd.startswith(entity.path + "/"):
            state["cwd"] = entity.parent

    del entities[entity.id]
    store.save_entities(entities)
    if entity.kind == "task":
        store.drop_blocks_for(entity.id)
    store.desc_path(entity.id).unlink(missing_ok=True)
    store.save_state(state)
    print(f"Deleted {entity.kind} '{entity.name}' [{entity.id}]")
