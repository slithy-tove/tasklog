"""Storage layer: every read and write of the data files happens here.

Data directory: ~/.tasklog by default, or the folder named by the TASKLOG_HOME variable.

  index.jsonl    One line per project or task, containing only header fields
                 (id, kind, parent, name, label, created). It is small, so it is
                 read on every command, and it is all that `cd` and `ls` need.
  blocks.jsonl   Append-only log of finished time blocks. Starting or stopping a
                 timer appends one line; existing history is never rewritten, so the
                 cost of recording time does not grow with the amount of history.
  state.json     The "pointer" (current project) and the running timer, if any.
  desc/<id>.txt  Long descriptions, one file per task. Only `tasklog ID desc` reads
                 them, so browsing projects never loads descriptions.

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
from typing import Dict, Iterator, Optional

from .errors import TasklogError

ID_CHARS = string.ascii_lowercase + string.digits   # alphabet for random IDs
ID_LENGTH = 6                                       # IDs are six characters
DEFAULT_LABEL = "None"


@dataclass
class Entity:
    """A project or a task.

    `parent` is the dotted path of the containing project; "" means the root.
    A project's own path is therefore `parent + "." + name` (or just `name` at root).
    """
    id: str
    kind: str                      # "project" or "task"
    parent: str
    name: str
    label: str = DEFAULT_LABEL     # tasks only; one label each
    created: str = ""

    @property
    def path(self) -> str:
        """Full dotted path. Only meaningful for projects."""
        return f"{self.parent}.{self.name}" if self.parent else self.name


class Store:
    """Owns every file under the data directory."""

    def __init__(self, home: Optional[str] = None):
        self.home = Path(home or os.environ.get("TASKLOG_HOME") or Path.home() / ".tasklog")
        self.index_path = self.home / "index.jsonl"
        self.blocks_path = self.home / "blocks.jsonl"
        self.state_path = self.home / "state.json"
        self.desc_dir = self.home / "desc"

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
        return entities

    def save_entities(self, entities: Dict[str, Entity]) -> None:
        """Rewrite the whole index. The index is small, so this is cheap."""
        self.home.mkdir(parents=True, exist_ok=True)
        text = "".join(json.dumps(asdict(e)) + "\n" for e in entities.values())
        _atomic_write(self.index_path, text)

    def new_id(self, entities: Dict[str, Entity]) -> str:
        """Random six-character ID that does not already exist in the index."""
        rng = random.SystemRandom()
        while True:
            candidate = "".join(rng.choice(ID_CHARS) for _ in range(ID_LENGTH))
            if candidate not in entities:
                return candidate

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

    def drop_blocks_for(self, task_id: str) -> int:
        """Remove every block belonging to a task; returns how many were removed.

        Used only by `ID delete`. This is the one place where blocks.jsonl is rewritten.
        """
        if not self.blocks_path.exists():
            return 0
        kept, dropped = [], 0
        with self.blocks_path.open(encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                if json.loads(line)["id"] == task_id:
                    dropped += 1
                else:
                    kept.append(line if line.endswith("\n") else line + "\n")
        _atomic_write(self.blocks_path, "".join(kept))
        return dropped

    # ---- descriptions ----

    def desc_path(self, task_id: str) -> Path:
        return self.desc_dir / f"{task_id}.txt"


def _atomic_write(path: Path, text: str) -> None:
    """Write to a temporary sibling file, then rename it over the target."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
