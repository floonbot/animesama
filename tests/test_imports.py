import importlib

import pytest

MODULES = [
    "engine.config.settings",
    "engine.config.logging_setup",
    "engine.domain.exceptions",
    "engine.utils.security",
    "engine.utils.aio",
    "engine.utils.circuit_breaker",
    "engine.cache.covers",
    "engine.download._patterns",
    "engine.download._rate_limiter",
    "engine.download._domain_strategy",
    "engine.download._host_breakers",
    "engine.download.queue",
    "engine.download._runtime",
    "engine.download.pipeline",
    "engine.download.interceptor",
    "engine.download.methods._proc_registry",
    "engine.download.methods.ffmpeg_engine",
    "engine.download.methods.nm3u8dl",
    "engine.download.methods.ytdlp_engine",
    "engine.download.worker",
    "engine.scraping.site.animessama",
    "engine.scraping.http_client",
    "engine.download._helpers",
    "engine.download._engine_utils",
    "engine.download.methods._nm3u8dl_parsing",
    "engine.download.methods._ytdlp_parsing",
    "engine.download.methods._ffmpeg_parsing",
    "engine.scraping._cache",
    "engine.scraping.favorites",
    "engine.scraping.episodes",
    "engine.scraping.players",
    "engine.scraping.search",
    "engine.scraping.parser",
    "engine.scraping.parser._base",
    "engine.scraping.parser.profile",
    "engine.scraping.parser.episodes",
    "engine.scraping.parser.players",
    "engine.scraping.parser.search",
    "engine.scraping.parser.naming",
    "engine.scraping.scraper",
    "engine.services.download_service",
    "web.api.models",
    "web.api.routes.sse",
    "web.api.routes.auth",
    "web.api.routes.download",
    "web.api.routes.settings",
    "web.api.routes.health",
    "web.api.routes.anime",
    "web.api.routes.anime.scraping",
    "web.api.routes.anime.library",
    "web.api.routes.anime.updates",
    "web.api.routes.anime.files",
    "web.api.routes.anime.covers",
    "engine.library.scanner",
    "engine.cache.ttl_cache",
    "engine.observability.metrics",
    "engine.library.updates",
    "web.api.app",
]

@pytest.mark.parametrize("module", MODULES)
def test_module_imports(module):
    importlib.import_module(module)

def test_scraper_public_api_intact():
    s = importlib.import_module("engine.scraping.scraper")
    for name in (
        "get_favorites_async",
        "get_episodes_async",
        "get_lecteurs_async",
        "search_async",
        "invalidate_fav_cache",
        "invalidate_ep_cache",
        "detecter_types_favoris_async",
        "clear_session_cache",
    ):
        assert hasattr(s, name), name

def test_create_app_builds():
    from web.api.app import create_app

    app = create_app()
    assert len(app.routes) > 0
