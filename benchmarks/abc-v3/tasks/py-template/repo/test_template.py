import pytest
from template import render


def test_simple():
    assert render("Hi {{ name }}!", {"name": "Ann"}) == "Hi Ann!"


def test_dotted_path_and_list_index():
    assert render("{{ user.tags.1 }}", {"user": {"tags": ["a", "b"]}}) == "b"


def test_html_escaped_by_default_and_raw():
    assert render("{{ x }}|{{ x|raw }}", {"x": "<b>"}) == "&lt;b&gt;|<b>"


def test_missing_raises_keyerror_with_path():
    with pytest.raises(KeyError) as e:
        render("{{ a.b }}", {"a": {}})
    assert e.value.args == ("a.b",)


def test_unknown_filter():
    with pytest.raises(ValueError):
        render("{{ x|shout }}", {"x": 1})
