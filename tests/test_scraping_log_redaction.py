import requests

import engine.download.methods.images as images


def test_telecharger_image_redacts_signed_url_in_log(monkeypatch, caplog):
    monkeypatch.setattr(images, "is_safe_url", lambda u: False)
    url = "https://cdn.example.com/page/001.jpg?token=SUPERSECRET&exp=999&sig=abc"
    with caplog.at_level("WARNING"):
        out = images._telecharger_image(requests.Session(), url)
    assert out is None
    assert "URL image non autorisée" in caplog.text
    assert "SUPERSECRET" not in caplog.text
    assert "sig=abc" not in caplog.text
