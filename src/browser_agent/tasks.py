"""Which MiniWoB++ tasks this repo runs, how they are grouped, and why the rest are left out.

The task set is every MiniWoB++ task (``book-flight``'s separate ``flight/`` benchmark aside)
whose solution fits the action space: click, type, select, scroll, press Enter. Tasks that
need a pointer gesture the action space does not have (drag, hover, free-form drawing, text
selection) are excluded up front, each with its reason; they are not counted as failures.
"""

from __future__ import annotations

from browser_agent import oracles  # noqa: F401  (registers every oracle)
from browser_agent.oracles.base import ORACLES

FAMILIES: dict[str, tuple[str, ...]] = {
    "click": (
        "click-button",
        "click-button-sequence",
        "click-color",
        "click-dialog",
        "click-dialog-2",
        "click-link",
        "click-pie",
        "click-pie-nodelay",
        "click-shades",
        "click-shape",
        "click-test",
        "click-test-2",
        "click-test-transfer",
        "click-widget",
        "focus-text",
        "focus-text-2",
        "button-delay",
    ),
    "choose": (
        "choose-list",
        "click-checkboxes",
        "click-checkboxes-large",
        "click-checkboxes-soft",
        "click-checkboxes-transfer",
        "click-option",
        "click-scroll-list",
        "number-checkboxes",
    ),
    "navigate": (
        "click-collapsible",
        "click-collapsible-nodelay",
        "click-collapsible-2",
        "click-collapsible-2-nodelay",
        "click-menu",
        "click-menu-2",
        "click-tab",
        "click-tab-2",
        "click-tab-2-easy",
        "click-tab-2-medium",
        "click-tab-2-hard",
        "navigate-tree",
        "multi-layouts",
        "multi-orderings",
    ),
    "form": (
        "enter-date",
        "enter-password",
        "enter-text",
        "enter-text-2",
        "enter-text-dynamic",
        "enter-time",
        "login-user",
        "login-user-popup",
        "form-sequence-2",
        "form-sequence-3",
        "use-autocomplete",
        "use-autocomplete-nodelay",
        "use-spinner",
        "choose-date",
        "choose-date-easy",
        "choose-date-medium",
        "choose-date-nodelay",
        "sign-agreement",
        "copy-paste",
        "copy-paste-2",
        "text-transform",
        "unicode-test",
    ),
    "reason": (
        "ascending-numbers",
        "count-shape",
        "count-sides",
        "find-greatest",
        "find-word",
        "generate-number",
        "grid-coordinate",
        "guess-number",
        "identify-shape",
        "odd-or-even",
        "read-table",
        "read-table-2",
        "scroll-text",
        "scroll-text-2",
        "simon-says",
        "simple-algebra",
        "simple-arithmetic",
        "stock-market",
        "tic-tac-toe",
        "visual-addition",
    ),
    "composite": (
        "book-flight",
        "book-flight-nodelay",
        "buy-ticket",
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
        "order-food",
        "phone-book",
        "search-engine",
        "social-media",
        "social-media-all",
        "social-media-some",
        "terminal",
    ),
}

# Out of the action space (no oracle). The last three were attempted and found to need a
# gesture the action space lacks; the evidence is in the README.
EXCLUDED: dict[str, str] = {
    "bisect-angle": "free-form click at a computed point on an SVG",
    "chase-circle": "tracking a moving target with the pointer",
    "circle-center": "free-form click at a computed point on an SVG",
    "daily-calendar": "drag to create an event",
    "drag-box": "drag",
    "drag-circle": "drag",
    "drag-cube": "drag",
    "drag-items": "drag",
    "drag-items-grid": "drag",
    "drag-shapes": "drag",
    "drag-shapes-2": "drag",
    "drag-single-shape": "drag",
    "drag-sort-numbers": "drag",
    "draw-circle": "free-form drawing",
    "draw-line": "free-form drawing",
    "find-midpoint": "free-form click at a computed point on an SVG",
    "form-sequence": "a slider that a click only ever sets to 0 (needs drag or arrow keys)",
    "highlight-text": "text selection",
    "highlight-text-2": "text selection",
    "hot-cold": "hover to find a hidden point, then a click at that exact point",
    "hover-shape": "hover",
    "moving-items": "clicking moving SVG targets",
    "resize-textarea": "drag a resize handle",
    "text-editor": "styling a word needs text selection; typing clears the formatting",
    "right-angle": "free-form click at a computed point on an SVG",
    "use-colorwheel": "drag on a colour wheel",
    "use-colorwheel-2": "drag on a colour wheel",
    "use-slider": "drag a slider handle",
    "use-slider-2": "drag slider handles",
}


# In-scope tasks the oracle cannot solve on every seed, and why (investigated, not guessed).
ORACLE_LIMITS: dict[str, str] = {
    "click-menu": "submenus open on hover; clicking a parent item selects it and ends the "
    "episode, so only top-level targets are reachable by click",
    "click-pie": "when the answer is the item the wheel starts on, wheelnav keeps re-inserting "
    "its title under the pointer and the click lands on the <svg>",
    "click-pie-nodelay": "as click-pie",
    "stock-market": "the price can stay under the threshold for 400 ms, less than one "
    "observe-and-encode cycle on a loaded machine",
    "button-delay": "a 1 s wait with a 150 ms tolerance, measured across an observe-and-encode "
    "cycle whose length depends on machine load",
    "choose-date-medium": "load-dependent: a datepicker animation outlasted the 3 s hover "
    "timeout once; the same seed passes on a rerun",
}


def family_of(task: str) -> str:
    for family, tasks in FAMILIES.items():
        if task in tasks:
            return family
    raise KeyError(f"{task} has no family")


def runnable_tasks() -> list[str]:
    """Tasks with an oracle, in family order."""
    return [t for tasks in FAMILIES.values() for t in tasks if t in ORACLES]


def unsolved_in_scope() -> list[str]:
    """In-scope tasks without an oracle (should be empty, or explained in the README)."""
    return [t for tasks in FAMILIES.values() for t in tasks if t not in ORACLES]
