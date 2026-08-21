import logging
import sys

from engine.config import logging_setup as ls


def _record_with_exc(msg: str, exc: BaseException) -> logging.LogRecord:
    try:
        raise exc
    except BaseException:
        ei = sys.exc_info()
    return logging.LogRecord("x", logging.ERROR, __file__, 1, msg, None, ei)


def test_clean_formatter_redacts_signed_url_in_exception_traceback():
    exc = RuntimeError("echec https://host/v.m3u8?token=SECRETLEAK1234")
    rec = _record_with_exc("boom", exc)

    out = ls.CleanFormatter().format(rec)

    assert "SECRETLEAK1234" not in out
    assert "https://host/v.m3u8" in out
    assert "Traceback" in out
    assert "boom" in out


def test_clean_formatter_exception_without_url_is_unchanged():
    rec = _record_with_exc("boom happened", ValueError("kaboom"))

    out = ls.CleanFormatter().format(rec)

    assert "ValueError: kaboom" in out
    assert "Traceback" in out
