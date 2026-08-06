"""One-time adoption of state written under an earlier name of this tool.

The state root is derived from the tool's own name, so renaming the tool orphans
everything that already existed: the new root starts empty, ``ingest`` restarts
ids at ``R-0001`` and collides with rules already adopted into ``CLAUDE.md``, the
archive of cited transcripts is stranded where ``verify`` cannot see it, and the
consumed-event markers are lost so every run re-reads the whole queue.

Copy, never move. The legacy root stays as a rollback and gets a marker file
recording that it has been read. Idempotent: once the new root has a ledger this
does nothing, so it is safe to call on every hook invocation.

Rules are copied only where the destination has no file of that name, because
the new root may already hold fresher state -- the session-end hook starts
writing there the moment the new version is installed.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterator
from pathlib import Path

from .atomic import write_text_atomic

# Earlier names of this tool, newest first. Each was ``~/.<name>``.
LEGACY_HOME_NAMES: tuple[str, ...] = ("claude-learn",)

MARKER_NAME = "MIGRATED-TO-CLAUDE-ADAPT-RULES.txt"

# Copied wholesale when absent from the destination.
_COPY_TREES: tuple[str, ...] = (
    "rules",
    "data/archive",
    "data/corpus",
    "data/reports",
)
_COPY_FILES: tuple[str, ...] = ("data/queue/queue.state.json",)

_QUEUE = "data/queue/queue.jsonl"


def legacy_homes() -> Iterator[Path]:
    for name in LEGACY_HOME_NAMES:
        path = Path.home() / f".{name}"
        if path.is_dir():
            yield path


def _copy_missing(src: Path, dst: Path) -> int:
    """Copy every file under ``src`` that ``dst`` does not already have."""
    copied = 0
    for source in src.rglob("*"):
        if not source.is_file():
            continue
        target = dst / source.relative_to(src)
        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied += 1
    return copied


def _queue_key(rec: dict) -> str:
    return f"{rec.get('session')}:{rec.get('uuid')}"


def _read_queue(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    records: list[dict] = []
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            if isinstance(rec, dict):
                records.append(rec)
    return records


def _merge_queues(legacy: Path, current: Path) -> int:
    """Union both queues by (session, record), ordered by timestamp.

    Neither side is authoritative: the legacy queue holds everything captured
    before the rename, the current one everything after.
    """
    existing = _read_queue(current)
    seen: set[str] = set()
    merged: list[dict] = []
    for rec in [*existing, *_read_queue(legacy)]:
        key = _queue_key(rec)
        if key in seen:
            continue
        seen.add(key)
        merged.append(rec)
    added = len(merged) - len(existing)
    if added <= 0:
        return 0
    merged.sort(key=lambda r: str(r.get("ts") or ""))
    write_text_atomic(
        current,
        "".join(json.dumps(rec, ensure_ascii=False) + "\n" for rec in merged),
    )
    return added


def needs_migration(home: Path) -> bool:
    """True when this root has no ledger but a legacy root does."""
    if (home / "rules" / "ledger.json").exists():
        return False
    return any((old / "rules" / "ledger.json").exists() for old in legacy_homes())


def migrate_legacy_home(home: Path | None = None) -> list[str]:
    """Adopt legacy state into ``home``. Returns one note per action taken."""
    if home is None:
        from .extract import home_dir

        home = home_dir()
    if not needs_migration(home):
        return []

    notes: list[str] = []
    for old in legacy_homes():
        if not (old / "rules" / "ledger.json").exists():
            continue
        for rel in _COPY_TREES:
            src = old / rel
            if src.is_dir() and (copied := _copy_missing(src, home / rel)):
                notes.append(f"{rel}: {copied} file(s)")
        for rel in _COPY_FILES:
            src, dst = old / rel, home / rel
            if src.is_file() and not dst.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                notes.append(rel)
        if added := _merge_queues(old / _QUEUE, home / _QUEUE):
            notes.append(f"queue: {added} event(s) merged")
        (old / MARKER_NAME).write_text(
            f"State copied to {home} by claude-adapt-rules.\n"
            "Kept as a rollback; nothing here is read any more.\n",
            encoding="utf-8",
        )
        notes.append(f"read from {old}")
    return notes
