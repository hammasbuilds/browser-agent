"""The scripted-oracle protocol.

An oracle is a generator. It reads the instruction and, with privileged access, the live page
(including task globals a real agent never sees), and yields one :class:`Step` at a time. The
harness observes the page, checks the step's target against every encoding, then executes the
step through the same :mod:`browser_agent.actions` executor the model uses, and resumes the
generator, which may re-read the page to decide what to do next.

``needs`` lists the facts that pick the target out from its neighbours, written the way the
page carries them; it is what "identifiable" is checked against. Often that is the
instruction's own wording ("submit", a name, a colour), but not always: "delete it" is carried
by an icon whose only name is its ``trash`` class, "the shortest flight" by a duration shown on
the page. The harness tags every need with where it can be found (instruction, visible page
text, or markup only; :func:`browser_agent.survival.need_source`) and the report is repeated
without the markup-only ones. It is empty when the instruction picks the target by position or
by being the only one of its kind.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

from playwright.sync_api import Page

from browser_agent.actions import Kind


@dataclass(frozen=True)
class Step:
    kind: Kind
    selector: str | None = None  # privileged CSS selector for exactly one element
    needs: tuple[str, ...] = ()
    text: str = ""
    options: tuple[str, ...] = field(default_factory=tuple)
    dy: int = 0
    wait_ms: int = 0  # extra settle time after the action (animations, delayed widgets)


@dataclass
class OracleContext:
    page: Page
    utterance: str

    def js(self, expression: str, arg: Any = None) -> Any:
        return self.page.evaluate(expression, arg)

    def quoted(self) -> list[str]:
        """Every double-quoted span in the instruction, in order."""
        return re.findall(r'"([^"]*)"', self.utterance)

    def texts(self, selector: str) -> list[str]:
        return self.page.eval_on_selector_all(
            selector, "els => els.map(e => e.textContent.replace(/\\s+/g, ' ').trim())"
        )

    def nth(self, selector: str, text: str) -> str:
        """A selector for the single element among ``selector`` whose text equals ``text``."""
        matches = [i for i, t in enumerate(self.texts(selector)) if t == text]
        if len(matches) != 1:
            raise OracleError(f"{len(matches)} elements match {selector!r} with text {text!r}")
        return f"{selector} >> nth={matches[0]}"


class OracleError(RuntimeError):
    """The oracle could not work out what to do: a harness bug or a task it cannot parse."""


Oracle = Callable[[OracleContext], Iterator[Step]]


@dataclass(frozen=True)
class Registered:
    fn: Oracle
    prelude: str | None  # JS run before the episode starts, to keep task internals reachable


ORACLES: dict[str, Registered] = {}


def oracle(*tasks: str, prelude: str | None = None) -> Callable[[Oracle], Oracle]:
    def register(fn: Oracle) -> Oracle:
        for task in tasks:
            if task in ORACLES:
                raise ValueError(f"two oracles registered for {task}")
            ORACLES[task] = Registered(fn, prelude)
        return fn

    return register
