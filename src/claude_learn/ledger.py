"""Rule ledger: identity, provenance, scope promotion, and rot tracking.

The ledger is the reason this compounds instead of becoming another stale
CLAUDE.md. Every rule keeps its evidence and two dates:

* ``first_seen``    - when the pipeline first distilled it
* ``last_violated`` - the most recent session where the agent broke it *after*
  it was adopted

A rule still being violated after adoption is not a rule the agent forgot --
it is a rule that is worded badly, buried too deep, or should have been a hook.
A rule with no violations for a long time has been internalised or was never
needed, and can stop costing context tokens.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .extract import rules_dir

SCHEMA_VERSION = 1

# Promotion gate. A preference is only global once it shows up somewhere else;
# one project's quirk stays in that project's rules file.
GLOBAL_MIN_PROJECTS = 2
GLOBAL_MIN_SESSIONS = 3

# Two candidate rules describing the same thing.
DUPLICATE_THRESHOLD = 0.6

VALID_CATEGORIES = (
    "anti-pattern",
    "expectation",
    "style",
    "process",
    "verification",
    "tooling",
)
VALID_STATUS = ("proposed", "adopted", "retired")

_TOKEN_RE = re.compile(r"[a-z0-9_]{3,}")
_STOP = frozenset(
    """the and for with that this you your not never always must should when into
    from have has are was were its it's use used using make makes made code claude
    agent rule rules""".split()
)


def _tokens(text: str) -> frozenset[str]:
    return frozenset(t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOP)


def _similarity(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds")


@dataclass(slots=True)
class Evidence:
    session: str
    ts: str
    quote: str
    project: str = ""
    uuid: str = ""


@dataclass(slots=True)
class Rule:
    id: str
    rule: str
    why: str
    category: str
    scope: str  # "global" or "repo:<project-name>"
    evidence: list[Evidence] = field(default_factory=list)
    status: str = "proposed"
    enforceable: bool = False  # mechanically checkable -> belongs in a hook
    first_seen: str = ""
    adopted: str = ""
    last_violated: str = ""
    violation_count: int = 0

    @property
    def projects(self) -> set[str]:
        return {e.project for e in self.evidence if e.project}

    @property
    def sessions(self) -> set[str]:
        return {e.session for e in self.evidence if e.session}

    @property
    def confidence(self) -> str:
        return f"{len(self.sessions)} session(s), {len(self.projects)} project(s)"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["evidence"] = [asdict(e) for e in self.evidence]
        return d

    @classmethod
    def from_dict(cls, d: dict) -> Rule:
        evidence = [Evidence(**e) for e in d.get("evidence", [])]
        return cls(**{**d, "evidence": evidence})


def decide_scope(evidence: Sequence[Evidence], fallback_project: str = "") -> str:
    """Apply the promotion gate: cross-project or repeated -> global."""
    projects = {e.project for e in evidence if e.project}
    sessions = {e.session for e in evidence if e.session}
    if len(projects) >= GLOBAL_MIN_PROJECTS or len(sessions) >= GLOBAL_MIN_SESSIONS:
        return "global"
    project = next(iter(projects), fallback_project) or "unknown"
    return f"repo:{project}"


@dataclass(slots=True)
class IngestResult:
    created: list[Rule] = field(default_factory=list)
    merged: list[tuple[Rule, str]] = field(default_factory=list)  # (rule, new quote)
    violations: list[Rule] = field(default_factory=list)
    rejected: list[tuple[dict, str]] = field(default_factory=list)  # (candidate, why)


class Ledger:
    """JSON-backed rule store. Small by design; read whole, write whole."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_ledger_path()
        self.rules: dict[str, Rule] = {}
        self.next_id = 1
        self.load()

    # ---------------------------------------------------------------- io ----
    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError, OSError):
            return
        self.next_id = int(raw.get("next_id", 1))
        for d in raw.get("rules", []):
            try:
                rule = Rule.from_dict(d)
            except TypeError:
                continue
            self.rules[rule.id] = rule

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema": SCHEMA_VERSION,
            "updated": _now(),
            "next_id": self.next_id,
            "rules": [r.to_dict() for r in self.rules.values()],
        }
        self.path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )

    # ------------------------------------------------------------ queries ---
    def by_scope(self, scope: str) -> list[Rule]:
        return [r for r in self.rules.values() if r.scope == scope]

    def scopes(self) -> list[str]:
        return sorted({r.scope for r in self.rules.values()})

    def find_similar(self, text: str, scope: str | None = None) -> Rule | None:
        best: tuple[float, Rule] | None = None
        for rule in self.rules.values():
            if scope and rule.scope != scope and rule.scope != "global":
                continue
            score = _similarity(text, rule.rule)
            if score >= DUPLICATE_THRESHOLD and (best is None or score > best[0]):
                best = (score, rule)
        return best[1] if best else None

    # ------------------------------------------------------------- writes ---
    def _mint_id(self) -> str:
        rid = f"R-{self.next_id:04d}"
        self.next_id += 1
        return rid

    def ingest(self, candidates: Iterable[dict]) -> IngestResult:
        """Add distilled candidates. Existing-rule matches become violations.

        A candidate that duplicates an adopted rule means the agent broke a rule
        it already had: recorded as a violation, not as a new rule.
        """
        result = IngestResult()
        for cand in candidates:
            text = str(cand.get("rule") or "").strip()
            if not text:
                result.rejected.append((cand, "missing 'rule'"))
                continue
            category = str(cand.get("category") or "expectation")
            if category not in VALID_CATEGORIES:
                result.rejected.append((cand, f"bad category {category!r}"))
                continue
            evidence = [
                Evidence(
                    session=str(e.get("session") or ""),
                    ts=str(e.get("ts") or ""),
                    quote=str(e.get("quote") or ""),
                    project=str(e.get("project") or ""),
                    uuid=str(e.get("uuid") or ""),
                )
                for e in cand.get("evidence", [])
                if isinstance(e, dict)
            ]
            if not evidence:
                result.rejected.append((cand, "no evidence"))
                continue

            existing = self.find_similar(text)
            if existing is not None:
                latest = max((e.ts for e in evidence if e.ts), default="")
                new_ev = [
                    e for e in evidence if e.uuid not in {x.uuid for x in existing.evidence}
                ]
                existing.evidence.extend(new_ev)
                existing.scope = decide_scope(existing.evidence, fallback_project="")
                if existing.status == "adopted" and latest > existing.adopted:
                    existing.violation_count += 1
                    existing.last_violated = latest
                    result.violations.append(existing)
                else:
                    result.merged.append((existing, text))
                continue

            rule = Rule(
                id=self._mint_id(),
                rule=text,
                why=str(cand.get("why") or "").strip(),
                category=category,
                scope=str(cand.get("scope") or "")
                or decide_scope(evidence, fallback_project=""),
                evidence=evidence,
                enforceable=bool(cand.get("enforceable")),
                first_seen=_now(),
            )
            # The model may propose a scope; the gate overrides it upward only.
            gated = decide_scope(evidence, fallback_project="")
            if rule.scope == "global" and gated != "global":
                rule.scope = gated
            self.rules[rule.id] = rule
            result.created.append(rule)
        return result

    def adopt(self, rule_id: str) -> Rule | None:
        rule = self.rules.get(rule_id)
        if rule is None:
            return None
        rule.status = "adopted"
        rule.adopted = _now()
        return rule

    def retire(self, rule_id: str) -> Rule | None:
        rule = self.rules.get(rule_id)
        if rule is None:
            return None
        rule.status = "retired"
        return rule

    # ------------------------------------------------------------ hygiene ---
    def rot_report(self, quiet_days: int = 30) -> dict[str, list[Rule]]:
        """Bucket adopted rules by whether they are still being broken."""
        threshold = (
            datetime.now(tz=timezone.utc) - timedelta(days=quiet_days)
        ).isoformat(timespec="seconds")
        escalate: list[Rule] = []
        quiet: list[Rule] = []
        for rule in self.rules.values():
            if rule.status != "adopted":
                continue
            if rule.last_violated and rule.last_violated >= threshold:
                escalate.append(rule)
            elif rule.adopted and rule.adopted < threshold:
                quiet.append(rule)
        escalate.sort(key=lambda r: -r.violation_count)
        return {"escalate": escalate, "quiet": quiet}


def default_ledger_path() -> Path:
    """User state, never the install directory — see extract.repo_root."""
    if env := os.environ.get("CLAUDE_LEARN_LEDGER"):
        return Path(env)
    return rules_dir() / "ledger.json"
