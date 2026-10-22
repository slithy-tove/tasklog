"""Storage layer: every read and write of the data files happens here.

Data directory: ~/.tasklog by default, or the folder named by the TASKLOG_HOME variable.

  index.jsonl    One line per project or task, containing only header fields
                 (id, kind, parent, name, label, status, created). It is small, so it
                 is read on every command, and it is all that `cd` and `ls` need.
  blocks.jsonl   Log of finished time blocks. Starting or stopping a timer appends one
                 line. Only `ID delete` and `ID edit` rewrite it.
  state.json     The "pointer" (current project) and the running timer, if any.
  desc/<id>.txt  Long descriptions, one file per task. Only `tasklog ID desc` reads
                 them, so browsing projects never loads descriptions.
  files/<id>/    Files attached to a task or project with `ID upload`, kept under
                 their original names. Only the upload, download and info commands
                 look here.

Files that must be rewritten (index.jsonl, state.json) are first written to a
temporary file and then renamed over the original, so a crash mid-write cannot
leave a half-written file behind.
"""
from __future__ import annotations

import json
import os
import random
import string
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

from .errors import TasklogError

ID_CHARS = string.ascii_lowercase + string.digits   # alphabet for random IDs
ID_LENGTH = 6                                       # IDs are six characters
DEFAULT_LABEL = "None"
FORMAT_VERSION = "2"                                # see Store._migrate_dots_to_slashes
OPEN = "open"                                       # task status: not finished
COMPLETE = "complete"                               # task status: finished


@dataclass
class Entity:
    """A project or a task.

    `parent` is the dotted path of the containing project; "" means the root.
    A project's own path is therefore `parent + "/" + name` (or just `name` at root).
    """
    id: str
    kind: str                      # "project" or "task"
    parent: str
    name: str
    label: str = DEFAULT_LABEL     # tasks only; one label each
    created: str = ""
    status: Optional[str] = None   # tasks only: OPEN or COMPLETE. Projects leave it None.

    @property
    def path(self) -> str:
        """Full slash-separated path, e.g. 'work/client1'. Only meaningful for projects."""
        return f"{self.parent}/{self.name}" if self.parent else self.name


class Store:
    """Owns every file under the data directory."""

    def __init__(self, home: Optional[str] = None):
        self.home = Path(home or os.environ.get("TASKLOG_HOME") or Path.home() / ".tasklog")
        self.index_path = self.home / "index.jsonl"
        self.blocks_path = self.home / "blocks.jsonl"
        self.state_path = self.home / "state.json"
        self.desc_dir = self.home / "desc"
        self.files_dir = self.home / "files"

    # ---- index: projects and tasks (headers only) ----

    def load_entities(self) -> Dict[str, Entity]:
        """Return every project and task, keyed by ID."""
        entities: Dict[str, Entity] = {}
        if self.index_path.exists():
            with self.index_path.open(encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        entity = Entity(**json.loads(line))
                        entities[entity.id] = entity
            if entities and not self._format_is_current():
                self._migrate_dots_to_slashes(entities)
        return entities

    def save_entities(self, entities: Dict[str, Entity]) -> None:
        """Rewrite the whole index. The index is small, so this is cheap."""
        self.home.mkdir(parents=True, exist_ok=True)
        text = "".join(json.dumps(asdict(e)) + "\n" for e in entities.values())
        _atomic_write(self.index_path, text)
        _atomic_write(self.format_path, FORMAT_VERSION + "\n")

    def new_id(self, entities: Dict[str, Entity]) -> str:
        """Random six-character ID that does not already exist in the index.

        "active" is excluded because it is reserved as the ACTIVE keyword.
        """
        rng = random.SystemRandom()
        while True:
            candidate = "".join(rng.choice(ID_CHARS) for _ in range(ID_LENGTH))
            if candidate not in entities and candidate != "active":
                return candidate

    # ---- format versioning ----
    # Version 1 separated project levels with "."; version 2 uses "/".
    # Data written by version 1 is converted once, the first time it is loaded.

    @property
    def format_path(self) -> Path:
        return self.home / "format"

    def _format_is_current(self) -> bool:
        return self.format_path.exists() and self.format_path.read_text(encoding="utf-8").strip() == FORMAT_VERSION

    def _migrate_dots_to_slashes(self, entities: Dict[str, Entity]) -> None:
        for e in entities.values():
            e.parent = e.parent.replace(".", "/")
        self.save_entities(entities)               # also writes the format marker
        state = self.load_state()
        state["cwd"] = state.get("cwd", "").replace(".", "/")
        self.save_state(state)

    # ---- state: pointer and running timer ----

    def load_state(self) -> dict:
        if self.state_path.exists():
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        return {"cwd": "", "active": None}

    def save_state(self, state: dict) -> None:
        self.home.mkdir(parents=True, exist_ok=True)
        _atomic_write(self.state_path, json.dumps(state, indent=2) + "\n")

    # ---- blocks: finished time ranges ----

    def append_block(self, task_id: str, start: datetime, end: datetime) -> None:
        """Record one finished time block. This only appends a line; nothing is rewritten."""
        self.home.mkdir(parents=True, exist_ok=True)
        line = json.dumps({
            "id": task_id,
            "start": start.isoformat(timespec="seconds"),
            "end": end.isoformat(timespec="seconds"),
        })
        with self.blocks_path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    def iter_blocks(self) -> Iterator[dict]:
        """Yield every finished block with datetime start and end values."""
        if not self.blocks_path.exists():
            return
        with self.blocks_path.open(encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    raw = json.loads(line)
                    yield {
                        "id": raw["id"],
                        "start": datetime.fromisoformat(raw["start"]),
                        "end": datetime.fromisoformat(raw["end"]),
                    }

    def replace_blocks_for(self, task_id: str, blocks: List[Tuple[datetime, datetime]]) -> int:
        """Swap every block of a task for `blocks`; returns how many old blocks were removed.

        Used by `ID edit` and, with an empty list, by `ID delete`. Blocks of other
        tasks are kept byte-for-byte. This rewrites blocks.jsonl, so callers must
        validate `blocks` first.
        """
        kept: List[str] = []
        dropped = 0
        if self.blocks_path.exists():
            with self.blocks_path.open(encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    if json.loads(line)["id"] == task_id:
                        dropped += 1
                    else:
                        kept.append(line if line.endswith("\n") else line + "\n")
        for start, end in blocks:
            kept.append(json.dumps({
                "id": task_id,
                "start": start.isoformat(timespec="seconds"),
                "end": end.isoformat(timespec="seconds"),
            }) + "\n")
        self.home.mkdir(parents=True, exist_ok=True)
        _atomic_write(self.blocks_path, "".join(kept))
        return dropped

    def drop_blocks_for(self, task_id: str) -> int:
        """Remove every block belonging to a task; returns how many were removed."""
        return self.replace_blocks_for(task_id, [])

    # ---- descriptions ----

    def desc_path(self, task_id: str) -> Path:
        return self.desc_dir / f"{task_id}.txt"

    # ---- attached files ----

    def files_path(self, entity_id: str) -> Path:
        """Folder holding the files attached to one task or project."""
        return self.files_dir / entity_id

    def drop_files_for(self, entity_id: str) -> None:
        """Delete every file attached to an item (used when the item is deleted)."""
        folder = self.files_path(entity_id)
        if folder.is_dir():
            for child in folder.iterdir():
                child.unlink()
            folder.rmdir()


def _atomic_write(path: Path, text: str) -> None:
    """Write to a temporary sibling file, then rename it over the target."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
