"""What was used, not what is installed — and the gap between them."""

from __future__ import annotations

from claude_adapt_rules.harness import collect, installed_skills, render

from .conftest import assistant, enqueue


def _skill(name: str) -> dict:
    rec = assistant(tools=[("Skill", "")])
    rec["message"]["content"][0]["input"] = {"skill": name}
    return rec


def _agent(subagent: str | None) -> dict:
    rec = assistant(tools=[("Agent", "")])
    rec["message"]["content"][0]["input"] = {"subagent_type": subagent} if subagent else {}
    return rec


def test_skills_agents_and_tools_are_separated(make_transcript, tmp_path):
    make_transcript(
        [
            enqueue("go"),
            _skill("superpowers:brainstorming"),
            _agent("code-reviewer"),
            assistant(tools=[("Read", "a.py"), ("Bash", "")]),
        ]
    )
    usages = collect(tmp_path / "projects")
    kinds = {(u.kind, u.name) for u in usages}
    assert ("skill", "superpowers:brainstorming") in kinds
    assert ("agent", "code-reviewer") in kinds
    assert ("tool", "Read") in kinds and ("tool", "Bash") in kinds


def test_repeat_use_is_counted_and_the_latest_date_kept(make_transcript, tmp_path):
    records = [enqueue("go")]
    for ts in ("2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z"):
        rec = _skill("update-config")
        rec["timestamp"] = ts
        records.append(rec)
    usages = collect(tmp_path / "projects")
    make_transcript(records)
    usages = collect(tmp_path / "projects")
    skill = next(u for u in usages if u.name == "update-config")
    assert skill.count == 2
    assert skill.last_used.startswith("2026-08-01")


def test_an_unnamed_subagent_is_still_recorded(make_transcript, tmp_path):
    make_transcript([enqueue("go"), _agent(None)])
    usages = collect(tmp_path / "projects")
    assert any(u.kind == "agent" and u.name == "general-purpose" for u in usages)


def test_installed_but_never_used_is_the_finding(make_transcript, tmp_path):
    make_transcript([enqueue("go"), _skill("used-one")])
    skills_root = tmp_path / "skills"
    for name in ("used-one", "never-fired"):
        (skills_root / name).mkdir(parents=True)

    usages = collect(tmp_path / "projects")
    used = {u.name for u in usages if u.kind == "skill"}
    assert installed_skills(skills_root) - used == {"never-fired"}

    text = render(usages, never_fired={"never-fired"})
    assert "never-fired" in text.split("## Installed but never observed")[1]


def test_missing_skills_directory_is_not_an_error(tmp_path):
    assert installed_skills(tmp_path / "nope") == set()


def test_render_states_it_measures_use_not_installation(make_transcript, tmp_path):
    make_transcript([enqueue("go")])
    text = render(collect(tmp_path / "projects"))
    assert "not what is installed" in text
