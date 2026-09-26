import pytest

from browser_agent.actions import Action, ActionError, parse_action


def test_parses_click_by_index_given_as_int_or_bracketed_string():
    assert parse_action('{"action": "click", "target": 5}') == Action("click", 5)
    assert parse_action({"action": "click", "target": "[12]"}).target == 12


def test_keeps_a_css_selector_as_a_string():
    assert parse_action({"action": "click", "target": " #subbtn "}).target == "#subbtn"


def test_type_carries_text_and_select_accepts_one_label_or_many():
    assert parse_action({"action": "type", "target": 3, "text": "hi"}).text == "hi"
    assert parse_action({"action": "select", "target": 3, "options": "A"}).options == ("A",)
    both = parse_action({"action": "select", "target": 3, "options": ["A", "B"]})
    assert both.options == ("A", "B")


def test_scroll_defaults_and_done_needs_no_target():
    assert parse_action({"action": "scroll", "target": None}).dy == 100
    assert parse_action({"action": "done"}) == Action("done")


def test_fields_irrelevant_to_the_kind_are_dropped():
    action = parse_action({"action": "click", "target": 1, "text": "x", "dy": 9})
    assert (action.text, action.dy, action.options) == ("", 0, ())


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ("not json", "not JSON"),
        ("[1, 2]", "JSON object"),
        ({"action": "hover", "target": 1}, "unknown action"),
        ({"action": "click"}, "needs a target"),
        ({"action": "click", "target": ""}, "needs a target"),
        ({"action": "click", "target": True}, "target must be"),
        ({"action": "click", "target": 1.5}, "target must be"),
        ({"action": "type", "target": 1, "text": 5}, "string 'text'"),
        ({"action": "select", "target": 1}, "needs 'options'"),
        ({"action": "select", "target": 1, "options": [1]}, "needs 'options'"),
        ({"action": "scroll", "dy": "down"}, "integer 'dy'"),
    ],
)
def test_rejects_malformed_actions_with_a_reason(payload, message):
    with pytest.raises(ActionError, match=message):
        parse_action(payload)


def test_describe_is_readable_history():
    assert Action("type", 4, text="bob").describe() == "type 4 text='bob'"
    assert Action("select", "#o", options=("A",)).describe() == "select '#o' options=['A']"
