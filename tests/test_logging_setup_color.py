import ctypes
import logging

import pytest

from engine.config import logging_setup as ls


class _FakeStdout:
    """Stdout stand-in whose isatty() returns a fixed value."""

    def __init__(self, isatty_value):
        self._isatty = isatty_value

    def isatty(self):
        return self._isatty


def test_supports_color_false_when_not_a_tty(monkeypatch):
    """A non-tty stdout short-circuits to no color regardless of env/platform."""
    monkeypatch.setattr(ls.sys, "stdout", _FakeStdout(False))
    monkeypatch.setattr(ls.os, "environ", {}, raising=True)
    monkeypatch.setattr(ls.sys, "platform", "linux")
    assert ls._supports_color() is False


def test_supports_color_false_when_no_color_env_set(monkeypatch):
    """An exported NO_COLOR disables color even on an interactive tty."""
    monkeypatch.setattr(ls.sys, "stdout", _FakeStdout(True))
    monkeypatch.setattr(ls.os, "environ", {"NO_COLOR": "1"}, raising=True)
    monkeypatch.setattr(ls.sys, "platform", "linux")
    assert ls._supports_color() is False


def test_supports_color_true_on_posix_tty(monkeypatch):
    """A posix interactive tty with no NO_COLOR yields color support."""
    monkeypatch.setattr(ls.sys, "stdout", _FakeStdout(True))
    monkeypatch.setattr(ls.os, "environ", {}, raising=True)
    monkeypatch.setattr(ls.sys, "platform", "linux")
    assert ls._supports_color() is True


class _FakeKernel32:
    """Records GetStdHandle/SetConsoleMode calls for the win32 path."""

    def __init__(self):
        self.std_handle_args = []
        self.console_mode_args = []

    def GetStdHandle(self, n):
        self.std_handle_args.append(n)
        return 4242

    def SetConsoleMode(self, handle, mode):
        self.console_mode_args.append((handle, mode))
        return 1


class _FakeWindll:
    def __init__(self, kernel32):
        self.kernel32 = kernel32


def test_supports_color_true_on_win32_enables_vt_mode(monkeypatch):
    """The win32 branch flips the console into VT mode and returns True."""
    monkeypatch.setattr(ls.sys, "stdout", _FakeStdout(True))
    monkeypatch.setattr(ls.os, "environ", {}, raising=True)
    monkeypatch.setattr(ls.sys, "platform", "win32")

    kernel32 = _FakeKernel32()
    monkeypatch.setattr(ctypes, "windll", _FakeWindll(kernel32), raising=False)

    assert ls._supports_color() is True
    assert kernel32.std_handle_args == [-11]
    assert kernel32.console_mode_args == [(4242, 7)]


def test_supports_color_win32_swallows_exception_returns_false(monkeypatch):
    """If the win32 console call raises, the except branch returns False."""
    monkeypatch.setattr(ls.sys, "stdout", _FakeStdout(True))
    monkeypatch.setattr(ls.os, "environ", {}, raising=True)
    monkeypatch.setattr(ls.sys, "platform", "win32")

    class _BoomWindll:
        @property
        def kernel32(self):
            raise OSError("no console")

    monkeypatch.setattr(ctypes, "windll", _BoomWindll(), raising=False)

    assert ls._supports_color() is False


class _RecordingStream:
    """Stream whose reconfigure records its kwargs."""

    def __init__(self):
        self.calls = []

    def reconfigure(self, **kwargs):
        self.calls.append(kwargs)


class _RaisingStream:
    """Stream whose reconfigure raises a swallowed error type."""

    def __init__(self, exc):
        self._exc = exc
        self.calls = 0

    def reconfigure(self, **kwargs):
        self.calls += 1
        raise self._exc


def test_ensure_utf8_stdio_reconfigures_present_streams(monkeypatch):
    """Both non-None streams get reconfigure(encoding=utf-8, errors=replace)."""
    out = _RecordingStream()
    err = _RecordingStream()
    monkeypatch.setattr(ls.sys, "stdout", out)
    monkeypatch.setattr(ls.sys, "stderr", err)

    ls._ensure_utf8_stdio()

    assert out.calls == [{"encoding": "utf-8", "errors": "replace"}]
    assert err.calls == [{"encoding": "utf-8", "errors": "replace"}]


def test_ensure_utf8_stdio_skips_none_stream(monkeypatch):
    """A None stream is skipped via continue and the other is still reconfigured."""
    err = _RecordingStream()
    monkeypatch.setattr(ls.sys, "stdout", None)
    monkeypatch.setattr(ls.sys, "stderr", err)

    ls._ensure_utf8_stdio()

    assert err.calls == [{"encoding": "utf-8", "errors": "replace"}]


@pytest.mark.parametrize("exc", [AttributeError("x"), ValueError("x"), OSError("x")])
def test_ensure_utf8_stdio_swallows_reconfigure_errors(monkeypatch, exc):
    """Reconfigure raising a handled error type is swallowed, no propagation."""
    out = _RaisingStream(exc)
    monkeypatch.setattr(ls.sys, "stdout", out)
    monkeypatch.setattr(ls.sys, "stderr", None)

    ls._ensure_utf8_stdio()

    assert out.calls == 1


def _make_record(name="engine.scraping.scan", level=logging.INFO, msg="hello", exc_info=None):
    return logging.LogRecord(
        name=name,
        level=level,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=(),
        exc_info=exc_info,
    )


def test_format_appends_exception_text():
    """When exc_info is set, the formatted exception is appended after the message."""
    formatter = ls.CleanFormatter()
    try:
        raise ValueError("kaboom")
    except ValueError:
        import sys as _sys

        exc_info = _sys.exc_info()
    record = _make_record(level=logging.ERROR, msg="boom happened", exc_info=exc_info)

    out = formatter.format(record)

    assert "boom happened" in out
    assert "ValueError: kaboom" in out
    assert "Traceback" in out


def test_format_uses_fallback_symbol_for_unknown_level():
    """A level name absent from _LEVEL_STYLES uses the bullet fallback and ljust label."""
    custom_level = 42
    logging.addLevelName(custom_level, "ZZZ")
    record = _make_record(level=custom_level, msg="weird")

    out = ls.CleanFormatter().format(record)

    assert "•" in out
    assert "ZZZ".ljust(5) in out
    assert "weird" in out


def test_format_known_level_uses_mapped_symbol_and_label():
    """A mapped level uses its configured symbol and padded label, not the fallback."""
    record = _make_record(level=logging.ERROR, msg="oops")
    color, sym, label = ls._LEVEL_STYLES["ERROR"]

    out = ls.CleanFormatter().format(record)

    assert sym in out
    assert label in out
    assert "•" not in out
    assert "oops" in out


def test_format_shortens_dotted_logger_name():
    """The formatted line carries only the truncated/padded last logger segment."""
    record = _make_record(name="engine.config.logging_setup", msg="x")

    out = ls.CleanFormatter().format(record)

    assert ls._shorten_name("engine.config.logging_setup") in out


def test_shorten_name_exact_width_segment_not_truncated():
    """A segment exactly equal to width is padded but never ellipsized."""
    out = ls._shorten_name("abcdef", width=6)
    assert out == "abcdef"
    assert "…" not in out
