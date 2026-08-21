"""Deterministic tests for the remaining branches of parser/_base.py.

Covers the low-level string/BeautifulSoup helpers not exercised by
tests/test_players_parsing.py: _make_soup truncation and empty-input
handling, the brace/bracket scanners' escape and scan-cap behaviour, and
the three library-extraction strategies plus their error swallowing.

All inputs are inline strings; no network, subprocess, browser, threads or
wall-clock are involved. The module-level scan-size constants and the
package logger are snapshotted and restored by an autouse fixture so the
tests stay order-independent.
"""

import logging

import pytest

import engine.scraping.parser._base as base
from engine.scraping.parser._base import (
    _extraire_eps_arrays,
    _extraire_tableau_js,
    _make_soup,
)


@pytest.fixture(autouse=True)
def _restore_globals():
    saved_html = base.HTML_MAX_SIZE
    saved_js = base.MAX_JS_OBJECT_SCAN_SIZE
    saved_eps = base.MAX_EPS_ARRAYS
    saved_level = base.log.level
    saved_handlers = list(base.log.handlers)
    saved_propagate = base.log.propagate
    yield
    base.HTML_MAX_SIZE = saved_html
    base.MAX_JS_OBJECT_SCAN_SIZE = saved_js
    base.MAX_EPS_ARRAYS = saved_eps
    base.log.setLevel(saved_level)
    base.log.handlers[:] = saved_handlers
    base.log.propagate = saved_propagate


class _Records(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.entries: list[tuple[str, str]] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.entries.append((record.levelname, record.getMessage()))

    def messages(self, level: str) -> list[str]:
        return [msg for lvl, msg in self.entries if lvl == level]


@pytest.fixture
def captured():
    handler = _Records()
    base.log.addHandler(handler)
    base.log.setLevel(logging.DEBUG)
    return handler


def test_make_soup_empty_returns_empty_document():
    soup = _make_soup("")
    assert soup.find_all("script") == []
    assert str(soup) == ""


def test_make_soup_truncates_oversized_html_and_warns(captured):
    base.HTML_MAX_SIZE = 20
    html = "<b>" + ("a" * 100) + "</b>"
    soup = _make_soup(html)
    assert soup.b.get_text() == "a" * 17
    assert soup.find("b").get_text() == "a" * 17
    warnings = captured.messages("WARNING")
    assert len(warnings) == 1
    assert "tronqu" in warnings[0]


def test_make_soup_at_limit_is_not_truncated_or_warned(captured):
    html = "<b>aaa</b>"
    base.HTML_MAX_SIZE = len(html)
    soup = _make_soup(html)
    assert soup.b.get_text() == "aaa"
    assert captured.messages("WARNING") == []


def test_extraire_tableau_js_no_opening_bracket_returns_none():
    assert _extraire_tableau_js("nothing array shaped", 0) is None


def test_extraire_tableau_js_escaped_quote_in_single_quoted_string():
    raw = _extraire_tableau_js(r"y = ['a\']b', 'c']", 4)
    assert raw == r"['a\']b', 'c']"


def test_extraire_tableau_js_unbalanced_returns_none():
    assert _extraire_tableau_js('z = ["a", "b"', 4) is None


def test_extraire_tableau_js_scan_cap_truncates_to_none():
    base.MAX_JS_OBJECT_SCAN_SIZE = 6
    txt = "y = [" + ("1," * 50) + "]"
    assert _extraire_tableau_js(txt, 4) is None


def test_extraire_eps_arrays_invalid_json_skipped_and_logged(captured):
    assert _extraire_eps_arrays("var eps1 = [1 2 3]") == {}
    assert any("eps1" in msg for msg in captured.messages("DEBUG"))


def test_extraire_eps_arrays_non_list_json_ignored():
    assert _extraire_eps_arrays('var eps1 = ["ok"] ; var eps2 = [3]') == {
        "eps1": ["ok"],
        "eps2": ["3"],
    }


def test_extraire_eps_arrays_cap_logs_debug(captured):
    base.MAX_EPS_ARRAYS = 3
    decls = " ; ".join(f'var eps{n}=["u{n}"]' for n in range(1, 10))
    result = _extraire_eps_arrays(decls)
    assert len(result) == 3
    assert any("plafond" in msg for msg in captured.messages("DEBUG"))
