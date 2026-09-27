# STATUS

**READY-FOR-MODEL-RUN.** Everything that needs no model is built, run and written up; the
model arm is built, tested against a fake client, and queued in `scripts/run_models.sh`.

## Self-score

An independent hostile review scored the first complete version 83. Every finding it raised
was fixed (list below) and the oracle run and all results were regenerated from scratch.

| Points | Criterion | Score | Reason |
|---:|---|---:|---|
| 15 | Works from a clean clone | 15 | Fresh clone: `uv sync`, `uv run pytest -q` (75 passed), `uv run python demo.py` all succeed offline; pages, tokenizer and fixtures are vendored and checksummed; the only machine requirement is Playwright's Chromium, and browser tests skip cleanly without it. |
| 20 | Real data, real result | 17 | 2,020 real MiniWoB++ episodes over 101 tasks, rewarded by the benchmark's own globals; tokens, survival and oracle results all from them. Capped: the brief's end question (which encoding a model succeeds with) needs the queued model arm. |
| 15 | Finding quality | 13 | Conditional measure (kept, given raw HTML shows it) so context-dependent tasks do not blur the comparison; one-variable ablation (`som` vs `som_listeners`) with a paired bootstrap interval excluding zero; four paired contrasts; five pairwise unions test whether combining rescues losses (it does not for colour/icon tasks); task-level CIs; every surprising number investigated (raw present = 1.000, clean DOM longer than raw on 19 tasks, the three imperfect oracle tasks, the review's too-easy match). Capped by the model arm. |
| 15 | Correctness | 14 | Evidence excludes indices and markup and matches whole words; agent restricted to its encoding's handles; a failing episode is recorded, never crashes or blocks a resume; truncated JSONL repaired. Residual: "needs" strings are chosen per task by hand. |
| 10 | Usability | 10 | Seven subcommands with `--help`; `show` prints any page in every encoding; missing Chromium, unknown/excluded task, empty `--tasks`, bad encoder, missing or empty results file, unreachable Ollama all give one-line errors (tested); `report --out-dir` never has to touch committed results; runs resume. |
| 10 | README | 10 | House format, five real Input/Output samples, paired-contrast table, NOT-do section, ten real problems including the one the review caught. |
| 10 | Code quality | 10 | ruff clean, typed, one module per concern, two runtime dependencies (playwright, tokenizers), both used; dead fields removed. |
| 5 | Honesty | 5 | Every README number is in `results/oracle.json`, `tokens.json` or `survival.json`; unbacked rerun claim removed; limits stated with causes. |
| | **Total** | **94** | Capped by the model arm; everything else at or near full marks. |

## Fixed after the independent review

- Identifiability matched rendered text, so indices (`[5]`) and markup (`>`) could satisfy a
  need. Fragments now carry *evidence* (content without indices or markup) and needs match as
  whole words; `use-autocomplete`'s prefix/suffix needs became the item's text accordingly.
- `enter-password` required the id word `verify`, which is not in the instruction; both fields
  now need nothing beyond being a text field ("into both text fields").
- `som_listeners` "lost none" is by construction; the README now says so and reports paired
  bootstrap differences instead of overlapping marginal intervals.
- "Actionable" equals "present" for the cleaned encodings by design; documented.
- `oracle --tasks ''` ran everything; any exception inside an episode could crash or block a
  run; a truncated JSONL line broke resume; `report` crashed on empty/all-failed input and
  always wrote to `results/`. All fixed and tested.
- The model could type into `#password` under the accessibility tree via a selector: indexed
  encodings now accept indices only, raw HTML selectors only. The model gained `wait` (the
  oracle waits between steps) and a 600 ms settle for jQuery UI animations.
- Stale counts, the pyproject encoder count, a stale comment, dead fields, missing types and
  duplicated CLI defaults.

## Done

- Playwright environment over 130 vendored MiniWoB++ tasks (pinned commit, git-blob checksums),
  served through Playwright's router with no socket and no network.
- One snapshot per observation (DOM walk + Chrome AX tree + Chrome click targets), five encoders.
- Action layer (click/type/select/scroll/submit/wait/done by index or selector) shared by the
  oracle and the model.
- Scripted oracles for 101 tasks; the other 29 are outside the action space and listed with
  reasons (three after a failed attempt).
- Oracle run: 101 tasks x 20 seeds; 98 tasks solved on every seed, 98.9% of episodes; the
  three imperfect tasks explained in `results/oracle.json`.
- Token cost per encoder (Qwen2.5 tokenizer), target survival per encoder, paired contrasts,
  pairwise unions, all with task-level bootstrap intervals.
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
  its target out. They are literal, but a judgement; a different reader could choose
  differently for icon buttons (class words such as `star`, `trash`) or row icons whose
  deciding fact sits beside them.
- **Strict identifiability** ignores adjacency and does not test uniqueness, which is why
  context-dependent tasks (10) fail even raw HTML. The conditional measure handles this for
  comparisons between encoders.
- **Pages are small.** Absolute token counts will not transfer to real sites.
- **Timing-sensitive tasks** (`stock-market`, `button-delay`, `simon-says`) depend on machine
  load for the oracle and will be hard for any 14B model at several seconds per step.
- The axtree encoder gives a text line the index of its parent element, which is generous
  (Playwright's aria snapshot gives text lines no ref).
- The package reads `vendor/` relative to the source tree; run it from a clone (it is not
  built into a wheel).

## Reproduce every result

```bash
unset VIRTUAL_ENV
uv sync
uv run python scripts/fetch_miniwob.py --verify     # 218/218 files match the pinned commit
uv run pytest -q                                    # 75 passed
uv run python demo.py                               # README Input/Output samples 1-4
uv run browser-agent show login-user --seed 0 --encoder axtree,som   # sample 2's encodings
uv run browser-agent oracle --seeds 20              # results/oracle_episodes.jsonl (~1 h)
uv run browser-agent report                         # results/{oracle,tokens,survival}.json, sample 5
bash scripts/run_models.sh --dry-run                # the queued job list and call estimate
```
