<h1 align="center">browser-agent (Playwright · MiniWoB++ · Chrome DevTools Protocol · Ollama)</h1>
<p align="center"><i>Before asking which page encoding a browser agent should read, ask what each one throws away</i></p>

<p align="center">
  <a href="#the-through-line">The through-line</a> &middot;
  <a href="#findings">Findings</a> &middot;
  <a href="#input--output">Input / Output</a> &middot;
  <a href="#quick-start">Quick start</a> &middot;
  <a href="#what-this-does-not-do">What it does NOT do</a> &middot;
  <a href="#problems-hit-while-building-this">Problems hit</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11%2B-blue" alt="python">
  <img src="https://img.shields.io/badge/browser-Playwright%20Chromium-informational" alt="browser">
  <img src="https://img.shields.io/badge/benchmark-MiniWoB%2B%2B%20(101%20tasks)-success" alt="benchmark">
  <img src="https://img.shields.io/badge/tests-75%20passing-success" alt="tests">
  <img src="https://img.shields.io/badge/model%20arm-queued-lightgrey" alt="model arm">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green" alt="license"></a>
</p>

---

Inspired by [browser-use](https://github.com/browser-use/browser-use) and
[browserbase/stagehand](https://github.com/browserbase/stagehand); no code from either is used.

## The through-line

```mermaid
flowchart TD
    A["MiniWoB++ page<br/>(101 tasks x 20 seeds)"] --> B["one snapshot:<br/>DOM walk + Chrome AX tree<br/>+ Chrome click targets"]
    B --> C1["raw_html"]
    B --> C2["clean_dom"]
    B --> C3["axtree"]
    B --> C4["som"]
    B --> C5["som_listeners"]
    O["scripted oracle<br/>(solves 98/101 tasks on every seed)"] --> T["the element it had to act on,<br/>and the words that pick it out"]
    C1 --> S["does the target survive?<br/>present / identifiable / actionable"]
    C2 --> S
    C3 --> S
    C4 --> S
    C5 --> S
    T --> S
    S --> M["model arm, queued:<br/>qwen2.5:14b under each encoding"]

    style S fill:#2563eb,color:#fff
```

A browser agent never sees the page. It sees an *encoding* of the page: raw HTML, a cleaned
DOM, the accessibility tree, or a numbered list of interactive elements. Every encoding is
cheaper than the one before it because it drops something. This repo measures what, without a
model: a scripted oracle solves each task through the same action layer the agent uses, and at
every step the element it acts on is looked up in all five encodings.

> **A numbered list of interactive elements is 3.6x cheaper than raw HTML and keeps 93% of the
> targets raw HTML shows, as many as a cleaned DOM at half its tokens, but only when it asks
> Chrome which elements have click listeners; the usual attribute-and-cursor heuristic keeps
> 86%. What no text encoding keeps is colour and icon identity: 10 of 101 tasks lose a target
> in every cleaned encoding, and no pair of encodings recovers them.**

## Findings

All numbers come from `results/*.json`, produced by `browser-agent oracle --seeds 20` and
`browser-agent report` on this machine. The unit is the task: each task contributes its mean
over seeds, and the intervals are 95% bootstraps over the 101 tasks. Survival counts only the
5,743 target steps of episodes the oracle actually solved.

| encoding | tokens, median first page | share of raw HTML | targets kept, of those raw HTML shows (95% CI) | tasks losing any | episodes where every target is usable |
|---|---:|---:|---:|---:|---:|
| `raw_html` | 210 | 1.00 | 1.000 (reference) | 0 | 0.914 |
| `clean_dom` | 113 | 0.57 | 0.925 [0.878, 0.965] | 13 | 0.804 |
| `axtree` | 63 | 0.31 | 0.899 [0.847, 0.946] | 18 | 0.739 |
| `som` | 54 | 0.26 | 0.863 [0.801, 0.918] | 22 | 0.710 |
| `som_listeners` | 71 | 0.28 | **0.931** [0.890, 0.969] | 13 | 0.811 |

"Kept" means the target is still *identifiable* and reachable by an index. Identifiable: the
words the instruction uses to pick the target out (its label, the colour it is described by,
the field name) appear, as whole words, in what the encoding says about the target itself or
a label bound to it: tag or role names, attribute values, text, accessible names and states,
never an index number or markup. 1,307 of the 5,743 target steps (23%) are picked by position
or are the only one of their kind; for those, present is enough. Every fragment a cleaned
encoding emits carries an index, so for the four of them "reachable" equals "present".
"Share of raw HTML" is the median over tasks of the per-task token ratio.

Paired differences in "kept" (per-task difference, bootstrapped over tasks), from
`contrasts_usable_given_raw`:

| comparison | mean difference | 95% CI |
|---|---:|---:|
| `som_listeners` - `som` | +0.069 | [+0.029, +0.115] |
| `clean_dom` - `som_listeners` | -0.006 | [-0.025, +0.006] |
| `clean_dom` - `axtree` | +0.027 | [-0.017, +0.073] |
| `som_listeners` - `axtree` | +0.033 | [-0.007, +0.077] |

1. **Listener detection is the cheapest win.** `som` finds interactive elements the way most
   DOM agents do: tag, ARIA role, `onclick`/`tabindex`, or where `cursor: pointer` starts.
   MiniWoB++ binds its handlers with d3 and jQuery, which leave no attribute behind. Asking
   Chrome for its own click-target flag (`DOMSnapshot.isClickable`) cut the tasks losing a
   target from 22 to 13 (the Reply and Forward buttons of four `email-inbox` variants,
   social-media, grid-coordinate, tic-tac-toe, ascending-numbers, form-sequence-3), for 16
   more tokens at the median; it adds elements to the list, so it cannot lose any. The gain,
   +0.069 [+0.029, +0.115], is the only contrast in the table whose interval excludes zero:
   with it, the list is statistically indistinguishable from `clean_dom` at half the tokens.
2. **The accessibility tree loses unlabelled form fields and unnamed controls.** `login-user`
   and `login-user-popup` put a `<label>` next to each input without `for=` and without
   wrapping it, so Chrome gives both textboxes an empty name. The tree shows `text "Username"`
   and a nameless `textbox` on separate lines; the id `username` that every HTML encoding keeps
   is gone. Of the 18 tasks `axtree` loses, 8 are ones `clean_dom` keeps: those two, the Send
   buttons of four `email-inbox` variants (an unnamed `<span>`), and the grid-coordinate and
   tic-tac-toe cells.
3. **Ten tasks lose a target in every cleaned encoding**, and combining encodings does not
   rescue them: the best pair (`axtree` + `som_listeners`) still keeps only 0.949
   [0.911, 0.981]. They are the tasks decided by colour (`click-color`, `click-shades`), by
   SVG shape kind (`click-shape`), and by icon-only buttons named only in a CSS class (the
   star and trash icons of six `email-inbox` variants, the `use-spinner` arrows). That
   information is in pixels and class names; a screenshot would carry it, and no vision model
   is installed here (see below).
4. **Cleaning does not always shrink the page.** `clean_dom` indexes every surviving element
   (`i=N`), and on 19 of 101 tasks, all small forms and checkbox lists, that made it *longer*
   than the raw HTML it came from.
5. **Raw HTML is not the ceiling it looks like.** It shows every target (present = 1.000, by
   construction), but on 10 tasks the deciding fact sits *next to* the element rather than in
   it: the post author beside a retweet icon, the duration beside a Book button, a label that
   is not bound to its input. Raw HTML only makes 91.4% of episodes fully usable, and 57% of
   its targets have a unique `#id` (task mean); the rest need a structural CSS selector. It
   also leaks: `find-greatest`'s face-down card values sit in the DOM at `font-size: 0`, and
   raw HTML and the accessibility tree both show them to an agent that should not see them.

The oracle itself solves 98 of 101 in-scope tasks on all 20 seeds (98.9% of 2,020 episodes).
The three exceptions are explained, not guessed, in `results/oracle.json`: `click-menu` opens
submenus on hover only (4/20), and `click-pie` and `click-pie-nodelay` lose the click when the
answer is the item the wheel starts on (17/20 each). Two timing-bound tasks depend on machine
load and solved 20/20 here: `stock-market`, whose buying window can be shorter than one
observe-and-encode cycle, and `button-delay`, whose 150 ms tolerance spans one.

### The model arm (built, tested with a fake, queued)

The findings above bound what a model *could* do with each encoding. Whether
`qwen2.5:14b-instruct` actually does it is queued: `scripts/run_models.sh` runs every
oracle-solved (task, seed) for seeds 0-4 under all five encodings, about 9,560 calls
(19,120 at most), then reports success per encoding and family with Wilson intervals, steps,
tokens, and success split by whether that episode's targets survived the encoding. The model
acts only through the handles its encoding shows (indices, or CSS selectors for raw HTML), may
`wait` up to 5 s like the oracle does, and a prompt too long for the context window is
recorded as an overflow rather than silently truncated. No vision model is installed, so
there is **no screenshot arm**; finding 3 is the case one would test.

## Input / Output

Real output from `uv run python demo.py` (the oracle solves each page; the benchmark's own
reward confirms it) and from `browser-agent show`. `P`/`I`/`A` = present / identifiable /
actionable; `.` = lost.

**1. A colour exists only in raw HTML.** `click-color`, seed 0:

```
click-color (seed 0): Click on the white colored box.
  benchmark reward: +1.0 after 1 steps
  tokens, first observation: raw_html 99  clean_dom 20  axtree 0  som 0  som_listeners 28
  step 1 click  needs [white]  raw_html PI.  clean_dom ...  axtree ...  som ...  som_listeners P.A
```

The boxes are attribute-free `<div>`s with a d3 click handler. `clean_dom` prunes them as
empty, the accessibility tree is empty, `som` sees nothing interactive, and `som_listeners`
lists four indistinguishable `[3]<div></div>` lines: clickable, but which one is white?

**2. The accessibility tree drops the field names.** `login-user`, seed 0:

```
login-user (seed 0): Enter the username "thaddeus" and the password "UT" into the text fields and press login.
  benchmark reward: +1.0 after 3 steps
  tokens, first observation: raw_html 101  clean_dom 103  axtree 35  som 55  som_listeners 55
  step 1 type   needs [username]  raw_html PIA  clean_dom PIA  axtree P.A  som PIA  som_listeners PIA
  step 2 type   needs [password]  raw_html PIA  clean_dom PIA  axtree P.A  som PIA  som_listeners PIA
  step 3 click  needs [login]  raw_html PIA  clean_dom PIA  axtree PIA  som PIA  som_listeners PIA
```

```
=== axtree (35 tokens)
- text "Username" [5]
- textbox [6]
- text "Password" [8]
- textbox [9]
- button "Login" [10]

=== som (55 tokens)
[5]<label>Username</label>
[6]<input id="username" type="text">
[8]<label>Password</label>
[9]<input id="password" type="password">
[10]<button id="subbtn">Login</button>
```

**3. Shape kind survives only as a tag name.** `click-shape`, seed 1:

```
click-shape (seed 1): Click on a rectangle
  benchmark reward: +1.0 after 1 steps
  tokens, first observation: raw_html 294  clean_dom 59  axtree 62  som 54  som_listeners 69
  step 1 click  needs [rect]  raw_html PI.  clean_dom ...  axtree P.A  som PIA  som_listeners PIA
```

**4. Hidden sections cost raw HTML 7x the tokens and change nothing.** `click-collapsible-2`,
seed 0:

```
click-collapsible-2 (seed 0): Expand the sections below, to find and click on the link "ut.".
  benchmark reward: +1.0 after 2 steps
  tokens, first observation: raw_html 751  clean_dom 97  axtree 52  som 70  som_listeners 70
  step 1 click  needs [Section #2]  raw_html PIA  clean_dom PIA  axtree PIA  som PIA  som_listeners PIA
  step 2 click  needs [ut.]  raw_html PI.  clean_dom PIA  axtree PIA  som PIA  som_listeners PIA
```

**5. The whole run**, from `browser-agent report`:

```
oracle: 98/101 tasks solved on every seed, 98.9% of 2020 episodes

encoder        tokens (median)   present  identif.   action.   ceiling
raw_html                   210     1.000     0.944     0.573     0.914
clean_dom                  113     0.918     0.869     0.918     0.804
axtree                      63     0.964     0.843     0.964     0.739
som                         54     0.879     0.813     0.879     0.710
som_listeners               71     0.987     0.875     0.987     0.811
```

## Quick start

```bash
git clone <this repo> browser-agent
cd browser-agent
uv sync
uv run playwright install chromium      # skip if Playwright's Chromium is already installed

uv run pytest -q                        # 75 tests, no network, no model
uv run python demo.py                   # four pages, five encodings, known answers
uv run browser-agent tasks              # the 101 runnable tasks and the 29 left out, with reasons
uv run browser-agent show click-color --seed 0
uv run browser-agent oracle --seeds 20  # ~1 h; resumable, writes results/oracle_episodes.jsonl
uv run browser-agent report             # results/oracle.json, tokens.json, survival.json

bash scripts/run_models.sh --dry-run    # the model-arm job list and call estimate
bash scripts/run_models.sh              # checks RAM, GPU and Ollama first, then runs
```

## Layout

```
src/browser_agent/
  pages.py        serves vendor/miniwob to Chromium through Playwright's router; no socket
  env.py          seeded MiniWoB++ episodes, rewarded by the benchmark's own globals
  snapshot.js     one DOM walk: stable data-ba-id stamps, text, visibility, live form state
  snapshot.py     merges the walk with Chrome's AX tree and click targets (CDP)
  encoders.py     raw_html, clean_dom, axtree, som, som_listeners
  actions.py      click / type / select / scroll / submit / wait / done, by index or selector
  survival.py     present / identifiable / actionable for one target in one encoding
  oracles/        scripted policies for 101 tasks (click, forms, reading, widgets)
  harness.py      oracle episodes -> results/oracle_episodes.jsonl
  report.py       oracle.json, tokens.json, survival.json, agent.json
  agent.py        the model arm: prompts, context-window guard, step budgets, jobs
  llm.py          Ollama client, on-disk generation cache, deterministic fake
  tasks.py        task families, exclusions, and the explained oracle limits
  tokens.py       Qwen2.5 token counts from the vendored tokenizer
vendor/miniwob/   MiniWoB++ pages pinned to commit 33c3b4d, checksummed (MIT, see LICENSE)
vendor/qwen2.5-tokenizer.json.gz   the Qwen2.5 tokenizer (a BPE table, not weights)
scripts/          fetch_miniwob.py, capture_fixture.py, run_models.sh
results/          every number in this README
```

## Requirements

Python 3.11+, `uv`, and Playwright's Chromium build (`uv run playwright install chromium`;
the full build is launched in new-headless mode, so the separate headless-shell download is
not needed). No GPU, no model and no network are needed for anything except the model arm,
which needs Ollama serving `qwen2.5:14b-instruct` and roughly 12 GB of free VRAM.

## Tests

```bash
uv run pytest -q
```

75 tests. The encoder and survival tests run on snapshots saved from real task pages
(`tests/fixtures/`), so they need no browser. The browser tests (`-m browser`) drive real
Chromium: seeded resets are deterministic, a wrong click gets the benchmark's negative reward,
the executor refuses indices the agent was not shown, pages cannot reach the network, and the
agent loop runs end to end against a fake model that reads the set-of-marks, a raw-HTML agent
that must fall back to selectors, a model that never returns JSON, and a prompt too long for
the context window (never sent), and an agent on an indexed encoding trying a CSS selector
(refused). They skip, rather than fail, when Chromium is missing.

## What this does NOT do

- **It does not say which encoding makes a model succeed.** Survival is an upper bound on what
  a model could do with an encoding. The model arm that measures actual success is built and
  queued, not run.
- **No screenshot arm.** No vision model is installed. The ten tasks every text encoding loses
  are the obvious place to test one.
- **It does not cover real websites.** MiniWoB++ pages are tiny (210 tokens of raw HTML at the
  median, 5,813 at most). Ratios between encodings transfer better than absolute counts.
- **"Identifiable" is strict and literal, and is not a uniqueness test.** The deciding words
  must appear in the element's own representation or a label bound to it; text merely nearby
  does not count, and it does not check that the words pick out *only* the target. The words
  themselves were chosen per task by hand (they are in `src/browser_agent/oracles/`). A model
  may still guess right from adjacency; the model arm's survival split measures how often.
- **The action space has no hover action, no drag and no text selection.** (A click does move
  the pointer onto the element first; no action hovers without clicking.) 29 tasks that need
  one are excluded up front and listed by `browser-agent tasks`, three of them
  (`form-sequence`, `hot-cold`, `text-editor`) after an oracle was attempted and failed for
  that reason.
- **It is not browser-use or Stagehand.** It rebuilds the observation-and-action core those
  projects share, to measure it; there is no planner, memory, vision, or cloud browser.

## Problems hit while building this

- **Playwright 1.63 looks for a separate `chromium-headless-shell` build** that was not
  installed; only full Chromium was. Launching with `channel="chromium"` uses the full build in
  new-headless mode.
- **Git rewrote the vendored pages.** With `core.autocrlf=input`, committing converted the
  MiniWoB++ files' line endings, so a fresh clone failed the blob checksums in
  `MANIFEST.json`. `.gitattributes` now marks `vendor/**` as `-text`.
- **Pages served through the router had no charset.** Chromium fell back to windows-1252, and
  `unicode-test`'s `ÖK` arrived as `Ã–K`: the task still "worked", but it was no longer testing
  unicode. HTML, JS and CSS are now served as UTF-8.
- **Routing requests disables Playwright's HTTP cache**, and `social-media` swaps each icon's
  image on hover. While the hover image loaded, the icon collapsed to zero width and the click's
  mousedown landed on its neighbour: 1 of 20 seeds solved. The executor now moves the pointer,
  waits 60 ms, then clicks; 20 of 20.
- **One button can sit over another** (`click-test-2`, seeds 6 and 13), and Playwright refuses a
  click whose centre is covered. The executor finds an uncovered point of the element first.
- **A closed `<select>`'s options fail `checkVisibility()`**, so the cleaned encodings silently
  dropped every choice but the selected one. Options now count as visible when their select is.
- **Typing timed out under load.** One 3 s budget for a whole `press_sequentially` failed
  `copy-paste-2`'s 60-character strings on 14 of 20 seeds while other jobs held the CPU. The
  budget now grows with the text.
- **Ollama silently drops the start of a prompt longer than `num_ctx`.** The model arm counts
  tokens with the Qwen2.5 tokenizer first and records a `context_overflow` instead of sending a
  prompt the model would only partly see.
- **Raw HTML's "present = 1.000" looked like a bug** and is not: the encoding is the page body,
  so every target is in it. The informative number is the conditional one: of the targets raw
  HTML shows identifiably, how many each cheaper encoding keeps.
- **The first identifiability check was too easy to pass.** It searched the rendered text, so
  a needed "5" was satisfied by the index `[5]` and a needed ">" by any tag's closing bracket.
  An independent review caught it; fragments now carry their content without indices or
  markup, and needs match as whole words. Survival was re-measured from scratch after the fix.

## Keywords

browser agent &middot; web agent &middot; Playwright &middot; MiniWoB++ &middot; DOM
distillation &middot; accessibility tree &middot; set-of-marks &middot; observation encoding
&middot; Chrome DevTools Protocol &middot; browser-use &middot; Stagehand &middot; LLM agents
&middot; Ollama &middot; Qwen2.5 &middot; agent evaluation &middot; token cost

## License

MIT. The vendored MiniWoB++ pages are MIT-licensed by their authors
(`vendor/miniwob/LICENSE`); the Qwen2.5 tokenizer is Apache-2.0.
