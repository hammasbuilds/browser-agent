"""End-to-end checks on real Chromium (skipped when Playwright's Chromium is not installed)."""

import json
import re

import pytest
from playwright.sync_api import Error as PlaywrightError

from browser_agent.actions import Action, ActionError, execute
from browser_agent.agent import Job, run_agent_episode, run_jobs
from browser_agent.encoders import ENCODERS
from browser_agent.harness import BrowserDiedError, load_jsonl, run_oracle_episode
from browser_agent.llm import FakeClient

pytestmark = pytest.mark.browser


def test_seeded_reset_is_deterministic(env):
    first = env.reset("click-button", 3).utterance
    assert env.reset("click-button", 3).utterance == first
    assert first.startswith('Click on the "')


def test_the_oracle_solves_a_task_and_records_survival_for_every_encoder(env):
    record = run_oracle_episode(env, "login-user", 0)
    assert record.success and record.error is None
    assert [s.kind for s in record.steps] == ["type", "type", "click"]
    assert set(record.steps[0].checks) == set(ENCODERS)
    assert record.steps[0].tokens["raw_html"] > record.steps[0].tokens["som"]
    # "username" is in the instruction; every need is tagged with where it was found
    assert record.steps[0].need_sources == ["instruction"]


def test_a_wrong_click_gets_the_benchmarks_negative_reward(env):
    env.reset("click-test-2", 0)
    execute(env.page, Action("click", "#subbtn2"), shown=None)
    outcome = env.outcome()
    assert outcome.done and outcome.raw_reward == -1.0


def test_executor_refuses_indices_the_agent_was_not_shown(env):
    snap = env.reset("click-test", 0)
    (button,) = [n.id for n in snap.nodes.values() if n.tag == "button"]
    with pytest.raises(ActionError, match="not in the current observation"):
        execute(env.page, Action("click", button), shown=set())
    with pytest.raises(ActionError, match="no element matches"):
        execute(env.page, Action("click", "#nope"), shown=None)
    with pytest.raises(ActionError, match="invalid selector"):
        execute(env.page, Action("click", "##"), shown=None)
    with pytest.raises(ActionError, match="exactly one"):
        execute(env.page, Action("click", "div"), shown=None)
    assert not env.outcome().done


def test_pages_cannot_reach_the_network(env):
    env.reset("click-test", 0)
    result = env.page.evaluate(
        "fetch('https://example.com/').then(() => 'reached', () => 'blocked')"
    )
    assert result == "blocked"


def _click_line(pattern):
    def policy(messages):
        page = messages[-1]["content"]
        found = re.search(pattern, page, re.M)
        return json.dumps({"action": "click", "target": int(found.group(1))})

    return policy


def test_agent_loop_succeeds_with_a_fake_that_reads_the_set_of_marks(env):
    fake = FakeClient(_click_line(r"^\[(\d+)\]<button[^>]*>Click Me!"))
    episode = run_agent_episode(env, fake, "click-test", 0, "som", max_steps=4)
    assert episode.success and episode.steps == 1 and len(fake.calls) == 1
    assert "Click the button." in fake.calls[0][-1]["content"]


def test_raw_html_agent_must_use_selectors_and_sees_its_errors(env):
    replies = iter(['{"action": "click", "target": 3}', '{"action": "click", "target": "#subbtn"}'])
    fake = FakeClient(lambda messages: next(replies))
    episode = run_agent_episode(env, fake, "click-test", 0, "raw_html", max_steps=4)
    assert episode.success and episode.action_errors == 1
    assert "not in the current observation" in episode.history[0]
    assert "error" in fake.calls[1][-1]["content"]  # the model is told what went wrong


def test_invalid_replies_are_counted_and_the_budget_is_respected(env):
    fake = FakeClient(lambda messages: "I think I should click the button")
    episode = run_agent_episode(env, fake, "click-test", 0, "axtree", max_steps=3)
    assert not episode.success and episode.invalid_replies == 3 and episode.steps == 3


def test_a_prompt_over_the_context_window_is_never_sent(env):
    fake = FakeClient(lambda messages: '{"action": "done"}')
    episode = run_agent_episode(env, fake, "click-test", 0, "raw_html", max_steps=3, num_ctx=300)
    assert episode.context_overflow and fake.calls == [] and not episode.success


def test_indexed_encodings_cannot_reach_past_what_they_show_with_a_selector(env):
    replies = iter(['{"action": "click", "target": "#subbtn"}', '{"action": "done"}'])
    fake = FakeClient(lambda messages: next(replies))
    episode = run_agent_episode(env, fake, "click-test", 0, "som", max_steps=3)
    assert not episode.success and episode.action_errors == 1
    assert "acted on by index" in episode.history[0]


def test_the_model_can_wait(env):
    replies = iter(['{"action": "wait", "ms": 50}', '{"action": "done"}'])
    fake = FakeClient(lambda messages: next(replies))
    episode = run_agent_episode(env, fake, "click-test", 0, "axtree", max_steps=3)
    assert episode.history == ["wait ms=50 -> ok", "done"] and episode.error is None


def test_agent_resume_repairs_a_line_cut_off_by_a_kill(env, tmp_path):
    out = tmp_path / "agent.jsonl"
    out.write_text('{"task": "click-test", "seed": 9', encoding="utf-8")  # killed mid-write
    fake = FakeClient(_click_line(r"^\[(\d+)\]<button[^>]*>Click Me!"))
    jobs = [Job("click-test", 0, "som", 4, 1, 0)]
    (episode,) = run_jobs(jobs, fake, out, env=env)
    assert episode.success
    (row,) = load_jsonl(out)
    assert (row["task"], row["seed"], row["success"]) == ("click-test", 0, True)
    assert run_jobs(jobs, fake, out, env=env) == []  # resumes: nothing left to do


def test_resume_keys_on_the_context_window_so_overflows_can_be_retried(env, tmp_path):
    out = tmp_path / "agent.jsonl"
    fake = FakeClient(_click_line(r"^\[(\d+)\]<button[^>]*>Click Me!"))
    jobs = [Job("click-test", 0, "som", 4, 1, 0)]
    (small,) = run_jobs(jobs, fake, out, num_ctx=300, env=env)
    assert small.context_overflow and small.num_ctx == 300
    (large,) = run_jobs(jobs, fake, out, env=env)  # a bigger window is a new job
    assert large.success and large.num_ctx == 16384
    assert run_jobs(jobs, fake, out, env=env) == []


def test_a_page_error_is_a_recorded_failure_not_an_exclusion(env):
    def policy(messages):
        raise PlaywrightError("Element is not attached to the DOM")

    episode = run_agent_episode(env, FakeClient(policy), "click-test", 0, "som", max_steps=2)
    assert not episode.success and episode.error == "Element is not attached to the DOM"


def test_a_dead_browser_stops_the_run_and_records_nothing(env, tmp_path, monkeypatch):
    out = tmp_path / "agent.jsonl"

    def policy(messages):
        # what a crash looks like from here: the call fails and the browser is gone
        monkeypatch.setattr(env, "alive", lambda: False)
        raise PlaywrightError("Target page, context or browser has been closed")

    with pytest.raises(BrowserDiedError):
        run_jobs([Job("click-test", 0, "som", 2, 1, 0)], FakeClient(policy), out, env=env)
    assert out.read_text() == ""  # nothing recorded, so a resume retries the episode
