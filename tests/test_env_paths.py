import pytest

from browser_agent.env import MiniWoBEnv, TaskNotFoundError
from browser_agent.pages import miniwob_dir, task_url


def test_an_empty_page_directory_fails_loudly_before_any_browser_work(tmp_path):
    with pytest.raises(TaskNotFoundError, match="click-test"):
        MiniWoBEnv(root=tmp_path).reset("click-test", 0)


def test_unknown_task_names_fail_loudly():
    with pytest.raises(TaskNotFoundError, match="no-such-task"):
        MiniWoBEnv().reset("no-such-task", 0)


def test_the_vendored_pages_are_found_from_the_package():
    assert (miniwob_dir() / "core" / "core.js").is_file()


def test_task_urls_live_on_the_fake_origin():
    assert task_url("click-test") == "http://miniwob.local/miniwob/click-test.html"
