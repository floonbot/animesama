import logging

import pytest

from engine.config import logging_setup as ls


@pytest.fixture(autouse=True)
def _restore_logging_global_state():
    root = logging.getLogger()
    root_handlers = list(root.handlers)
    root_level = root.level

    asyncio_logger = logging.getLogger("asyncio")
    asyncio_filters = list(asyncio_logger.filters)
    asyncio_level = asyncio_logger.level

    quiet_levels = {name: logging.getLogger(name).level for name in ls._QUIET_MODULES}

    yield

    root.handlers[:] = root_handlers
    root.setLevel(root_level)

    asyncio_logger.filters[:] = asyncio_filters
    asyncio_logger.setLevel(asyncio_level)

    for name, lvl in quiet_levels.items():
        logging.getLogger(name).setLevel(lvl)


def _stream_handlers(logger):
    return [h for h in logger.handlers if isinstance(h, logging.StreamHandler)]


def _noise_filters(target):
    return [f for f in target.filters if isinstance(f, ls._AsyncioNoiseFilter)]


def test_setup_logging_installs_single_clean_streamhandler_at_level():
    ls.setup_logging(logging.DEBUG)

    root = logging.getLogger()
    handlers = _stream_handlers(root)
    assert len(handlers) == 1
    assert isinstance(handlers[0].formatter, ls.CleanFormatter)
    assert root.level == logging.DEBUG


def test_setup_logging_quiets_each_quiet_module_to_warning():
    ls.setup_logging(logging.DEBUG)

    for name in ls._QUIET_MODULES:
        assert logging.getLogger(name).level == logging.WARNING


def test_setup_logging_adds_one_noise_filter_to_asyncio_and_handler():
    ls.setup_logging(logging.INFO)

    asyncio_logger = logging.getLogger("asyncio")
    assert len(_noise_filters(asyncio_logger)) == 1

    handler = _stream_handlers(logging.getLogger())[0]
    assert len(_noise_filters(handler)) == 1


def test_setup_logging_replaces_prior_root_handlers():
    sentinel = logging.NullHandler()
    root = logging.getLogger()
    root.handlers[:] = [sentinel]

    ls.setup_logging(logging.INFO)

    assert sentinel not in root.handlers
    assert len(_stream_handlers(root)) == 1


def test_setup_logging_is_idempotent_no_filter_or_handler_duplication():
    ls.setup_logging(logging.INFO)
    ls.setup_logging(logging.WARNING)

    root = logging.getLogger()
    assert len(_stream_handlers(root)) == 1
    assert root.level == logging.WARNING

    asyncio_logger = logging.getLogger("asyncio")
    assert len(_noise_filters(asyncio_logger)) == 1


def test_clean_formatter_scrubs_signed_url():
    rec = logging.LogRecord(
        "x", logging.INFO, __file__, 1, "u https://h/v.m3u8?token=SECRETCF", None, None
    )
    out = ls.CleanFormatter().format(rec)
    assert "SECRETCF" not in out
    assert "https://h/v.m3u8" in out


def test_setup_logging_attaches_log_ring():
    from engine.observability.log_ring import log_ring

    ls.setup_logging(logging.INFO)
    assert log_ring in logging.getLogger().handlers


def test_setup_logging_log_ring_not_duplicated():
    from engine.observability.log_ring import log_ring

    ls.setup_logging(logging.INFO)
    ls.setup_logging(logging.WARNING)
    assert logging.getLogger().handlers.count(log_ring) == 1


def test_banner_outputs_title_subtitle_url_and_hint(capsys):
    ls.banner("My App", url="http://x", subtitle="sub")
    out = capsys.readouterr().out
    assert "My App" in out
    assert "http://x" in out
    assert "sub" in out
    assert "Ctrl+C" in out


def test_banner_omits_optional_lines_when_empty(capsys):
    ls.banner("Solo")
    out = capsys.readouterr().out
    assert "Solo" in out
    assert "→" not in out


def test_section_prints_marker_and_title(capsys):
    ls.section("Phase 1")
    out = capsys.readouterr().out
    assert "▸ Phase 1" in out


def test_step_prints_text(capsys):
    ls.step("do it")
    out = capsys.readouterr().out
    assert "do it" in out


def test_summary_reports_counts_and_duration(capsys):
    ls.summary(title="Anime", succes=3, echoues=1, skipped=2, duration=125)
    out = capsys.readouterr().out
    assert "Résumé : Anime" in out
    assert "Succès  : 3" in out
    assert "Échecs  : 1" in out
    assert "Ignorés : 2" in out
    assert "Durée : 2m05s" in out


def test_summary_all_zero_reports_no_episode(capsys):
    ls.summary(title="Empty")
    out = capsys.readouterr().out
    assert "(aucun épisode traité)" in out
    assert "Durée" not in out


def test_summary_omits_zero_categories(capsys):
    ls.summary(title="Partial", succes=2)
    out = capsys.readouterr().out
    assert "Succès  : 2" in out
    assert "Échecs" not in out
    assert "Ignorés" not in out
    assert "(aucun épisode traité)" not in out
