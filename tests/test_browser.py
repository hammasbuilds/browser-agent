"""End-to-end checks on real Chromium (skipped when Playwright's Chromium is not installed)."""

import json
import re

import pytest

from browser_agent.actions import Action, ActionError, execute
from browser_agent.agent import run_agent_episode
from browser_agent.harness import run_oracle_episode
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
    assert set(record.steps[0].checks) == {
        "raw_html",
        "clean_dom",
        "axtree",
        "som",
        "som_listeners",
    }
    assert record.steps[0].tokens["raw_html"] > record.steps[0].tokens["som"]


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
