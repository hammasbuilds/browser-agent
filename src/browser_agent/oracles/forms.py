"""Oracles for text-entry and focus tasks."""

from __future__ import annotations

import re
from collections.abc import Iterator

from browser_agent.oracles.base import OracleContext, OracleError, Step, oracle


def _match(pattern: str, text: str) -> re.Match[str]:
    found = re.search(pattern, text)
    if found is None:
        raise OracleError(f"cannot parse {text!r}")
    return found


@oracle("focus-text")
def focus_text(ctx: OracleContext) -> Iterator[Step]:
    yield Step("click", "#tt")


@oracle("focus-text-2")
def focus_text_2(ctx: OracleContext) -> Iterator[Step]:
    nth = {"1st": 1, "2nd": 2, "3rd": 3}[_match(r"the (\w+) input", ctx.utterance)[1]]
    # Picked by position only: every encoding keeps document order, so no string is needed.
    yield Step("click", f"#tt{nth}")


@oracle("enter-text")
def enter_text(ctx: OracleContext) -> Iterator[Step]:
    (text,) = ctx.quoted()
    yield Step("type", "#tt", text=text)
    yield Step("click", "#subbtn", needs=("submit",))


@oracle("enter-text-2")
def enter_text_2(ctx: OracleContext) -> Iterator[Step]:
    (text,) = ctx.quoted()
    upper = "upper case" in ctx.utterance
    yield Step("type", "#tt", text=text.upper() if upper else text.lower())
    yield Step("click", "#subbtn", needs=("submit",))


@oracle("enter-password")
def enter_password(ctx: OracleContext) -> Iterator[Step]:
    (password,) = ctx.quoted()
    yield Step("type", "#password", needs=("password",), text=password)
    yield Step("type", "#verify", needs=("verify",), text=password)
    yield Step("click", "#subbtn", needs=("submit",))


@oracle("login-user")
def login_user(ctx: OracleContext) -> Iterator[Step]:
    user, password = ctx.quoted()
    yield Step("type", "#username", needs=("username",), text=user)
    yield Step("type", "#password", needs=("password",), text=password)
    yield Step("click", "#subbtn", needs=("login",))
