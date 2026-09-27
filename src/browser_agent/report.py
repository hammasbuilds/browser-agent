"""Turn oracle episodes (JSONL) into the three results files the README quotes.

``results/oracle.json``    does the harness solve each task? (per-task success, Wilson CI)
``results/tokens.json``    observation cost per encoder, in Qwen2.5 tokens
``results/survival.json``  target survival per encoder: present / identifiable / actionable

Unit of analysis: the task. Each task contributes its mean over seeds; intervals bootstrap
over tasks. Survival uses only steps from episodes the oracle solved, so every target measured
is one that provably had to be acted on.
"""

from __future__ import annotations

from collections import defaultdict
from itertools import combinations
from typing import Any

from browser_agent.encoders import ENCODERS
from browser_agent.stats import bootstrap_mean_ci, mean, quantile, wilson
from browser_agent.tasks import ORACLE_LIMITS, family_of

LEVELS = ("present", "identifiable", "actionable")
Episode = dict[str, Any]


def _success(ep: Episode) -> bool:
    return bool(ep["done"]) and ep["raw_reward"] > 0


def _by_task(episodes: list[Episode]) -> dict[str, list[Episode]]:
    grouped: dict[str, list[Episode]] = defaultdict(list)
    for ep in episodes:
        grouped[ep["task"]].append(ep)
    return dict(grouped)


def _interval(values: list[float]) -> dict[str, float]:
    lo, hi = bootstrap_mean_ci(values)
    return {"mean": round(mean(values), 4), "ci95": [round(lo, 4), round(hi, 4)]}


# ---- oracle --------------------------------------------------------------------------------


def oracle_summary(episodes: list[Episode]) -> dict[str, Any]:
    per_task = {}
    for task, eps in sorted(_by_task(episodes).items()):
        wins = sum(_success(e) for e in eps)
        lo, hi = wilson(wins, len(eps))
        failures = [
            {"seed": e["seed"], "raw_reward": e["raw_reward"], "error": e["error"]}
            for e in eps
            if not _success(e)
        ]
        per_task[task] = {
            "family": family_of(task),
            "episodes": len(eps),
            "solved": wins,
            "rate": round(wins / len(eps), 4),
            "wilson95": [round(lo, 4), round(hi, 4)],
            "steps_mean": round(mean([len(e["steps"]) for e in eps]), 2),
            "failures": failures[:5],
        }
        if failures:
            per_task[task]["explanation"] = ORACLE_LIMITS.get(task, "UNEXPLAINED")
    rates = [t["rate"] for t in per_task.values()]
    return {
        "tasks": len(per_task),
        "episodes": len(episodes),
        "tasks_always_solved": sum(r == 1.0 for r in rates),
        "tasks_never_solved": sorted(k for k, t in per_task.items() if t["solved"] == 0),
        "tasks_sometimes_failed": sorted(k for k, t in per_task.items() if 0 < t["rate"] < 1),
        "episode_success_rate": round(sum(_success(e) for e in episodes) / len(episodes), 4),
        "per_task": per_task,
    }


# ---- tokens --------------------------------------------------------------------------------


def token_summary(episodes: list[Episode]) -> dict[str, Any]:
    """Tokens of the first observation, and of every observation the oracle made."""
    first: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    every: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    for ep in episodes:
        if not ep["steps"]:
            continue
        for name, n in ep["steps"][0]["tokens"].items():
            first[name][ep["task"]].append(n)
        for step in ep["steps"]:
            for name, n in step["tokens"].items():
                every[name][ep["task"]].append(n)
    out: dict[str, Any] = {"unit": "Qwen2.5 tokens per observation; per-task mean over seeds"}
    raw_first = {t: mean(v) for t, v in first["raw_html"].items()}
    for name in ENCODERS:
        per_task = {t: mean(v) for t, v in first[name].items()}
        values = list(per_task.values())
        ratios = [per_task[t] / raw_first[t] for t in per_task if raw_first[t] > 0]
        out[name] = {
            "first_obs": {
                "median": round(quantile(values, 0.5), 1),
                "mean": round(mean(values), 1),
                "p90": round(quantile(values, 0.9), 1),
                "max": round(max(values), 1),
                "max_task": max(per_task, key=lambda t: per_task[t]),
            },
            "all_obs_mean": round(mean([mean(v) for v in every[name].values()]), 1),
            "share_of_raw_html_median": round(quantile(ratios, 0.5), 4),
            "per_task_first_obs": {t: round(v, 1) for t, v in sorted(per_task.items())},
        }
    return out


# ---- survival ------------------------------------------------------------------------------


CLEANERS = [n for n in ENCODERS if n != "raw_html"]
# Every pair of cleaners except som + som_listeners, where one contains the other by design.
PAIRS = [p for p in combinations(CLEANERS, 2) if set(p) != {"som", "som_listeners"}]


def _usable(step: dict[str, Any], name: str) -> bool:
    """Identifiable, and reachable: by an index, or for raw_html by any CSS selector."""
    check = step["checks"][name]
    return check["identifiable"] and (check["actionable"] or name == "raw_html")


def survival_summary(episodes: list[Episode]) -> dict[str, Any]:
    solved = [e for e in episodes if _success(e)]
    # task -> encoder -> level -> list of 0/1 over target steps
    cells: dict[str, dict[str, dict[str, list[int]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(list))
    )
    # task -> encoder -> 0/1 over target steps whose needs raw_html shows: kept by this encoder?
    kept: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    # task -> encoder -> list of 0/1 per episode: every target identifiable and reachable
    ceiling: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    examples: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for ep in solved:
        targeted = [s for s in ep["steps"] if s["checks"]]
        for name in ENCODERS:
            ok_all = True
            for step in targeted:
                check = step["checks"][name]
                for level in LEVELS:
                    cells[ep["task"]][name][level].append(int(check[level]))
                usable = _usable(step, name)
                if step["checks"]["raw_html"]["identifiable"]:
                    kept[ep["task"]][name].append(int(usable))
                ok_all = ok_all and usable
                if not check["identifiable"] and ep["task"] not in examples[name]:
                    examples[name][ep["task"]] = {
                        "seed": ep["seed"],
                        "utterance": ep["utterance"],
                        "needs": step["needs"],
                        "present": check["present"],
                    }
            if targeted:
                ceiling[ep["task"]][name].append(int(ok_all))
        for a, b in PAIRS:
            for step in targeted:
                if step["checks"]["raw_html"]["identifiable"]:
                    either = _usable(step, a) or _usable(step, b)
                    kept[ep["task"]][f"{a}+{b}"].append(int(either))

    tasks = sorted(cells)
    out: dict[str, Any] = {
        "unit": "per-task mean over target steps in oracle-solved episodes; CI bootstraps tasks",
        "usable_given_raw": "of the targets raw_html shows identifiably, the share this encoding "
        "keeps identifiable and reachable by an index (raw_html: by any selector)",
        "tasks": len(tasks),
        "target_steps": sum(len(cells[t]["raw_html"]["present"]) for t in tasks),
        "encoders": {},
    }
    for name in ENCODERS:
        entry: dict[str, Any] = {}
        for level in LEVELS:
            per_task = {t: mean(cells[t][name][level]) for t in tasks}
            entry[level] = _interval(list(per_task.values()))
            entry[level]["tasks_below_1"] = sorted(t for t, v in per_task.items() if v < 1)
        kept_by_task = {t: mean(kept[t][name]) for t in tasks if kept[t][name]}
        entry["usable_given_raw"] = _interval(list(kept_by_task.values()))
        entry["usable_given_raw"]["tasks"] = len(kept_by_task)
        entry["usable_given_raw"]["tasks_losing_some"] = sorted(
            t for t, v in kept_by_task.items() if v < 1
        )
        ceil = {t: mean(ceiling[t][name]) for t in tasks if ceiling[t][name]}
        entry["episode_ceiling"] = _interval(list(ceil.values()))
        by_family: dict[str, list[float]] = defaultdict(list)
        for t in tasks:
            by_family[family_of(t)].append(mean(cells[t][name]["identifiable"]))
        entry["identifiable_by_family"] = {
            f: {"tasks": len(v), "mean": round(mean(v), 4)} for f, v in sorted(by_family.items())
        }
        entry["examples_lost"] = examples[name]
        out["encoders"][name] = entry
    out["pairs_usable_given_raw"] = {}
    for a, b in PAIRS:
        pair = f"{a}+{b}"
        by_task = {t: mean(kept[t][pair]) for t in tasks if kept[t][pair]}
        out["pairs_usable_given_raw"][pair] = _interval(list(by_task.values()))
        out["pairs_usable_given_raw"][pair]["tasks_losing_some"] = sorted(
            t for t, v in by_task.items() if v < 1
        )
    return out


# ---- model arm -----------------------------------------------------------------------------


def agent_summary(agent_eps: list[Episode], oracle_eps: list[Episode]) -> dict[str, Any]:
    """Success per encoder (macro over tasks, and per family), cost, and the survival join.

    The join asks the question the non-model analysis cannot: when the oracle's targets were
    *not* identifiable in an encoding, how often did the model still succeed with it?
    """
    oracle_by_key = {(e["task"], e["seed"]): e for e in oracle_eps}
    out: dict[str, Any] = {"model": sorted({e["model"] for e in agent_eps}), "encoders": {}}
    for name in ENCODERS:
        eps = [e for e in agent_eps if e["encoder"] == name]
        if not eps:
            continue
        per_task: dict[str, list[int]] = defaultdict(list)
        per_family: dict[str, list[int]] = defaultdict(list)
        split: dict[str, list[int]] = {"all_targets_identifiable": [], "some_target_lost": []}
        for e in eps:
            per_task[e["task"]].append(int(e["success"]))
            per_family[family_of(e["task"])].append(int(e["success"]))
            oracle = oracle_by_key.get((e["task"], e["seed"]))
            if oracle is not None:
                checks = [s["checks"][name] for s in oracle["steps"] if s["checks"]]
                key = (
                    "all_targets_identifiable"
                    if all(c["identifiable"] for c in checks)
                    else "some_target_lost"
                )
                split[key].append(int(e["success"]))
        wins = sum(int(e["success"]) for e in eps)
        entry: dict[str, Any] = {
            "episodes": len(eps),
            "tasks": len(per_task),
            "success_macro": _interval([mean(v) for v in per_task.values()]),
            "success_pooled": round(wins / len(eps), 4),
            "success_pooled_wilson95": [round(x, 4) for x in wilson(wins, len(eps))],
            "steps_mean": round(mean([e["steps"] for e in eps]), 2),
            "prompt_tokens_mean": round(mean([e["prompt_tokens"] for e in eps]), 1),
            "context_overflow_rate": round(mean([int(e["context_overflow"]) for e in eps]), 4),
            "invalid_reply_rate": round(
                sum(e["invalid_replies"] for e in eps) / max(1, sum(e["steps"] for e in eps)), 4
            ),
            "by_family": {},
            "by_survival": {},
        }
        for fam, v in sorted(per_family.items()):
            lo, hi = wilson(sum(v), len(v))
            entry["by_family"][fam] = {
                "episodes": len(v),
                "success": round(mean(v), 4),
                "wilson95": [round(lo, 4), round(hi, 4)],
            }
        for key, v in split.items():
            if v:
                lo, hi = wilson(sum(v), len(v))
                entry["by_survival"][key] = {
                    "episodes": len(v),
                    "success": round(mean(v), 4),
                    "wilson95": [round(lo, 4), round(hi, 4)],
                }
        out["encoders"][name] = entry
    return out
