"""Ingest reconciles the index with the corpus: rebuild what changed, prune what is gone.

The plan is the whole decision, so it is tested on its own; `ingest_client` only carries
it out. The config half: every setting that shapes the index moves the fingerprint.
"""
import pytest
from pydantic import ValidationError

from app.config.schema import CorpusConfig
from app.ingest import plan

FP = "fp-now"


def test_only_an_edited_file_is_rebuilt():
    files = {"a.md": "h1", "b.md": "h2-edited"}
    indexed = {"a.md": ("h1", FP), "b.md": ("h2", FP)}
    assert plan(files, indexed, FP) == (["b.md"], [])


def test_a_settings_change_rebuilds_every_file():
    files = {"a.md": "h1", "b.md": "h2"}
    indexed = {"a.md": ("h1", "fp-old"), "b.md": ("h2", "fp-old")}
    assert plan(files, indexed, FP) == (["a.md", "b.md"], [])


def test_rows_from_before_the_fingerprint_column_are_rebuilt():
    assert plan({"a.md": "h1"}, {"a.md": ("h1", None)}, FP) == (["a.md"], [])


def test_a_deleted_file_is_pruned_and_a_new_one_added():
    files = {"new.md": "h3"}
    indexed = {"gone.md": ("h1", FP)}
    assert plan(files, indexed, FP) == (["new.md"], ["gone.md"])


def test_force_rebuilds_unchanged_files():
    assert plan({"a.md": "h1"}, {"a.md": ("h1", FP)}, FP, force=True) == (["a.md"], [])


def test_fingerprint_moves_with_every_index_setting_but_not_the_folder():
    base = CorpusConfig(source="corpora/x/")
    assert base.fingerprint() == CorpusConfig(source="corpora/moved/").fingerprint()
    for change in (
        {"chunking": {"chunk_size": 512}},
        {"chunking": {"overlap": 10}},
        {"embedding": {"model": "voyage-3.5"}},
    ):
        assert CorpusConfig(source="corpora/x/", **change).fingerprint() != base.fingerprint()


def test_an_embedding_model_of_another_width_is_refused_at_load():
    with pytest.raises(ValidationError, match="1024-dim"):
        CorpusConfig(source="corpora/x/", embedding={"model": "text-embedding-3-small"})
