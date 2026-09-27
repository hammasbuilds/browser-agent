from browser_agent.agent import TIMING_TASKS, plan_jobs
from browser_agent.encoders import ENCODERS
from browser_agent.report import agent_summary, oracle_summary, survival_summary, token_summary


def step(ok_for: set[str], tokens: int = 100, targeted: bool = True, source: str = "instruction"):
    checks = (
        {
            n: {
                "present": True,
                "identifiable": n in ok_for,
                "actionable": True,
                "need_hits": [n in ok_for],
            }
            for n in ENCODERS
        }
        if targeted
        else {}
    )
    return {
        "kind": "click",
        "target": 3,
        "needs": ["x"],
        "need_sources": [source],
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


def agent_row(task, success, model="m", encoder="som", **extra):
    row = {
        "task": task,
        "seed": 0,
        "encoder": encoder,
        "model": model,
        "success": success,
        "steps": 1,
        "prompt_tokens": 30,
        "invalid_replies": 0,
        "context_overflow": False,
    }
    return {**row, **extra}


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
    assert out["need_sources"] == {"instruction": 5, "page": 0, "markup": 0}


def test_dropping_markup_needs_changes_only_the_steps_that_had_them():
    eps = [
        episode("click-test", 0, [step({"raw_html"}, source="markup")]),
        episode("click-link", 0, [step({"raw_html"}, source="instruction")]),
    ]
    sens = survival_summary(eps)["sensitivity_usable_given_raw"]
    assert sens["all_needs"]["clean_dom"]["mean"] == 0.0
    # without the markup need, click-test's target needs nothing and is kept; click-link is not
    assert sens["no_markup_needs"]["clean_dom"]["mean"] == 0.5
    assert sens["no_markup_needs"]["clean_dom"]["tasks_losing_some"] == ["click-link"]
    assert sens["instruction_needs_only"]["clean_dom"]["mean"] == 0.5


def test_contrasts_are_paired_per_task_differences():
    eps = [
        episode("click-test", 0, [step({"raw_html", "clean_dom"})]),
        episode("click-link", 0, [step({"raw_html", "clean_dom", "axtree"})]),
    ]
    contrasts = survival_summary(eps)["contrasts_usable_given_raw"]
    assert contrasts["clean_dom - axtree"]["mean"] == 0.5  # (1 - 0 + 1 - 1) / 2
    assert contrasts["som_listeners - som"] == {"mean": 0.0, "ci95": [0.0, 0.0]}
    assert "clean_dom_wide - clean_dom" in contrasts


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


def test_timing_bound_tasks_are_left_out_unless_asked_for():
    timed = [episode(TIMING_TASKS[0], 0, [step(ALL)])]
    assert plan_jobs(timed, ["som"], seeds=[0]) == []
    assert len(plan_jobs(timed, ["som"], seeds=[0], include_timing=True)) == 1
    assert len(plan_jobs(timed, ["som"], seeds=[0], tasks=[TIMING_TASKS[0]])) == 1


def test_agent_summary_splits_success_by_whether_the_targets_were_usable():
    agent = [
        agent_row("click-color", False, steps=3, prompt_tokens=90, invalid_replies=1),
        agent_row("click-test", True),
    ]
    out = agent_summary(agent, EPISODES)["models"]["m"]["encoders"]["som"]
    assert out["by_survival"]["all_targets_usable"]["success"] == 1.0
    assert out["by_survival"]["some_target_lost"]["success"] == 0.0
    assert out["success_macro"]["mean"] == 0.5
    assert out["invalid_reply_rate"] == 0.25


def test_the_survival_split_uses_the_usable_measure_not_identifiable_alone():
    # identifiable but not reachable by an index: lost for the split, as for the ceiling
    unreachable = step({"raw_html"})
    unreachable["checks"]["som"] = {
        "present": True,
        "identifiable": True,
        "actionable": False,
        "need_hits": [True],
    }
    oracle = [episode("click-test", 0, [unreachable])]
    out = agent_summary([agent_row("click-test", True)], oracle)["models"]["m"]
    assert "some_target_lost" in out["encoders"]["som"]["by_survival"]


def test_models_are_never_pooled():
    agent = [agent_row("click-test", True, model="a"), agent_row("click-test", False, model="b")]
    models = agent_summary(agent, EPISODES)["models"]
    assert models["a"]["encoders"]["som"]["success_macro"]["mean"] == 1.0
    assert models["b"]["encoders"]["som"]["success_macro"]["mean"] == 0.0


def test_page_errors_count_as_failures_and_are_reported():
    agent = [agent_row("click-test", True), agent_row("click-color", False, error="detached")]
    summary = agent_summary(agent, EPISODES)["models"]["m"]
    assert summary["page_errors"] == 1
    assert summary["encoders"]["som"]["episodes"] == 2
    assert summary["encoders"]["som"]["success_macro"]["mean"] == 0.5
