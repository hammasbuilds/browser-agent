# STATUS

**READY-FOR-MODEL-RUN.** Everything that needs no model is built, run and written up; the
model arm is built, tested against a fake client, and queued in `scripts/run_models.sh`.

## Self-score

| Points | Criterion | Score | Reason |
|---:|---|---:|---|
| 15 | Works from a clean clone | 15 | Fresh clone: `uv sync`, `uv run pytest -q` (63 passed), `uv run python demo.py` all succeed; pages, tokenizer and fixtures are vendored and checksummed; the only machine requirement is Playwright's Chromium, and browser tests skip cleanly without it. |
| 20 | Real data, real result | 17 | 2,020 real MiniWoB++ episodes over 101 tasks, rewarded by the benchmark's own globals; tokens, survival and oracle results all from them. Capped: the brief's headline question (which encoding a model succeeds with) needs the queued model arm. |
| 15 | Finding quality | 13 | Non-obvious and controlled: the conditional measure (kept, given raw HTML shows it) removes context-dependent tasks that hurt every encoder alike; `som` vs `som_listeners` is a one-variable ablation; five encoder pairs test whether combining rescues the losses (it does not, for colour/icon tasks); task-level bootstrap CIs; every surprising number (raw present = 1.000, clean DOM longer than raw on 19 tasks, 5 oracle failures) investigated and explained. Capped for the same model-arm reason. |
| 15 | Correctness | 14 | Reviewed four harness bugs to root cause (charset, hover image collapse, covered centres, closed-select visibility) and fixed each in shared code, not in an oracle. Tests assert behaviour on real page snapshots and on real Chromium. Residual: "needs" strings are chosen per task by hand (see weaknesses). |
| 10 | Usability | 10 | `browser-agent --help` with seven subcommands; `show` prints any page in every encoding; missing Chromium, missing task, missing results file and unreachable Ollama all give one-line errors; runs resume. |
| 10 | README | 10 | House format, five real Input/Output samples, NOT-do section, nine real problems. |
| 10 | Code quality | 10 | ruff clean, typed, one module per concern, two runtime dependencies (playwright, tokenizers), both used. |
| 5 | Honesty | 5 | Every README number is in `results/oracle.json`, `tokens.json` or `survival.json`; limits and the oracle's five imperfect tasks are stated with causes. |
| | **Total** | **94** | Capped by the model arm; everything else at or near full marks. |

## Done

- Playwright environment over 130 vendored MiniWoB++ tasks (pinned commit, git-blob checksums),
  served through Playwright's router with no socket and no network.
- One snapshot per observation (DOM walk + Chrome AX tree + Chrome click targets), five encoders.
- Action layer (click/type/select/scroll/submit/done by index or selector) shared by the oracle
  and the model; refuses indices the encoding did not show.
- Scripted oracles for 101 tasks; the other 29 are outside the action space and listed with
  reasons (three after a failed attempt).
- Oracle run: 101 tasks x 20 seeds; 96 tasks solved on every seed, 98.8% of episodes; the five
  imperfect tasks explained in `results/oracle.json`.
- Token cost per encoder (Qwen2.5 tokenizer) and target survival per encoder, with task-level
  bootstrap intervals and a pairwise-combination ablation.
- Model arm: prompts, Ollama client, disk cache keyed by (model, messages, options), context
  guard, per-seed step budgets from the oracle, JSONL output, report with a survival split.

## Queued for the model run

`bash scripts/run_models.sh` (checks free RAM >= 5 GB, free VRAM >= 12 GB, and that Ollama
serves the model; `--dry-run` prints the plan). Defaults: `qwen2.5:14b-instruct`, seeds 0-4,
`num_ctx` 16384, all five encoders.

- 2,485 episodes (497 oracle-solved (task, seed) pairs x 5 encoders).
- About **9,550 calls** expected (oracle steps + 1 per episode), **19,100 at most** (budget
  2 x oracle steps + 2).
- `SEEDS=10` doubles both. Output: `results/agent_episodes.jsonl`, `results/agent.json`.

## Known weaknesses

- **"needs" is hand-chosen per task.** Each oracle states which words from the instruction pick
  its target out. They are literal and were chosen before looking at survival, but they are a
  judgement; a different reader could pick `"address"` or the address itself (phone-book now
  accepts either, `"a|b"`). The per-task choices are in `src/browser_agent/oracles/`.
- **Strict identifiability** ignores adjacency, which is why context-dependent tasks (10) fail
  even raw HTML. The conditional measure handles this for comparisons between encoders.
- **Pages are small.** Absolute token counts will not transfer to real sites.
- **Timing-sensitive tasks** (`stock-market`, `button-delay`, `simon-says`) depend on machine
  load for the oracle and will be hard for any 14B model at several seconds per step.
- The axtree encoder gives a text line the index of its parent element, which is generous
  (Playwright's aria snapshot gives text lines no ref).

## Reproduce every result

```bash
unset VIRTUAL_ENV
uv sync
uv run python scripts/fetch_miniwob.py --verify     # 218/218 files match the pinned commit
uv run pytest -q                                    # 63 passed
uv run python demo.py                               # README Input/Output samples 1-4
uv run browser-agent show login-user --seed 0 --encoder axtree,som   # sample 2's encodings
uv run browser-agent oracle --seeds 20              # results/oracle_episodes.jsonl (~1 h)
uv run browser-agent report                         # results/{oracle,tokens,survival}.json, sample 5
bash scripts/run_models.sh --dry-run                # the queued job list and call estimate
```
