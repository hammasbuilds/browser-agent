import pytest

from browser_agent.stats import bootstrap_mean_ci, mean, quantile, wilson
from browser_agent.tokens import count_tokens


def test_wilson_matches_the_textbook_value_and_handles_the_edges():
    lo, hi = wilson(8, 10)
    assert lo == pytest.approx(0.4902, abs=1e-4) and hi == pytest.approx(0.9433, abs=1e-4)
    assert wilson(0, 0) == (0.0, 0.0)
    lo, hi = wilson(20, 20)
    assert hi == 1.0 and 0.8 < lo < 0.85  # all-success still gets a lower bound below 1


def test_bootstrap_is_deterministic_and_brackets_the_mean():
    values = [0.0, 0.5, 1.0, 1.0, 0.25]
    a = bootstrap_mean_ci(values)
    assert a == bootstrap_mean_ci(values)
    assert a[0] <= mean(values) <= a[1]
    assert bootstrap_mean_ci([1.0, 1.0, 1.0]) == (1.0, 1.0)


def test_quantile_interpolates():
    assert quantile([1, 2, 3, 4], 0.5) == 2.5
    assert quantile([7], 0.9) == 7


@pytest.mark.parametrize("fn", [mean, lambda v: bootstrap_mean_ci(v), lambda v: quantile(v, 0.5)])
def test_empty_input_is_an_error_not_a_silent_zero(fn):
    with pytest.raises(ValueError):
        fn([])


def test_qwen_tokenizer_counts_without_special_tokens():
    assert count_tokens("") == 0
    assert count_tokens("hello world") == 2
    assert count_tokens('<button id="subbtn">Submit</button>') > 5
