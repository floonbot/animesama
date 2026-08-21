import engine.download._helpers as h


def test_normaliser_coerces_nonstr_titre_and_nonint_saison_episode():
    item = {"episodes": [{"titre": 123, "saison": "abc", "episode": "x", "url": "u"}]}
    eps = h.normaliser_episodes(item)
    assert isinstance(eps[0]["titre"], str)
    assert isinstance(eps[0]["saison"], int)
    assert isinstance(eps[0]["episode"], int)


def test_normaliser_nonstr_titre_falls_back_to_default():
    item = {"episodes": [{"titre": ["a", "b"], "url": "u"}]}
    eps = h.normaliser_episodes(item)
    assert eps[0]["titre"] == "Anime"


def test_normaliser_preserves_valid_values():
    item = {"episodes": [{"titre": "Naruto", "saison": 2, "episode": 5}]}
    eps = h.normaliser_episodes(item)
    assert eps[0]["titre"] == "Naruto"
    assert eps[0]["saison"] == 2
    assert eps[0]["episode"] == 5


def test_normaliser_falsy_saison_still_defaults_to_one():
    item = {"episodes": [{"titre": "T", "saison": 0, "episode": 0}]}
    eps = h.normaliser_episodes(item)
    assert eps[0]["saison"] == 1
    assert eps[0]["episode"] == 0
