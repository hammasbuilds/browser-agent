import contextlib
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from browser_agent.cli import main
from browser_agent.encoders import ENCODERS


def run(*argv):
    """Exit code 2 and one ``error:`` line, whatever the bad input was."""
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        code = main(list(argv))
    assert code == 2, (argv, code)
    (line,) = err.getvalue().splitlines()
    assert line.startswith("error: "), line
    return line


def test_bad_inputs_get_one_line_reasons_not_tracebacks(tmp_path):
    assert "unknown encoder" in run("agent", "--encoder", "bogus", "--dry-run")
    assert "at least 1" in run("oracle", "--seeds", "0")
    assert "not a MiniWoB++ task" in run("oracle", "--tasks", "nope")
    assert "out of the action space (drag)" in run("oracle", "--tasks", "drag-box")
    assert "not found" in run("report", "--episodes", str(tmp_path / "none.jsonl"))
    assert "not found" in run("agent", "--oracle-episodes", str(tmp_path / "none.jsonl"))
    assert "names no task" in run("oracle", "--tasks", " , ")
    empty = tmp_path / "empty.jsonl"
    empty.write_text("")
    assert "holds no episodes" in run("report", "--episodes", str(empty))
    corrupt = tmp_path / "corrupt.jsonl"
    corrupt.write_text('{"a": 1}\nnot json\n{"a": 3}\n')
    assert "line 2 is not JSON" in run("report", "--episodes", str(corrupt))


def test_dry_run_plans_from_oracle_episodes_without_touching_a_model(tmp_path, capsys):
    step = {
        "checks": {},
        "tokens": {n: 10 for n in ENCODERS},
    }
    episodes = tmp_path / "oracle.jsonl"
    rows = [
        {"task": "click-test", "seed": 0, "done": True, "raw_reward": 1.0, "steps": [step]},
        {"task": "click-link", "seed": 0, "done": True, "raw_reward": -1.0, "steps": [step]},
    ]
    episodes.write_text("".join(json.dumps(r) + "\n" for r in rows))
    assert main(["agent", "--dry-run", "--seeds", "2", "--oracle-episodes", str(episodes)]) == 0
    out = capsys.readouterr().out
    n = len(ENCODERS)
    assert f"{n} episodes" in out and f"~{2 * n} expected" in out and f"{4 * n} at most" in out
    common = ["agent", "--dry-run", "--oracle-episodes", str(episodes)]
    # a task the oracle file never mentions is a typo, not an empty plan
    assert "no oracle episodes for nosuch" in run(*common, "--tasks", "click-test,nosuch")
    # a known task the oracle never solved gives no jobs
    assert "no jobs" in run(*common, "--tasks", "click-link")
    assert "must exceed" in run(*common, "--num-ctx", "-5")


def test_tasks_lists_every_family_and_every_exclusion(capsys):
    assert main(["tasks"]) == 0
    out = capsys.readouterr().out
    assert "in scope but no oracle" not in out
    assert "out of the action space (29)" in out


def test_report_writes_where_it_is_told(tmp_path):
    from test_report import EPISODES

    episodes = tmp_path / "oracle.jsonl"
    episodes.write_text("".join(json.dumps(e) + "\n" for e in EPISODES))
    out = tmp_path / "out"
    assert main(["report", "--episodes", str(episodes), "--out-dir", str(out)]) == 0
    assert sorted(p.name for p in out.iterdir()) == [
        "allow_list.json",
        "oracle.json",
        "survival.json",
        "tokens.json",
    ]


def test_results_are_written_with_unix_line_endings(tmp_path):
    from test_report import EPISODES

    episodes = tmp_path / "oracle.jsonl"
    episodes.write_text("".join(json.dumps(e) + "\n" for e in EPISODES))
    main(["report", "--episodes", str(episodes), "--out-dir", str(tmp_path)])
    assert b"\r\n" not in (tmp_path / "survival.json").read_bytes()


def test_encoder_names_are_stripped_and_empty_lists_refused(tmp_path, capsys):
    from test_report import EPISODES

    episodes = tmp_path / "oracle.jsonl"
    episodes.write_text("".join(json.dumps(e) + "\n" for e in EPISODES))
    common = ["agent", "--dry-run", "--oracle-episodes", str(episodes)]
    assert main([*common, "--encoder", "som, axtree"]) == 0
    out = capsys.readouterr().out
    assert "  som " in out and "  axtree " in out and "clean_dom" not in out
    assert "names no encoder" in run(*common, "--encoder", " , ")


def test_argparse_and_our_own_bad_input_share_exit_code_2():
    with pytest.raises(SystemExit) as exc:
        main(["oracle", "--seeds", "many"])
    assert exc.value.code == 2
    assert "at least 1" in run("oracle", "--seeds", "0")


def test_every_flag_has_help_and_shows_its_default(capsys):
    from browser_agent.cli import build_parser

    parser = build_parser()
    subparsers = next(a for a in parser._actions if a.dest == "command").choices
    for name, sub in subparsers.items():
        for action in sub._actions:
            if action.dest != "help":
                assert action.help, (name, action.dest)
    with pytest.raises(SystemExit):
        main(["agent", "--help"])
    assert "(default: 5)" in capsys.readouterr().out


def test_default_paths_do_not_depend_on_the_working_directory(tmp_path, monkeypatch):
    from browser_agent import cli

    monkeypatch.chdir(tmp_path)
    assert cli.RESULTS.is_absolute() and (cli.ROOT / "vendor").is_dir()
    assert cli.ORACLE_EPISODES.parent == cli.RESULTS


def test_unicode_output_survives_a_redirected_cp1252_stdout(tmp_path):
    # Windows gives a redirected stdout the ANSI code page; before the fix, printing a
    # character outside it (unicode-test's page, here a model tag) raised UnicodeEncodeError.
    from test_report import EPISODES

    episodes = tmp_path / "oracle.jsonl"
    episodes.write_text("".join(json.dumps(e) + "\n" for e in EPISODES))
    argv = ["agent", "--dry-run", "--model", "q✓Ā", "--oracle-episodes", str(episodes)]
    env = {**os.environ, "PYTHONIOENCODING": "cp1252"}
    env["PYTHONPATH"] = str(Path(__file__).parents[1] / "src")
    out = subprocess.run(
        [sys.executable, "-m", "browser_agent.cli", *argv], capture_output=True, env=env
    )
    assert out.returncode == 0, out.stderr.decode("utf-8", "replace")
    assert "model q✓Ā," in out.stdout.decode("utf-8")
