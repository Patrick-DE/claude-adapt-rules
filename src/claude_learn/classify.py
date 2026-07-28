"""Decide whether a rule is about one project or about all work.

Evidence count is a proxy for generality, and it is a bad one. "Never commit code
that does not build" was said once, in one project, and applies everywhere; "start the
backend through start_debug.bat" would still be local if it were said fifty times.

So generality is judged, not counted: the distiller labels each rule `universal` or
`project`. Judgement is not trusted blindly — a rule that names a path, a filename, an
identifier or a project cannot be universal no matter what the label says, and the veto
below enforces that.
"""

from __future__ import annotations

import re

UNIVERSAL = "universal"
PROJECT = "project"
VALID_APPLIES = (UNIVERSAL, PROJECT)

# Structural markers of project-specific text.
_MARKERS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("a file extension", re.compile(r"\b[\w-]+\.(?:ts|tsx|js|jsx|py|rs|go|java|cs|rb|php|sh|ps1|bat|cmd|json|toml|yaml|yml|md|log|db|sql|env)\b", re.IGNORECASE)),
    ("a path", re.compile(r"(?:[A-Za-z]:[\\/]|(?:\.{1,2})?[\\/][\w.-]+[\\/])")),
    ("a snake_case identifier", re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b")),
    ("a camelCase identifier", re.compile(r"\b[a-z][a-z0-9]*[A-Z][A-Za-z0-9]*\b")),
    ("an ALL_CAPS constant", re.compile(r"\b[A-Z][A-Z0-9]{2,}(?:_[A-Z0-9]+)+\b")),
)


def looks_project_specific(text: str, project_names: tuple[str, ...] = ()) -> str | None:
    """Reason the text is project-specific, or None if nothing local was found."""
    for label, pattern in _MARKERS:
        if match := pattern.search(text):
            return f"{label} ({match.group(0)})"
    lowered = text.lower()
    for name in project_names:
        # Single-word project names like "app" are too generic to judge on.
        if len(name) > 4 and name.lower() in lowered:
            return f"the project name ({name})"
    return None


def resolve_applies(
    text: str, claimed: str | None, project_names: tuple[str, ...] = ()
) -> tuple[str, str | None]:
    """Return (applies, veto_reason).

    An unlabelled rule stays unlabelled (None) so the caller can fall back to the
    evidence-count gate. A `universal` claim is downgraded when the text names
    something local; a `project` claim is never overridden — narrow is the safe default.
    """
    if claimed not in VALID_APPLIES:
        return "", None
    if claimed == PROJECT:
        return PROJECT, None
    reason = looks_project_specific(text, project_names)
    if reason:
        return PROJECT, reason
    return UNIVERSAL, None
