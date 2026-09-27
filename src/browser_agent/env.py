"""A MiniWoB++ episode driven through Playwright, rewarded by the benchmark's own globals.

The reset protocol follows the upstream Selenium instance (``miniwob/selenium_instance.py``):
seed ``Math.seedrandom``, call ``core.startEpisodeReal()``, wait for ``WOB_TASK_READY``, then
read ``WOB_DONE_GLOBAL`` / ``WOB_RAW_REWARD_GLOBAL`` after every action. Two deliberate
differences, both applied identically to every policy:

* the page is reloaded for every episode, so one episode's leftovers cannot leak into the next;
* ``core.EPISODE_MAX_TIME`` is raised (default 10 minutes, upstream 10 s) and the reported
  reward is the *raw* reward, which carries no time penalty. A 14B model thinking for 20 s per
  step would otherwise time out on every task, and "slow" is not what this repo measures.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import TracebackType

from playwright.sync_api import (
    Browser,
    BrowserContext,
    CDPSession,
    Page,
    Playwright,
    sync_playwright,
)
from playwright.sync_api import Error as PlaywrightError

from browser_agent.pages import install_routes, task_path, task_url
from browser_agent.snapshot import Snapshot, capture

DEFAULT_EPISODE_MS = 600_000
VIEWPORT = {"width": 800, "height": 600}

# Lets privileged code name an element found by JavaScript: it gets the same kind of stamp the
# snapshot walk gives every element, from the same counter.
STAMP_HELPER = """() => {
  window.__baNext = window.__baNext || 1;
  window.__baStamp = el => {
    if (!el.hasAttribute('data-ba-id')) el.setAttribute('data-ba-id', String(window.__baNext++));
    return Number(el.getAttribute('data-ba-id'));
  };
}"""


class MissingBrowserError(RuntimeError):
    """Chromium for this Playwright version is not installed."""


class TaskNotFoundError(FileNotFoundError):
    pass


@dataclass(frozen=True)
class Outcome:
    done: bool
    raw_reward: float
    reason: str | None


def launch_browser(pw: Playwright) -> Browser:
    """Launch Playwright's own Chromium build (the full one, in new-headless mode)."""
    try:
        return pw.chromium.launch(channel="chromium")
    except PlaywrightError as exc:
        if "Executable doesn't exist" in str(exc):
            raise MissingBrowserError(
                "Playwright's Chromium is not installed. Run: uv run playwright install chromium"
            ) from exc
        raise


class MiniWoBEnv:
    """One browser, one page, any number of episodes.

    Use as a context manager::

        with MiniWoBEnv() as env:
            snap = env.reset("click-button", seed=3)
            ...
            outcome = env.outcome()
    """

    def __init__(self, episode_ms: int = DEFAULT_EPISODE_MS, root: Path | None = None):
        self.episode_ms = episode_ms
        self.root = root
        self._pw: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self.page: Page | None = None
        self._cdp: CDPSession | None = None

    def __enter__(self) -> MiniWoBEnv:
        self._pw = sync_playwright().start()
        try:
            self._browser = launch_browser(self._pw)
        except BaseException:
            self._pw.stop()
            raise
        self._context = self._browser.new_context(viewport=VIEWPORT)
        install_routes(self._context, self.root)
        self.page = self._context.new_page()
        self._cdp = self._context.new_cdp_session(self.page)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._browser is not None:
            self._browser.close()
        if self._pw is not None:
            self._pw.stop()

    def _live_page(self) -> Page:
        if self.page is None:
            raise RuntimeError("MiniWoBEnv must be used inside a `with` block")
        return self.page

    def reset(self, task: str, seed: int, prelude: str | None = None) -> Snapshot:
        """Load ``task`` fresh and start a seeded episode.

        ``prelude`` is JavaScript run after the page loads and before the problem is generated;
        the oracle uses it to keep references to task internals. It must not change behaviour.
        """
        if not task_path(task, self.root).is_file():
            raise TaskNotFoundError(f"no MiniWoB++ page for task {task!r}")
        page = self._live_page()
        page.goto(task_url(task))
        page.wait_for_function("typeof core !== 'undefined' && typeof genProblem === 'function'")
        page.evaluate(STAMP_HELPER)
        if prelude:
            page.evaluate(prelude)
        page.evaluate(
            """([seed, ms]) => {
                Math.seedrandom(String(seed));
                core.EPISODE_MAX_TIME = ms;
                core.startEpisodeReal();
            }""",
            [seed, self.episode_ms],
        )
        page.wait_for_function("WOB_TASK_READY === true")
        return self.observe()

    def observe(self) -> Snapshot:
        assert self._cdp is not None
        return capture(self._live_page(), self._cdp)

    def outcome(self) -> Outcome:
        done, raw, reason = self._live_page().evaluate(
            "[WOB_DONE_GLOBAL, WOB_RAW_REWARD_GLOBAL, WOB_REWARD_REASON]"
        )
        return Outcome(bool(done), float(raw), None if reason is None else str(reason))
