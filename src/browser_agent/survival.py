"""Does an encoding still contain the element the oracle had to act on?

Three nested checks, per (encoding, target):

``present``       some fragment of the encoding represents the target or an element that
                  activates it: its own subtree, or a ``<label>`` bound to it (HTML semantics:
                  clicking or filling a label reaches its control).
``identifiable``  present, and the *evidence* of those fragments (content without indices or
                  markup, see :mod:`browser_agent.encoders`) contains every string the
                  instruction uses to pick the target out (its button text, the colour it is
                  described by, the field name...), each as a whole run of tokens. Matching is
                  case-insensitive, whitespace-collapsed, with HTML entities decoded; ``"a|b"``
                  accepts either spelling of one fact (``textarea`` in HTML is ``multiline`` in
                  the accessibility tree). A step with no such strings (a target picked by
                  position, or the only one of its kind) is identifiable whenever present.
``actionable``    present, and one of those fragments carries an index the action layer
                  accepts. The four cleaned encodings index every fragment they emit, so for
                  them this equals ``present`` by design; it discriminates only for
                  ``raw_html``, which has no indices and reports whether a *short* selector (a
                  unique ``#id``) exists rather than only a structural path.

"Identifiable" is strict: text sitting next to the element in the encoding does not count,
because nothing in the encoding ties it to the element. An unlabelled ``<input>`` preceded by
the word "Username" is present but not identifiable. It is also not a uniqueness test: it asks
whether the deciding words reach the target, not whether they reach only the target. A model
may still guess right from adjacency; the model arm measures whether it does.
"""

from __future__ import annotations

import html
import re
from dataclasses import asdict, dataclass
from typing import Any

from browser_agent.encoders import Encoding
from browser_agent.snapshot import Snapshot


def normalise(text: str) -> str:
    return " ".join(html.unescape(text).casefold().split())


def _contains(blob: str, need: str) -> bool:
    """``need`` occurs in ``blob`` as a whole run of tokens: "5" is not found in "15"."""
    pattern = r"(?<![0-9a-z])" + re.escape(normalise(need)) + r"(?![0-9a-z])"
    return re.search(pattern, blob) is not None


@dataclass(frozen=True)
class TargetCheck:
    present: bool
    identifiable: bool
    actionable: bool
    need_hits: tuple[bool, ...] = ()  # per need: found in the target's evidence?

    def as_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["need_hits"] = list(self.need_hits)
        return out


NEED_SOURCES = ("instruction", "page", "markup")


def need_source(need: str, utterance: str, page_text: str) -> str:
    """Where a need's words can be found by an agent that has not seen the answer.

    ``instruction``: in the task instruction itself. ``page``: not in the instruction but in
    the visible text of the page (a flight duration, a card value). ``markup``: only in tag
    names, ids, classes or other attributes (an icon button's ``trash`` class, a ``rect``).
    The survival report is repeated with ``markup`` needs dropped, because they measure
    whether an encoding keeps the page's own naming, not the instruction's wording.
    """
    alts = need.split("|")
    if any(_contains(normalise(utterance), alt) for alt in alts):
        return "instruction"
    if any(_contains(normalise(page_text), alt) for alt in alts):
        return "page"
    return "markup"


def activators(snap: Snapshot, target: int) -> set[int]:
    """Stamps of elements whose activation reaches ``target``: its subtree and bound labels."""
    out = {nid for nid in snap.nodes if snap.is_within(nid, target)}
    node = snap.nodes[target]
    parent = node.parent
    while parent != -1:
        if snap.nodes[parent].tag == "label":
            out |= {nid for nid in snap.nodes if snap.is_within(nid, parent)}
        parent = snap.nodes[parent].parent
    own_id = node.attr("id")
    if own_id:
        for other in snap.nodes.values():
            if other.tag == "label" and other.attr("for") == own_id:
                out |= {nid for nid in snap.nodes if snap.is_within(nid, other.id)}
    return out


def unique_id_selector(snap: Snapshot, target: int) -> bool:
    own_id = snap.nodes[target].attr("id")
    return bool(own_id) and sum(1 for n in snap.nodes.values() if n.attr("id") == own_id) == 1


def check(enc: Encoding, snap: Snapshot, target: int, needs: tuple[str, ...]) -> TargetCheck:
    reach = activators(snap, target)
    owned = [f for f in enc.fragments if f.owner in reach]
    if not owned:
        return TargetCheck(False, False, False, tuple(False for _ in needs))
    blob = normalise(" ".join(f.evidence for f in owned))
    hits = tuple(any(_contains(blob, alt) for alt in need.split("|")) for need in needs)
    identifiable = all(hits)
    if enc.name == "raw_html":
        actionable = unique_id_selector(snap, target)
    else:
        actionable = any(f.handle is not None for f in owned)
    return TargetCheck(True, identifiable, actionable, hits)
