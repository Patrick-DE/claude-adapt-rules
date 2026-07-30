"""Keep the transcripts that rules are built on.

Claude Code deletes transcripts after `cleanupPeriodDays` (default 30). Measured
2026-07-26: the oldest file in `~/.claude/projects` was exactly 30 days old, and
three sessions cited by already-distilled rules had been deleted that same day —
their evidence was no longer verifiable.

A rule outlives its transcript, so the evidence has to be archived or the audit
trail rots. Only sessions that actually produced evidence are copied, which keeps
this to a fraction of the full transcript store.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

from .extract import data_dir
from .ledger import Ledger
from .transcripts import iter_session_files, projects_root


def archive_dir(out: Path | None = None) -> Path:
    return (out or data_dir()) / "archive"


def archived_files(out: Path | None = None) -> Iterator[Path]:
    root = archive_dir(out)
    if root.is_dir():
        yield from root.glob("*/*.jsonl")


def cited_sessions(
    ledger: Ledger | None = None, corpus: Path | None = None
) -> set[str]:
    """Session ids referenced by ledger evidence or by the extracted corpus."""
    ids: set[str] = set()
    if ledger is not None:
        for rule in ledger.rules.values():
            ids.update(ev.session[:8] for ev in rule.evidence if ev.session)
    corpus = corpus or (data_dir() / "corpus" / "events.jsonl")
    if corpus.exists():
        with corpus.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                if sid := str(rec.get("session") or ""):
                    ids.add(sid[:8])
    return ids


@dataclass(slots=True)
class ArchiveResult:
    copied: int = 0
    refreshed: int = 0
    skipped: int = 0
    total_bytes: int = 0
    missing: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.missing is None:
            self.missing = []


def archive(
    sessions: Iterable[str] | None = None,
    root: Path | None = None,
    out: Path | None = None,
) -> ArchiveResult:
    """Copy the named sessions (default: every cited one) into the archive.

    Transcripts only ever grow, so an existing copy is refreshed when the live
    file is larger and left alone otherwise.
    """
    wanted = {s[:8] for s in sessions} if sessions is not None else None
    dest_root = archive_dir(out)
    dest_root.mkdir(parents=True, exist_ok=True)

    result = ArchiveResult()
    seen: set[str] = set()
    for path in iter_session_files(root or projects_root()):
        sid = path.stem[:8]
        if wanted is not None and sid not in wanted:
            continue
        seen.add(sid)
        target_dir = dest_root / path.parent.name
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / path.name
        try:
            source_size = path.stat().st_size
            if target.exists():
                if target.stat().st_size >= source_size:
                    result.skipped += 1
                    continue
                shutil.copy2(path, target)
                result.refreshed += 1
            else:
                shutil.copy2(path, target)
                result.copied += 1
            result.total_bytes += source_size
        except OSError:
            continue

    if wanted is not None:
        # Sessions already deleted by cleanup: only recoverable from the archive.
        archived = {p.stem[:8] for p in archived_files(out)}
        result.missing = sorted(wanted - seen - archived)
    return result
