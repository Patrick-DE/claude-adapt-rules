#!/usr/bin/env python3
"""SessionStart hook: inject this project's learned rules as session context.

Reads the hook payload on stdin, prints hook JSON on stdout, and stays silent when
the project has no rules.

Contract: always exit 0 and never write to stderr. A context hook that errors would
interrupt every session start in every project; failures go to
``<home>/data/hook.log`` instead.
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
        from claude_adapt_rules.extract import data_dir
        from claude_adapt_rules.inject import session_start_payload
        from claude_adapt_rules.migrate import migrate_legacy_home

        # Without this the first session after an upgrade silently injects
        # nothing: the rules exist, but under the previous state root.
        migrate_legacy_home()
        out = data_dir()
        raw = sys.stdin.read()
        # PowerShell's pipeline prepends a UTF-8 BOM; json.loads rejects it.
        payload = json.loads(raw.lstrip("﻿")) if raw.strip() else {}
        cwd = payload.get("cwd") or str(Path.cwd())

        result = session_start_payload(cwd)
        if result is not None:
            print(json.dumps(result, ensure_ascii=False))
    except Exception:  # noqa: BLE001 - deliberate, see contract above
        try:
            target = out or Path.home() / ".claude-adapt-rules" / "data"
            target.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(tz=timezone.utc).isoformat(timespec="seconds")
            with (target / "hook.log").open("a", encoding="utf-8") as fh:
                fh.write(f"[{stamp}] inject failed\n{traceback.format_exc()}")
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
