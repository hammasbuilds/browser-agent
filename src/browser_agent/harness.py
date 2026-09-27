"""Run the scripted oracle over tasks and seeds, measuring every encoding at every step.

Each step: observe the page, encode it seven ways, count tokens, resolve the oracle's target,
check the target against every encoding (:mod:`browser_agent.survival`), then execute the step
through the shared action executor and read the benchmark's reward.
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from playwright.sync_api import Error as PlaywrightError

from browser_agent import oracles  # noqa: F401  (registers every oracle)
from browser_agent.actions import Action, execute
from browser_agent.encoders import encode_all
from browser_agent.env import MiniWoBEnv
from browser_agent.oracles.base import ORACLES, OracleContext, OracleError, Step
from browser_agent.snapshot import Snapshot
from browser_agent.survival import check, need_source
from browser_agent.tokens import count_tokens

SETTLE_MS = 100


class BrowserDiedError(RuntimeError):
    """The browser went away mid-run; nothing was recorded for the episode in flight."""


MAX_ORACLE_STEPS = 40


@dataclass
class StepRecord:
    kind: str
    target: int | None
    needs: list[str]
    need_sources: list[str]  # per need: instruction / page / markup (survival.need_source)
    target_visible: bool | None
    checks: dict[str, dict[str, Any]]
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


def measure(
    snap: Snapshot, target: int | None, needs: tuple[str, ...]
) -> tuple[dict[str, int], dict[str, dict[str, Any]]]:
    encodings = encode_all(snap)
    tokens = {name: count_tokens(enc.text) for name, enc in encodings.items()}
    checks: dict[str, dict[str, Any]] = {}
    if target is not None:
        checks = {
            name: check(enc, snap, target, needs).as_dict() for name, enc in encodings.items()
        }
    return tokens, checks


def run_oracle_episode(env: MiniWoBEnv, task: str, seed: int) -> EpisodeRecord:
    """One seeded episode. Never raises for a task-level failure: the failure is recorded.

    Anything that goes wrong inside the episode (an action the page refuses, an oracle that
    cannot parse the page, a Playwright timeout, a bug in an oracle) ends that episode with
    ``error`` set, so one bad (task, seed) cannot stop, or forever block the resume of, a run.
    """
    registered = ORACLES[task]
    record = EpisodeRecord(task, seed, "", 0.0, False, None, None)
    try:
        first = env.reset(task, seed, registered.prelude)
        assert env.page is not None
        record.utterance = first.utterance
        steps = registered.fn(OracleContext(env.page, first.utterance))
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
                    need_sources=[
                        need_source(n, snap.utterance, snap.page_text()) for n in step.needs
                    ],
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
        outcome = env.outcome()
        record.done, record.raw_reward = outcome.done, outcome.raw_reward
        record.reason = outcome.reason
    except Exception as exc:  # noqa: BLE001  (recorded, reported as a failure, never hidden)
        first_line = str(exc).strip().splitlines()[0] if str(exc).strip() else ""
        record.error = f"{type(exc).__name__}: {first_line}"
        with contextlib.suppress(PlaywrightError, RuntimeError):
            outcome = env.outcome()
            record.done, record.raw_reward = outcome.done, outcome.raw_reward
    return record


def run_oracle(
    tasks: list[str],
    seeds: list[int],
    out: Path,
    progress: Callable[[EpisodeRecord], None] | None = None,
) -> list[EpisodeRecord]:
    """Run every (task, seed), appending one JSON line per episode to ``out``.

    Episodes already in ``out`` are skipped, so an interrupted run resumes where it stopped.
    If the browser itself dies, the run stops *without* recording that episode, so a resume
    retries it instead of inheriting a crash as a task failure.
    """
    done = {(e["task"], e["seed"]) for e in load_jsonl(out, repair=True)} if out.exists() else set()
    out.parent.mkdir(parents=True, exist_ok=True)
    records: list[EpisodeRecord] = []
    with MiniWoBEnv() as env, out.open("a", encoding="utf-8", newline="
") as fh:
        for task in tasks:
            for seed in seeds:
                if (task, seed) in done:
                    continue
                record = run_oracle_episode(env, task, seed)
                if not env.alive():
                    raise BrowserDiedError(f"browser died during {task} seed {seed}: rerun")
                fh.write(json.dumps(record.as_dict()) + "\n")
                fh.flush()
                records.append(record)
                if progress is not None:
                    progress(record)
    return records


def load_jsonl(path: Path, repair: bool = False) -> list[dict]:
    """Read one JSON object per line.

    A run killed mid-write leaves a truncated last line. It is skipped when reading and, with
    ``repair=True`` (before appending more), cut from the file so the next record starts on a
    line of its own. A bad line anywhere else is corruption and raises.
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    records: list[dict] = []
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            if i != len(lines) - 1:
                raise ValueError(f"{path}: line {i + 1} is not JSON") from None
            if repair:
                keep = "".join(json.dumps(r) + "\n" for r in records)
                path.write_text(keep, encoding="utf-8", newline="
")
    return records
