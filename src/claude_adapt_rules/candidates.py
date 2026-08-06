"""Validate a candidates file before it is allowed near the ledger.

Distillation is the one model step, and until now its output went straight into
`ingest` on the strength of a human having read it. Once the step runs unattended
that reader is gone, so the gate has to be mechanical: a candidates file is only
safe to ingest if every quote in it is verbatim in the session it cites.

This is deliberately separate from `verify`, which checks the *ledger*. By then a
bad quote is already a rule. Checking the candidates file catches it before it
becomes one, which is the only point at which discarding is cheap.

Stdlib-only, like everything else in the runtime.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .ledger import VALID_CATEGORIES, Evidence, Rule
from .verify import load_sessions, verify_rules


@dataclass(slots=True)
class CheckResult:
    total: int = 0
    accepted: list[dict] = field(default_factory=list)
    rejected: list[tuple[dict, str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.rejected

    def summary(self) -> str:
        return f"{len(self.accepted)}/{self.total} candidate(s) usable"


def _structural_problem(cand: dict) -> str | None:
    """Schema faults, checked before the expensive transcript comparison."""
    if not isinstance(cand, dict):
        return "not an object"
    if not str(cand.get("rule") or "").strip():
        return "missing 'rule'"
    category = str(cand.get("category") or "")
    if category not in VALID_CATEGORIES:
        return f"bad category {category!r}"
    evidence = cand.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        return "no evidence"
    for ev in evidence:
        if not isinstance(ev, dict):
            return "evidence entry is not an object"
        if not str(ev.get("quote") or "").strip():
            return "evidence entry has no quote"
        if not str(ev.get("session") or "").strip():
            return "evidence entry has no session"
    return None


def _as_rule(cand: dict, index: int) -> Rule:
    """A throwaway Rule so the existing verifier can be reused unchanged."""
    return Rule(
        id=f"CAND-{index:04d}",
        rule=str(cand.get("rule") or ""),
        why=str(cand.get("why") or ""),
        category=str(cand.get("category") or "expectation"),
        scope="global",
        evidence=[
            Evidence(
                session=str(e.get("session") or ""),
                ts=str(e.get("ts") or ""),
                quote=str(e.get("quote") or ""),
                project=str(e.get("project") or ""),
                uuid=str(e.get("uuid") or ""),
            )
            for e in cand.get("evidence", [])
            if isinstance(e, dict)
        ],
    )


def load_candidates(path: Path) -> list[dict]:
    """Read a candidates file in either accepted shape."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        payload = payload.get("rules", [])
    return list(payload) if isinstance(payload, list) else []


def check(
    candidates: list[dict],
    root: Path | None = None,
    archive: list[Path] | None = None,
) -> CheckResult:
    """Split candidates into those safe to ingest and those that are not.

    An expired transcript rejects the candidate rather than passing as it does in
    `verify`. There the distinction protects an existing rule from looking
    fabricated when its evidence merely aged out; here nothing is protected yet,
    and admitting a quote nobody can check is how unverifiable rules are born.
    """
    result = CheckResult(total=len(candidates))
    checkable: list[tuple[dict, Rule]] = []
    for i, cand in enumerate(candidates):
        problem = _structural_problem(cand)
        if problem:
            result.rejected.append((cand if isinstance(cand, dict) else {}, problem))
            continue
        checkable.append((cand, _as_rule(cand, i)))

    if not checkable:
        return result

    sessions = load_sessions(root, archive=archive)
    verdict = verify_rules([rule for _, rule in checkable], sessions)
    bad = {p.rule_id: p.kind for p in verdict.problems}
    for cand, rule in checkable:
        if kind := bad.get(rule.id):
            result.rejected.append((cand, f"evidence {kind}"))
        else:
            result.accepted.append(cand)
    return result
