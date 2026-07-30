"""Scoring: what selects an event, and what must not."""

from __future__ import annotations

from claude_adapt_rules.signals import is_acknowledgement, score_prompt, score_session, select
from claude_adapt_rules.transcripts import parse_session

from .conftest import DENIAL, assistant, enqueue, tool_result


def events_for(path) -> list:
    return score_session(parse_session(path).prompts)


def test_following_an_edit_alone_does_not_select(make_transcript):
    """407 of 778 local prompts follow an edit. If that selected, nothing is filtered."""
    path = make_transcript(
        [
            enqueue("start"),
            assistant(tools=[("Edit", "src/app.py")]),
            enqueue("commit and push"),
        ]
    )
    events = events_for(path)
    after_edit = next(e for e in events if e.prompt.text == "commit and push")
    assert "after_edit" in after_edit.structural
    assert all(e.prompt.text != "commit and push" for e in select(events))


def test_corrective_words_after_an_edit_do_select(make_transcript):
    path = make_transcript(
        [
            enqueue("start"),
            assistant(tools=[("Edit", "src/app.py")]),
            enqueue("no, don't mock the backend, that is wrong"),
        ]
    )
    selected = select(events_for(path))
    assert [e.prompt.text for e in selected] == ["no, don't mock the backend, that is wrong"]


def test_denied_turn_selects_even_without_corrective_words(make_transcript):
    path = make_transcript(
        [
            enqueue("go"),
            assistant(tools=[("Bash", "")]),
            tool_result(DENIAL),
            enqueue("run it through the wrapper"),
        ]
    )
    selected = select(events_for(path))
    assert any("user_denied" in e.structural for e in selected)


def test_repeated_instruction_detected(make_transcript):
    path = make_transcript(
        [
            enqueue("always run the type checker before you claim done"),
            assistant("ok"),
            enqueue("run the type checker before claiming done, always"),
        ]
    )
    events = events_for(path)
    assert "repeated_instruction" in events[1].structural
    assert events[1].repeat_of == events[0].prompt.uuid


def test_german_negation_scores():
    from claude_adapt_rules.transcripts import Prompt

    prompt = Prompt(
        project="p",
        project_name="p",
        session="s",
        uuid="u",
        ts="2026-07-01T00:00:00Z",
        git_branch="",
        text="nicht den globalen zustand nutzen, stattdessen den parameter",
        turn=0,
        prev_assistant_text="",
        prev_tools=(),
        prev_files=(),
        user_denied=False,
        classifier_denied=False,
        interrupted=False,
    )
    event = score_prompt(prompt)
    assert "negation_de" in event.lexical
    assert event.score >= 2


def test_acknowledgements_skipped(make_transcript):
    path = make_transcript([enqueue("ok"), enqueue("weiter"), enqueue("+500k")])
    assert events_for(path) == []
    assert is_acknowledgement("  Yes ")
    assert not is_acknowledgement("yes, but never use inline styles")
