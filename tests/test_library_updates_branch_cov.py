from engine.library.updates import ep_est_ignore


def test_ep_est_ignore_mixed_valid_and_invalid_saison():
    regle = {"saisons_ignorees": [2, "x"]}
    assert ep_est_ignore(regle, 2, 1) is True
    assert ep_est_ignore(regle, 1, 1) is False


def test_ep_est_ignore_mixed_valid_and_invalid_episode():
    regle = {"episodes_ignores": {"1": [3, "bad"]}}
    assert ep_est_ignore(regle, 1, 3) is True
    assert ep_est_ignore(regle, 1, 9) is False
