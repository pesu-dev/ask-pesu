"""Tests for the ranking arithmetic in ``services/api/app/rag.py``.

The repository deliberately has no test suite for the services: both validate
the live collection, the embedding model and every payload before doing any
work, so a writer/reader mismatch is a startup crash rather than something a
test has to catch.

Ranking is the exception. It is pure arithmetic over document metadata, with no
external state to validate against, and its failure mode is silent -- documents
come back in a slightly wrong order and nothing errors. The functions here take
their inputs explicitly and touch no network, no models and no Qdrant, which is
what makes them worth testing and cheap to test.
"""

import math

import pytest
from app.rag import blend, community_factor, deduplicate, describe_sources
from langchain_core.documents.base import Document

RANKING = {"community_weight": 0.30, "reference_score": 25}


def doc(**metadata: object) -> Document:
    """Build a document carrying only the metadata a test cares about."""
    return Document(page_content=metadata.pop("text", "body"), metadata=dict(metadata))


class TestCommunityFactor:
    """Endorsement, log-scaled because Reddit scores are heavy-tailed."""

    def test_missing_score_is_neutral_but_zero_is_not(self):
        # The distinction is the whole point: 0 is an observed value and real
        # information, None means nobody recorded one.
        assert community_factor(None, 100) == 0.5
        assert community_factor(0, 100) == 0.0

    def test_negative_scores_clamp_to_zero(self):
        assert community_factor(-91, 100) == 0.0

    def test_saturates_at_the_reference_and_never_exceeds_one(self):
        assert community_factor(100, 100) == pytest.approx(1.0)
        assert community_factor(697, 100) == 1.0

    def test_is_logarithmic(self):
        assert community_factor(8, 100) == pytest.approx(math.log1p(8) / math.log1p(100))
        # Concave, which is what compresses the heavy tail: the midpoint scores
        # far above the average of the endpoints, so a handful of viral threads
        # cannot run away with every ranking they appear in.
        assert community_factor(50, 100) > (community_factor(0, 100) + community_factor(100, 100)) / 2
        # Sub-linear: ten times the score is nowhere near ten times the factor.
        assert community_factor(80, 100) < 10 * community_factor(8, 100)


class TestBlend:
    """The multiplier is a pure penalty: it can demote, never promote."""

    def test_never_scores_above_the_documents_own_relevance(self):
        (out,) = blend([doc(_score=0.9, root_comment_score=10_000)], RANKING)
        assert out.metadata["_final"] <= 0.9 + 1e-9

    def test_worst_case_penalty_is_bounded_by_the_weight(self):
        (out,) = blend([doc(_score=1.0, root_comment_score=0)], RANKING)
        assert out.metadata["_final"] == pytest.approx(1 - RANKING["community_weight"], abs=1e-6)

    def test_endorsement_breaks_a_tie(self):
        loved = doc(_score=0.80, root_comment_score=60, post_id="loved")
        ignored = doc(_score=0.80, root_comment_score=0, post_id="ignored")
        assert [d.metadata["post_id"] for d in blend([ignored, loved], RANKING)] == ["loved", "ignored"]

    def test_missing_score_metadata_does_not_raise(self):
        (out,) = blend([doc()], RANKING)
        assert out.metadata["_final"] == 0.0

    def test_zero_weight_preserves_relevance_exactly(self):
        (out,) = blend([doc(_score=0.42, root_comment_score=0)], {**RANKING, "community_weight": 0.0})
        assert out.metadata["_final"] == pytest.approx(0.42)


class TestDeduplicate:
    """The library's dedup is disabled by our own per-query annotation."""

    def test_collapses_the_same_point_and_keeps_the_better_score(self):
        docs = [doc(_id="p1", _score=0.61), doc(_id="p2", _score=0.55), doc(_id="p1", _score=0.83)]
        out = deduplicate(docs)
        assert [d.metadata["_id"] for d in out] == ["p1", "p2"]
        assert out[0].metadata["_score"] == 0.83

    def test_a_worse_duplicate_does_not_displace_the_better_one(self):
        out = deduplicate([doc(_id="p1", _score=0.83), doc(_id="p1", _score=0.10)])
        assert len(out) == 1
        assert out[0].metadata["_score"] == 0.83

    def test_documents_without_an_id_are_all_kept(self):
        assert len(deduplicate([doc(), doc(), doc()])) == 3

    def test_empty_input(self):
        assert deduplicate([]) == []


class TestDescribeSources:
    """Citations come from the documents themselves, not from the model's prose."""

    LAYOUT = "TITLE: Placement policy explained\nCONTENT: body\nCOMMENT TREE: If you get a T1 you cannot sit again"

    def test_reads_the_title_and_a_snippet_of_the_discussion(self):
        (out,) = describe_sources([doc(text=self.LAYOUT, permalink="https://reddit.com/a")])
        assert out["title"] == "Placement policy explained"
        assert out["snippet"].startswith("If you get a T1")
        assert out["permalink"] == "https://reddit.com/a"

    def test_collapses_documents_that_share_a_thread(self):
        docs = [doc(text=self.LAYOUT, permalink="https://reddit.com/a") for _ in range(3)]
        assert len(describe_sources(docs)) == 1

    def test_falls_back_to_the_permalink_when_there_is_no_title(self):
        (out,) = describe_sources([doc(text="no layout here", permalink="https://reddit.com/b")])
        assert out["title"] == "https://reddit.com/b"
        # An empty preview is worse than a rough one.
        assert out["snippet"] == "no layout here"

    def test_skips_documents_with_no_permalink(self):
        assert describe_sources([doc(text=self.LAYOUT)]) == []

    def test_truncates_long_snippets(self):
        long_doc = doc(text="TITLE: t\nCONTENT: c\nCOMMENT TREE: " + "word " * 500, permalink="https://reddit.com/c")
        (out,) = describe_sources([long_doc], snippet_chars=50)
        assert len(out["snippet"]) == 50

    def test_no_documents(self):
        assert describe_sources([]) == []


class TestEndorsementRanks:
    """Endorsement, not relevance, orders the documents that clear the gate."""

    def test_endorsement_outranks_a_small_relevance_gap(self):
        # The cross-encoder separates the top documents by only a few percent,
        # so a well-endorsed answer has to be able to overcome that.
        endorsed = doc(_score=0.95, root_comment_score=40, post_id="endorsed")
        ignored = doc(_score=0.99, root_comment_score=0, post_id="ignored")
        assert [d.metadata["post_id"] for d in blend([ignored, endorsed], RANKING)] == ["endorsed", "ignored"]

    def test_relevance_still_holds_a_weak_document_down(self):
        # The gate is permissive, so endorsement must not be able to promote
        # something that barely answers the question.
        barely = doc(_score=0.35, root_comment_score=200, post_id="barely")
        solid = doc(_score=0.98, root_comment_score=2, post_id="solid")
        assert [d.metadata["post_id"] for d in blend([barely, solid], RANKING)] == ["solid", "barely"]

    def test_several_answers_from_one_thread_all_survive(self):
        # Nothing caps per thread: they are different people answering, and
        # keeping them is usually the best available result.
        docs = [doc(_score=0.9, root_comment_score=10 - i, post_id="p") for i in range(6)]
        assert len(blend(docs, RANKING)) == 6
