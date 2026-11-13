"""Offline checks for examples/browser-avatar/run.py (the one-command launcher)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

RUN_PY = Path(__file__).resolve().parents[1] / "examples" / "browser-avatar" / "run.py"


@pytest.fixture(scope="module")
def run():
    spec = importlib.util.spec_from_file_location("example_run", RUN_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GOOD = {
    "LIVEKIT_URL": "wss://demo.livekit.cloud",
    "LIVEKIT_API_KEY": "APIkeyValue1",
    "LIVEKIT_API_SECRET": "apiSecretValue2",
    "OPENAI_API_KEY": "sk-openaiValue3",
    "MESHLITE_PUBLISHABLE_KEY": "ml_pk_test_publishableValue4",
    "MESHLITE_SECRET_KEY": "ml_sk_test_secretValue5",
    "MESHLITE_AVATAR": "avatar-id-6",
}


def test_complete_settings_pass(run):
    problems, warnings = run.validate(GOOD)
    assert problems == []
    assert warnings == []


def test_env_example_is_reported_as_unset(run):
    example = run.read_env_file(run.ENV_EXAMPLE)
    problems, _ = run.validate(example)
    named = {problem.split(" ")[0] for problem in problems}
    assert named == set(run.REQUIRED)


def test_parser_handles_quotes_comments_and_export(run, tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        '﻿# comment\nexport A=1\nB="two words" # trailing\nC=\'x#y\'\nD=plain # note\n\nbad line\nE=\n',
        encoding="utf-8",
    )
    assert run.read_env_file(env) == {"A": "1", "B": "two words", "C": "x#y", "D": "plain", "E": ""}


def test_missing_file_gives_nothing(run, tmp_path):
    assert run.read_env_file(tmp_path / "nope.env") == {}


def test_process_environment_wins_over_file(run):
    merged = run.effective_settings({"MESHLITE_AVATAR": "from-file"}, {"MESHLITE_AVATAR": "from-env", "HOME": "/x"})
    assert merged["MESHLITE_AVATAR"] == "from-env"
    assert "HOME" not in merged


def test_swapped_keys_are_explained(run):
    settings = dict(GOOD, MESHLITE_PUBLISHABLE_KEY=GOOD["MESHLITE_SECRET_KEY"], MESHLITE_SECRET_KEY=GOOD["MESHLITE_PUBLISHABLE_KEY"])
    problems, _ = run.validate(settings)
    assert any("MESHLITE_PUBLISHABLE_KEY must start with ml_pk_" in p for p in problems)
    assert any("MESHLITE_SECRET_KEY must start with ml_sk_" in p for p in problems)


def test_mixed_environments_are_refused(run):
    problems, _ = run.validate(dict(GOOD, MESHLITE_SECRET_KEY="ml_sk_live_secretValue5"))
    assert any("different environments" in p for p in problems)


def test_live_keys_on_http_origin_warn(run):
    settings = dict(GOOD, MESHLITE_PUBLISHABLE_KEY="ml_pk_live_a", MESHLITE_SECRET_KEY="ml_sk_live_b")
    problems, warnings = run.validate(settings)
    assert problems == []
    assert any("https://" in w for w in warnings)


def test_bad_url_and_port(run):
    problems, _ = run.validate(dict(GOOD, LIVEKIT_URL="demo.livekit.cloud", PORT="70000"))
    assert any("LIVEKIT_URL must start with" in p for p in problems)
    assert any("PORT must be" in p for p in problems)


def test_messages_never_contain_values(run):
    broken = dict(GOOD, MESHLITE_PUBLISHABLE_KEY="secretLookingValueA", MESHLITE_SECRET_KEY="secretLookingValueB",
                  LIVEKIT_URL="notaurl-secretLookingValueC", PORT="secretLookingValueD")
    problems, warnings = run.validate(broken)
    text = "\n".join(problems + warnings)
    assert problems
    assert "secretLookingValue" not in text


def test_check_mode_reports_and_exits_without_values(run, tmp_path, monkeypatch, capsys):
    env = tmp_path / ".env"
    env.write_text("LIVEKIT_API_SECRET=veryPrivateValue\n", encoding="utf-8")
    monkeypatch.setattr(run, "ENV_FILE", env)
    for name in run.REQUIRED:
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(SystemExit) as stop:
        run.main(["--check"])
    assert stop.value.code == 1
    output = capsys.readouterr().out
    assert "LIVEKIT_URL is not set" in output
    assert "LIVEKIT_API_SECRET is not set" not in output
    assert "veryPrivateValue" not in output


def test_check_mode_succeeds_with_complete_file(run, tmp_path, monkeypatch, capsys):
    env = tmp_path / ".env"
    env.write_text("".join(f"{name}={value}\n" for name, value in GOOD.items()), encoding="utf-8")
    monkeypatch.setattr(run, "ENV_FILE", env)
    for name in list(run.REQUIRED) + ["PORT", "PUBLIC_ORIGIN"]:
        monkeypatch.delenv(name, raising=False)
    assert run.main(["--check"]) == 0
    assert "Configuration looks complete" in capsys.readouterr().out


def test_agent_json_lines_are_condensed(run):
    info = '{"message": "registered worker", "level": "INFO", "name": "livekit.agents", "pid": 1}'
    assert run.tidy_agent_line(info) == "registered worker"
    assert run.tidy_agent_line('{"message": "job runner initialized", "level": "INFO"}') is None
    assert run.tidy_agent_line('{"message": "x", "level": "DEBUG"}') is None
    error = '{"message": "boom", "level": "ERROR", "exc_info": "Traceback (most recent call last):\\nValueError"}'
    assert run.tidy_agent_line(error) == "ERROR boom\nTraceback (most recent call last):\nValueError"
    assert run.tidy_agent_line("plain text line") == "plain text line"
    assert run.tidy_agent_line("{not json") == "{not json"


def test_livekit_server_noise_is_dropped(run):
    cpu = "2026-11-13T15:24:12.647+0800\tERROR\tlivekit\thwstats/cpu_null.go:38\tCPU monitoring unsupported on current platform."
    assert run.tidy_livekit_line(cpu) is None
    assert run.tidy_livekit_line("github.com/livekit/protocol/utils/hwstats.newPlatformCPUMonitor") is None
    assert run.tidy_livekit_line("2026-11-13T15:24:12.692+0800\tINFO\tlivekit\tstarting LiveKit server") is None
    warning = "2026-11-13T15:24:12.692+0800\tWARN\tlivekit\tsomething real"
    assert run.tidy_livekit_line(warning) == warning
