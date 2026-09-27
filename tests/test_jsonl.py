import json

import pytest

from browser_agent.harness import load_jsonl


def test_a_truncated_last_line_is_skipped_and_repaired_before_appending(tmp_path):
    path = tmp_path / "episodes.jsonl"
    path.write_text(json.dumps({"a": 1}) + "\n" + '{"a": 2, "b"', encoding="utf-8")
    assert load_jsonl(path) == [{"a": 1}]
    assert path.read_text(encoding="utf-8").endswith('"b"')  # reading alone changes nothing
    assert load_jsonl(path, repair=True) == [{"a": 1}]
    assert path.read_text(encoding="utf-8") == json.dumps({"a": 1}) + "\n"


def test_a_bad_line_in_the_middle_is_corruption(tmp_path):
    path = tmp_path / "episodes.jsonl"
    path.write_text('{"a": 1}\nnot json\n{"a": 3}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="line 2"):
        load_jsonl(path)


def test_repair_writes_unix_line_endings(tmp_path):
    path = tmp_path / "episodes.jsonl"
    path.write_bytes(b'{"a": 1}\n{"a": ')
    load_jsonl(path, repair=True)
    assert path.read_bytes() == b'{"a": 1}\n'
