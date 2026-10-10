"""The eval comparator (#20): pure scoring, no model, no BIRD."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[3] / "evals/runner"))

import report  # noqa: E402
from suites import triage  # noqa: E402
from suites.bird import has_order_by, same_result  # noqa: E402


def test_order_is_ignored_unless_gold_sorts():
    assert same_result([[1], [2]], [[2], [1]], ordered=False)
    assert not same_result([[1], [2]], [[2], [1]], ordered=True)
    assert same_result([[1], [2]], [[1], [2]], ordered=True)


def test_gold_order_by_is_detected_at_the_top_level_only():
    assert has_order_by("SELECT a FROM t ORDER BY a DESC LIMIT 1")
    assert not has_order_by("SELECT a FROM t")
    assert not has_order_by("SELECT a FROM (SELECT a FROM t ORDER BY a) GROUP BY a")
    assert not has_order_by("not sql at all (")


def test_floats_are_rounded_and_null_is_not_empty_string():
    assert same_result([[0.1 + 0.2]], [[0.3]], ordered=False)
    assert same_result([[1]], [[1.0]], ordered=False)
    assert not same_result([[0.3]], [[0.31]], ordered=False)
    assert not same_result([[None]], [[""]], ordered=False)


def test_duplicates_count():
    assert not same_result([[1], [1], [2]], [[1], [2], [2]], ordered=False)
    assert not same_result([[1], [1]], [[1]], ordered=False)
    assert same_result([[1], [1], [2]], [[1], [2], [1]], ordered=False)


def test_percentile_and_summary():
    assert report.pct([1, 2, 3, 4, 100], 0.95) == 100
    assert report.pct([], 0.95) == 0.0
    rs = [{"correct": True, "outcome": "answer", "cost_usd": 1, "latency_ms": 10, "cache_read_tokens": 1, "cache_write_tokens": 0},
          {"correct": False, "outcome": "ticket", "cost_usd": 3, "latency_ms": 30, "cache_read_tokens": 2, "cache_write_tokens": 5}]
    s = report.summarize(rs)
    assert s["accuracy"] == 0.5 and s["cost_usd"]["mean"] == 2 and s["cache_read_tokens"] == 3
    assert s["outcomes"] == {"answer": 1, "ticket": 1}


def test_confusion_matrix():
    m = triage.confusion([{"expected": "handoff", "got": "question"}, {"expected": "handoff", "got": "handoff"}])
    assert m["handoff"] == {"question": 1, "handoff": 1} and not m["question"]
