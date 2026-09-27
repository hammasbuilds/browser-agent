from conftest import load_snapshot
from test_encoders import node, snap_of

from browser_agent.encoders import Encoding, Fragment, encode_all
from browser_agent.survival import activators, check, need_source, normalise


def by_text(snap, tag, text):
    (hit,) = [n.id for n in snap.nodes.values() if n.tag == tag and snap.visible_text(n.id) == text]
    return hit


def test_colour_target_survives_only_in_raw_html_and_only_as_present_in_listener_som():
    snap = load_snapshot("click-color-0")
    (white,) = [n.id for n in snap.nodes.values() if n.attr("data-color") == "white"]
    got = {k: check(e, snap, white, ("white",)) for k, e in encode_all(snap).items()}
    assert got["raw_html"].identifiable
    assert not got["raw_html"].actionable  # no id: only a structural selector reaches it
    assert got["som_listeners"].present and got["som_listeners"].actionable
    assert not got["som_listeners"].identifiable
    for name in ("clean_dom", "axtree", "som"):
        assert not got[name].present, name


def test_a_wrapping_label_counts_as_part_of_its_checkbox():
    snap = load_snapshot("click-checkboxes-1")
    box = next(n.id for n in snap.nodes.values() if n.attr("type") == "checkbox")
    label = snap.nodes[box].parent
    assert snap.nodes[label].tag == "label"
    assert label in activators(snap, box)
    name = snap.visible_text(label)
    for enc_name, enc in encode_all(snap).items():
        assert check(enc, snap, box, (name,)).identifiable, enc_name


def test_label_for_attribute_binds_like_a_wrapping_label():
    snap = snap_of(
        node(1, -1, "div", [2, 3]),
        node(2, 1, "label", ["Email"], attrs=[("for", "e")]),
        node(3, 1, "input", attrs=[("id", "e")]),
    )
    assert activators(snap, 3) == {2, 3}


def test_unlabelled_password_box_is_present_but_not_identifiable_in_the_ax_tree():
    snap = load_snapshot("login-user-0")
    (pw,) = [n.id for n in snap.nodes.values() if n.attr("id") == "password"]
    encs = encode_all(snap)
    ax = check(encs["axtree"], snap, pw, ("password",))
    assert ax.present and ax.actionable and not ax.identifiable
    assert check(encs["clean_dom"], snap, pw, ("password",)).identifiable
    assert check(encs["raw_html"], snap, pw, ("password",)).actionable  # unique #password


def test_alternatives_accept_either_spelling_of_the_same_fact():
    snap = snap_of(node(1, -1, "textarea"))
    enc = Encoding(
        "axtree", "- textbox [multiline] [1]", [Fragment(1, "- textbox [multiline] [1]", 1)]
    )
    assert check(enc, snap, 1, ("textarea|multiline",)).identifiable
    assert not check(enc, snap, 1, ("textarea",)).identifiable


def test_text_next_to_the_element_does_not_count():
    snap = snap_of(node(1, -1, "div", [2, 3]), node(2, 1, "span", ["Name"]), node(3, 1, "input"))
    enc = Encoding(
        "clean_dom",
        "<span i=2>Name</span> <input i=3>",
        [Fragment(2, "<span i=2>Name</span>", 2), Fragment(3, "<input i=3>", 3)],
    )
    result = check(enc, snap, 3, ("name",))
    assert result.present and not result.identifiable


def test_normalise_folds_case_whitespace_and_entities():
    assert normalise("  Tom &amp;\n JERRY ") == "tom & jerry"


def test_clicking_inside_a_link_reaches_it():
    snap = load_snapshot("click-link-0")
    link = next(n.id for n in snap.nodes.values() if n.attr("class") == "alink")
    word = snap.visible_text(link)
    assert check(encode_all(snap)["axtree"], snap, link, (word,)).identifiable
    assert by_text(snap, "span", word) == link


def test_an_index_or_markup_never_counts_as_evidence():
    snap = load_snapshot("click-color-0")
    (white,) = [n.id for n in snap.nodes.values() if n.attr("data-color") == "white"]
    listed = encode_all(snap)["som_listeners"]
    assert f"[{white}]<div></div>" in listed.text
    assert not check(listed, snap, white, (str(white),)).identifiable
    assert not check(listed, snap, white, (">",)).identifiable
    assert check(listed, snap, white, ("div",)).identifiable  # the tag itself is content


def test_needs_match_whole_tokens_only():
    snap = snap_of(node(1, -1, "button", ["15 items"]))
    enc = Encoding("clean_dom", "", [Fragment(1, "button 15 items", 1)])
    assert check(enc, snap, 1, ("15",)).identifiable
    assert not check(enc, snap, 1, ("5",)).identifiable
    assert not check(enc, snap, 1, ("item",)).identifiable


def test_needs_are_tagged_by_where_an_agent_could_find_them():
    utterance = "Find the email by Deva and delete it."
    page = "Deva Morbi. Purus. 1h 32m"
    assert need_source("Deva", utterance, page) == "instruction"
    assert need_source("1h 32m", utterance, page) == "page"
    assert need_source("trash", utterance, page) == "markup"
    assert need_source("textarea|delete", utterance, page) == "instruction"  # any spelling
