from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from browser_agent.env import MiniWoBEnv, MissingBrowserError
from browser_agent.snapshot import Snapshot

FIXTURES = Path(__file__).parent / "fixtures"


def load_snapshot(name: str) -> Snapshot:
    """A first observation saved from a real task page by scripts/capture_fixture.py."""
    return Snapshot.from_json((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def env() -> Iterator[MiniWoBEnv]:
    """One real Chromium for the whole session; the browser tests skip if it is missing."""
    try:
        with MiniWoBEnv() as live:
            yield live
    except MissingBrowserError as exc:
        pytest.skip(str(exc))
