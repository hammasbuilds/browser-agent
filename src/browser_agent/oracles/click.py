"""Oracles for the click-* tasks: pick the right element(s) and click."""

from __future__ import annotations

import re
from collections.abc import Iterator

from browser_agent.oracles.base import OracleContext, OracleError, Step, oracle


def submit(selector: str = "#subbtn", label: str = "submit") -> Step:
    return Step("click", selector, needs=(label,))


@oracle("click-test")
def click_test(ctx: OracleContext) -> Iterator[Step]:
    yield Step("click", "#subbtn")


@oracle("click-test-2")
def click_test_2(ctx: OracleContext) -> Iterator[Step]:
    yield Step("click", "#subbtn", needs=("ONE",))


@oracle("click-button-sequence")
def click_button_sequence(ctx: OracleContext) -> Iterator[Step]:
    yield Step("click", "#subbtn", needs=("ONE",))
    yield Step("click", "#subbtn2", needs=("TWO",))


@oracle("click-button")
def click_button(ctx: OracleContext) -> Iterator[Step]:
    (label,) = ctx.quoted()
    # Buttons can repeat; the task rewards a click on any button with the winning text.
    yield Step("click", f"#area button:text-is({label!r}) >> nth=0", needs=(label,))


@oracle("click-link")
def click_link(ctx: OracleContext) -> Iterator[Step]:
    (word,) = ctx.quoted()
    # Several links can share the winning text; the task rewards any of them.
    yield Step("click", f"#area .alink:text-is({word!r}) >> nth=0", needs=(word,))


def _checkbox_names(ctx: OracleContext, prefix: str) -> list[str]:
    body = re.match(prefix + r"(.*) and click Submit\.$", ctx.utterance)
    if body is None:
        raise OracleError(f"cannot parse {ctx.utterance!r}")
    names = body.group(1)
    return [] if names == "nothing" else names.split(", ")


def _labels(ctx: OracleContext) -> list[str]:
    return ctx.texts("#area label")


@oracle("click-checkboxes", "click-checkboxes-large", "click-checkboxes-transfer")
def click_checkboxes(ctx: OracleContext) -> Iterator[Step]:
    labels = _labels(ctx)
    for name in _checkbox_names(ctx, "Select "):
        yield Step("click", f"#area label >> nth={labels.index(name)} >> input", needs=(name,))
    yield submit()


@oracle("click-checkboxes-soft")
def click_checkboxes_soft(ctx: OracleContext) -> Iterator[Step]:
    groups: list[list[str]] = ctx.js("SYNONYMS")
    labels = _labels(ctx)
    for word in _checkbox_names(ctx, "Select words similar to "):
        group = next(g for g in groups if word in g)
        hits = [i for i, label in enumerate(labels) if label in group]
        if len(hits) != 1:
            raise OracleError(f"{len(hits)} checkboxes are synonyms of {word!r}")
        yield Step("click", f"#area label >> nth={hits[0]} >> input", needs=(labels[hits[0]],))
    yield submit()


@oracle("click-option")
def click_option(ctx: OracleContext) -> Iterator[Step]:
    (name,) = _checkbox_names(ctx, "Select ")
    labels = _labels(ctx)
    yield Step("click", f"#area label >> nth={labels.index(name)} >> input", needs=(name,))
    yield submit()


@oracle("click-collapsible", "click-collapsible-nodelay")
def click_collapsible(ctx: OracleContext) -> Iterator[Step]:
    header = ctx.texts("#area h3")[0]
    yield Step("click", "#area h3", needs=(header,), wait_ms=500)
    yield submit()


@oracle("click-collapsible-2", "click-collapsible-2-nodelay")
def click_collapsible_2(ctx: OracleContext) -> Iterator[Step]:
    (word,) = ctx.quoted()
    section = ctx.js(
        """w => {
            const heads = [...document.querySelectorAll('#area h3')];
            return heads.findIndex(h => [...h.nextElementSibling.querySelectorAll('.alink')]
                .some(a => a.textContent === w));
        }""",
        word,
    )
    if section < 0:
        raise OracleError(f"no section holds link {word!r}")
    header = ctx.texts("#area h3")[section]
    yield Step("click", f"#area h3 >> nth={section}", needs=(header,), wait_ms=500)
    yield Step("click", f"#area .alink:text-is({word!r}) >> nth=0", needs=(word,))


@oracle("click-color")
def click_color(ctx: OracleContext) -> Iterator[Step]:
    color = re.match(r"Click on the (.+) colored box\.$", ctx.utterance)
    if color is None:
        raise OracleError(f"cannot parse {ctx.utterance!r}")
    name = color.group(1)
    yield Step("click", f'#area .color[data-color="{name}"]', needs=(name,))


@oracle("click-dialog")
def click_dialog(ctx: OracleContext) -> Iterator[Step]:
    # The instruction says "x"; the button is an icon whose only text is "Close".
    yield Step("click", ".ui-dialog-titlebar button", needs=("close",))


@oracle("click-dialog-2")
def click_dialog_2(ctx: OracleContext) -> Iterator[Step]:
    (label,) = ctx.quoted()
    if label == "x":
        yield Step("click", ".ui-dialog-titlebar button", needs=("close",))
    else:
        yield Step("click", ctx.nth(".ui-dialog-buttonpane button", label), needs=(label,))


@oracle("click-tab")
def click_tab(ctx: OracleContext) -> Iterator[Step]:
    tab = re.search(r"Tab #(\d)", ctx.utterance)
    if tab is None:
        raise OracleError(f"cannot parse {ctx.utterance!r}")
    yield Step("click", f'#area ul a[href="#tabs-{tab.group(1)}"]', needs=(f"Tab #{tab[1]}",))


@oracle("click-tab-2", "click-tab-2-easy", "click-tab-2-medium", "click-tab-2-hard")
def click_tab_2(ctx: OracleContext) -> Iterator[Step]:
    word = ctx.quoted()[-1]
    panel = ctx.js(
        """w => [...document.querySelectorAll('#area > div[id^=tabs-]')]
                .findIndex(p => [...p.querySelectorAll('.alink')].some(a => a.textContent === w))""",
        word,
    )
    if panel < 0:
        raise OracleError(f"no tab holds link {word!r}")
    active = ctx.js("$('#area').tabs('option', 'active')")
    if active != panel:
        yield Step("click", f'#area ul a[href="#tabs-{panel + 1}"]', needs=(f"Tab #{panel + 1}",))
    yield Step("click", f"#tabs-{panel + 1} .alink:text-is({word!r}) >> nth=0", needs=(word,))


@oracle("click-widget")
def click_widget(ctx: OracleContext) -> Iterator[Step]:
    (kind,) = ctx.quoted()
    # The reward reads data-type; the only evidence of it an encoder can keep is the tag
    # (and the type attribute for inputs).
    evidence = {
        "radio": "radio",
        "checkbox": "checkbox",
        "text": "input|textbox",
        "textarea": "textarea|multiline",
        "button": "button",
    }[kind]
    yield Step("click", f'#area [data-type="{kind}"] >> nth=0', needs=(evidence,))


@oracle("click-menu-2")
def click_menu_2(ctx: OracleContext) -> Iterator[Step]:
    icons = {
        "ui-icon-disk": "Save",
        "ui-icon-seek-start": "Prev",
        "ui-icon-stop": "Stop",
        "ui-icon-play": "Play",
        "ui-icon-seek-end": "Next",
        "ui-icon-zoomin": "Zoom In",
        "ui-icon-zoomout": "Zoom Out",
    }
    quoted = ctx.quoted()
    if len(quoted) == 2:
        label = quoted[1]
    else:
        icon = ctx.js("document.querySelector('#query .ui-icon').classList[1]")
        label = icons[icon]
    yield Step("click", "#open-menu", needs=("Menu",), wait_ms=200)
    if label in ("Prev", "Stop", "Play", "Next"):
        # Nested under "Playback": jQuery UI opens it on hover or on click.
        yield Step("click", "#menu > li:has(ul) > div", needs=("Playback",), wait_ms=400)
    item = f"#menu li:not(:has(ul)):has(> div:text-is({label!r}))"
    yield Step("click", item, needs=(label,))


@oracle("click-menu")
def click_menu(ctx: OracleContext) -> Iterator[Step]:
    path = ctx.utterance.removeprefix("Select ").split(">")
    for depth, name in enumerate(path):
        chain = " > ".join(["#menu"] + ["li > ul"] * depth)
        # Hover-driven jQuery UI menu: clicking an item with a submenu opens it.
        yield Step("click", f"{chain} > li > div:text-is({name!r})", needs=(name,), wait_ms=400)


@oracle("click-scroll-list")
def click_scroll_list(ctx: OracleContext) -> Iterator[Step]:
    body = re.match(r"Select (.*) from the scroll list and click Submit\.$", ctx.utterance)
    if body is None:
        raise OracleError(f"cannot parse {ctx.utterance!r}")
    names = tuple(body.group(1).split(", "))
    yield Step("select", "#options", needs=names, options=names)
    yield Step("click", "#area button", needs=("submit",))


@oracle("choose-list")
def choose_list(ctx: OracleContext) -> Iterator[Step]:
    body = re.match(r"Select (.*) from the list and click Submit\.$", ctx.utterance)
    if body is None:
        raise OracleError(f"cannot parse {ctx.utterance!r}")
    name = body.group(1)
    yield Step("select", "#options", needs=(name,), options=(name,))
    yield Step("click", "#area button", needs=("submit",))


@oracle("click-shades")
def click_shades(ctx: OracleContext) -> Iterator[Step]:
    color = re.search(r"shades of (\w+)", ctx.utterance)
    if color is None:
        raise OracleError(f"cannot parse {ctx.utterance!r}")
    count = ctx.js(f"document.querySelectorAll('#area span[data-color=\"{color[1]}\"]').length")
    for i in range(count):
        yield Step("click", f'#area span[data-color="{color[1]}"] >> nth={i}', needs=(color[1],))
    yield Step("click", "#area button", needs=("submit",))


SHAPE_TAGS = {"circle": "circle", "rectangle": "rect", "triangle": "polygon"}

# Installed before the episode starts: keep the task's own grid and description objects so the
# oracle can ask the task's own matcher which shape is right.
SHAPE_HOOK = """
(() => {
  const render = shapes.renderGrid, describe = shapes.generalDesc;
  shapes.renderGrid = function (svg, grid) { window.__baGrid = grid; return render(svg, grid); };
  shapes.generalDesc = function (s) { const d = describe(s); window.__baDesc = d; return d; };
})()
"""


def shape_needs(parts: list[str]) -> tuple[str, ...]:
    """Evidence strings for a shapes.js description ``[size, colour, text-or-type]``.

    Size is carried only by numeric geometry, and "letter"/"digit"/"shape"/"item" name a
    category rather than a value, so neither contributes a string.
    """
    _, color, what = parts
    needs = [color] if color else []
    if what in SHAPE_TAGS:
        needs.append(SHAPE_TAGS[what])
    elif len(what) == 1:
        needs.append(what)
    return tuple(needs)


@oracle("click-shape", prelude=SHAPE_HOOK)
def click_shape(ctx: OracleContext) -> Iterator[Step]:
    parts, stamp = ctx.js(
        """() => {
            const d = window.__baDesc;
            const hit = window.__baGrid.shapes.find(s => shapes.shapeMatchesText(s, d));
            return [d.parts, window.__baStamp(hit.svg_shape[0][0])];
        }"""
    )
    yield Step("click", f'[data-ba-id="{stamp}"]', needs=shape_needs(parts))
