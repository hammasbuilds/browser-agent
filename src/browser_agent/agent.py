"""The model arm: an LLM acting on MiniWoB++ through one encoding at a time.

Everything the model sees is the instruction, its own previous actions with their results, and
the current page in the chosen encoding. It answers with one JSON action, executed by the same
executor the oracle uses, restricted to the indices that encoding actually showed.

Budgets are per (task, seed): ``2 x oracle steps + 2`` actions, where the oracle's step count
for that exact seed comes from ``results/oracle_episodes.jsonl``. A prompt that does not fit
the context window is not sent (Ollama would silently drop its beginning); the episode ends as
a ``context_overflow`` failure, which is a real cost of that encoding.
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from playwright.sync_api import Error as PlaywrightError

from browser_agent.actions import MAX_WAIT_MS, ActionError, execute, parse_action
from browser_agent.encoders import ENCODERS, Encoding
from browser_agent.env import MiniWoBEnv
from browser_agent.harness import BrowserDiedError, load_jsonl
from browser_agent.llm import ChatClient, Message
from browser_agent.tokens import count_tokens

DEFAULT_NUM_CTX = 16384
REPLY_TOKENS = 256
TEMPLATE_OVERHEAD = 32  # Qwen chat-template tokens around two messages, rounded up
# After each action, before the next observation: long enough for the jQuery UI animations
# (accordion, datepicker) the oracle waits 400-600 ms for.
SETTLE_MS = 600

SYSTEM = f"""You operate a web page to complete a task. Each turn you get the task, your \
previous actions with their results, and the current page. Reply with exactly one action as a \
JSON object and nothing else:
{{"action": "click", "target": T}}
{{"action": "type", "target": T, "text": "..."}}         (replaces the field's contents)
{{"action": "select", "target": T, "options": ["label"]}} (list every label to select)
{{"action": "scroll", "target": T, "dy": 100}}           (target null scrolls the window)
{{"action": "submit", "target": T}}                      (presses Enter in T)
{{"action": "wait", "ms": 1000}}                         (at most {MAX_WAIT_MS} ms)
{{"action": "done"}}                                     (only when the task is complete)
"""

TARGET_HELP = {
    "raw_html": "T is a CSS selector that matches exactly one element of the HTML below.",
    "clean_dom": "T is the number in an element's i=N attribute, e.g. 12.",
    "axtree": "T is the number in square brackets at the end of a line, e.g. 12 for [12].",
    "som": "T is the number in square brackets at the start of a line, e.g. 12 for [12].",
    "som_listeners": "T is the number in square brackets at the start of a line, e.g. 12 for [12].",
}
TARGET_HELP["clean_dom_wide"] = TARGET_HELP["clean_dom"]
TARGET_HELP["som_listeners_wide"] = TARGET_HELP["som_listeners"]

PAGE_LABEL = {
    "raw_html": "the page's HTML",
    "clean_dom": "a cleaned version of the page's HTML",
    "axtree": "the page's accessibility tree",
    "som": "the page's interactive elements",
    "som_listeners": "the page's interactive elements",
}
PAGE_LABEL["clean_dom_wide"] = PAGE_LABEL["clean_dom"]
PAGE_LABEL["som_listeners_wide"] = PAGE_LABEL["som_listeners"]


def build_messages(utterance: str, history: list[str], enc: Encoding) -> list[Message]:
    past = "\n".join(f"{i + 1}. {h}" for i, h in enumerate(history)) or "(none)"
    user = (
        f"Task: {utterance}\n\n"
        f"Previous actions:\n{past}\n\n"
        f"{TARGET_HELP[enc.name]}\n\n"
        f"Current page ({PAGE_LABEL[enc.name]}):\n{enc.text}\n\n"
        "Next action (JSON only):"
    )
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]


def prompt_tokens(messages: list[Message]) -> int:
    return sum(count_tokens(m["content"]) for m in messages) + TEMPLATE_OVERHEAD


def options_for(num_ctx: int) -> dict[str, Any]:
    return {"temperature": 0, "seed": 0, "num_ctx": num_ctx, "num_predict": REPLY_TOKENS}


@dataclass
class AgentEpisode:
    task: str
    seed: int
    encoder: str
    model: str
    success: bool
    raw_reward: float
    done: bool
    steps: int
    max_steps: int
    prompt_tokens: int
    invalid_replies: int
    action_errors: int
    context_overflow: bool
    history: list[str]
    num_ctx: int = DEFAULT_NUM_CTX
    # A page-level Playwright error ended the episode early. It still counts as a failure: the
    # page misbehaving under the model's actions is part of the task. (A browser that dies
    # outright stops the run instead; nothing is recorded, and resume retries the episode.)
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def run_agent_episode(
    env: MiniWoBEnv,
    client: ChatClient,
    task: str,
    seed: int,
    encoder: str,
    max_steps: int,
    num_ctx: int = DEFAULT_NUM_CTX,
) -> AgentEpisode:
    if num_ctx <= REPLY_TOKENS:
        raise ValueError(f"num_ctx must exceed the {REPLY_TOKENS}-token reply budget")
    encode = ENCODERS[encoder]
    # Indexed encodings are acted on by the indices they show; raw HTML only by selectors.
    by_selector = encoder == "raw_html"
    episode = AgentEpisode(
        task,
        seed,
        encoder,
        client.model,
        False,
        0.0,
        False,
        0,
        max_steps,
        0,
        0,
        0,
        False,
        [],
        num_ctx,
    )
    history = episode.history
    try:
        snap = env.reset(task, seed)
        assert env.page is not None
        for _ in range(max_steps):
            enc = encode(snap)
            messages = build_messages(snap.utterance, history, enc)
            n_prompt = prompt_tokens(messages)
            if n_prompt + REPLY_TOKENS > num_ctx:
                episode.context_overflow = True
                break
            reply = client.chat(messages, options_for(num_ctx))
            episode.prompt_tokens += n_prompt
            episode.steps += 1
            try:
                action = parse_action(reply)
            except ActionError as exc:
                episode.invalid_replies += 1
                history.append(f"{reply.strip()[:120]!r} -> invalid reply: {exc}")
                continue
            if action.kind == "done":
                history.append("done")
                break
            try:
                execute(env.page, action, shown=enc.handles, selectors=by_selector)
                history.append(f"{action.describe()} -> ok")
            except ActionError as exc:
                episode.action_errors += 1
                history.append(f"{action.describe()} -> error: {exc}")
            env.page.wait_for_timeout(SETTLE_MS)
            if env.outcome().done:
                break
            snap = env.observe()
        outcome = env.outcome()
        episode.done, episode.raw_reward = outcome.done, outcome.raw_reward
        episode.success = outcome.done and outcome.raw_reward > 0
    except PlaywrightError as exc:
        if not env.alive():
            raise BrowserDiedError(f"browser died during {task} seed {seed}") from exc
        episode.error = str(exc).strip().splitlines()[0] if str(exc).strip() else "PlaywrightError"
    return episode


# ---- job planning --------------------------------------------------------------------------


@dataclass(frozen=True)
class Job:
    task: str
    seed: int
    encoder: str
    max_steps: int
    oracle_steps: int
    oracle_prompt_tokens: int  # tokens of this encoding summed over the oracle's observations


# Tasks whose reward depends on acting within a window measured in hundreds of milliseconds.
# A model that takes seconds per step fails them whatever it reads, and slower (longer)
# encodings fail them more, so they would measure latency, not the encoding. Excluded from
# the model arm unless asked for.
TIMING_TASKS = ("button-delay", "simon-says", "stock-market")


def plan_jobs(
    oracle_episodes: list[dict[str, Any]],
    encoders: list[str],
    seeds: list[int],
    tasks: list[str] | None = None,
    include_timing: bool = False,
) -> list[Job]:
    """One job per (task, seed, encoder) whose oracle episode was solved."""
    jobs: list[Job] = []
    for ep in oracle_episodes:
        if not (ep["done"] and ep["raw_reward"] > 0) or ep["seed"] not in seeds:
            continue
        if tasks is not None and ep["task"] not in tasks:
            continue
        if ep["task"] in TIMING_TASKS and not include_timing and tasks is None:
            continue
        n = len(ep["steps"])
        for name in encoders:
            jobs.append(
                Job(
                    task=ep["task"],
                    seed=ep["seed"],
                    encoder=name,
                    max_steps=2 * n + 2,
                    oracle_steps=n,
                    oracle_prompt_tokens=sum(s["tokens"][name] for s in ep["steps"]),
                )
            )
    return jobs


def run_jobs(
    jobs: list[Job],
    client: ChatClient,
    out: Path,
    num_ctx: int = DEFAULT_NUM_CTX,
    progress: Callable[[AgentEpisode], None] | None = None,
    env: MiniWoBEnv | None = None,
) -> list[AgentEpisode]:
    """Run jobs not yet in ``out`` (keyed by task, seed, encoder, model, num_ctx), appending.

    Uses ``env`` if given (already entered), otherwise launches and closes its own browser.
    """
    seen = set()
    if out.exists():
        done = load_jsonl(out, repair=True)
        seen = {
            (e["task"], e["seed"], e["encoder"], e["model"], e.get("num_ctx", DEFAULT_NUM_CTX))
            for e in done
        }
    out.parent.mkdir(parents=True, exist_ok=True)
    results: list[AgentEpisode] = []
    pending = [j for j in jobs if (j.task, j.seed, j.encoder, client.model, num_ctx) not in seen]
    if not pending:
        return results
    browser = contextlib.nullcontext(env) if env is not None else MiniWoBEnv()
    with browser as env, out.open("a", encoding="utf-8", newline="
") as fh:
        for job in pending:
            episode = run_agent_episode(
                env, client, job.task, job.seed, job.encoder, job.max_steps, num_ctx
            )
            if not env.alive():
                raise BrowserDiedError(f"browser died during {job}: rerun to resume")
            fh.write(json.dumps(episode.as_dict()) + "\n")
            fh.flush()
            results.append(episode)
            if progress is not None:
                progress(episode)
    return results
