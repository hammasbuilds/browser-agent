"""Run the scripted oracle over tasks and seeds, measuring every encoding at every step.

Each step: observe the page, encode it five ways, count tokens, resolve the oracle's target,
check the target against every encoding (:mod:`browser_agent.survival`), then execute the step
through the shared action executor and read the benchmark's reward.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from browser_agent import oracles  # noqa: F401  (registers every oracle)
from browser_agent.actions import Action, ActionError, execute
from browser_agent.encoders import encode_all
from browser_agent.env import MiniWoBEnv
from browser_agent.oracles.base import ORACLES, OracleContext, OracleError, Step
from browser_agent.snapshot import Snapshot
from browser_agent.survival import check
from browser_agent.tokens import count_tokens

SETTLE_MS = 100
MAX_ORACLE_STEPS = 40


@dataclass
class StepRecord:
    kind: str
    target: int | None
    needs: list[str]
    target_visible: bool | None
    checks: dict[str, dict[str, bool]]
    tokens: dict[str, int]


@dataclass
class EpisodeRecord:
    task: str
    seed: int
    utterance: str
    raw_reward: float
    done: bool
    reason: str | None
    error: str | None
    steps: list[StepRecord] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return self.done and self.raw_reward > 0

    def as_dict(self) -> dict:
        return asdict(self)


def _target_stamp(env: MiniWoBEnv, selector: str) -> int:
    assert env.page is not None
    loc = env.page.locator(selector)
    count = loc.count()
    if count != 1:
        raise OracleError(f"oracle selector {selector!r} matched {count} elements")
    stamp = loc.get_attribute("data-ba-id")
    if stamp is None:
        raise OracleError(f"oracle target {selector!r} is outside the observed page")
    return int(stamp)


def measure(snap: Snapshot, target: int | None, needs: tuple[str, ...]):
    encodings = encode_all(snap)
    tokens = {name: count_tokens(enc.text) for name, enc in encodings.items()}
    checks: dict[str, dict[str, bool]] = {}
    if target is not None:
        checks = {
            name: check(enc, snap, target, needs).as_dict() for name, enc in encodings.items()
        }
    return tokens, checks


def run_oracle_episode(env: MiniWoBEnv, task: str, seed: int) -> EpisodeRecord:
    registered = ORACLES[task]
    first = env.reset(task, seed, registered.prelude)
    assert env.page is not None
    record = EpisodeRecord(task, seed, first.utterance, 0.0, False, None, None)
    ctx = OracleContext(env.page, first.utterance)
    steps = registered.fn(ctx)
    try:
        for _ in range(MAX_ORACLE_STEPS):
            step: Step | None = next(steps, None)
            if step is None:
                break
            snap = env.observe()
            target = _target_stamp(env, step.selector) if step.selector else None
            tokens, checks = measure(snap, target, step.needs)
            record.steps.append(
                StepRecord(
                    kind=step.kind,
                    target=target,
                    needs=list(step.needs),
                    target_visible=None if target is None else target in snap.visible,
                    checks=checks,
                    tokens=tokens,
                )
            )
            action = Action(step.kind, target, step.text, step.options, step.dy)
            execute(env.page, action, shown=None)
            env.page.wait_for_timeout(SETTLE_MS + step.wait_ms)
            if env.outcome().done:
                break
        else:
            record.error = f"oracle exceeded {MAX_ORACLE_STEPS} steps"
    except (ActionError, OracleError) as exc:
        record.error = f"{type(exc).__name__}: {exc}"
    outcome = env.outcome()
    record.done, record.raw_reward, record.reason = outcome.done, outcome.raw_reward, outcome.reason
    return record


def run_oracle(
    tasks: list[str],
    seeds: list[int],
    out: Path,
    progress: Callable[[EpisodeRecord], None] | None = None,
) -> list[EpisodeRecord]:
    """Run every (task, seed), appending one JSON line per episode to ``out``.

    Episodes already in ``out`` are skipped, so an interrupted run resumes where it stopped.
    """
    done = {(e["task"], e["seed"]) for e in load_jsonl(out)} if out.exists() else set()
    out.parent.mkdir(parents=True, exist_ok=True)
    records: list[EpisodeRecord] = []
    with MiniWoBEnv() as env, out.open("a", encoding="utf-8") as fh:
        for task in tasks:
            for seed in seeds:
                if (task, seed) in done:
                    continue
                record = run_oracle_episode(env, task, seed)
                fh.write(json.dumps(record.as_dict()) + "\n")
                fh.flush()
                records.append(record)
                if progress is not None:
                    progress(record)
    return records


def load_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]
