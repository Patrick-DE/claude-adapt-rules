#!/usr/bin/env python3
"""SessionEnd capture entry point. Reads the hook payload on stdin.

Python rather than a shell script so one file covers Windows, macOS and Linux.

Contract: always exit 0, never write to stderr. A capture step that can fail is a
capture step that breaks unrelated work in every project. Failures land in
``<home>/data/hook.log``.
"""

from __future__ import annotations

import json
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def main() -> int:
    out = None
    try:
        from claude_adapt_rules.extract import data_dir, queue_transcript

        out = data_dir()
        raw = sys.stdin.read()
        if not raw.strip():
            return 0
        # PowerShell's pipeline prepends a UTF-8 BOM, which json.loads rejects with
        # "Unexpected UTF-8 BOM". Observed in data/hook.log on Windows.
        payload = json.loads(raw.lstrip("﻿"))
        transcript = payload.get("transcript_path")
        if not transcript:
            return 0
        path = Path(transcript)
        if not path.is_file():
            return 0
        queue_transcript(path, out=out)
    except Exception:  # noqa: BLE001 - deliberate, see contract above
        try:
            target = out or Path.home() / ".claude-adapt-rules" / "data"
            target.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(tz=timezone.utc).isoformat(timespec="seconds")
            with (target / "hook.log").open("a", encoding="utf-8") as fh:
                fh.write(f"[{stamp}] capture failed\n{traceback.format_exc()}")
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
