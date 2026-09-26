import pytest

from browser_agent.env import MiniWoBEnv, TaskNotFoundError
from browser_agent.pages import ENV_VAR, miniwob_dir, task_url


def test_an_empty_page_directory_fails_loudly_before_any_browser_work(tmp_path):
    with pytest.raises(TaskNotFoundError, match="click-test"):
        MiniWoBEnv(root=tmp_path).reset("click-test", 0)


def test_the_env_var_overrides_the_vendored_pages(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_VAR, str(tmp_path))
    assert miniwob_dir() == tmp_path
    with pytest.raises(TaskNotFoundError):
        MiniWoBEnv().reset("click-test", 0)


def test_unknown_task_names_fail_loudly():
    with pytest.raises(TaskNotFoundError, match="no-such-task"):
        MiniWoBEnv().reset("no-such-task", 0)


def test_task_urls_live_on_the_fake_origin():
    assert task_url("click-test") == "http://miniwob.local/miniwob/click-test.html"
