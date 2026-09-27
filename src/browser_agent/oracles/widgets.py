"""Oracles for the composite-widget tasks: inboxes, feeds, pickers, menus and multi-step forms."""

from __future__ import annotations

import re
from collections.abc import Iterator

from browser_agent.actions import Kind
from browser_agent.oracles.base import OracleContext, OracleError, Step, oracle


def _match(pattern: str, text: str) -> re.Match[str]:
    found = re.search(pattern, text)
    if found is None:
        raise OracleError(f"cannot parse {text!r}")
    return found


def _stamped(stamp: int) -> str:
    return f'[data-ba-id="{stamp}"]'


# ---- email inbox ---------------------------------------------------------------------------

# Keep the task's email list and its expected-details object: two emails can share a sender,
# and only the one the task picked carries the body a forward is checked against.
EMAIL_HOOK = """
(() => {
  const show = displayEmailSummaries, query = displayQuery;
  displayEmailSummaries = function (emails) {
    window.__baEmails = emails;
    return show.apply(this, arguments);
  };
  displayQuery = function (details) {
    window.__baDetails = details;
    return query.apply(this, arguments);
  };
})()
"""


@oracle(
    "email-inbox",
    "email-inbox-delete",
    "email-inbox-forward",
    "email-inbox-forward-nl",
    "email-inbox-forward-nl-turk",
    "email-inbox-important",
    "email-inbox-nl-turk",
    "email-inbox-noscroll",
    "email-inbox-reply",
    "email-inbox-star-reply",
    prelude=EMAIL_HOOK,
)
def email_inbox(ctx: OracleContext) -> Iterator[Step]:
    action, name, index, reply, forward = ctx.js(
        """() => {
            const d = window.__baDetails;
            return [d.action, d.email.name, window.__baEmails.indexOf(d.email),
                    d.reply || '', d.forward || ''];
        }"""
    )
    # Open the email rather than use the row's own icons: in the opened view there is one
    # trash and one star, so the icon alone picks the target out.
    yield Step("click", f'#main .email-thread[data-index="{index}"]', needs=(name,))
    if action == "delete":
        # Icon-only; the page names it only by its class word "trash".
        yield Step("click", "#email .email-actions .trash", needs=("trash",))
    elif action == "important":
        # Icon-only; the page names it only by its class word "star".
        yield Step("click", "#email .email-actions .star", needs=("star",))
    elif action == "reply":
        yield Step("click", "#email .email-reply", needs=("reply",))
        yield Step("type", "#reply-text", text=reply)
        # Icon-only; the page names it only by its id word "send".
        yield Step("click", "#send-reply", needs=("send",))
    elif action == "forward":
        yield Step("click", "#email .email-forward", needs=("forward",))
        # The only single-line input on the forward screen; its "to:" label is not bound to it.
        yield Step("type", "#forward .forward-sender", text=forward)
        yield Step("click", "#send-forward", needs=("send",))
    else:
        raise OracleError(f"unknown email action {action!r}")


# ---- social media --------------------------------------------------------------------------

SOCIAL_ACTIONS = {
    "Share via DM": "share",
    "Copy link to Tweet": "copy",
    "Embed Tweet": "embed",
    "Mute": "menu-user",
    "Block": "block-user",
    "Report": "report",
    "Reply": "reply",
    "Retweet": "retweet",
    "Like": "like",
    "Share": "share",
}


def _posts_by(ctx: OracleContext, user: str) -> list[int]:
    return [i for i, u in enumerate(ctx.texts("#area .media .username")) if u == user]


def _icon(post: int, cls: str, user: str) -> Step:
    # Icon-only; the page names each icon only by its class word. The post is picked by the
    # username, which sits in the post's header rather than in the icon.
    return Step("click", f"#area .media >> nth={post} >> .{cls}", needs=(user, cls))


@oracle("social-media")
def social_media(ctx: OracleContext) -> Iterator[Step]:
    user, label = ctx.texts("#query .bold")
    cls = SOCIAL_ACTIONS[label]
    post = _posts_by(ctx, user)[0]
    if cls in ("reply", "retweet", "like"):
        yield _icon(post, cls, user)
    else:
        yield _icon(post, "more", user)
        # Only the opened menu is shown, so the item's label is enough.
        yield Step("click", f"#area .media >> nth={post} >> li.{cls}", needs=(label,))


@oracle("social-media-all", "social-media-some")
def social_media_many(ctx: OracleContext) -> Iterator[Step]:
    bold = ctx.texts("#query .bold")
    label, user = bold[0], bold[-1]
    posts = _posts_by(ctx, user)
    if len(bold) == 3:
        posts = posts[: int(bold[1])]
    for post in posts:
        yield _icon(post, SOCIAL_ACTIONS[label], user)
    yield Step("click", "#submitRow button", needs=("submit",))


# ---- search engine, phone book -------------------------------------------------------------


@oracle("search-engine")
def search_engine(ctx: OracleContext) -> Iterator[Step]:
    found = _match(r'enter "(.+)" and press "Search".* the (\d+)\w\w search result', ctx.utterance)
    query, rank = found[1], int(found[2])
    # The only text box on the page.
    yield Step("type", "#search-text", text=query)
    yield Step("click", "#search", needs=("search",))
    page = (rank - 1) // 3 + 1
    if page > 1:
        link = f'#pagination li.page-item:not(.prev):not(.next) a:text-is("{page}")'
        yield Step("click", link, needs=(str(page),))
    # Picked by its rank on the page only.
    yield Step("click", f'#page-content a[data-result="{rank - 1}"]')


# Keep the contact the task picked: names can repeat across the five pages.
PHONE_HOOK = """
(() => {
  const show = displayProblem;
  displayProblem = function (expected) {
    window.__baContact = expected;
    return show.apply(this, arguments);
  };
})()
"""


@oracle("phone-book", prelude=PHONE_HOOK)
def phone_book(ctx: OracleContext) -> Iterator[Step]:
    index, prop = ctx.js("() => [window.__baContact.index, window.__baContact.property]")
    for _ in range(index):
        # The pager's "next" arrow; its only text is ">".
        yield Step("click", "#pagination li.next a", needs=(">",))
    # One contact is shown at a time; the link is picked by which property it is, a word the
    # page keeps only in the link's class and in a neighbouring "Phone:" style caption.
    yield Step("click", f"#contact a.{prop}", needs=(prop,))


# ---- login with a popup --------------------------------------------------------------------


@oracle("login-user-popup")
def login_user_popup(ctx: OracleContext) -> Iterator[Step]:
    user, password = ctx.quoted()
    for field, value in (("username", user), ("password", password)):
        # Focusing a field may raise the popup, which disables the form until dismissed.
        yield Step("click", f"#{field}", needs=(field,))
        if ctx.js("() => document.querySelector('#popup') !== null"):
            yield Step("click", "#popup-cancel", needs=("cancel",))
        yield Step("type", f"#{field}", needs=(field,), text=value)
    yield Step("click", "#subbtn", needs=("ok",))


# ---- multi-layouts, multi-orderings --------------------------------------------------------


@oracle("multi-layouts", "multi-orderings")
def multi_layouts(ctx: OracleContext) -> Iterator[Step]:
    found = _match(r"Search for (.+) movies directed by (.+) from year (\d+)\.", ctx.utterance)
    values = {"genre": found[1], "director": found[2], "year": found[3]}
    # No input is bound to its caption, so find each one's caption by its row.
    fields: list[list] = ctx.js(
        """() => [...document.querySelectorAll('#area input[type=text]')].map(i => [
            window.__baStamp(i),
            i.closest('p, .row, tr, .field, .ui-entry').textContent.toLowerCase()])"""
    )
    evidence = {"genre": "genre", "director": "director", "year": "year|released date"}
    for stamp, caption in fields:
        key = next((k for k in ("genre", "director") if k in caption), "year")
        yield Step("type", _stamped(stamp), needs=(evidence[key],), text=values[key])
    submit = "#area button, #area .final, #area .ui-submit"
    (label,) = ctx.texts(submit)
    yield Step("click", submit, needs=(label,))


# ---- navigate-tree -------------------------------------------------------------------------


@oracle("navigate-tree")
def navigate_tree(ctx: OracleContext) -> Iterator[Step]:
    (name,) = ctx.quoted()
    # Any node with the name wins; prefer one already shown, else open its folders top-down.
    chain: list[list] = ctx.js(
        """name => {
            const spans = [...document.querySelectorAll('#tree span')]
                .filter(s => s.textContent === name);
            const hit = spans.find(s => s.offsetParent !== null) || spans[0];
            const out = [];
            for (let li = hit.parentElement.parentElement.closest('li'); li;
                 li = li.parentElement.closest('li')) {
                if (li.classList.contains('expandable')) {
                    const s = li.querySelector(':scope > span');
                    out.unshift([window.__baStamp(s), s.textContent]);
                }
            }
            out.push([window.__baStamp(hit), name]);
            return out;
        }""",
        name,
    )
    for stamp, text in chain:
        yield Step("click", _stamped(stamp), needs=(text,))


# ---- order-food, buy-ticket ----------------------------------------------------------------


@oracle("order-food")
def order_food(ctx: OracleContext) -> Iterator[Step]:
    by_type = re.match(r"Order (\d+) items that are (.+)$", ctx.utterance)
    if by_type:
        count, kind = int(by_type[1]), by_type[2]
        # Any item carrying the type will do; order it ``count`` times.
        stamp = ctx.js(
            """kind => window.__baStamp([...document.querySelectorAll('.food-item')]
                .find(d => d.querySelector(`img[alt="${kind}"]`)).querySelector('.add'))""",
            kind,
        )
        # The type is shown only as the alt/title of an icon beside the "+", not inside it.
        for _ in range(count):
            yield Step("click", _stamped(stamp), needs=(kind, "+"))
    else:
        body = _match(r"Order one of each item: (.+)$", ctx.utterance)[1]
        for item in (n.strip() for n in body.split(", ")):
            stamp = ctx.js(
                """name => window.__baStamp([...document.querySelectorAll('.food-item')]
                    .find(d => d.dataset.item.trim() === name).querySelector('.add'))""",
                item,
            )
            # The item's name sits beside its "+" button, not inside it.
            yield Step("click", _stamped(stamp), needs=(item, "+"))
    yield Step("click", "#submit-order button", needs=("order",))


def _best_flight(ctx: OracleContext, rows: str, button: str, goal: str) -> tuple[int, str]:
    """Stamp the booking button of the flight that best meets ``goal``, and say what shows it.

    ``goal`` is "cheapest", "most expensive", "shortest" or "longest". The evidence is the
    value the choice rests on: the price (inside the button) or the duration (beside it).
    """
    return ctx.js(
        """([rows, button, goal]) => {
            const all = [...document.querySelectorAll(rows)].map(f => ({
                button: f.querySelector(button),
                price: Number(f.querySelector(button).dataset.price),
                duration: Number(f.querySelector('.time-duration').dataset.duration),
                shown: f.querySelector('.time-duration').textContent,
            }));
            const key = goal.includes('expensive') || goal.includes('cheapest')
                ? 'price' : 'duration';
            const sign = goal.includes('cheapest') || goal.includes('shortest') ? 1 : -1;
            all.sort((a, b) => sign * (a[key] - b[key]));
            const best = all[0];
            const evidence = key === 'price' ? '$' + best.price : best.shown;
            return [window.__baStamp(best.button), evidence];
        }""",
        [rows, button, goal],
    )


@oracle("buy-ticket")
def buy_ticket(ctx: OracleContext) -> Iterator[Step]:
    goal = _match(r"Buy the ticket with the (.+)\.$", ctx.utterance)[1]
    stamp, evidence = _best_flight(ctx, "#area .flight", ".buy-ticket", goal)
    yield Step("click", _stamped(stamp), needs=(evidence,))


# ---- sign-agreement ------------------------------------------------------------------------


@oracle("sign-agreement")
def sign_agreement(ctx: OracleContext) -> Iterator[Step]:
    if ctx.utterance.startswith("Click the cancel button"):
        yield Step("click", "#cancel", needs=("cancel",))
        return
    name, button = ctx.quoted()
    # The form stays disabled until the textarea has been scrolled to its end.
    yield Step("scroll", "#text-area", needs=("textarea|multiline",), dy=100_000)
    yield Step("type", "#name", needs=("name",), text=name)
    yield Step("click", f"#{button.lower()}", needs=(button,))


# ---- form sequences ------------------------------------------------------------------------

ORDINALS = {"1st": 1, "2nd": 2, "3rd": 3}


@oracle("form-sequence-2")
def form_sequence_2(ctx: OracleContext) -> Iterator[Step]:
    found = _match(
        r'Check the (\w+) radio button and enter the number "(-?\d+)" into the (\w+) textbox',
        ctx.utterance,
    )
    radio, number, box = ORDINALS[found[1]], found[2], ORDINALS[found[3]]
    # Both controls are picked by position only.
    yield Step("click", f"#area input[type=radio] >> nth={radio - 1}")
    yield Step("type", f"#input-{box}", text=number)
    yield Step("click", "#subbtn", needs=("submit",))


@oracle("form-sequence-3")
def form_sequence_3(ctx: OracleContext) -> Iterator[Step]:
    found = _match(
        r'Choose (.+) from the dropdown, then click the button labeled "(\w+)"', ctx.utterance
    )
    option, label = found[1], found[2]
    # The native <select> is hidden behind a selectric widget; open it and pick the item.
    yield Step("click", "#dropdown-container .selectric")
    yield Step("click", ctx.nth("#dropdown-container .selectric-items li", option), needs=(option,))
    yield Step("click", f"#buttons button:text-is({label!r})", needs=(label,))


# ---- autocomplete, spinner -----------------------------------------------------------------


def _menu_item(ctx: OracleContext, start: str, end: str, contains: bool = False) -> int:
    """Stamp the first open autocomplete item that starts with ``start`` and ends with ``end``.

    With ``contains`` it is the first item containing ``start`` (case-sensitive) instead.
    """
    stamp = ctx.js(
        """([start, end, contains]) => {
            const items = [...document.querySelectorAll('ul.ui-autocomplete li')]
                .filter(li => li.offsetParent !== null);
            const hit = items.find(li => {
                const t = li.textContent;
                return contains ? t.includes(start) : t.startsWith(start) && t.endsWith(end);
            });
            return hit ? window.__baStamp(hit) : null;
        }""",
        [start, end, contains],
    )
    if stamp is None:
        raise OracleError(f"no autocomplete item for {start!r}/{end!r}")
    return stamp


@oracle("use-autocomplete", "use-autocomplete-nodelay")
def use_autocomplete(ctx: OracleContext) -> Iterator[Step]:
    quoted = ctx.quoted()
    start, end = quoted[0], quoted[1] if len(quoted) > 1 else ""
    # jQuery UI autocomplete searches 300 ms after the last key unless the task sets delay 0.
    wait = 100 if "nodelay" in ctx.page.url else 600
    yield Step("type", "#tags", needs=("tags",), text=start, wait_ms=wait)
    stamp = _menu_item(ctx, start, end)
    yield Step("click", _stamped(stamp), needs=tuple(s for s in (start, end) if s))
    yield Step("click", "#subbtn", needs=("submit",))


@oracle("use-spinner")
def use_spinner(ctx: OracleContext) -> Iterator[Step]:
    n = int(_match(r"Select (-?\d+) with the spinner", ctx.utterance)[1])
    # The field ignores the keyboard; only the arrow buttons change it. They are icon-only
    # and named only by the class words "up" and "down".
    arrow = "up" if n > 0 else "down"
    for _ in range(abs(n)):
        yield Step("click", f"#area .ui-spinner-{arrow}", needs=(arrow,))
    yield Step("click", "#subbtn", needs=("submit",))


# ---- datepicker ----------------------------------------------------------------------------


def _pick_date(ctx: OracleContext, field: str, date: str, animated: bool) -> Iterator[Step]:
    """Open the jQuery UI datepicker on ``field`` and pick ``date`` (MM/DD/YYYY)."""
    month, day, year = (int(p) for p in date.split("/"))
    yield Step("click", field, wait_ms=500 if animated else 0)
    shown_month, shown_year = ctx.js(
        """() => {
            const td = document.querySelector('#ui-datepicker-div td[data-month]');
            return [Number(td.dataset.month) + 1, Number(td.dataset.year)];
        }"""
    )
    offset = (year - shown_year) * 12 + (month - shown_month)
    for _ in range(abs(offset)):
        way = "next" if offset > 0 else "prev"
        yield Step("click", f"#ui-datepicker-div a.ui-datepicker-{way}", needs=(way,))
    cell = f'#ui-datepicker-div td[data-month="{month - 1}"][data-year="{year}"]'
    # The day number alone: the month is carried by the calendar's header, not the cell.
    yield Step("click", f'{cell} a:text-is("{day}")', needs=(str(day),))


@oracle("choose-date", "choose-date-easy", "choose-date-medium", "choose-date-nodelay")
def choose_date(ctx: OracleContext) -> Iterator[Step]:
    date = _match(r"Select (\d\d/\d\d/\d{4}) as the date", ctx.utterance)[1]
    animated = "nodelay" not in ctx.page.url
    yield from _pick_date(ctx, "#datepicker", date, animated)
    yield Step("click", "#subbtn", needs=("submit",))


# ---- book-flight ---------------------------------------------------------------------------


@oracle("book-flight", "book-flight-nodelay")
def book_flight(ctx: OracleContext) -> Iterator[Step]:
    found = _match(
        r"Book the (\w+) one-way flight from: (.+) to: (.+) on (\d\d/\d\d/\d{4})\.$",
        ctx.utterance,
    )
    goal, origin, destination, date = found[1], found[2], found[3], found[4]
    animated = "nodelay" not in ctx.page.url
    wait = 600 if animated else 100
    for field, place in (("#flight-from", origin), ("#flight-to", destination)):
        yield Step("type", field, needs=(field[8:],), text=place, wait_ms=wait)
        stamp = _menu_item(ctx, place, "", contains=True)
        yield Step("click", _stamped(stamp), needs=(place,))
    yield from _pick_date(ctx, "#datepicker", date, animated)
    yield Step("click", "#search", needs=("search",))
    stamp, evidence = _best_flight(ctx, "#results .flight", ".flight-price", goal)
    yield Step("click", _stamped(stamp), needs=(evidence,))


# ---- button-delay --------------------------------------------------------------------------


def _press(ctx: OracleContext, selector: str) -> Kind:
    """Click a button, or press Enter on it when another element covers its centre.

    The two buttons are placed at random and can overlap; a click lands on the centre.
    """
    covered = ctx.js(
        """sel => {
            const el = document.querySelector(sel), r = el.getBoundingClientRect();
            const hit = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
            return !el.contains(hit);
        }""",
        selector,
    )
    return "submit" if covered else "click"


@oracle("button-delay")
def button_delay(ctx: OracleContext) -> Iterator[Step]:
    seconds = int(_match(r"wait (\d+) seconds", ctx.utterance)[1])
    before = ctx.js("() => Date.now()")
    yield Step(_press(ctx, "#subbtn"), "#subbtn", needs=("ONE",))
    # The wait is timed here rather than with ``wait_ms``: the harness observes and encodes the
    # page between the two presses, and that time counts towards the delay. Assume it costs
    # what it cost before the first press, and wait out the rest.
    clicked, now = ctx.js("() => [currentTime, Date.now()]")
    remaining = seconds * 1000 - (now - clicked) - (clicked - before)
    if remaining > 0:
        ctx.page.wait_for_timeout(remaining)
    yield Step(_press(ctx, "#subbtn2"), "#subbtn2", needs=("TWO",))


# ---- terminal ------------------------------------------------------------------------------


@oracle("terminal")
def terminal(ctx: OracleContext) -> Iterator[Step]:
    body = ctx.utterance
    ext = "" if "no file extension" in body else _match(r"extension \.(\S+)$", body)[1]
    # Keys go to a 1x1 transparent input that the terminal focuses on click.
    yield Step("type", "#terminal-target", text="ls")
    yield Step("submit", "#terminal-target")
    listing = ctx.texts("#terminal .terminal-output .output")[-1].split()
    target = next(f for f in listing if (f.split(".", 1) + [""])[1] == ext)
    yield Step("type", "#terminal-target", text=f"rm {target}")
    yield Step("submit", "#terminal-target")


# ---- click-pie -----------------------------------------------------------------------------


@oracle("click-pie", "click-pie-nodelay")
def click_pie(ctx: OracleContext) -> Iterator[Step]:
    (label,) = ctx.quoted()
    # Known limit: item 0 starts selected, and hovering it makes wheelnav re-insert its title
    # over and over, so the mousedown of a centre click lands on the <svg> and nothing happens.
    # When the label is item 0's this click is still made, and the episode fails.
    wait = 0 if "nodelay" in ctx.page.url else 1600
    # The spreader's only text is "+".
    yield Step("click", "#wheelnav-divWheel-spreadertitle", needs=("+",), wait_ms=wait)
    stamp = ctx.js(
        """label => window.__baStamp([...document.querySelectorAll(
            '#divWheel text[id^="wheelnav-divWheel-title-"]')]
            .find(t => t.textContent === label))""",
        label,
    )
    yield Step("click", _stamped(stamp), needs=(label,))
