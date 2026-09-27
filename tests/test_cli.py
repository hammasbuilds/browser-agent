import json

import pytest

from browser_agent.cli import main
from browser_agent.encoders import ENCODERS


def run(*argv):
    with pytest.raises(SystemExit) as exc:
        main(list(argv))
    return str(exc.value)


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
    assert sorted(p.name for p in out.iterdir()) == ["oracle.json", "survival.json", "tokens.json"]


def test_results_are_written_with_unix_line_endings(tmp_path):
    from test_report import EPISODES

    episodes = tmp_path / "oracle.jsonl"
    episodes.write_text("".join(json.dumps(e) + "\n" for e in EPISODES))
    main(["report", "--episodes", str(episodes), "--out-dir", str(tmp_path)])
    assert b"\r\n" not in (tmp_path / "survival.json").read_bytes()
