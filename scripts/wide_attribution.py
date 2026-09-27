"""Which attribute rescues each target the wide allow-list recovers: styling, or data-*?

The wide ablation adds ``class``, ``style`` and ``data-*``. MiniWoB++ often writes the grader's
answer into a ``data-*`` attribute (``data-color`` in click-shades, ``data-type`` in
click-widget), which a real site would not do. This reruns the oracle on the tasks the narrow
encoders lose, with two extra encoders that add ``class`` and ``style`` but no ``data-*``, and
writes per task how much of the recovery survives without them.

    uv run python scripts/wide_attribution.py            # seeds 0-19, ~5 min
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

from browser_agent.encoders import ENCODERS, clean_dom, som_listeners
from browser_agent.harness import load_jsonl, run_oracle
from browser_agent.stats import mean

ROOT = Path(__file__).resolve().parents[1]
PAIRS = {
    "clean_dom": ("clean_dom_wide", "clean_dom_wide_no_data"),
    "som_listeners": ("som_listeners_wide", "som_listeners_wide_no_data"),
}


def usable(step: dict, name: str) -> bool:
    check = step["checks"][name]
    return check["identifiable"] and check["actionable"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seeds", type=int, default=20)
    parser.add_argument("--survival", default=str(ROOT / "results" / "survival.json"))
    parser.add_argument("--out-dir", default=str(ROOT / "results"))
    args = parser.parse_args()

    ENCODERS["clean_dom_wide_no_data"] = lambda s: clean_dom(s, wide=True, data=False)
    ENCODERS["som_listeners_wide_no_data"] = lambda s: som_listeners(s, wide=True, data=False)

    survival = json.loads(Path(args.survival).read_text(encoding="utf-8"))["encoders"]
    tasks = sorted(
        {t for narrow in PAIRS for t in survival[narrow]["usable_given_raw"]["tasks_losing_some"]}
    )
    out_dir = Path(args.out_dir)
    episodes_path = out_dir / "wide_attribution_episodes.jsonl"
    run_oracle(tasks, list(range(args.seeds)), episodes_path)

    kept: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    for ep in load_jsonl(episodes_path):
        if not (ep["done"] and ep["raw_reward"] > 0):
            continue
        for step in ep["steps"]:
            if step["checks"] and step["checks"]["raw_html"]["identifiable"]:
                for narrow, variants in PAIRS.items():
                    for name in (narrow, *variants):
                        kept[ep["task"]][name].append(int(usable(step, name)))
    result = {
        "note": "share of raw-identifiable targets kept, per task, seeds 0..N-1",
        "tasks": {
            task: {name: round(mean(v), 4) for name, v in sorted(by_name.items())}
            for task, by_name in sorted(kept.items())
        },
    }
    for narrow, (wide, no_data) in PAIRS.items():
        gained = [t for t, v in result["tasks"].items() if v[wide] > v[narrow]]
        result[f"{narrow}: tasks gained by wide"] = gained
        result[f"{narrow}: of those, gained without data-*"] = [
            t for t in gained if result["tasks"][t][no_data] > result["tasks"][t][narrow]
        ]
    (out_dir / "wide_attribution.json").write_text(
        json.dumps(result, indent=1) + "\n", encoding="utf-8", newline="\n"
    )
    print(json.dumps({k: v for k, v in result.items() if k != "tasks"}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
