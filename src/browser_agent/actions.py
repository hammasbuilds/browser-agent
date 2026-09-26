"""The action space, shared by the scripted oracle and the model agent.

An action names its target either by an index taken from the current observation or by a CSS
selector. Indices are the ``data-ba-id`` stamps, so an index shown by any encoder resolves to
the same element; the executor refuses an index the current observation did not show, so a
model cannot act on something its encoding hid from it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Locator, Page

Kind = Literal["click", "type", "select", "scroll", "submit", "done"]
KINDS: tuple[str, ...] = ("click", "type", "select", "scroll", "submit", "done")
NEEDS_TARGET = {"click", "type", "select", "submit"}


class ActionError(ValueError):
    """An action that is malformed or cannot be carried out on the current page."""


@dataclass(frozen=True)
class Action:
    kind: Kind
    target: int | str | None = None  # index from the observation, or a CSS selector
    text: str = ""  # for type
    options: tuple[str, ...] = field(default_factory=tuple)  # for select (labels)
    dy: int = 0  # for scroll, in pixels

    def describe(self) -> str:
        where = "" if self.target is None else f" {self.target!r}"
        extra = ""
        if self.kind == "type":
            extra = f" text={self.text!r}"
        elif self.kind == "select":
            extra = f" options={list(self.options)!r}"
        elif self.kind == "scroll":
            extra = f" dy={self.dy}"
        return f"{self.kind}{where}{extra}"


def parse_action(obj: Any) -> Action:
    """Validate a model's JSON object (or JSON text) into an :class:`Action`."""
    if isinstance(obj, str):
        try:
            obj = json.loads(obj)
        except json.JSONDecodeError as exc:
            raise ActionError(f"not JSON: {exc.msg}") from exc
    if not isinstance(obj, dict):
        raise ActionError("an action must be a JSON object")
    kind = obj.get("action")
    if kind not in KINDS:
        raise ActionError(f"unknown action {kind!r}; expected one of {', '.join(KINDS)}")
    target = obj.get("target")
    if isinstance(target, str):
        stripped = target.strip().strip("[]")
        target = int(stripped) if stripped.isdigit() else target.strip()
        if target == "":
            target = None
    elif isinstance(target, bool) or not (target is None or isinstance(target, int)):
        raise ActionError("target must be an index (integer) or a CSS selector (string)")
    if kind in NEEDS_TARGET and target is None:
        raise ActionError(f"{kind} needs a target")
    text = obj.get("text", "")
    if kind == "type" and not isinstance(text, str):
        raise ActionError("type needs a string 'text'")
    options = obj.get("options", obj.get("option", ()))
    if isinstance(options, str):
        options = (options,)
    if kind == "select" and (not options or not all(isinstance(o, str) for o in options)):
        raise ActionError("select needs 'options': a label or a list of labels")
    dy = obj.get("dy", 100)
    if kind == "scroll" and (isinstance(dy, bool) or not isinstance(dy, int)):
        raise ActionError("scroll needs an integer 'dy'")
    return Action(
        kind=kind,
        target=target,
        text=text if kind == "type" else "",
        options=tuple(options) if kind == "select" else (),
        dy=dy if kind == "scroll" else 0,
    )


def resolve(page: Page, target: int | str, shown: set[int] | None) -> Locator:
    """Turn an index or selector into a locator for exactly one element."""
    if isinstance(target, int):
        if shown is not None and target not in shown:
            raise ActionError(f"index {target} is not in the current observation")
        loc = page.locator(f'[data-ba-id="{target}"]')
    else:
        loc = page.locator(target)
    try:
        count = loc.count()
    except PlaywrightError as exc:
        raise ActionError(f"invalid selector {target!r}") from exc
    if count == 0:
        raise ActionError(f"no element matches {target!r}")
    if count > 1:
        raise ActionError(f"{target!r} matches {count} elements; it must match exactly one")
    return loc


def execute(page: Page, action: Action, shown: set[int] | None, timeout_ms: int = 3000) -> None:
    """Carry out ``action``. ``shown`` is the set of indices the agent was shown (None: any)."""
    if action.kind == "done":
        return
    if action.kind == "scroll" and action.target is None:
        page.evaluate("dy => window.scrollBy(0, dy)", action.dy)
        return
    assert action.target is not None
    loc = resolve(page, action.target, shown)
    try:
        if action.kind == "click":
            loc.click(timeout=timeout_ms)
        elif action.kind == "type":
            loc.fill("", timeout=timeout_ms)
            loc.press_sequentially(action.text, timeout=timeout_ms)
        elif action.kind == "select":
            loc.select_option(label=list(action.options), timeout=timeout_ms)
        elif action.kind == "scroll":
            loc.evaluate("(el, dy) => el.scrollBy(0, dy)", action.dy)
        elif action.kind == "submit":
            loc.press("Enter", timeout=timeout_ms)
    except PlaywrightError as exc:
        first_line = str(exc).strip().splitlines()[0]
        raise ActionError(f"{action.describe()} failed: {first_line}") from exc
