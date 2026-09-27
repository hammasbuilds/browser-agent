# STATUS

**READY-FOR-MODEL-RUN.** Everything that needs no model is built, run and written up; the
model arm is built, tested against fakes, and queued in `scripts/run_models.sh`.

## Self-score

History: my first self-score was 94; the internal hostile review scored 83, then 92 after
fixes; the coordinator's independent review scored **86** (model-arm cap 5) and found that the
headline was true by construction and that "needs" were not what the README said they were.
Those points were fair. Everything it listed is fixed below, with regression tests, and the
oracle run and all results were regenerated from scratch.

| Points | Criterion | Score | Reason |
|---:|---|---:|---|
| 15 | Works from a clean clone | 15 | Fresh clone: `uv sync`, `uv run pytest -q` (95 passed), `uv run python demo.py` succeed offline; pages, tokenizer and fixtures vendored and checksummed; browser tests skip cleanly without Chromium. |
| 20 | Real data, real result | 16 | 2,020 real MiniWoB++ episodes over 101 tasks, benchmark reward, seven encoders measured at every step. Capped: the end question (which encoding a model succeeds with) needs the queued model arm. |
| 15 | Finding quality | 12 | The allow-list ablation now tests the headline's mechanism instead of assuming it (and an attribution run separates styling from MiniWoB's `data-*` grading leaks); needs are tagged by source with a sensitivity analysis; paired contrasts with task-level bootstrap CIs. Capped by the model arm; the needs are still hand-chosen, and "identifiable" is not a uniqueness test. |
| 15 | Correctness | 14 | All reviewer bugs fixed and tested (model pooling, resume key, Ollama error paths, unknown tasks, split measure, CRLF, pipefail, page vs browser errors). Residual: stock-market is load-dependent for the oracle (19/20 this run, 20/20 the last). |
| 10 | Usability | 10 | Six subcommands with `--help`; one-line errors for every bad input found so far (tested); resumable runs; `--out-dir`. |
| 10 | README | 10 | House format, five real samples (sample 1 prose corrected), ablation and sensitivity tables, NOT-do section, real problems including both review catches. |
| 10 | Code quality | 10 | ruff clean, typed, dead `Node.outer` removed (fixtures shrank ~12%), two runtime dependencies. |
| 5 | Honesty | 4 | Every README number traces to `results/*.json`; the headline was rewritten to what the ablation supports. One point held back because the earlier headline shipped overstated. |
| | **Total** | **91** | |

## Fixed after the coordinator's review (86)

1. **Headline true by construction.** Added `clean_dom_wide` and `som_listeners_wide` (the
   same encoders plus `class`, `style`, `data-*`) as a real arm, measured in every episode.
   `som_listeners_wide` keeps 0.976 [0.948, 0.997] of raw-identifiable targets at 0.39 of raw
   HTML's tokens (median 112 vs 71 narrow); `clean_dom_wide` 0.979 at 0.95. Paired gains:
   +0.045 [+0.015, +0.080] and +0.054 [+0.022, +0.094]. `scripts/wide_attribution.py` shows
   every rescue survives without `data-*` except `click-shades` (colour named only in
   `data-color`). Headline and finding 3 rewritten accordingly.
2. **Needs vs instruction.** Every need is tagged instruction / page / markup
   (`survival.need_source`): 3,173 / 1,190 / 275 of 4,638. The rule is described truthfully in
   `oracles/base.py` and the README, and `sensitivity_usable_given_raw` reports survival with
   markup-only (and page-text) needs dropped: every encoder moves up by at most 1.6 points,
   no ranking changes; `axtree` loses 16 tasks instead of 18 (the `send` cases).
3. `agent_summary` reports per model, never pooled (tested with two fake models).
4. Resume key includes `num_ctx`, so an overflow can be retried with a larger window; the
   window must exceed the reply budget (`--num-ctx -5` is refused).
5. `OllamaClient` retries with exponential backoff on any transport, timeout or payload
   failure, then raises one `LLMUnavailableError`; tested against a local socket that drops,
   stalls, sends garbage, a half status line, or an error payload, and one that recovers.
6. Dead `Node.outer` removed from the snapshot (it copied every element's outerHTML).
7. README sample 1 prose corrected (the boxes do have attributes; lines are `[3]`-`[6]`);
   STATUS said seven subcommands, there are six.
8. `agent --tasks click-color,nosuch` is an error; the agent survival split uses the same
   usable measure as the ceiling; results JSON is written with `\n` line endings.
9. `run_models.sh` captures `/api/tags` before grepping (no pipefail false negative); the
   timing-bound tasks are excluded from the model arm by default (`--include-timing`); a
   non-fatal page error is now a counted failure, and only a dead browser stops the run
   without recording.

Earlier rounds (internal review): evidence without indices or markup, whole-word matching,
paired contrasts, handle restriction per encoding, the `wait` action, crash-proof episodes,
truncated-JSONL repair.

## Done

- Playwright environment over 130 vendored MiniWoB++ tasks, served through Playwright's
  router with no socket and no network; seven encoders from one snapshot.
- Scripted oracles for 101 tasks (29 others excluded with reasons); oracle run 101 x 20 seeds,
  97 tasks solved on every seed, 98.9% of episodes, the four imperfect tasks explained.
- Token cost, survival, paired contrasts, pairwise unions, need-source sensitivity,
  allow-list attribution; all with task-level bootstrap intervals.
- Model arm: prompts, retrying Ollama client, disk cache, context guard, per-seed budgets,
  per-model report with a usable-target split.

## Queued for the model run

`bash scripts/run_models.sh` (checks free RAM >= 5 GB, free VRAM >= 12 GB, Ollama serving
the model; `--dry-run` prints the plan). Defaults: `qwen2.5:14b-instruct`, seeds 0-4,
`num_ctx` 16384, all seven encoders, timing-bound tasks excluded.

- 3,381 episodes (483 oracle-solved (task, seed) pairs x 7 encoders).
- About **13,020 calls** expected (oracle steps + 1), **26,040 at most** (2 x oracle steps + 2).
- To run only the five main encoders: `uv run browser-agent agent --encoder raw_html,clean_dom,axtree,som,som_listeners` (5/7 of the calls).

## Known weaknesses

- **Needs are hand-chosen per task**, now tagged by source with a sensitivity analysis, but
  still a judgement, and identifiability is not a uniqueness test.
- **Pages are small**; absolute token counts will not transfer to real sites. `data-*` in
  MiniWoB++ sometimes holds the grader's answer, which inflates the wide arm on `click-shades`.
- **Timing-sensitive tasks** are load-dependent for the oracle and excluded from the model arm.
- The axtree encoder gives a text line its parent element's index (generous).
- The package reads `vendor/` relative to the source tree; run it from a clone.

## Reproduce every result

```bash
unset VIRTUAL_ENV
uv sync
uv run python scripts/fetch_miniwob.py --verify     # 218/218 files match the pinned commit
uv run pytest -q                                    # 95 passed
uv run python demo.py                               # README Input/Output samples 1-4
uv run browser-agent show click-color --seed 0 --encoder clean_dom,som_listeners,som_listeners_wide
uv run browser-agent show login-user --seed 0 --encoder axtree,som
uv run browser-agent oracle --seeds 20              # results/oracle_episodes.jsonl (~1 h)
uv run browser-agent report                         # results/{oracle,tokens,survival}.json, sample 5
uv run python scripts/wide_attribution.py           # results/wide_attribution.json (~5 min)
bash scripts/run_models.sh --dry-run                # the queued job list and call estimate
```
