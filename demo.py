"""Four MiniWoB++ pages, solved by the oracle, seen through all seven encoders.

For each page: the instruction, what each encoding costs in tokens, and whether the element
the oracle had to act on survives in it (P = present, I = identifiable, A = actionable). The
correct answer is known for every one: the benchmark's own reward says the oracle solved it.

    uv run python demo.py
"""

from __future__ import annotations

import sys

from browser_agent.encoders import ENCODERS
from browser_agent.env import MiniWoBEnv, MissingBrowserError
from browser_agent.harness import run_oracle_episode

CASES = [("click-color", 0), ("login-user", 0), ("click-shape", 1), ("click-collapsible-2", 0)]


def flags(check: dict[str, bool]) -> str:
    return "".join(
        letter if check[key] else "."
        for letter, key in (("P", "present"), ("I", "identifiable"), ("A", "actionable"))
    )


def show(env: MiniWoBEnv, task: str, seed: int) -> None:
    record = run_oracle_episode(env, task, seed)
    print(f"\n{task} (seed {seed}): {record.utterance}")
    print(f"  benchmark reward: {record.raw_reward:+.1f} after {len(record.steps)} steps")
    first = record.steps[0].tokens
    print("  tokens, first observation: " + "  ".join(f"{n} {first[n]}" for n in ENCODERS))
    for i, step in enumerate(record.steps, 1):
        needs = ", ".join(step.needs) or "(position only)"
        cells = "  ".join(f"{n} {flags(step.checks[n])}" for n in ENCODERS)
        print(f"  step {i} {step.kind:<6} needs [{needs}]  {cells}")


def main() -> int:
    try:
        with MiniWoBEnv() as env:
            for task, seed in CASES:
                show(env, task, seed)
    except MissingBrowserError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
