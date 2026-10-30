import pytest
from template import render


def test_quotes_escaped_and_no_double_escape():
    assert render("{{ x }}", {"x": "a&b \"c\" 'd' <e>"}) == "a&amp;b &quot;c&quot; &#x27;d&#x27; &lt;e&gt;"
    assert render("{{ x }}", {"x": "&lt;"}) == "&amp;lt;"


def test_none_and_bool_text():
    assert render("[{{ n }}][{{ t }}][{{ f }}][{{ z }}]", {"n": None, "t": True, "f": False, "z": 0}) == "[][true][false][0]"


def test_escaped_open_braces_are_literal_and_not_placeholders():
    assert render("\\{{ x }} {{ x }}", {"x": 1}) == "{{ x }} 1"
    assert render("a\\b {{ x }}", {"x": 1}) == "a\\b 1"
    assert render("\\{{", {}) == "{{"


def test_values_are_not_rescanned():
    assert render("{{ a }}", {"a": "{{ b }}", "b": "X"}) == "{{ b }}"
    assert render("{{ a|raw }}", {"a": "{{ b }}", "b": "X"}) == "{{ b }}"


def test_lookup_failures_report_full_path():
    for tpl, ctx in (("{{ a.b.c }}", {"a": {"b": 1}}), ("{{ l.5 }}", {"l": [1]}), ("{{ s.0 }}", {"s": "str"}),
                     ("{{ d.1 }}", {"d": {"x": 1}}), ("{{ missing }}", {})):
        with pytest.raises(KeyError) as e:
            render(tpl, ctx)
        assert e.value.args == (tpl[3:-3].strip(),)


def test_digit_keys_in_dicts_are_ordinary_keys():
    assert render("{{ d.1 }}", {"d": {"1": "one"}}) == "one"


@pytest.mark.parametrize("tpl", ["{{ }}", "{{ a..b }}", "{{ a. }}", "{{ a-b }}", "{{ a|upper }}", "{{ a|raw|raw }}", "{{ a b }}", "oops {{ a"])
def test_malformed_raises_value_error(tpl):
    with pytest.raises(ValueError):
        render(tpl, {"a": 1})


def test_whitespace_around_path_and_filter_and_plain_text_unchanged():
    assert render("  {{   a.b | raw  }}\n\t}} {", {"a": {"b": "<"}}) == "  <\n\t}} {"
