"""Regression: lecteurs_depuis_arrays must return players in numeric var order.
sorted() on the raw keys ("eps1", "eps2", ... "eps10") is lexicographic, so
eps10/eps11 sorted before eps2, scrambling the cascade priority of the secondary
players for a season with >= 10 lecteur arrays. The fix keys the sort on
(len(name), name), which is numeric for the guaranteed "eps<digits>" names.
"""

from engine.scraping.parser.players import lecteurs_depuis_arrays


def test_numeric_order_with_ten_plus_players():
    arrays = {f"eps{i}": [f"https://h{i}.tld/v"] for i in range(1, 12)}
    out = lecteurs_depuis_arrays(arrays, 1)
    hosts = [d["host"] for d in out]
    assert hosts == [f"h{i}.tld" for i in range(1, 12)]


def test_single_digit_order_preserved():
    arrays = {"eps1": ["https://a.tld/v"], "eps2": ["https://b.tld/v"]}
    out = lecteurs_depuis_arrays(arrays, 1)
    assert [d["host"] for d in out] == ["a.tld", "b.tld"]
