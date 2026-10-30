import copy
import random

import pytest
from intervals import merge, subtract, total_length


def test_empty_interval_does_not_bridge_or_survive():
    assert merge([(3, 3)]) == []
    assert merge([(1, 2), (2, 2), (2, 3)]) == [(1, 3)]


def test_validation_applies_to_absorbed_and_empty_inputs():
    with pytest.raises(ValueError):
        merge([(0, 10), (5, 4)])
    with pytest.raises(ValueError):
        subtract([(0, 10)], [(9, 2)])
    with pytest.raises(ValueError):
        total_length([(3, 2)])


def test_inputs_not_modified():
    a = [(5, 6), (1, 2), (2, 3)]
    b = [(2, 5)]
    before = copy.deepcopy((a, b))
    merge(a)
    subtract(a, b)
    total_length(a)
    assert (a, b) == before


def test_subtract_spanning_several_and_touching_edges():
    assert subtract([(0, 4), (6, 10)], [(2, 8)]) == [(0, 2), (8, 10)]
    assert subtract([(0, 5)], [(5, 9)]) == [(0, 5)]
    assert subtract([(0, 5)], [(-3, 0)]) == [(0, 5)]
    assert subtract([(0, 5)], [(0, 2), (2, 5)]) == []


def test_subtract_merges_inputs_first_and_result_is_merged():
    assert subtract([(0, 3), (3, 6)], [(2, 4)]) == [(0, 2), (4, 6)]
    assert subtract([], [(1, 2)]) == []
    assert subtract([(1, 2)], []) == [(1, 2)]


def test_floats_and_total_length_type():
    assert merge([(0.5, 1.5), (1.5, 2.0)]) == [(0.5, 2.0)]
    assert total_length([(0, 3), (2, 5)]) == 5 and isinstance(total_length([(0, 3)]), int)
    assert total_length([]) == 0


def test_matches_pointwise_model_on_random_inputs():
    rng = random.Random(11)
    for _ in range(300):
        def rnd():
            return [tuple(sorted((rng.randint(0, 12), rng.randint(0, 12)))) for _ in range(rng.randint(0, 5))]
        a, b = rnd(), rnd()
        pa = {x + 0.5 for s, e in a for x in range(s, e)}
        pb = {x + 0.5 for s, e in b for x in range(s, e)}
        want = sorted(pa - pb)
        got = subtract(a, b)
        pts = sorted(x + 0.5 for s, e in got for x in range(s, e))
        assert pts == want
        assert all(got[i][1] < got[i + 1][0] for i in range(len(got) - 1))
        assert all(s < e for s, e in got)
        assert total_length(a) == len(pa)
