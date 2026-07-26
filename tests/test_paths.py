"""State must never default into the install directory.

As a plugin, the install directory is
``~/.claude/plugins/cache/<marketplace>/<plugin>/<version>/`` — a new version is a new
directory, so a ledger stored there is orphaned on every update.
"""

from __future__ import annotations

from pathlib import Path

from claude_learn import extract as extract_mod
from claude_learn.ledger import default_ledger_path


def test_defaults_live_under_the_user_home(monkeypatch):
    for var in ("CLAUDE_LEARN_HOME", "CLAUDE_LEARN_DATA_DIR", "CLAUDE_LEARN_RULES_DIR", "CLAUDE_LEARN_LEDGER"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: Path("/home/example")))

    assert extract_mod.home_dir() == Path("/home/example/.claude-learn")
    assert extract_mod.data_dir() == Path("/home/example/.claude-learn/data")
    assert extract_mod.rules_dir() == Path("/home/example/.claude-learn/rules")
    assert default_ledger_path() == Path("/home/example/.claude-learn/rules/ledger.json")


def test_nothing_defaults_into_the_install_directory(monkeypatch):
    for var in ("CLAUDE_LEARN_HOME", "CLAUDE_LEARN_DATA_DIR", "CLAUDE_LEARN_RULES_DIR", "CLAUDE_LEARN_LEDGER"):
        monkeypatch.delenv(var, raising=False)
    install = extract_mod.repo_root()
    for path in (extract_mod.data_dir(), extract_mod.rules_dir(), default_ledger_path()):
        assert install not in path.parents, f"{path} would be wiped by a plugin update"


def test_home_override_moves_everything(monkeypatch, tmp_path):
    for var in ("CLAUDE_LEARN_DATA_DIR", "CLAUDE_LEARN_RULES_DIR", "CLAUDE_LEARN_LEDGER"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("CLAUDE_LEARN_HOME", str(tmp_path / "state"))

    assert extract_mod.data_dir() == tmp_path / "state" / "data"
    assert extract_mod.rules_dir() == tmp_path / "state" / "rules"
    assert default_ledger_path() == tmp_path / "state" / "rules" / "ledger.json"


def test_narrower_overrides_win(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_LEARN_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("CLAUDE_LEARN_DATA_DIR", str(tmp_path / "elsewhere"))
    monkeypatch.setenv("CLAUDE_LEARN_LEDGER", str(tmp_path / "custom.json"))

    assert extract_mod.data_dir() == tmp_path / "elsewhere"
    assert default_ledger_path() == tmp_path / "custom.json"
    assert extract_mod.rules_dir() == tmp_path / "state" / "rules"  # unset, follows home
