"""Work repeated by hand leaves no corrective signal, so nothing else finds it.

Idea credited to Task-Observer (rebelytics, CC BY 4.0), which treats coverage
gaps as a first-class category alongside corrections.
"""

from __future__ import annotations

import json

from claude_adapt_rules.transcripts import parse_session
from claude_adapt_rules.workflows import (
    MIN_OCCURRENCES,
    collect,
    is_distinctive,
    normalise,
    render,
)

from .conftest import assistant, enqueue


def _span(tools: list[str]) -> dict:
    return assistant(tools=[(t, "") for t in tools])


def _sessions(make_transcript, records, session="s1", project="C--x-repos-demo"):
    return [parse_session(make_transcript(records, project=project, session=session))]


def test_normalise_keeps_the_shape_not_the_volume():
    """Reading four files then editing is the same procedure as reading two."""
    assert normalise(["Read", "Read", "Read", "Edit", "Bash"]) == ("Read", "Edit", "Bash")
    assert normalise(["Read", "TodoWrite", "Edit"]) == ("Read", "Edit")


def test_the_ordinary_edit_loop_is_not_a_skill_candidate():
    """Measured on the real corpus: Read -> Edit -> Bash, 7x across 4 projects.

    That is what coding is. Reporting it buried every distinctive sequence.
    """
    assert not is_distinctive(("Read", "Edit", "Bash"))
    assert not is_distinctive(("Bash", "Edit", "Bash", "Edit"))
    assert is_distinctive(("Bash", "Workflow", "Bash"))


def test_a_repeated_distinctive_sequence_is_reported(make_transcript):
    records = []
    for i in range(MIN_OCCURRENCES):
        records += [
            _span(["Bash", "Workflow", "Bash"]),
            enqueue(f"now do the next batch {i}"),
        ]
    found = collect(_sessions(make_transcript, records))
    assert len(found) == 1
    assert found[0].tools == ("Bash", "Workflow", "Bash")
    assert found[0].occurrences == MIN_OCCURRENCES
    assert found[0].example_prompt.startswith("now do the next batch")


def test_a_sequence_the_user_corrected_is_not_proposed(make_transcript):
    """A span that drew a complaint is already covered by the corrective signals."""
    records = []
    for _ in range(MIN_OCCURRENCES):
        records += [
            _span(["Bash", "Workflow", "Bash"]),
            enqueue("no, don't do it that way"),
        ]
    assert collect(_sessions(make_transcript, records)) == []


def test_a_denied_or_interrupted_span_is_not_proposed(make_transcript):
    records = []
    for i in range(MIN_OCCURRENCES):
        records += [
            _span(["Bash", "Workflow", "Bash"]),
            json.loads(
                json.dumps(
                    {
                        "type": "user",
                        "message": {
                            "role": "user",
                            "content": [{"type": "text", "text": "[Request interrupted by user]"}],
                        },
                    }
                )
            ),
            enqueue(f"carry on {i}"),
        ]
    assert collect(_sessions(make_transcript, records)) == []


def test_one_off_work_is_not_a_habit(make_transcript):
    records = [_span(["Bash", "Workflow", "Bash"]), enqueue("do the thing")]
    assert collect(_sessions(make_transcript, records)) == []


def test_render_states_truncation_rather_than_hiding_it(make_transcript):
    records = []
    for i in range(MIN_OCCURRENCES):
        for tool in ("Workflow", "PowerShell"):
            records += [_span(["Bash", tool, "Bash"]), enqueue(f"next {tool} {i}")]
    found = collect(_sessions(make_transcript, records))
    assert len(found) == 2
    assert "1 further candidate(s) not shown" in render(found, limit=1)
    assert "_None:" in render([])
