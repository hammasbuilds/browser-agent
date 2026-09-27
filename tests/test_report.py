from browser_agent.agent import plan_jobs
from browser_agent.encoders import ENCODERS
from browser_agent.report import agent_summary, oracle_summary, survival_summary, token_summary


def step(ok_for: set[str], tokens: int = 100, targeted: bool = True):
    checks = (
        {
            n: {"present": True, "identifiable": n in ok_for, "actionable": n in ok_for}
            for n in ENCODERS
        }
        if targeted
        else {}
    )
    return {
        "kind": "click",
        "target": 3,
        "needs": ["x"],
        "target_visible": True,
        "checks": checks,
        "tokens": {n: tokens * (i + 1) for i, n in enumerate(ENCODERS)},
    }


def episode(task, seed, steps, reward=1.0):
    return {
        "task": task,
        "seed": seed,
        "utterance": "Click x.",
        "raw_reward": reward,
        "done": True,
        "reason": None,
        "error": None,
        "steps": steps,
    }


ALL = set(ENCODERS)
EPISODES = [
    episode("click-test", 0, [step(ALL)]),
    episode("click-test", 1, [step(ALL)]),
    episode("click-color", 0, [step({"raw_html"})]),
    episode("click-color", 1, [step({"raw_html"}), step(ALL)]),
    episode("click-color", 2, [step(set())], reward=-1.0),  # failed: excluded from survival
]


def test_oracle_summary_counts_tasks_and_keeps_failures():
    out = oracle_summary(EPISODES)
    assert out["tasks"] == 2 and out["episodes"] == 5
    assert out["tasks_always_solved"] == 1
    assert out["tasks_sometimes_failed"] == ["click-color"]
    assert out["per_task"]["click-color"]["failures"][0]["seed"] == 2


def test_survival_is_a_mean_of_task_means_over_solved_episodes_only():
    out = survival_summary(EPISODES)
    assert out["tasks"] == 2 and out["target_steps"] == 5
    clean = out["encoders"]["clean_dom"]
    # click-test: 2/2 identifiable; click-color: 1 of 3 steps -> (1 + 1/3) / 2
    assert clean["identifiable"]["mean"] == round((1 + 1 / 3) / 2, 4)
    assert clean["identifiable"]["tasks_below_1"] == ["click-color"]
    # ceiling: an episode counts only if every target step was usable
    assert clean["episode_ceiling"]["mean"] == 0.5
    assert out["encoders"]["raw_html"]["episode_ceiling"]["mean"] == 1.0
    assert "click-color" in clean["examples_lost"]
    # of the targets raw_html shows identifiably, how many clean_dom keeps usable
    assert clean["usable_given_raw"]["mean"] == round((1 + 1 / 3) / 2, 4)
    assert clean["usable_given_raw"]["tasks_losing_some"] == ["click-color"]
    assert out["target_steps_without_needs"] == 0 and out["invisible_target_steps"] == {}


def test_contrasts_are_paired_per_task_differences():
    eps = [
        episode("click-test", 0, [step({"raw_html", "clean_dom"})]),
        episode("click-link", 0, [step({"raw_html", "clean_dom", "axtree"})]),
    ]
    contrasts = survival_summary(eps)["contrasts_usable_given_raw"]
    assert contrasts["clean_dom - axtree"]["mean"] == 0.5  # (1 - 0 + 1 - 1) / 2
    assert contrasts["som_listeners - som"] == {"mean": 0.0, "ci95": [0.0, 0.0]}


def test_token_summary_reports_share_of_raw_html():
    out = token_summary(EPISODES)
    assert out["raw_html"]["share_of_raw_html_median"] == 1.0
    assert out["clean_dom"]["share_of_raw_html_median"] == 2.0  # fixture: clean = 2 x raw


def test_plan_jobs_budgets_twice_the_oracle_and_skips_unsolved_seeds():
    jobs = plan_jobs(EPISODES, ["som", "axtree"], seeds=[0, 1, 2])
    keys = {(j.task, j.seed, j.encoder) for j in jobs}
    assert ("click-color", 2, "som") not in keys  # oracle failed that seed
    assert len(jobs) == 8
    long = next(j for j in jobs if j.task == "click-color" and j.seed == 1)
    assert (long.oracle_steps, long.max_steps) == (2, 6)
    assert plan_jobs(EPISODES, ["som"], seeds=[0], tasks=["click-test"])[0].task == "click-test"


def test_agent_summary_splits_success_by_whether_the_targets_survived():
    agent = [
        {
            "task": "click-color",
            "seed": 0,
            "encoder": "som",
            "model": "m",
            "success": False,
            "steps": 3,
            "prompt_tokens": 90,
            "invalid_replies": 1,
            "context_overflow": False,
        },
        {
            "task": "click-test",
            "seed": 0,
            "encoder": "som",
            "model": "m",
            "success": True,
            "steps": 1,
            "prompt_tokens": 30,
            "invalid_replies": 0,
            "context_overflow": False,
        },
    ]
    out = agent_summary(agent, EPISODES)["encoders"]["som"]
    assert out["by_survival"]["all_targets_identifiable"]["success"] == 1.0
    assert out["by_survival"]["some_target_lost"]["success"] == 0.0
    assert out["success_macro"]["mean"] == 0.5
    assert out["invalid_reply_rate"] == 0.25
