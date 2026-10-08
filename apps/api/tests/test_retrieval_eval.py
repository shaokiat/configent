"""The eval's metric functions, on hand-built rankings."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "evals"))
from retrieval_eval import recall_at_k, reciprocal_rank  # noqa: E402


def test_duplicate_chunks_count_once():
    # Three chunks of "a" must not push "b" out of the top 2 documents.
    assert recall_at_k(["b"], ["a", "a", "a", "b"], k=2) == 1.0
    assert reciprocal_rank(["b"], ["a", "a", "a", "b"]) == 0.5


def test_recall_is_a_fraction_of_expected():
    assert recall_at_k(["a", "z"], ["a", "b"], k=5) == 0.5
    assert recall_at_k(["a"], ["b", "c", "a"], k=2) == 0.0


def test_mrr_first_expected_wins_and_absent_is_zero():
    assert reciprocal_rank(["a", "c"], ["b", "c", "a"]) == 0.5
    assert reciprocal_rank(["a"], ["b"]) == 0.0
