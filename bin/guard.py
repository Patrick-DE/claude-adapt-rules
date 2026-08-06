#!/usr/bin/env python3
"""PreToolUse hook: refuse a tool call that breaks a guarded rule.

Reads the hook payload on stdin. Exit 2 with the reason on stderr is the
documented way to block a PreToolUse call and hand the reason back to the agent;
exit 0 allows it.

Contract: this hook sits in front of *every* tool call, so a failure here would
brick every session in every project. Anything unexpected therefore allows the
call and lands in ``<home>/data/hook.log`` -- a deliberate, documented
degradation, and the only place in this codebase where failing open is correct.
The loud path is ``cli guards --set``, which refuses to store a guard it cannot
compile in the first place.
"""

from __future__ import annotations

import json
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

ALLOW, BLOCK = 0, 2


def main() -> int:
    out = None
    try:
        from claude_adapt_rules.extract import data_dir
        from claude_adapt_rules.guards import active_guards, check, record_fire
        from claude_adapt_rules.ledger import Ledger
        from claude_adapt_rules.migrate import migrate_legacy_home

        migrate_legacy_home()
        out = data_dir()
        raw = sys.stdin.read()
        if not raw.strip():
            return ALLOW
        # PowerShell's pipeline prepends a UTF-8 BOM; json.loads rejects it.
        payload = json.loads(raw.lstrip("﻿"))
        tool_name = str(payload.get("tool_name") or "")
        if not tool_name:
            return ALLOW

        guards = active_guards(Ledger())
        if not guards:
            return ALLOW
        violation = check(tool_name, payload.get("tool_input"), guards)
        if violation is None:
            return ALLOW
        # A fire is the one signal that needs no distillation run to observe: the
        # agent was about to break a rule and was stopped.
        record_fire(
            violation, datetime.now(tz=timezone.utc).isoformat(timespec="seconds"), out=out
        )
        sys.stderr.write(violation.reason + "\n")
        return BLOCK
    except Exception:  # noqa: BLE001 - deliberate, see contract above
        try:
            target = out or Path.home() / ".claude-adapt-rules" / "data"
            target.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(tz=timezone.utc).isoformat(timespec="seconds")
            with (target / "hook.log").open("a", encoding="utf-8") as fh:
                fh.write(f"[{stamp}] guard failed\n{traceback.format_exc()}")
        except OSError:
            pass
        return ALLOW


if __name__ == "__main__":
    sys.exit(main())
