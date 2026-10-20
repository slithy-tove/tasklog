"""Name validation, project-path resolution, and ID matching.

Partial IDs: any unique prefix of an ID is accepted. "3f" works if only one task
ID starts with "3f". An exact match always wins, even if it is also a prefix of
another ID.
"""
from typing import Dict, Optional

from .errors import TasklogError
from .store import Entity


def validate_name(name: str) -> str:
    """Reject names that would break dotted paths or the command syntax."""
    name = name.strip()
    if not name:
        raise TasklogError("name cannot be empty")
    for bad in (".", "/", ":"):
        if bad in name:
            raise TasklogError(f"name '{name}' cannot contain '{bad}'")
    return name


def projects_by_path(entities: Dict[str, Entity]) -> Dict[str, Entity]:
    """Map each project's dotted path to its entity."""
    return {e.path: e for e in entities.values() if e.kind == "project"}


def display_path(path: str) -> str:
    return path if path else "(root)"


def resolve_project(entities: Dict[str, Entity], base: str, target: str) -> str:
    """Turn a `cd` argument into an absolute project path.

    - A leading "/" starts from the root; otherwise the path is relative to `base`.
    - Dots separate levels: "work.client1" enters client1 inside work.
    - ".." goes up one level; "." stays put.
    - Every level must already exist as a project.
    """
    projects = projects_by_path(entities)
    if target.startswith("/"):
        current = ""
        target = target[1:]
    else:
        current = base

    parts = target.split(".") if target else []
    for part in parts:
        if part == "":
            raise TasklogError(f"malformed project path '{target}'")
        if part == ".":
            continue
        if part == "..":
            current = current.rpartition(".")[0]   # "a.b" -> "a"; "a" -> ""
            continue
        child = f"{current}.{part}" if current else part
        if child not in projects:
            raise TasklogError(f"no project named '{part}' under {display_path(current)}")
        current = child
    return current


def resolve_id(entities: Dict[str, Entity], text: str, kind: Optional[str] = "task") -> Entity:
    """Find an entity by full or partial ID.

    kind="task" or "project" restricts the search to that kind; kind=None searches both.
    """
    needle = text.strip().lower()
    candidates = [e for e in entities.values() if kind is None or e.kind == kind]

    for e in candidates:
        if e.id == needle:
            return e

    matches = [e for e in candidates if needle and e.id.startswith(needle)]
    if not matches:
        raise TasklogError(f"no {kind} matches ID '{text}'")
    if len(matches) > 1:
        listing = "\n".join(f"  {e.id}  {e.name}" for e in matches)
        raise TasklogError(f"ID '{text}' is ambiguous; it matches:\n{listing}\n"
                           f"type more characters to narrow it down")
    return matches[0]
