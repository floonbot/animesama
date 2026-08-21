import asyncio

import pytest

import engine.download.extractor.browser_extractor as be
import engine.download.extractor.registry as registry
import engine.download.interceptor as ic
from engine.download import _host_breakers as hb
from engine.download import pipeline
from engine.download.queue import CancelToken
from engine.utils.circuit_breaker import CircuitOpenError


class _FakeMetrics:
    def __init__(self, raises: bool = False) -> None:
        self.raises = raises
        self.calls: list[tuple[str, int]] = []

    def incr(self, name: str, n: int = 1) -> None:
        if self.raises:
            raise RuntimeError("metrics down")
        self.calls.append((name, n))

    def observe(self, name: str, value: float) -> None:
        if self.raises:
            raise RuntimeError("metrics down")

    def set_gauge(self, name: str, value: float) -> None:
        if self.raises:
            raise RuntimeError("metrics down")


class FakeQueue:
    def __init__(self) -> None:
        self._cancelled = CancelToken()
        self.events: list[tuple[str, dict]] = []

    def emit(self, event, data) -> None:
        self.events.append((event, data))


LECTEUR = {"src": "https://player.example/embed", "host": "player.example"}


@pytest.fixture(autouse=True)
def _reset_pipeline_globals():
    saved_cache = dict(pipeline._ext_cache)
    saved_inflight = dict(pipeline._ext_inflight)
    saved_prefetch = pipeline._PREFETCH_ENABLED
    saved_retries = pipeline.RETRIES_EFFECTIFS
    saved_delay = pipeline.DELAI_RETRY_EFFECTIF
    pipeline._ext_cache.clear()
    pipeline._ext_inflight.clear()
    yield
    pipeline._ext_cache.clear()
    pipeline._ext_cache.update(saved_cache)
    pipeline._ext_inflight.clear()
    pipeline._ext_inflight.update(saved_inflight)
    pipeline._PREFETCH_ENABLED = saved_prefetch
    pipeline.RETRIES_EFFECTIFS = saved_retries
    pipeline.DELAI_RETRY_EFFECTIF = saved_delay


@pytest.fixture(autouse=True)
def _clear_breakers():
    saved = dict(hb._breakers)
    hb._breakers.clear()
    yield
    hb._breakers.clear()
    hb._breakers.update(saved)


def _patch_metrics(monkeypatch, fake):
    import engine.observability.metrics as metrics_mod

    monkeypatch.setattr(metrics_mod, "metrics", fake)


class TestRecordMetricsExceptBranches:
    """pipeline._record_host / _record_via : l'echec de metrics.incr est avale."""

    def test_record_host_swallows_metrics_failure(self, monkeypatch):
        _patch_metrics(monkeypatch, _FakeMetrics(raises=True))
        pipeline._record_host("HOST.example", "attempt")

    def test_record_via_swallows_metrics_failure(self, monkeypatch):
        _patch_metrics(monkeypatch, _FakeMetrics(raises=True))
        pipeline._record_via("network_seq")

    def test_record_host_records_when_metrics_ok(self, monkeypatch):
        fake = _FakeMetrics()
        _patch_metrics(monkeypatch, fake)
        pipeline._record_host("Host.Example", "ok")
        assert ("host_ok_host.example", 1) in fake.calls


class TestPrefetchFinallyFutureAlreadyDone:
    """prefetch_extraction (branche 108->exit) : fut deja done dans finally → pas de set_result."""

    def test_future_already_done_is_not_set_again(self, monkeypatch):
        monkeypatch.setattr(pipeline, "_PREFETCH_ENABLED", True)

        ep_url = "https://anime-sama.to/ep?prefetch-done"
        sentinel = object()

        async def fake_sleep(_):
            inflight = pipeline._ext_inflight[ep_url]
            inflight.set_result(sentinel)
            raise RuntimeError("stop after pre-resolving the future")

        monkeypatch.setattr(pipeline.asyncio, "sleep", fake_sleep)

        async def scenario():
            await pipeline.prefetch_extraction({"url": ep_url}, FakeQueue())
            return None

        asyncio.run(scenario())

        assert ep_url not in pipeline._ext_inflight


class TestPrefetchDeadlineTimeout:
    """prefetch_extraction : la cascade Playwright depasse _PREFETCH_DEADLINE -> wait_for TimeoutError, comportement identique a un prefetch echoue (pas de cache, inflight purge)."""

    def test_pipeline_timeout_skips_cache_and_clears_inflight(self, monkeypatch):
        monkeypatch.setattr(pipeline, "_PREFETCH_ENABLED", True)

        ep_url = "https://anime-sama.to/ep?prefetch-deadline"

        async def no_sleep(_):
            return None

        monkeypatch.setattr(pipeline.asyncio, "sleep", no_sleep)

        async def lecteurs(url):
            return [LECTEUR]

        monkeypatch.setattr("engine.scraping.scraper.get_lecteurs_async", lecteurs)
        monkeypatch.setattr(pipeline, "partition_lecteurs", lambda lec: ([], list(lec)))

        async def pipeline_result(*a, **k):
            return {"url": "https://cdn/must-not-be-cached.m3u8", "headers": {}}

        monkeypatch.setattr(pipeline, "_pipeline_playwright", pipeline_result)

        async def boom_wait_for(aw, timeout=0):
            aw.close()
            raise TimeoutError()

        monkeypatch.setattr(pipeline.asyncio, "wait_for", boom_wait_for)

        asyncio.run(pipeline.prefetch_extraction({"url": ep_url}, FakeQueue()))

        assert ep_url not in pipeline._ext_cache
        assert ep_url not in pipeline._ext_inflight


class TestTraiterEpisodePrefetchEnabledNoCache:
    """_traiter_un_episode_impl (branche 229->254) : prefetch actif mais aucun cache → chemin normal."""

    def test_prefetch_enabled_without_cache_falls_to_normal_path(self, monkeypatch):
        monkeypatch.setattr(pipeline, "_PREFETCH_ENABLED", True)
        monkeypatch.setattr(pipeline, "_skip_existants_actif", lambda: False)
        monkeypatch.setattr(pipeline, "_fichier_existe", lambda d, n: False)

        ep_url = "https://anime-sama.to/ep?no-prefetch-cache"
        ep = {"titre": "Show", "saison": 1, "episode": 1, "langue": "", "url": ep_url}

        called = {"normal": False}

        async def get(url):
            called["normal"] = True
            return []

        monkeypatch.setattr("engine.scraping.scraper.get_lecteurs_async", get)

        async def must_not_lancer(*a, **k):
            raise AssertionError("prefetched path must not run without a cache hit")

        monkeypatch.setattr(pipeline, "_lancer_download_pipeline", must_not_lancer)

        out = asyncio.run(pipeline._traiter_un_episode(ep, 0, 1, "Show", FakeQueue()))

        assert out == "echoues"
        assert called["normal"] is True
        assert ep_url not in pipeline._ext_inflight
        assert ep_url not in pipeline._ext_cache


class TestYtdlpSurLecteursFileNoneContinues:
    """_ytdlp_sur_lecteurs (branche 319->290) : fichier None apres _run_in_pool → boucle continue."""

    def test_none_result_continues_to_next_lecteur(self, monkeypatch):
        monkeypatch.setattr("engine.utils.security.is_safe_url", lambda u: True)
        monkeypatch.setattr(pipeline, "domain_mark_used", lambda d: None)
        monkeypatch.setattr(pipeline, "host_disponible", lambda h: True)

        async def no_wait(domain):
            return None

        monkeypatch.setattr(pipeline, "domain_wait", no_wait)

        seen: list[str] = []

        async def pool(fn, src, dossier, nom_ep, headers, cancelled, on_progress):
            seen.append(src)
            return None

        monkeypatch.setattr(pipeline, "_run_in_pool", pool)

        lecteurs = [
            {"src": "https://a.example/1", "host": "a.example"},
            {"src": "https://b.example/2", "host": "b.example"},
        ]
        out = asyncio.run(
            pipeline._ytdlp_sur_lecteurs(lecteurs, "/tmp", "ep", "[x]", FakeQueue())
        )

        assert out is None
        assert seen == ["https://a.example/1", "https://b.example/2"]


class TestPipelinePlaywrightSeqLoop:
    """_pipeline_playwright_impl : chemin sequentiel via get_breaker.call."""

    def _patch_no_parallel_no_browser_extractor(self, monkeypatch):
        monkeypatch.setattr("engine.utils.security.is_safe_url", lambda u: True)
        monkeypatch.setattr(pipeline, "host_disponible", lambda h: True)

        async def par_none(lecteurs, timeout=8, on_win=None):
            return None

        monkeypatch.setattr(
            "engine.download.interceptor.intercepter_lecteurs_parallele", par_none
        )

        async def fake_extraire(src, timeout=10, mode="standard"):
            return {"best": None}

        monkeypatch.setattr(
            "engine.download.extractor.browser_extractor.extraire_flux", fake_extraire
        )

    def test_circuit_open_error_continues_seq_loop(self, monkeypatch):
        """branche 415->401 : CircuitOpenError leve par le breaker → except pass → lecteur suivant."""
        self._patch_no_parallel_no_browser_extractor(monkeypatch)

        seen: list[str] = []

        class OpenBreaker:
            async def call(self, fn, src, timeout):
                seen.append(src)
                raise CircuitOpenError("ouvert")

        monkeypatch.setattr(pipeline, "get_breaker", lambda h: OpenBreaker())

        lecteurs = [
            {"src": "https://a.example/1", "host": "a.example"},
            {"src": "https://b.example/2", "host": "b.example"},
        ]
        out = asyncio.run(pipeline._pipeline_playwright_impl(lecteurs, "[x]", FakeQueue()))

        assert out is None
        assert seen == ["https://a.example/1", "https://b.example/2"]

    def test_seq_falsy_result_continues_to_next_lecteur(self, monkeypatch):
        """branche 415->401 (variante) : breaker renvoie un resultat falsy → lecteur suivant."""
        self._patch_no_parallel_no_browser_extractor(monkeypatch)

        seen: list[str] = []

        class EmptyBreaker:
            async def call(self, fn, src, timeout):
                seen.append(src)
                return None

        monkeypatch.setattr(pipeline, "get_breaker", lambda h: EmptyBreaker())

        lecteurs = [
            {"src": "https://a.example/1", "host": "a.example"},
            {"src": "https://b.example/2", "host": "b.example"},
        ]
        out = asyncio.run(pipeline._pipeline_playwright_impl(lecteurs, "[x]", FakeQueue()))

        assert out is None
        assert seen == ["https://a.example/1", "https://b.example/2"]


class TestPipelinePlaywrightImplRuntimeError:
    """_pipeline_playwright_impl (ligne ~420/422) : RuntimeError du breaker → except avale → suite."""

    def test_runtime_error_in_seq_then_forensic_wins(self, monkeypatch):
        monkeypatch.setattr("engine.utils.security.is_safe_url", lambda u: True)
        monkeypatch.setattr(pipeline, "host_disponible", lambda h: True)

        async def par_none(lecteurs, timeout=8, on_win=None):
            return None

        monkeypatch.setattr(
            "engine.download.interceptor.intercepter_lecteurs_parallele", par_none
        )

        class RaiseBreaker:
            async def call(self, fn, src, timeout):
                raise RuntimeError("aucun flux livré")

        monkeypatch.setattr(pipeline, "get_breaker", lambda h: RaiseBreaker())

        async def fake_extraire(src, timeout=10, mode="standard"):
            return {"best": {"url": "https://cdn.example/x.m3u8", "headers": {"r": "1"}}}

        monkeypatch.setattr(
            "engine.download.extractor.browser_extractor.extraire_flux", fake_extraire
        )

        out = asyncio.run(pipeline._pipeline_playwright_impl([LECTEUR], "[x]", FakeQueue()))

        assert out == {"url": "https://cdn.example/x.m3u8", "headers": {"r": "1"}}


class TestLancerDownloadRateLimitNoDomain:
    """_lancer_download_pipeline (branche 488->490) : RateLimitError sans domaine → pas de penalite."""

    def test_ratelimit_without_domain_skips_penalty(self, monkeypatch):
        monkeypatch.setattr("engine.utils.security.is_safe_url", lambda u: True)
        monkeypatch.setattr(pipeline, "_espace_disque_suffisant", lambda d: True)
        monkeypatch.setattr(pipeline, "get_domain", lambda u: "")

        penalised: list[str] = []
        monkeypatch.setattr(
            pipeline, "domain_apply_penalty", lambda d: penalised.append(d)
        )

        import engine.download.methods.ytdlp_engine as ytdlp_mod

        calls: list[str] = []

        def fn_nm(url, dossier, nom, headers, cancelled, on_progress):
            calls.append("nm")
            return None

        def fn_yt(url, dossier, nom, headers, cancelled, on_progress):
            calls.append("yt")
            raise ytdlp_mod.RateLimitError("403")

        def fn_ff(url, dossier, nom, headers, cancelled, on_progress):
            calls.append("ff")
            return "ff.mp4"

        async def scenario():
            return await pipeline._lancer_download_pipeline(
                "relative/no/scheme/v.m3u8", "/tmp/out", "ep", {}, FakeQueue(),
                "[x] S01E001", fn_nm, fn_yt, fn_ff,
            )

        out = asyncio.run(scenario())

        assert out == "ff.mp4"
        assert calls == ["nm", "yt", "ff"]
        assert penalised == []


class TestPipelinePlaywrightImplSequentialRuntimeErrorLine:
    """Couvre explicitement l'except RuntimeError du maillon sequentiel (log.debug, pas de crash)."""

    def test_sequential_runtime_error_swallowed_returns_none(self, monkeypatch):
        monkeypatch.setattr("engine.utils.security.is_safe_url", lambda u: True)
        monkeypatch.setattr(pipeline, "host_disponible", lambda h: True)

        async def par_none(lecteurs, timeout=8, on_win=None):
            return None

        monkeypatch.setattr(
            "engine.download.interceptor.intercepter_lecteurs_parallele", par_none
        )

        class RaiseBreaker:
            async def call(self, fn, src, timeout):
                raise RuntimeError("aucun flux livré")

        monkeypatch.setattr(pipeline, "get_breaker", lambda h: RaiseBreaker())

        async def fake_extraire(src, timeout=10, mode="standard"):
            return {"best": None}

        monkeypatch.setattr(
            "engine.download.extractor.browser_extractor.extraire_flux", fake_extraire
        )

        out = asyncio.run(pipeline._pipeline_playwright_impl([LECTEUR], "[x]", FakeQueue()))

        assert out is None


class TestInterceptorOnWinRaises:
    """intercepter_lecteurs_parallele (lignes 414-415) : on_win qui leve est avale, le resultat reste."""

    @pytest.fixture(autouse=True)
    def _isolate(self, monkeypatch):
        async def anoop(*a, **k):
            return None

        monkeypatch.setattr(ic, "_install_loop_exception_handler", lambda: None)
        monkeypatch.setattr(ic, "_reset_browser_apres_erreur", anoop)
        monkeypatch.setattr(ic.asyncio, "sleep", anoop)

    def test_on_win_exception_is_swallowed(self, monkeypatch):
        async def stub(src, timeout=8, _in_parallel=False):
            return {"url": src + "/master.m3u8", "headers": {}}

        monkeypatch.setattr(ic, "intercepter_lecteur", stub)

        def on_win(_src):
            raise RuntimeError("on_win boom")

        result = asyncio.run(
            ic.intercepter_lecteurs_parallele(
                [{"src": "https://winner"}], timeout=2, on_win=on_win
            )
        )

        assert result == {"url": "https://winner/master.m3u8", "headers": {}}


class TestInterceptorMeilleurResultatPure:
    """_meilleur_resultat : priorite m3u8 > txt > premier."""

    def test_m3u8_wins_over_txt_and_first(self):
        resultats = [
            {"url": "https://h/a.bin"},
            {"url": "https://h/b.txt"},
            {"url": "https://h/c.m3u8"},
        ]
        assert ic._meilleur_resultat(resultats)["url"] == "https://h/c.m3u8"

    def test_txt_wins_when_no_m3u8(self):
        resultats = [
            {"url": "https://h/a.bin"},
            {"url": "https://h/b.txt"},
        ]
        assert ic._meilleur_resultat(resultats)["url"] == "https://h/b.txt"

    def test_first_when_neither_m3u8_nor_txt(self):
        resultats = [{"url": "https://h/a.bin"}, {"url": "https://h/b.mp4"}]
        assert ic._meilleur_resultat(resultats)["url"] == "https://h/a.bin"

    def test_empty_is_none(self):
        assert ic._meilleur_resultat([]) is None


class TestInterceptorParalleleEmptyAndNoSrc:
    """intercepter_lecteurs_parallele : liste vide ou sans src → None."""

    def test_empty_list_returns_none(self):
        assert asyncio.run(ic.intercepter_lecteurs_parallele([])) is None

    def test_no_exploitable_src_returns_none(self):
        assert asyncio.run(
            ic.intercepter_lecteurs_parallele([{"nosrc": 1}, "x", {"src": ""}])
        ) is None


class FakeFrame:
    def __init__(self, url):
        self.url = url
        self.evaluate_calls: list[str] = []

    async def evaluate(self, js):
        self.evaluate_calls.append(js)
        return []


class FakeCdpBE:
    def __init__(self):
        self._handlers: dict[str, list] = {}
        self.detached = False

    async def send(self, *a, **k):
        return None

    def on(self, event, handler):
        self._handlers.setdefault(event, []).append(handler)

    def fire(self, event, params):
        for handler in self._handlers.get(event, []):
            handler(params)

    async def detach(self):
        self.detached = True


class FakePageBE:
    def __init__(self, cdp, child_frames=None):
        self._cdp = cdp
        self._child_frames = list(child_frames or [])
        self._handlers: dict[str, list] = {}
        self.main_frame = self
        self.url = "http://host/main"
        self.closed = False
        self.goto_calls: list[dict] = []
        self._fire_on_goto: list[tuple[str, dict]] = []

    @property
    def frames(self):
        return [self.main_frame, *self._child_frames]

    def on(self, event, handler):
        self._handlers.setdefault(event, []).append(handler)

    def fire_on_goto(self, event, params):
        self._fire_on_goto.append((event, params))

    async def goto(self, *a, **k):
        self.goto_calls.append(k)
        for event, params in self._fire_on_goto:
            self._cdp.fire(event, params)

    async def click(self, selector, timeout=None):
        raise RuntimeError("no play")

    async def content(self):
        return ""

    async def evaluate(self, js):
        return []

    async def close(self):
        self.closed = True


class FakeCtxBE:
    def __init__(self, page, cdp):
        self._page = page
        self._cdp = cdp
        self.closed = False
        self.init_scripts: list[str] = []

    async def new_page(self):
        return self._page

    async def add_init_script(self, js):
        self.init_scripts.append(js)

    async def new_cdp_session(self, page):
        return self._cdp

    async def close(self):
        self.closed = True


class FakeBrowserBE:
    def __init__(self, ctx):
        self._ctx = ctx

    def is_connected(self):
        return True

    async def new_context(self, **kwargs):
        return self._ctx


def _patch_browser_extractor(monkeypatch, browser, js_code=""):
    async def fake_get_browser():
        return browser

    async def anoop(*a, **k):
        return None

    monkeypatch.setattr(ic, "get_browser", fake_get_browser)
    monkeypatch.setattr(ic, "apply_stealth", anoop)
    monkeypatch.setattr(be.asyncio, "sleep", anoop)
    monkeypatch.setattr(ic, "_reset_browser_apres_erreur", anoop)
    monkeypatch.setattr(be, "_charger_js_hooks", lambda: js_code)
    ic._ctx_semaphore_state["sem"] = None
    ic._ctx_semaphore_state["loop"] = None


@pytest.fixture
def _restore_interceptor_sem():
    saved_sem = ic._ctx_semaphore_state["sem"]
    saved_loop = ic._ctx_semaphore_state["loop"]
    saved_browser = ic._browser
    saved_pw = ic._playwright
    yield
    ic._ctx_semaphore_state["sem"] = saved_sem
    ic._ctx_semaphore_state["loop"] = saved_loop
    ic._browser = saved_browser
    ic._playwright = saved_pw


class TestBrowserExtractorPureScoring:
    """_score_url / _meilleur_resultat / _normaliser : fonctions pures, scoring deterministe."""

    def test_score_m3u8_beats_mp4(self):
        assert be._score_url("https://h/a.m3u8", "fetch") > be._score_url(
            "https://h/a.mp4", "fetch"
        )

    def test_score_cdp_type_adds_points(self):
        base = be._score_url("https://h/a.bin", "other")
        assert be._score_url("https://h/a.bin", "cdp_request") == base + be._SCORE_CDP

    def test_meilleur_resultat_picks_highest_score(self):
        results = [
            {"url": "https://h/plain.bin", "type": "dom"},
            {"url": "https://h/master.m3u8", "type": "cdp_response"},
        ]
        assert be._meilleur_resultat(results)["url"] == "https://h/master.m3u8"

    def test_normaliser_strips_fragment(self):
        assert be._normaliser("https://h/v.m3u8#x") == "https://h/v.m3u8"


class TestBrowserExtractorBranches:
    """extraire_flux : branches deterministes 138->140, 214->217, 219->221, 233->238, 311->313, 330->335."""

    def test_no_js_code_skips_init_script(self, monkeypatch, _restore_interceptor_sem):
        """branche 219->221 : js_code vide → ctx.add_init_script non appele."""
        cdp = FakeCdpBE()
        page = FakePageBE(cdp)
        ctx = FakeCtxBE(page, cdp)
        _patch_browser_extractor(monkeypatch, FakeBrowserBE(ctx), js_code="")

        result = asyncio.run(be.extraire_flux("http://host/embed", timeout=3, mode="fast"))

        assert ctx.init_scripts == []
        assert result["best"] is None

    def test_no_sem_skips_acquire_and_release(self, monkeypatch, _restore_interceptor_sem):
        """branches 214->217 et 311->313 : _ctx_semaphore() None → ni acquire ni release."""
        cdp = FakeCdpBE()
        page = FakePageBE(cdp)
        ctx = FakeCtxBE(page, cdp)
        _patch_browser_extractor(monkeypatch, FakeBrowserBE(ctx), js_code="")
        monkeypatch.setattr(ic, "_ctx_semaphore", lambda: None)

        result = asyncio.run(be.extraire_flux("http://host/embed", timeout=3, mode="fast"))

        assert result["best"] is None
        assert page.closed is True

    def test_cdp_request_without_req_id_still_added(self, monkeypatch, _restore_interceptor_sem):
        """branche 233->238 : requestId absent → pas de stockage cdp_hdrs, _ajouter quand meme."""
        cdp = FakeCdpBE()
        page = FakePageBE(cdp)
        page.fire_on_goto(
            "Network.requestWillBeSent",
            {"request": {"url": "https://cdn.example/master.m3u8", "headers": {}}},
        )
        ctx = FakeCtxBE(page, cdp)
        _patch_browser_extractor(monkeypatch, FakeBrowserBE(ctx), js_code="")

        result = asyncio.run(be.extraire_flux("http://host/embed", timeout=3, mode="fast"))

        assert result["best"] is not None
        assert result["best"]["url"] == "https://cdn.example/master.m3u8"

    def test_frame_scan_without_js_code_skips_injection(self, monkeypatch, _restore_interceptor_sem):
        """branche 138->140 : js_code vide → _injecter_hooks_frame non appele, scan continue."""
        cdp = FakeCdpBE()
        child = FakeFrame("http://host/child")
        page = FakePageBE(cdp, child_frames=[child])
        ctx = FakeCtxBE(page, cdp)
        _patch_browser_extractor(monkeypatch, FakeBrowserBE(ctx), js_code="")

        result = asyncio.run(be.extraire_flux("http://host/embed", timeout=3, mode="standard"))

        assert child.evaluate_calls == ["window.__STREAM_LOGS__ || []"]
        assert result["best"] is None

    def test_best_headers_unmatched_returns_empty(self, monkeypatch, _restore_interceptor_sem):
        """branche 330->335 : aucune entree timeline ne correspond au best → headers vides."""
        cdp = FakeCdpBE()
        page = FakePageBE(cdp)
        page.fire_on_goto(
            "Network.requestWillBeSent",
            {"request": {"url": "https://cdn.example/v.m3u8", "headers": {"a": "b"}}},
        )
        ctx = FakeCtxBE(page, cdp)
        _patch_browser_extractor(monkeypatch, FakeBrowserBE(ctx), js_code="")

        real_meilleur = be._meilleur_resultat

        def fake_meilleur(all_results):
            best = real_meilleur(all_results)
            if best is not None:
                return {"url": "https://cdn.example/UNSEEN.m3u8", "type": best.get("type", "")}
            return best

        monkeypatch.setattr(be, "_meilleur_resultat", fake_meilleur)

        result = asyncio.run(be.extraire_flux("http://host/embed", timeout=3, mode="fast"))

        assert result["best"] is not None
        assert result["best"]["url"] == "https://cdn.example/UNSEEN.m3u8"
        assert result["best"]["headers"] == {}


class TestInterceptorResetAndNoSemaphore:
    """interceptor : reset sans rien d'ouvert + intercepter_lecteur sans semaphore."""

    def test_reset_browser_apres_erreur_with_nothing_open_is_noop(self, _restore_interceptor_sem):
        """branches 218->223 et 223->exit : browser et playwright None → ni close ni stop."""
        ic._browser = None
        ic._playwright = None
        asyncio.run(ic._reset_browser_apres_erreur())
        assert ic._browser is None
        assert ic._playwright is None

    def test_intercepter_lecteur_without_semaphore_skips_acquire_release(
        self, monkeypatch, _restore_interceptor_sem
    ):
        """branches 301->304 et 347->349 : _ctx_semaphore None → ni acquire ni release, nettoyage normal."""
        monkeypatch.setattr(ic, "_ctx_semaphore", lambda: None)

        cdp = FakeCdpBE()
        page = FakePageBE(cdp)
        ctx = FakeCtxBE(page, cdp)
        browser = FakeBrowserBE(ctx)

        async def fake_get_browser():
            return browser

        async def anoop(*a, **k):
            return None

        monkeypatch.setattr(ic, "_get_browser", fake_get_browser)
        monkeypatch.setattr(ic, "_appliquer_stealth", anoop)
        monkeypatch.setattr(ic.asyncio, "sleep", anoop)

        result = asyncio.run(ic.intercepter_lecteur("https://h/embed", timeout=2))

        assert result is None
        assert page.closed is True
        assert ctx.closed is True


@pytest.fixture
def _isolate_registry():
    registry._ensure_loaded()
    saved_registry = list(registry._REGISTRY)
    yield
    registry._REGISTRY[:] = saved_registry
    registry._loaded = True


class TestRegistryGaps:
    """registry : register dedup, _ensure_loaded import echoue, _host_of cas limites, host_headers UA."""

    def test_register_returns_existing_on_duplicate_name(self, _isolate_registry):
        """ligne 47 : nom deja present → renvoie l'instance existante, pas d'ajout."""
        registry._REGISTRY.clear()
        first = registry.HostExtractor(name="dup", domains=("a.com",))
        registry.register(first)
        n = len(registry._REGISTRY)
        second = registry.HostExtractor(name="dup", domains=("b.com",))
        returned = registry.register(second)
        assert returned is first
        assert len(registry._REGISTRY) == n

    def test_ensure_loaded_swallows_import_failure(self, monkeypatch, _isolate_registry):
        """lignes 58-59 : l'import des hosts leve → except avale, _loaded reste True."""
        import builtins

        registry._loaded = False
        real_import = builtins.__import__
        raised: list[str] = []

        def boom(name, globals=None, locals=None, fromlist=(), level=0):
            if "hosts" in (fromlist or ()) and name.startswith("engine.download.extractor"):
                raised.append(name)
                raise ImportError("hosts boom")
            return real_import(name, globals, locals, fromlist, level)

        monkeypatch.setattr(builtins, "__import__", boom)
        registry._ensure_loaded()
        assert raised == ["engine.download.extractor"]
        assert registry._loaded is True

    def test_host_of_urlparse_exception_returns_empty(self, monkeypatch):
        """lignes 68-69 : urlparse leve sur une url avec schema → renvoie ''."""

        def boom(_s):
            raise ValueError("bad url")

        monkeypatch.setattr(registry, "urlparse", boom)
        assert registry._host_of("https://host/path") == ""

    def test_host_of_strips_path(self):
        """ligne 72 : host avec '/' → on garde la partie avant le slash."""
        assert registry._host_of("video.example.com/path/to") == "video.example.com"

    def test_host_of_strips_userinfo(self):
        """ligne 74 : host avec '@' → on garde la partie apres l'arobase."""
        assert registry._host_of("user:pass@video.example.com") == "video.example.com"

    def test_host_headers_includes_user_agent(self, _isolate_registry):
        """ligne 98 : un extracteur avec user_agent injecte l'entete user-agent."""
        ext = registry.HostExtractor(
            name="ua-host", domains=("uah.example",), user_agent="CustomUA/1.0"
        )
        registry.register(ext)
        out = registry.host_headers("https://uah.example/v")
        assert out["user-agent"] == "CustomUA/1.0"
