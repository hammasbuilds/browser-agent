"""One observation of a task page, captured once and shared by every encoder.

A :class:`Snapshot` is plain data (JSON round-trippable), so encoders and the survival analysis
can be tested against snapshots saved from real MiniWoB++ pages without launching a browser.

Three sources are merged, all keyed by the ``data-ba-id`` stamp that ``snapshot.js`` puts on
each element:

* the DOM walk from ``snapshot.js`` (tags, attributes, text, visibility, live form state);
* Chrome's accessibility tree (``Accessibility.getFullAXTree``), mapped back to stamps through
  ``DOM.getDocument``'s backend node ids;
* Chrome's own click-target flag (``DOMSnapshot.captureSnapshot``'s ``isClickable``), which
  covers listeners attached from JavaScript that no attribute or style reveals.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from functools import cached_property
from importlib.resources import files
from typing import Any

from playwright.sync_api import CDPSession, Page

EXCLUDED_IDS = ("query", "reward-display", "sync-task-cover", "click-canvas")
_WALK_JS = files("browser_agent").joinpath("snapshot.js").read_text(encoding="utf-8")


@dataclass
class Node:
    id: int
    parent: int
    tag: str
    attrs: list[list[str]]
    children: list[int | str]
    shown: bool
    rect: list[int]
    cursor: str
    value: str | None
    checked: bool | None
    outer: str

    def attr(self, name: str) -> str | None:
        for key, value in self.attrs:
            if key == name:
                return value
        return None


@dataclass
class AXNode:
    role: str
    name: str
    owner: int | None  # stamp of the element (or of a text node's parent element)
    is_text_node: bool
    ignored: bool
    props: dict[str, Any]
    children: list[int]  # indices into Snapshot.ax


@dataclass
class Snapshot:
    utterance: str
    nodes: dict[int, Node]
    roots: list[int]
    raw_html: str
    ax: list[AXNode]
    ax_root: int
    clickable: set[int] = field(default_factory=set)

    # ---- derived views -------------------------------------------------------------------

    @cached_property
    def visible(self) -> set[int]:
        """Stamps of elements a user could see: shown, and with area or a visible child."""
        out: set[int] = set()

        def walk(nid: int) -> bool:
            node = self.nodes[nid]
            child_visible = False
            for child in node.children:
                if isinstance(child, int) and walk(child):
                    child_visible = True
            has_area = node.rect[2] > 0 and node.rect[3] > 0
            ok = node.shown and (has_area or child_visible)
            if ok:
                out.add(nid)
            return ok

        for root in self.roots:
            walk(root)
        # A closed <select>'s options have no box and fail checkVisibility, yet they are real
        # choices: they count as visible exactly when their <select> is.
        for node in self.nodes.values():
            if node.tag in ("option", "optgroup"):
                select = node.parent
                while select != -1 and self.nodes[select].tag != "select":
                    select = self.nodes[select].parent
                if select in out:
                    out.add(node.id)
                else:
                    out.discard(node.id)
        return out

    def is_within(self, nid: int, ancestor: int) -> bool:
        """True when ``nid`` is ``ancestor`` or lies inside it."""
        while nid != -1:
            if nid == ancestor:
                return True
            nid = self.nodes[nid].parent
        return False

    def visible_text(self, nid: int) -> str:
        """Text under an element that sits in visible elements, whitespace collapsed."""
        parts: list[str] = []
        visible = self.visible

        def walk(i: int) -> None:
            for child in self.nodes[i].children:
                if isinstance(child, str):
                    parts.append(child)
                elif child in visible:
                    walk(child)

        if nid in visible:
            walk(nid)
        return " ".join(" ".join(parts).split())

    # ---- serialisation -------------------------------------------------------------------

    def to_json(self) -> str:
        data = {
            "utterance": self.utterance,
            "nodes": [asdict(n) for n in self.nodes.values()],
            "roots": self.roots,
            "raw_html": self.raw_html,
            "ax": [asdict(a) for a in self.ax],
            "ax_root": self.ax_root,
            "clickable": sorted(self.clickable),
        }
        return json.dumps(data)

    @classmethod
    def from_json(cls, text: str) -> Snapshot:
        data = json.loads(text)
        nodes = {n["id"]: Node(**n) for n in data["nodes"]}
        return cls(
            utterance=data["utterance"],
            nodes=nodes,
            roots=data["roots"],
            raw_html=data["raw_html"],
            ax=[AXNode(**a) for a in data["ax"]],
            ax_root=data["ax_root"],
            clickable=set(data["clickable"]),
        )


# ---- capture ---------------------------------------------------------------------------


def _backend_to_stamp(document: dict[str, Any]) -> tuple[dict[int, int], set[int]]:
    """Map every backend node id to the stamp of its element (text nodes: their parent's)."""
    stamps: dict[int, int] = {}
    text_nodes: set[int] = set()

    def walk(node: dict[str, Any], parent_stamp: int | None) -> None:
        stamp: int | None = None
        if node.get("nodeType") == 1:
            attrs = node.get("attributes", [])
            for k, v in zip(attrs[::2], attrs[1::2], strict=True):
                if k == "data-ba-id":
                    stamp = int(v)
            if stamp is not None:
                stamps[node["backendNodeId"]] = stamp
        elif node.get("nodeType") == 3 and parent_stamp is not None:
            stamps[node["backendNodeId"]] = parent_stamp
            text_nodes.add(node["backendNodeId"])
        for child in node.get("children", []):
            walk(child, stamp)

    walk(document["root"], None)
    return stamps, text_nodes


_AX_PROPS = {
    "checked",
    "selected",
    "expanded",
    "disabled",
    "pressed",
    "level",
    "multiline",
    "multiselectable",
}


def _ax_nodes(raw: list[dict[str, Any]], stamps: dict[int, int], text_nodes: set[int]):
    index = {n["nodeId"]: i for i, n in enumerate(raw)}
    out: list[AXNode] = []
    for n in raw:
        backend = n.get("backendDOMNodeId")
        props: dict[str, Any] = {}
        for p in n.get("properties", []):
            if p["name"] in _AX_PROPS:
                props[p["name"]] = p["value"].get("value")
        if "value" in n and n["value"].get("value") not in (None, ""):
            props["value"] = n["value"]["value"]
        out.append(
            AXNode(
                role=n.get("role", {}).get("value", ""),
                name=str(n.get("name", {}).get("value", "") or ""),
                owner=stamps.get(backend) if backend is not None else None,
                is_text_node=backend in text_nodes,
                ignored=bool(n.get("ignored")),
                props=props,
                children=[index[c] for c in n.get("childIds", []) if c in index],
            )
        )
    root = next(i for i, n in enumerate(raw) if n.get("role", {}).get("value") == "RootWebArea")
    return out, root


def _clickable(snap: dict[str, Any], stamps: dict[int, int]) -> set[int]:
    doc = snap["documents"][0]["nodes"]
    backend = doc["backendNodeId"]
    return {
        stamps[backend[i]]
        for i in doc.get("isClickable", {}).get("index", [])
        if backend[i] in stamps
    }


def capture(page: Page, cdp: CDPSession) -> Snapshot:
    walked = page.evaluate(_WALK_JS, list(EXCLUDED_IDS))
    utterance = page.evaluate(
        "(() => { const u = core.getUtterance();"
        " return typeof u === 'string' ? u : u.utterance; })()"
    )
    document = cdp.send("DOM.getDocument", {"depth": -1})
    stamps, text_nodes = _backend_to_stamp(document)
    ax, ax_root = _ax_nodes(cdp.send("Accessibility.getFullAXTree")["nodes"], stamps, text_nodes)
    dom_snap = cdp.send("DOMSnapshot.captureSnapshot", {"computedStyles": []})
    nodes = {n["id"]: Node(**n) for n in walked["nodes"]}
    return Snapshot(
        utterance=utterance,
        nodes=nodes,
        roots=walked["roots"],
        raw_html=walked["raw_html"],
        ax=ax,
        ax_root=ax_root,
        clickable=_clickable(dom_snap, stamps),
    )
