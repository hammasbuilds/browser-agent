from conftest import load_snapshot

from browser_agent.encoders import ENCODERS, clean_dom, encode_all, looks_interactive, som
from browser_agent.snapshot import Node, Snapshot


def node(nid, parent, tag, children=(), attrs=(), shown=True, rect=(0, 0, 10, 10), **kw):
    return Node(
        id=nid,
        parent=parent,
        tag=tag,
        attrs=[list(a) for a in attrs],
        children=list(children),
        shown=shown,
        rect=list(rect),
        cursor=kw.get("cursor", "auto"),
        value=kw.get("value"),
        checked=kw.get("checked"),
        outer=kw.get("outer", f"<{tag}></{tag}>"),
    )


def snap_of(*nodes, roots=(1,)):
    return Snapshot("", {n.id: n for n in nodes}, list(roots), "<body></body>", [], 0)


def test_every_encoder_runs_on_real_pages_and_indices_all_resolve_to_page_elements():
    for name in ("click-color-0", "login-user-0", "choose-list-0", "click-checkboxes-1"):
        snap = load_snapshot(name)
        encs = encode_all(snap)
        assert set(encs) == set(ENCODERS)
        assert encs["raw_html"].handles == set()
        for enc in encs.values():
            assert enc.handles <= set(snap.nodes), (name, enc.name)


def test_indexing_every_element_can_make_clean_dom_longer_than_raw_html():
    # choose-list: a bare <select> whose options gain an i=N each. Not a bug; a cost.
    encs = encode_all(load_snapshot("choose-list-0"))
    assert len(encs["clean_dom"].text) > len(encs["raw_html"].text)


def test_raw_html_keeps_the_colour_that_every_cleaner_throws_away():
    encs = encode_all(load_snapshot("click-color-0"))
    assert 'data-color="white"' in encs["raw_html"].text
    for name in ("clean_dom", "axtree", "som", "som_listeners"):
        assert "white" not in encs[name].text, name


def test_colour_boxes_are_click_targets_only_chrome_knows_about():
    snap = load_snapshot("click-color-0")
    boxes = [n for n in snap.nodes.values() if n.attr("class") == "color"]
    assert len(boxes) == 4
    assert not any(looks_interactive(snap, b) for b in boxes)
    assert all(b.id in snap.clickable for b in boxes)
    listed = encode_all(snap)["som_listeners"].handles
    assert {b.id for b in boxes} <= listed


def test_unassociated_labels_leave_textboxes_nameless_in_the_accessibility_tree():
    ax = encode_all(load_snapshot("login-user-0"))["axtree"].text
    assert '- text "Username"' in ax
    assert "- textbox [" in ax and 'textbox "' not in ax


def test_closed_select_options_count_as_visible_choices():
    snap = load_snapshot("choose-list-0")
    options = [n.id for n in snap.nodes.values() if n.tag == "option"]
    assert options and set(options) <= snap.visible
    assert "Somalia" in clean_dom(snap).text and "Somalia" in som(snap).text


def test_clean_dom_prunes_invisible_and_empty_elements_and_unwraps_bare_wrappers():
    snap = snap_of(
        node(1, -1, "div", [2, 4, 5]),
        node(2, 1, "div", [3]),  # bare wrapper around a button: unwrapped
        node(3, 2, "button", ["Go"]),
        node(4, 1, "span", ["secret"], shown=False),
        node(5, 1, "div", []),  # empty, attribute-less: pruned
    )
    text = clean_dom(snap).text
    assert text == "<button i=3>Go</button>"
    assert [f.owner for f in clean_dom(snap).fragments] == [3]


def test_clean_dom_keeps_live_form_state_not_the_stale_attribute():
    snap = snap_of(
        node(1, -1, "form", [2, 3]),
        node(2, 1, "input", attrs=[("id", "q"), ("value", "old")], value="typed"),
        node(3, 1, "input", attrs=[("type", "checkbox")], checked=True),
    )
    text = clean_dom(snap).text
    assert 'value="typed"' in text and "old" not in text
    assert "checked" in text


def test_som_lists_where_a_pointer_cursor_starts_not_every_inheriting_child():
    snap = snap_of(
        node(1, -1, "div", [2]),
        node(2, 1, "div", [3, "Open"], cursor="pointer"),
        node(3, 2, "span", ["icon"], cursor="pointer"),
    )
    assert som(snap).handles == {2}


def test_som_truncates_long_text_and_writes_void_tags_without_a_closer():
    snap = snap_of(
        node(1, -1, "div", [2, 3]),
        node(2, 1, "button", ["x" * 300]),
        node(3, 1, "input", attrs=[("type", "text")]),
    )
    lines = som(snap).text.splitlines()
    assert lines[0].endswith("...</button>") and len(lines[0]) < 130
    assert lines[1] == '[3]<input type="text">'
