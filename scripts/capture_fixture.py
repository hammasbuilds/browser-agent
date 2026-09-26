"""Save the first observation of a task as a JSON snapshot for the browser-free tests.

uv run python scripts/capture_fixture.py click-color 0 login-user 0 ...
"""

from __future__ import annotations

import sys
from pathlib import Path

from browser_agent.env import MiniWoBEnv

OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures"


def main(argv: list[str]) -> int:
    if not argv or len(argv) % 2:
        print(__doc__)
        return 2
    pairs = list(zip(argv[::2], map(int, argv[1::2]), strict=True))
    OUT.mkdir(parents=True, exist_ok=True)
    with MiniWoBEnv() as env:
        for task, seed in pairs:
            path = OUT / f"{task}-{seed}.json"
            path.write_text(env.reset(task, seed).to_json(), encoding="utf-8")
            print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
