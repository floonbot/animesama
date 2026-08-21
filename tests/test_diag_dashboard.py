def test_le_diagnostic_est_une_page_de_l_app(client):
    body = client.get("/").text
    assert 'data-page="diag"' in body
    assert 'id="page-diag"' in body
    assert "Diagnostic" in body


def test_la_page_autonome_a_disparu(client):
    assert client.get("/diag.html").status_code == 404
    assert client.get("/js/diag.js").status_code == 404
    assert client.get("/css/diag.css").status_code == 404


def test_plus_aucun_lien_vers_la_page_autonome(client):
    assert "diag.html" not in client.get("/").text


def test_diag_module_is_offline(client):
    r = client.get("/js/pages/diag.js")
    assert r.status_code == 200
    assert "javascript" in r.headers["content-type"].lower()
    assert "http://" not in r.text
    assert "https://" not in r.text


def test_diag_module_calls_same_origin_api(client):
    r = client.get("/js/pages/diag.js")
    assert "/api/health" in r.text
    assert "/api/metrics" in r.text
    assert "/api/logs" in r.text


def test_diag_passe_par_api_js_et_non_par_fetch_nu(client):
    """La page autonome faisait ses propres fetch : timeout, en-tetes et
    invalidation de cache divergeaient du reste de l'application."""
    src = client.get("/js/pages/diag.js").text
    assert "from '../api.js'" in src
    assert "api.get(" in src
    assert "fetch(" not in src


def test_diag_reutilise_le_flux_sse_de_l_app(client):
    src = client.get("/js/pages/diag.js").text
    assert "EventSource" not in src
    assert "sse-activity" in src

    events = client.get("/js/events.js").text
    assert "sse-activity" in events
    assert "sse-state" in events


def test_diag_ne_rafraichit_pas_hors_de_la_vue(client):
    src = client.get("/js/pages/diag.js").text
    assert "visibilitychange" in src
    assert "page-changed" in src

    router = client.get("/js/router.js").text
    assert "page-changed" in router
