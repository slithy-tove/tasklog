"""Name validation, project-path resolution, and ID matching.

Project paths use "/" between levels, like a file system:
  work            a top-level project
  work/client1    a subproject of work
  /work/client1   the same, written from the root (a leading "/" means "from root")

Partial IDs: any unique prefix of an ID is accepted ("3f" works if only one ID starts
with "3f"). An exact match always wins.

The keyword ACTIVE refers to the currently running task, wherever a task ID is expected.
"""
from typing import Dict, Optional

from .errors import TasklogError
from .store import Entity

SEP = "/"                 # separator between project levels
ACTIVE_KEYWORD = "active" # shorthand for the running task


def validate_name(name: str) -> str:
    """Reject names that would break paths or the command syntax."""
    name = name.strip()
    if not name:
        raise TasklogError("name cannot be empty")
    if SEP in name:
        raise TasklogError(f"name '{name}' cannot contain '{SEP}'")
    if ":" in name:
        raise TasklogError(f"name '{name}' cannot contain ':'")
    if name in (".", ".."):
        raise TasklogError(f"name cannot be '{name}'")
    return name


def projects_by_path(entities: Dict[str, Entity]) -> Dict[str, Entity]:
    """Map each project's path (e.g. 'work/client1') to its entity."""
    return {e.path: e for e in entities.values() if e.kind == "project"}


def display_path(path: str) -> str:
    return path if path else "(root)"


def join_path(parent: str, name: str) -> str:
    """Path of a child named `name` inside `parent` ("" is the root)."""
    return f"{parent}{SEP}{name}" if parent else name


def resolve_project(entities: Dict[str, Entity], base: str, target: str) -> str:
    """Turn a `cd` argument into an absolute project path.

    - A leading "/" starts from the root; otherwise the path is relative to `base`.
    - ".." goes up one level; "." stays put.
    - Every named level must already exist as a project.
    """
    projects = projects_by_path(entities)
    if target.startswith(SEP):
        current = ""
        target = target[1:]
    else:
        current = base

    target = target.rstrip(SEP)          # allow a trailing slash: "work/"
    parts = target.split(SEP) if target else []
    for part in parts:
        if part == "":
            raise TasklogError(f"malformed project path '{target}'")
        if part == ".":
            continue
        if part == "..":
            current = current.rpartition(SEP)[0]   # "a/b" -> "a"; "a" -> ""
            continue
        child = f"{current}{SEP}{part}" if current else part
        if child not in projects:
            raise TasklogError(f"no project named '{part}' under {display_path(current)}")
        current = child
    return current


def resolve_id(entities: Dict[str, Entity], text: str, kind: Optional[str] = "task",
               active_id: Optional[str] = None) -> Entity:
    """Find an entity by full ID, partial ID, or the ACTIVE keyword.

    kind="task" or "project" restricts the search to that kind; kind=None searches both.
    active_id is the ID of the running task, used to resolve the ACTIVE keyword.
    """
    needle = text.strip().lower()

    if needle == ACTIVE_KEYWORD:
        if active_id is None or active_id not in entities:
            raise TasklogError("nothing is being tracked right now")
        entity = entities[active_id]
        return entity

    candidates = [e for e in entities.values() if kind is None or e.kind == kind]

    for e in candidates:
        if e.id == needle:
            return e

    matches = [e for e in candidates if needle and e.id.startswith(needle)]
    if not matches:
        label = kind or "item"
        raise TasklogError(f"no {label} matches ID '{text}'")
    if len(matches) > 1:
        listing = "\n".join(f"  {e.id}  {e.name}" for e in matches)
        raise TasklogError(f"ID '{text}' is ambiguous; it matches:\n{listing}\n"
                           f"type more characters to narrow it down")
    return matches[0]
