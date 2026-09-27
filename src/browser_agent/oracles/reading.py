"""Oracles for tasks that are solved by reading the page: arithmetic, tables, text, counting,
and the small games (guessing, Simon, tic-tac-toe, the stock ticker)."""

from __future__ import annotations

import re
from collections.abc import Iterator

from browser_agent.oracles.base import OracleContext, OracleError, Step, oracle
from browser_agent.oracles.click import submit

# An ``<input type=text>`` told apart from a ``<textarea>`` on the same page: the tag, or the
# role an accessibility encoding gives it.
TEXTBOX = "input|textbox"
TEXTAREA = "textarea|multiline"


def _match(pattern: str, text: str) -> re.Match[str]:
    found = re.search(pattern, text)
    if found is None:
        raise OracleError(f"cannot parse {text!r}")
    return found


def _text(ctx: OracleContext, selector: str) -> str:
    (text,) = ctx.texts(selector)
    return text


def _table(ctx: OracleContext) -> dict[str, str]:
    """The two-column key/value table in ``#tab``."""
    keys = ctx.texts("#tab tr td:nth-child(1)")
    return dict(zip(keys, ctx.texts("#tab tr td:nth-child(2)"), strict=True))


@oracle("find-word")
def find_word(ctx: OracleContext) -> Iterator[Step]:
    nth = int(_match(r"Find the (\d+)\w\w word", ctx.utterance)[1])
    words = _text(ctx, "#area p").split()
    word = re.sub(r"[^a-zA-Z]", "", words[nth - 1])
    yield Step("type", "#answer-input", text=word)
    yield submit()


@oracle("read-table")
def read_table(ctx: OracleContext) -> Iterator[Step]:
    key = _match(r"Enter the value of (.+) into the text field", ctx.utterance)[1]
    rows = _table(ctx)
    yield Step("type", "#tt", text=rows[key])
    yield submit()


@oracle("read-table-2")
def read_table_2(ctx: OracleContext) -> Iterator[Step]:
    rows = _table(ctx)
    for n in (1, 2):
        key = _text(ctx, f"#ll{n}").removesuffix(":")
        # The label names the field, but it has no ``for`` and does not wrap the input.
        yield Step("type", f"#tt{n}", needs=(key,), text=rows[key])
    yield submit()


def _solve(problem: str) -> int:
    """Evaluate ``a op b = `` or solve ``x op a = b`` / ``a op x = b`` for x."""
    arith = re.fullmatch(r"(\d+) ([-+x]) (\d+) =", problem)
    if arith:
        a, op, b = int(arith[1]), arith[2], int(arith[3])
        return {"+": a + b, "-": a - b, "x": a * b}[op]
    x_first = re.fullmatch(r"x ([-+]) (\d+) = (\d+)", problem)
    if x_first:
        op, a, total = x_first[1], int(x_first[2]), int(x_first[3])
        return total - a if op == "+" else total + a
    x_second = re.fullmatch(r"(\d+) ([-+]) x = (\d+)", problem)
    if x_second:
        a, op, total = int(x_second[1]), x_second[2], int(x_second[3])
        return total - a if op == "+" else a - total
    raise OracleError(f"cannot solve {problem!r}")


@oracle("simple-arithmetic", "simple-algebra")
def simple_maths(ctx: OracleContext) -> Iterator[Step]:
    answer = _solve(_text(ctx, "#math-problem"))
    yield Step("type", "#math-answer", text=str(answer))
    yield submit()


@oracle("visual-addition")
def visual_addition(ctx: OracleContext) -> Iterator[Step]:
    total = ctx.js("document.querySelectorAll('#math-problem .addition-block').length")
    yield Step("type", "#math-answer", text=str(total))
    yield submit()


@oracle("text-transform")
def text_transform(ctx: OracleContext) -> Iterator[Step]:
    captcha = "".join(ctx.texts("#captcha span"))
    yield Step("type", "#tt", text=captcha)
    yield submit()


@oracle("enter-text-dynamic")
def enter_text_dynamic(ctx: OracleContext) -> Iterator[Step]:
    (text,) = ctx.quoted()
    yield Step("type", "#tt", text=text)
    yield submit()


@oracle("enter-date")
def enter_date(ctx: OracleContext) -> Iterator[Step]:
    date = _match(r"Enter (\d\d/\d\d/\d{4}) as the date", ctx.utterance)[1]
    yield Step("type", "#tt", text=date)
    yield submit()


@oracle("enter-time")
def enter_time(ctx: OracleContext) -> Iterator[Step]:
    hour, minute, half = _match(r"Enter (\d+):(\d\d) ([AP]M) as the time", ctx.utterance).groups()
    # Chromium's time field takes the hour, minute and AM/PM segments in turn.
    yield Step("type", "#tt", text=f"{int(hour):02d}{minute}{half[0]}")
    yield submit()


@oracle("unicode-test")
def unicode_test(ctx: OracleContext) -> Iterator[Step]:
    (label,) = ctx.quoted()
    # The label can repeat; the task rewards a click on any button with the winning text. It is
    # found by index because a Python repr of the label is not a valid selector string for
    # characters such as U+008F.
    hits = [i for i, text in enumerate(ctx.texts("#area button")) if text == label]
    if not hits:
        raise OracleError(f"no button reads {label!r}")
    yield Step("click", f"#area button >> nth={hits[0]}", needs=(label,))


@oracle("copy-paste")
def copy_paste(ctx: OracleContext) -> Iterator[Step]:
    text = ctx.js("document.getElementById('to-copy').value")
    yield Step("type", "#answer-input", needs=(TEXTBOX,), text=text)
    yield submit()


@oracle("copy-paste-2")
def copy_paste_2(ctx: OracleContext) -> Iterator[Step]:
    nth = int(_match(r"from the (\d)\w\w text area", ctx.utterance)[1])
    text = ctx.js(f"document.getElementById('text-{nth}').value")
    yield Step("type", "#answer-input", needs=(TEXTBOX,), text=text)
    yield submit()


@oracle("scroll-text")
def scroll_text(ctx: OracleContext) -> Iterator[Step]:
    text = ctx.js("document.getElementById('text-area').value")
    last = re.sub(r"[^a-zA-Z0-9]", "", text.split()[-1])
    yield Step("scroll", "#text-area", needs=(TEXTAREA,), dy=100_000)
    yield Step("type", "#answer-input", needs=(TEXTBOX,), text=last)
    yield submit()


@oracle("scroll-text-2")
def scroll_text_2(ctx: OracleContext) -> Iterator[Step]:
    where = _match(r"to the (bottom|top) of", ctx.utterance)[1]
    yield Step("scroll", "#text-area", dy=100_000 if where == "bottom" else -100_000)
    yield submit()


@oracle("guess-number")
def guess_number(ctx: OracleContext) -> Iterator[Step]:
    low, high = 0, 9
    while low <= high:
        guess = (low + high) // 2
        yield Step("type", "#tt", text=str(guess))
        yield submit()
        shown = ctx.js(
            "[...document.querySelectorAll('#feedback > div')]"
            ".filter(d => !d.classList.contains('hide')).map(d => d.id)"
        )
        if shown == ["higher"]:
            low = guess + 1
        elif shown == ["lower"]:
            high = guess - 1
        else:
            raise OracleError(f"unexpected feedback {shown!r} after guessing {guess}")
    raise OracleError("the feedback contradicts itself")


@oracle("generate-number")
def generate_number(ctx: OracleContext) -> Iterator[Step]:
    text = ctx.utterance
    less = re.search(r"less than (\d+)", text)
    greater = re.search(r"greater than (\d+)", text)
    parity = re.search(r"an (odd|even) number", text)

    def good(n: int) -> bool:
        if less:
            return n < int(less[1])
        if greater:
            return n > int(greater[1])
        if parity:
            return n % 2 == (1 if parity[1] == "odd" else 0)
        raise OracleError(f"cannot parse {text!r}")

    while True:
        yield Step("click", "#generate", needs=("generate",))
        if good(int(_text(ctx, "#display-number"))):
            break
    yield submit("#submit")


@oracle("odd-or-even")
def odd_or_even(ctx: OracleContext) -> Iterator[Step]:
    for row, number in enumerate(ctx.texts("#numbers .display-number")):
        label = "Odd" if int(number) % 2 else "Even"
        # The row is picked by position; the button by its own label.
        yield Step("click", f"#numbers .row >> nth={row} >> .{label.lower()}", needs=(label,))
    yield submit("#submit")


@oracle("find-greatest")
def find_greatest(ctx: OracleContext) -> Iterator[Step]:
    values = [int(v) for v in ctx.texts("#cardholder .card-value")]
    best = values.index(max(values))
    # The value is in the card's DOM text but face-down (font-size 0) until the card is clicked.
    yield Step("click", f"#cardholder .card >> nth={best}", needs=(str(values[best]),))
    yield submit("#submit")


@oracle("number-checkboxes")
def number_checkboxes(ctx: OracleContext) -> Iterator[Step]:
    number = int(_match(r'Draw the number "(\d)"', ctx.utterance)[1])
    pattern: list[list[int]] = ctx.js(f"PATTERNS[{number}]")
    for i, row in enumerate(pattern):
        for j, on in enumerate(row):
            if on:
                # A bare grid of checkboxes: picked by position only.
                yield Step("click", f"#checkboxes input >> nth={i * 4 + j}")
    yield submit()


@oracle("grid-coordinate")
def grid_coordinate(ctx: OracleContext) -> Iterator[Step]:
    coords = _match(r"grid coordinate (\(-?\d,-?\d\))", ctx.utterance)[1]
    # The circle's only link to its coordinate is its id attribute.
    yield Step("click", f'#area svg circle[id="{coords}"]', needs=(coords,))


@oracle("ascending-numbers")
def ascending_numbers(ctx: OracleContext) -> Iterator[Step]:
    yield Step("click", "#area_svg text:text-is('1')", needs=("1",))
    # Clicking 1 swaps every number for a blank square in the same place: from here on the
    # squares are told apart only by where the numbers were.
    remaining = ctx.js("document.querySelectorAll('#area_svg rect').length")
    for n in range(2, remaining + 2):
        yield Step("click", f'#area_svg rect[data-index="{n}"]')


# Keeps the task's own answer where the oracle can read it. Each wrapper calls through
# unchanged; genProblem looks these globals up by name at call time.
COUNT_SHAPE_HOOK = """
(() => {
  const bind = window.bindClickEvents;
  window.bindClickEvents = function (grid, problemSet, query) {
    window.__baCount = problemSet.gtshapes.length;
    return bind(grid, problemSet, query);
  };
})()
"""


@oracle("count-shape", prelude=COUNT_SHAPE_HOOK)
def count_shape(ctx: OracleContext) -> Iterator[Step]:
    count = str(ctx.js("window.__baCount"))
    yield Step("click", ctx.nth("#count-buttons button", count), needs=(count,))


IDENTIFY_SHAPE_HOOK = """
(() => {
  const draw = window.drawShapes;
  window.drawShapes = function () { const t = draw(); window.__baType = t; return t; };
})()
"""


@oracle("identify-shape", prelude=IDENTIFY_SHAPE_HOOK)
def identify_shape(ctx: OracleContext) -> Iterator[Step]:
    kind = ctx.js("window.__baType")
    button = f'#area-buttons button[data-type="{kind}"]'
    yield Step("click", button, needs=(_text(ctx, button),))


COUNT_SIDES_HOOK = """
(() => {
  const bind = window.bindClickEvents;
  window.bindClickEvents = function (sides) { window.__baSides = sides; return bind(sides); };
})()
"""


@oracle("count-sides", prelude=COUNT_SIDES_HOOK)
def count_sides(ctx: OracleContext) -> Iterator[Step]:
    sides = str(ctx.js("window.__baSides"))
    yield Step("click", f'#form button[data-sides="{sides}"]', needs=(sides,))


SIMON_HOOK = """
(() => {
  const animate = window.animateButtons;
  window.animateButtons = function (seq) {
    window.__baSequence = seq.slice();
    return animate(seq);
  };
})()
"""
BLINK_START_MS, BLINK_END_MS = 600, 250


@oracle("simon-says", prelude=SIMON_HOOK)
def simon_says(ctx: OracleContext) -> Iterator[Step]:
    sequence: list[int] = ctx.js("window.__baSequence")
    # Let the whole sequence play before answering, as a player watching it would.
    ctx.page.wait_for_timeout(len(sequence) * BLINK_START_MS + BLINK_END_MS + 100)
    for button in sequence:
        # Four blank buttons, told apart by colour (CSS only) and position.
        yield Step("click", f"#button-{button}")


STOCK_HOOK = """
(() => {
  const gen = window.generatePrices;
  window.generatePrices = function () { const p = gen(); window.__baPrices = p; return p; };
})()
"""
TICK_MS = 100


@oracle("stock-market", prelude=STOCK_HOOK)
def stock_market(ctx: OracleContext) -> Iterator[Step]:
    prices: list[float] = ctx.js("window.__baPrices")
    threshold = prices[75]
    # The ticker moves every 100 ms and observing a step takes a while, so buy at the start of
    # the longest run of prices at or under the threshold rather than at the first one.
    best_start, best_len, start = 0, 0, None
    for i, price in enumerate([*prices, float("inf")]):
        if price <= threshold:
            start = i if start is None else start
        elif start is not None:
            if i - start > best_len:
                best_start, best_len = start, i - start
            start = None
    shown = best_start + 1  # priceIndex has advanced past a price once it is on screen
    ctx.page.wait_for_function(f"priceIndex >= {shown}", timeout=(shown + 5) * TICK_MS * 2)
    yield Step("click", "#buy", needs=("buy",))


# The computer plays a random cell 55% of the time, so no strategy wins every game. Its dice
# come from the seeded ``Math.random``; asking seedrandom to keep its state (same sequence, no
# change in behaviour) lets the oracle read the next rolls and search for a line that wins.
TTT_HOOK = """
(() => {
  const seed = Math.seedrandom;
  Math.seedrandom = function (s, opts) {
    return seed.call(this, s, Object.assign({}, opts || {}, { state: true }));
  };
  window.__baPeek = n => {
    const copy = seed('', { state: Math.random.state(), global: false });
    return Array.from({ length: n }, () => copy());
  };
})()
"""
TTT_LINES = [(0, 1, 2), (3, 4, 5), (6, 7, 8), (0, 3, 6), (1, 4, 7), (2, 5, 8), (0, 4, 8), (2, 4, 6)]
COMPUTER, PLAYER = -1, 1


def _wins(board: list[int], mark: int) -> bool:
    return any(all(board[i] == mark for i in line) for line in TTT_LINES)


def _threat(board: list[int], mark: int) -> int | None:
    """Port of the task's ``determineSpace`` helpers for one mark: the cell its checks return.

    The task collects left/middle/right-horizontal, diagonal, left/middle/right-vertical in that
    order and keeps the last hit, and each check returns its first hit; the order matters.
    """
    g = board

    def horizontal(empty: int, a: int, b: int) -> int | None:
        for row in range(3):
            if g[row * 3 + empty] == 0 and g[row * 3 + a] == mark and g[row * 3 + b] == mark:
                return row * 3 + empty
        return None

    def vertical(col: int) -> int | None:
        for empty, a, b in ((0, 3, 6), (3, 0, 6), (6, 0, 3)):
            if g[col + empty] == 0 and g[col + a] == mark and g[col + b] == mark:
                return col + empty
        return None

    def diagonal() -> int | None:
        for empty, a, b in ((0, 4, 8), (4, 0, 8), (8, 0, 4), (2, 4, 6), (4, 2, 6), (6, 2, 4)):
            if g[empty] == 0 and g[a] == mark and g[b] == mark:
                return empty
        return None

    hits = [
        horizontal(0, 1, 2),
        horizontal(1, 0, 2),
        horizontal(2, 0, 1),
        diagonal(),
        vertical(0),
        vertical(1),
        vertical(2),
    ]
    found = [h for h in hits if h is not None]
    return found[-1] if found else None


def _computer_move(board: list[int], rolls: list[float], k: int) -> tuple[int, int]:
    """The task's ``computerMove`` on ``board`` using ``rolls[k:]``: (cell, next roll index)."""
    free = [i for i in range(9) if board[i] == 0]
    smart = int(rolls[k] * 100) >= 55 and len(free) != 9
    k += 1
    cell = None
    if smart:
        cell = _threat(board, COMPUTER)
        if cell is None:
            cell = _threat(board, PLAYER)
    if cell is None:
        cell = free[int(rolls[k] * len(free))]
        k += 1
    return cell, k


def _winning_line(board: list[int], rolls: list[float], k: int = 0) -> list[int] | None:
    """Player moves that win against the computer's predicted replies, or None."""
    for move in (i for i in range(9) if board[i] == 0):
        after = board.copy()
        after[move] = PLAYER
        if _wins(after, PLAYER):
            return [move]
        if 0 not in after:
            continue
        cell, nxt = _computer_move(after, rolls, k)
        after[cell] = COMPUTER
        if _wins(after, COMPUTER) or 0 not in after:
            continue
        rest = _winning_line(after, rolls, nxt)
        if rest is not None:
            return [move, *rest]
    return None


@oracle("tic-tac-toe", prelude=TTT_HOOK)
def tic_tac_toe(ctx: OracleContext) -> Iterator[Step]:
    board: list[int] = ctx.js("gameState.slice()")
    rolls: list[float] = ctx.js("window.__baPeek(12)")
    line = _winning_line(board, rolls)
    if line is None:
        raise OracleError(f"no winning line exists from {board} with these rolls")
    k = 0
    for move in line:
        expected = board.copy()
        expected[move] = PLAYER
        if not _wins(expected, PLAYER):
            cell, k = _computer_move(expected, rolls, k)
            expected[cell] = COMPUTER
        # The empty cells are told apart only by their place in the grid.
        yield Step("click", f"#ttt-{move}")
        board = ctx.js("gameState.slice()")
        if board != expected and not _wins(expected, PLAYER):
            raise OracleError(f"predicted {expected}, the game shows {board}")
