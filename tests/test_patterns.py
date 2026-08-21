from engine.download._patterns import url_a_ignorer, url_est_stream


def test_detects_m3u8():
    assert url_est_stream("https://cdn.host/master.m3u8") is True

def test_ignores_images_and_css():
    assert url_a_ignorer("https://host/logo.png") is True
    assert url_a_ignorer("https://host/app.css") is True

def test_js_ignored_but_not_json():
    assert url_a_ignorer("https://host/app.js") is True
    assert url_a_ignorer("https://host/data.json") is False

def test_plain_page_not_stream():
    assert url_est_stream("https://host/index.html") is False
