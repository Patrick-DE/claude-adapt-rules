"""Whole-file writes that cannot leave a half-written file behind.

The ledger, the queue and the corpus are each rewritten whole on every save. With
a plain ``write_text`` an interruption mid-write leaves a truncated file, and a
truncated ledger loads as *zero rules* -- after which the next save makes that
permanent and ``next_id`` restarts at 1, colliding with ids already adopted into
CLAUDE.md. Reproduced: 43 rules to 0.

Write to a sibling temp file, flush to disk, then ``os.replace``, which is atomic
on POSIX and on Windows. A reader either sees the old file or the new one.
"""

from __future__ import annotations

import os
from pathlib import Path


def write_text_atomic(path: Path, text: str, encoding: str = "utf-8") -> None:
    """Replace ``path`` with ``text``, or leave it exactly as it was."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        with tmp.open("w", encoding=encoding, newline="") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        # A leftover .tmp would be picked up by nothing, but it would confuse
        # anyone reading the state directory.
        tmp.unlink(missing_ok=True)
        raise
