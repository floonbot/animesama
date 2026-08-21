"""Regression: _host_of kept a trailing dot (FQDN root label), so a URL like
'https://dood.watch./e/x' resolved to host 'dood.watch.' which matched no
registered extractor and fell through to the generic one. The trailing dot is
now stripped.
"""

from engine.download.extractor.registry import _host_of, get_extractor


def test_host_of_strips_trailing_dot_from_url():
    assert _host_of("https://dood.watch./e/xyz") == "dood.watch"


def test_host_of_strips_trailing_dot_from_bare_host():
    assert _host_of("dood.watch.") == "dood.watch"


def test_host_of_plain_url_unchanged():
    assert _host_of("https://dood.watch/e/xyz") == "dood.watch"


def test_get_extractor_resolves_trailing_dot_host():
    ext_dot = get_extractor("https://dood.watch./e/xyz")
    ext_plain = get_extractor("https://dood.watch/e/xyz")
    assert ext_dot.__class__ is ext_plain.__class__
