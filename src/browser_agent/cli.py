"""``browser-agent``: run the oracle, measure encoders, and queue the model arm.

browser-agent tasks                         which tasks run, which are out of scope and why
browser-agent show click-color --seed 0     print every encoding of one page, with tokens
browser-agent oracle --seeds 20             solve tasks with the scripted oracle (JSONL)
browser-agent report                        oracle, tokens, survival and allow_list JSON
browser-agent agent --dry-run               list the model-arm jobs and the call estimate
browser-agent agent                         run the model arm (needs Ollama)
browser-agent agent-report                  agent.json from the model-arm episodes

Bad input is reported as one ``error: ...`` line on stderr with exit code 2, the same code
argparse uses for its own usage errors.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from browser_agent.agent import DEFAULT_NUM_CTX, AgentEpisode, Job
from browser_agent.encoders import ENCODERS, encode_all
from browser_agent.env import MissingBrowserError, TaskNotFoundError
from browser_agent.harness import BrowserDiedError, EpisodeRecord, load_jsonl
from browser_agent.llm import DEFAULT_MODEL, DEFAULT_URL, LLMUnavailableError

# Anchored to the clone, like the vendored pages, so no default depends on the working directory.
ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results"
CACHE = ROOT / "cache"
ORACLE_EPISODES = RESULTS / "oracle_episodes.jsonl"
AGENT_EPISODES = RESULTS / "agent_episodes.jsonl"


class UsageError(Exception):
    """Bad input from the command line: reported as ``error: ...`` with exit code 2."""


def _seeds(n: int) -> list[int]:
    if n < 1:
        raise UsageError("--seeds must be at least 1")
    return list(range(n))


def _tasks(value: str | None) -> list[str] | None:
    """None when --tasks was not given; otherwise a non-empty list of names."""
    if value is None:
        return None
    names = [t.strip() for t in value.split(",") if t.strip()]
    if not names:
        raise UsageError("--tasks was given but names no task")
    return names


def _episodes(path: Path, hint: str) -> list[dict]:
    if not path.is_file():
        raise UsageError(f"{path} not found; {hint}")
    try:
        episodes = load_jsonl(path)
    except ValueError as exc:
        raise UsageError(str(exc)) from None
    if not episodes:
        raise UsageError(f"{path} holds no episodes; {hint}")
    return episodes


def _encoders(value: str) -> list[str]:
    if value.strip() == "all":
        return list(ENCODERS)
    names = [n.strip() for n in value.split(",") if n.strip()]
    if not names:
        raise UsageError("--encoder was given but names no encoder")
    unknown = [n for n in names if n not in ENCODERS]
    if unknown:
        raise UsageError(f"unknown encoder(s) {unknown}; choose from {', '.join(ENCODERS)}")
    return names


def _write(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {path}")


def cmd_tasks(args: argparse.Namespace) -> int:
    from browser_agent.tasks import EXCLUDED, FAMILIES, runnable_tasks, unsolved_in_scope

    runnable = set(runnable_tasks())
    for family, tasks in FAMILIES.items():
        print(f"{family}: " + ", ".join(t for t in tasks if t in runnable))
    missing = unsolved_in_scope()
    if missing:
        print(f"\nin scope but no oracle ({len(missing)}): {', '.join(missing)}")
    print(f"\nout of the action space ({len(EXCLUDED)}):")
    for task, reason in EXCLUDED.items():
        print(f"  {task}: {reason}")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    from browser_agent.env import MiniWoBEnv
    from browser_agent.tokens import count_tokens

    names = _encoders(args.encoder)
    with MiniWoBEnv() as env:
        snap = env.reset(args.task, args.seed)
    print(f"task: {args.task}  seed: {args.seed}\ninstruction: {snap.utterance}\n")
    for name, enc in encode_all(snap).items():
        if name in names:
            print(f"=== {name} ({count_tokens(enc.text)} tokens)\n{enc.text}\n")
    return 0


def cmd_oracle(args: argparse.Namespace) -> int:
    from browser_agent.harness import run_oracle
    from browser_agent.tasks import EXCLUDED, runnable_tasks

    runnable = runnable_tasks()
    tasks = _tasks(args.tasks) or runnable
    for task in tasks:
        if task not in runnable:
            reason = EXCLUDED.get(task)
            why = f"out of the action space ({reason})" if reason else "not a MiniWoB++ task"
            raise UsageError(f"no oracle for {task!r}: {why}; see `browser-agent tasks`")

    def progress(r: EpisodeRecord) -> None:
        mark = "ok " if r.success else "FAIL"
        extra = f"  {r.error}" if r.error else ""
        print(f"{mark} {r.task} seed={r.seed} reward={r.raw_reward:+.2f}{extra}", flush=True)

    run_oracle(tasks, _seeds(args.seeds), Path(args.out), progress)
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    from browser_agent.report import (
        allow_list_summary,
        oracle_summary,
        survival_summary,
        token_summary,
    )

    episodes = _episodes(Path(args.episodes), "run `browser-agent oracle` first")
    if not any(e["done"] and e["raw_reward"] > 0 for e in episodes):
        raise UsageError("no episode was solved, so there are no targets to measure")
    oracle = oracle_summary(episodes)
    tokens = token_summary(episodes)
    survival = survival_summary(episodes)
    out_dir = Path(args.out_dir)
    _write(out_dir / "oracle.json", oracle)
    _write(out_dir / "tokens.json", tokens)
    _write(out_dir / "survival.json", survival)
    _write(out_dir / "allow_list.json", allow_list_summary(episodes, tokens))
    print(
        f"\noracle: {oracle['tasks_always_solved']}/{oracle['tasks']} tasks solved on every seed,"
        f" {oracle['episode_success_rate']:.1%} of {oracle['episodes']} episodes"
    )
    print(
        f"\n{'encoder':<28}{'tokens (median)':>16}{'present':>10}{'identif.':>10}"
        f"{'action.':>10}{'ceiling':>10}"
    )
    for name in ENCODERS:
        s = survival["encoders"][name]
        print(
            f"{name:<28}{tokens[name]['first_obs']['median']:>16.0f}"
            f"{s['present']['mean']:>10.3f}{s['identifiable']['mean']:>10.3f}"
            f"{s['actionable']['mean']:>10.3f}{s['episode_ceiling']['mean']:>10.3f}"
        )
    return 0


def cmd_agent(args: argparse.Namespace) -> int:
    from browser_agent.agent import REPLY_TOKENS, TIMING_TASKS, plan_jobs, run_jobs
    from browser_agent.llm import CachedClient, OllamaClient

    oracle = _episodes(Path(args.oracle_episodes), "the model arm budgets steps from it")
    if args.num_ctx <= REPLY_TOKENS:
        raise UsageError(f"--num-ctx must exceed the {REPLY_TOKENS}-token reply budget")
    tasks = _tasks(args.tasks)
    if tasks is not None:
        known = {e["task"] for e in oracle}
        unknown = [t for t in tasks if t not in known]
        if unknown:
            raise UsageError(f"no oracle episodes for {', '.join(unknown)} in the oracle file")
    jobs = plan_jobs(
        oracle, _encoders(args.encoder), _seeds(args.seeds), tasks, args.include_timing
    )
    if not jobs:
        raise UsageError("no jobs: no oracle-solved episode matches those tasks and seeds")
    if args.dry_run:
        by_encoder: dict[str, list[Job]] = {}
        for job in jobs:
            by_encoder.setdefault(job.encoder, []).append(job)
        print(f"model {args.model}, num_ctx {args.num_ctx}, {len(jobs)} episodes")
        if not args.include_timing and args.tasks is None:
            print(f"  (timing-bound tasks excluded: {', '.join(TIMING_TASKS)})")
        for name, js in by_encoder.items():
            expected = sum(j.oracle_steps + 1 for j in js)
            upper = sum(j.max_steps for j in js)
            toks = sum(j.oracle_prompt_tokens for j in js)
            print(
                f"  {name:<28} {len(js):>5} episodes  calls: ~{expected} expected,"
                f" {upper} at most  prompt tokens at oracle length: ~{toks:,}"
            )
        total_expected = sum(j.oracle_steps + 1 for j in jobs)
        total_upper = sum(j.max_steps for j in jobs)
        print(f"total calls: ~{total_expected} expected (oracle steps + 1), {total_upper} at most")
        return 0
    client = CachedClient(OllamaClient(model=args.model, base_url=args.url), Path(args.cache))

    def progress(e: AgentEpisode) -> None:
        mark = "ok " if e.success else "FAIL"
        print(f"{mark} {e.encoder:<28} {e.task} seed={e.seed} steps={e.steps}", flush=True)

    run_jobs(jobs, client, Path(args.out), args.num_ctx, progress)
    print(f"cache: {client.hits} hits, {client.misses} new generations")
    return 0


def cmd_agent_report(args: argparse.Namespace) -> int:
    from browser_agent.report import agent_summary

    agent = _episodes(Path(args.episodes), "run `browser-agent agent` first")
    oracle = _episodes(Path(args.oracle_episodes), "run `browser-agent oracle` first")
    summary = agent_summary(agent, oracle)
    _write(Path(args.out_dir) / "agent.json", summary)
    for model, per_model in summary["models"].items():
        print(f"\n{model}")
        for name, s in per_model["encoders"].items():
            lo, hi = s["success_macro"]["ci95"]
            print(
                f"  {name:<28} success {s['success_macro']['mean']:.3f} [{lo:.3f}, {hi:.3f}]"
                f"  tokens/episode {s['prompt_tokens_mean']:.0f}"
            )
    return 0


def build_parser() -> argparse.ArgumentParser:
    fmt = argparse.ArgumentDefaultsHelpFormatter
    parser = argparse.ArgumentParser(
        prog="browser-agent",
        description="A Playwright browser agent over MiniWoB++ with pluggable observation "
        "encoders, and a measurement of what each encoder throws away.",
        formatter_class=fmt,
    )
    sub = parser.add_subparsers(dest="command", required=True)
    encoder_help = f"comma list of encoders, or 'all' ({', '.join(ENCODERS)})"

    tasks = sub.add_parser("tasks", help="list runnable and excluded tasks", formatter_class=fmt)
    tasks.set_defaults(fn=cmd_tasks)

    show = sub.add_parser("show", help="print every encoding of one task page", formatter_class=fmt)
    show.add_argument("task", help="MiniWoB++ task name, e.g. click-color")
    show.add_argument("--seed", type=int, default=0, help="page seed")
    show.add_argument("--encoder", default="all", help=encoder_help)
    show.set_defaults(fn=cmd_show)

    oracle = sub.add_parser(
        "oracle", help="run the scripted oracle and record every step", formatter_class=fmt
    )
    oracle.add_argument("--tasks", help="comma list of tasks (omit for every task with an oracle)")
    oracle.add_argument("--seeds", type=int, default=20, help="run seeds 0..N-1")
    oracle.add_argument(
        "--out", default=str(ORACLE_EPISODES), help="episode JSONL; appended to, so runs resume"
    )
    oracle.set_defaults(fn=cmd_oracle)

    report = sub.add_parser(
        "report", help="summarise oracle episodes into results/*.json", formatter_class=fmt
    )
    report.add_argument("--episodes", default=str(ORACLE_EPISODES), help="oracle episode JSONL")
    report.add_argument("--out-dir", default=str(RESULTS), help="where the JSON goes")
    report.set_defaults(fn=cmd_report)

    agent = sub.add_parser("agent", help="run (or --dry-run) the model arm", formatter_class=fmt)
    agent.add_argument("--encoder", default="all", help=encoder_help)
    agent.add_argument("--seeds", type=int, default=5, help="run seeds 0..N-1")
    agent.add_argument("--tasks", help="comma list of tasks (omit for every oracle-solved task)")
    agent.add_argument("--model", default=DEFAULT_MODEL, help="Ollama model tag")
    agent.add_argument("--url", default=DEFAULT_URL, help="Ollama base URL")
    agent.add_argument(
        "--num-ctx", type=int, default=DEFAULT_NUM_CTX, help="context window sent to Ollama"
    )
    agent.add_argument("--cache", default=str(CACHE), help="generation cache directory")
    agent.add_argument(
        "--oracle-episodes",
        default=str(ORACLE_EPISODES),
        help="oracle episode JSONL: which (task, seed) pairs run, and their step budgets",
    )
    agent.add_argument(
        "--out", default=str(AGENT_EPISODES), help="agent episode JSONL; appended to"
    )
    agent.add_argument(
        "--dry-run", action="store_true", help="print the jobs and call estimate, call nothing"
    )
    agent.add_argument(
        "--include-timing",
        action="store_true",
        help="also run the timing-bound tasks (they measure model latency, not the encoding)",
    )
    agent.set_defaults(fn=cmd_agent)

    agent_report = sub.add_parser(
        "agent-report", help="summarise model-arm episodes", formatter_class=fmt
    )
    agent_report.add_argument("--episodes", default=str(AGENT_EPISODES), help="agent episode JSONL")
    agent_report.add_argument(
        "--oracle-episodes", default=str(ORACLE_EPISODES), help="oracle episode JSONL"
    )
    agent_report.add_argument("--out-dir", default=str(RESULTS), help="where agent.json goes")
    agent_report.set_defaults(fn=cmd_agent_report)
    return parser


def _utf8_stdio() -> None:
    """Page text is Unicode (unicode-test); a redirected Windows stream defaults to cp1252."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    _utf8_stdio()
    args = build_parser().parse_args(argv)
    try:
        return args.fn(args)
    except (
        UsageError,
        MissingBrowserError,
        TaskNotFoundError,
        LLMUnavailableError,
        BrowserDiedError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
