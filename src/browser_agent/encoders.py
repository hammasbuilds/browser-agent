"""Five ways to turn one :class:`Snapshot` into the text a model reads.

Every encoder returns an :class:`Encoding`: the text itself, plus a list of fragments saying
which element each piece of text came from and which index (if any) the action layer will
accept for it. The fragments are what make "does the target survive this encoding?" a question
with a mechanical answer instead of a judgement call.

``raw_html``       the page's ``<body>`` exactly as serialised. No indices; act by CSS selector.
``clean_dom``      visible elements only, a short attribute allow-list, empty wrappers pruned,
                   single-child wrappers unwrapped, every surviving element indexed ``i=N``.
``axtree``         Chrome's accessibility tree, rendered like Playwright's aria snapshot, every
                   element-backed line indexed ``[N]``.
``som``            set-of-marks as text: only elements that look interactive (tag, ARIA role,
                   ``onclick``/``tabindex``/``contenteditable``, or where ``cursor: pointer``
                   starts), each on one ``[N]<tag ...>text</tag>`` line. No other page text.
``som_listeners``  ``som`` plus anything Chrome reports as a click target, which catches
                   listeners attached from JavaScript (d3 ``.on``, jQuery ``.on``).
"""

from __future__ import annotations

import html
from collections.abc import Callable
from dataclasses import dataclass, field

from browser_agent.snapshot import AXNode, Node, Snapshot

KEEP_ATTRS = (
    "id",
    "name",
    "type",
    "placeholder",
    "aria-label",
    "title",
    "role",
    "href",
    "alt",
    "for",
)
VOID_TAGS = {"input", "img", "br", "hr"}
FORM_TAGS = {"input", "textarea", "select", "button", "img", "option"}
PRUNE_TAGS = {"br", "hr", "wbr"}
SOM_TEXT_LIMIT = 100


@dataclass
class Fragment:
    owner: int  # stamp of the element this text represents
    text: str
    handle: int | None  # the index an action may use to reach ``owner``


@dataclass
class Encoding:
    name: str
    text: str
    fragments: list[Fragment] = field(default_factory=list)

    @property
    def handles(self) -> set[int]:
        return {f.handle for f in self.fragments if f.handle is not None}


def _attr_text(node: Node) -> str:
    parts: list[str] = []
    for key in KEEP_ATTRS:
        value = node.attr(key)
        if value is not None:
            parts.append(f'{key}="{html.escape(value)}"' if value else key)
    if node.value:
        parts.append(f'value="{html.escape(node.value)}"')
    if node.checked:
        parts.append("selected" if node.tag == "option" else "checked")
    return " ".join(parts)


# ---- raw HTML ------------------------------------------------------------------------------


def raw_html(snap: Snapshot) -> Encoding:
    frags = [Fragment(n.id, n.outer, None) for n in snap.nodes.values()]
    return Encoding("raw_html", snap.raw_html, frags)


# ---- cleaned DOM ---------------------------------------------------------------------------


def clean_dom(snap: Snapshot) -> Encoding:
    frags: list[Fragment] = []
    visible = snap.visible

    def render(nid: int) -> str:
        node = snap.nodes[nid]
        if nid not in visible or node.tag in PRUNE_TAGS:
            return ""
        attrs = _attr_text(node)
        inner: list[str] = []
        own_text = False
        rendered_children = 0
        for child in node.children:
            if isinstance(child, str):
                if child.strip():
                    inner.append(html.escape(child.strip(), quote=False))
                    own_text = True
            else:
                out = render(child)
                if out:
                    inner.append(out)
                    rendered_children += 1
        body = " ".join(inner)
        if not attrs and not body and node.tag not in FORM_TAGS:
            return ""  # an empty, attribute-less element carries nothing a reader can use
        if not attrs and not own_text and rendered_children == 1 and node.tag not in FORM_TAGS:
            return body  # unwrap a bare single-child wrapper; clicks on the child bubble up
        head = f"{node.tag} i={nid}" + (f" {attrs}" if attrs else "")
        text = f"<{head}>" if node.tag in VOID_TAGS else f"<{head}>{body}</{node.tag}>"
        frags.append(Fragment(nid, text, nid))
        return text

    text = "\n".join(filter(None, (render(r) for r in snap.roots)))
    return Encoding("clean_dom", text, frags)


# ---- accessibility tree --------------------------------------------------------------------

TRANSPARENT_ROLES = {
    "generic",
    "none",
    "presentation",
    "LabelText",
    "paragraph",
    "Section",
    "Canvas",
    "Pre",
}
DROPPED_ROLES = {"InlineTextBox", "LineBreak"}
STATEFUL_PROPS = {"checked", "expanded", "pressed", "selected"}  # "false" is news for these


def _ax_line(node: AXNode, indent: int) -> str:
    props = []
    for key, value in node.props.items():
        if key == "value" or (value is False and key not in STATEFUL_PROPS):
            continue
        props.append(key if value is True else f"{key}={str(value).lower()}")
    head = node.role + (f' "{node.name}"' if node.name else "")
    head += "".join(f" [{p}]" for p in props)
    head += f" [{node.owner}]"
    if "value" in node.props:
        head += f": {node.props['value']}"
    return "  " * indent + "- " + head


def axtree(snap: Snapshot) -> Encoding:
    lines: list[str] = []
    frags: list[Fragment] = []

    def walk(i: int, indent: int, parent_name: str) -> None:
        node = snap.ax[i]
        if node.role in DROPPED_ROLES:
            return
        emitted = False
        name = " ".join(node.name.split())
        if node.ignored or node.owner is None:
            pass  # not exposed, or outside the task area: lift its children
        elif node.role == "StaticText":
            if name and name != parent_name:
                line = "  " * indent + f'- text "{name}" [{node.owner}]'
                lines.append(line)
                frags.append(Fragment(node.owner, line, node.owner))
            return
        elif not (node.role in TRANSPARENT_ROLES and not name):
            line = _ax_line(node, indent)
            lines.append(line)
            frags.append(Fragment(node.owner, line, node.owner))
            emitted = True
        for child in node.children:
            walk(child, indent + 1 if emitted else indent, name if emitted else parent_name)

    walk(snap.ax_root, 0, "")
    return Encoding("axtree", "\n".join(lines), frags)


# ---- set-of-marks --------------------------------------------------------------------------

INTERACTIVE_TAGS = {"a", "button", "input", "select", "textarea", "summary", "details", "label"}
INTERACTIVE_TAGS |= {"option"}
INTERACTIVE_ROLES = {
    "button",
    "link",
    "checkbox",
    "radio",
    "tab",
    "menuitem",
    "menuitemcheckbox",
    "menuitemradio",
    "option",
    "combobox",
    "textbox",
    "searchbox",
    "switch",
    "slider",
    "spinbutton",
    "treeitem",
    "listbox",
}


def looks_interactive(snap: Snapshot, node: Node) -> bool:
    """The attribute/CSS heuristic most DOM agents use (no event-listener knowledge)."""
    if node.tag in INTERACTIVE_TAGS or node.attr("role") in INTERACTIVE_ROLES:
        return True
    if node.attr("onclick") is not None or node.attr("contenteditable") in ("", "true"):
        return True
    tabindex = node.attr("tabindex")
    if tabindex is not None and tabindex.strip() != "-1":
        return True
    parent = snap.nodes.get(node.parent)
    return node.cursor == "pointer" and (parent is None or parent.cursor != "pointer")


def _som(snap: Snapshot, name: str, keep: Callable[[Node], bool]) -> Encoding:
    lines: list[str] = []
    frags: list[Fragment] = []
    visible = snap.visible
    for nid in _document_order(snap):
        node = snap.nodes[nid]
        if nid not in visible or not keep(node):
            continue
        text = snap.visible_text(nid)
        if len(text) > SOM_TEXT_LIMIT:
            text = text[: SOM_TEXT_LIMIT - 3] + "..."
        attrs = _attr_text(node)
        head = node.tag + (f" {attrs}" if attrs else "")
        if node.tag in VOID_TAGS:
            line = f"[{nid}]<{head}>"
        else:
            line = f"[{nid}]<{head}>{html.escape(text, quote=False)}</{node.tag}>"
        lines.append(line)
        frags.append(Fragment(nid, line, nid))
    return Encoding(name, "\n".join(lines), frags)


def _document_order(snap: Snapshot) -> list[int]:
    order: list[int] = []

    def walk(nid: int) -> None:
        order.append(nid)
        for child in snap.nodes[nid].children:
            if isinstance(child, int):
                walk(child)

    for root in snap.roots:
        walk(root)
    return order


def som(snap: Snapshot) -> Encoding:
    return _som(snap, "som", lambda n: looks_interactive(snap, n))


def som_listeners(snap: Snapshot) -> Encoding:
    return _som(
        snap, "som_listeners", lambda n: looks_interactive(snap, n) or n.id in snap.clickable
    )


ENCODERS: dict[str, Callable[[Snapshot], Encoding]] = {
    "raw_html": raw_html,
    "clean_dom": clean_dom,
    "axtree": axtree,
    "som": som,
    "som_listeners": som_listeners,
}


def encode_all(snap: Snapshot) -> dict[str, Encoding]:
    return {name: fn(snap) for name, fn in ENCODERS.items()}
