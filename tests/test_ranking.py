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
from app.rag import blend, community_factor, deduplicate, describe_sources, recency_factor
from langchain_core.documents.base import Document

DAY = 86400.0
NOW = 1_800_000_000.0

RANKING = {
    "recency_weight": 0.0,
    "community_weight": 0.30,
    "grace_days": 365,
    "half_life_days": 730,
    "reference_score": 25,
}
# Recency is off by default, so the tests that exercise the decay switch it on
# explicitly rather than depending on the shipped value.
WITH_RECENCY = {**RANKING, "recency_weight": 0.15, "community_weight": 0.0}


def doc(**metadata: object) -> Document:
    """Build a document carrying only the metadata a test cares about."""
    return Document(page_content=metadata.pop("text", "body"), metadata=dict(metadata))


class TestRecencyFactor:
    """Staleness decay: flat through the grace period, then halving."""

    def test_missing_timestamp_is_treated_as_current(self):
        # An indexing gap is not evidence of staleness, so it must not penalise.
        assert recency_factor(None, NOW, 365, 730) == 1.0

    def test_inside_the_grace_period_is_never_penalised(self):
        for age_days in (0, 1, 100, 364, 365):
            assert recency_factor(NOW - age_days * DAY, NOW, 365, 730) == 1.0

    def test_halves_one_half_life_after_the_grace_period(self):
        assert recency_factor(NOW - (365 + 730) * DAY, NOW, 365, 730) == pytest.approx(0.5)
        assert recency_factor(NOW - (365 + 1460) * DAY, NOW, 365, 730) == pytest.approx(0.25)

    def test_a_future_timestamp_cannot_exceed_one(self):
        # 0.5 ** negative is greater than 1, which would let the blend push a
        # document above its own relevance and break the "pure penalty" rule.
        assert recency_factor(NOW + 30 * DAY, NOW, 365, 730) == 1.0

    def test_decays_monotonically(self):
        ages = [0, 365, 500, 1000, 2000, 5000]
        factors = [recency_factor(NOW - a * DAY, NOW, 365, 730) for a in ages]
        assert factors == sorted(factors, reverse=True)


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
    """The multiplier is a pure penalty and only ever a tie-breaker."""

    def test_never_scores_above_the_documents_own_relevance(self):
        best = doc(_score=0.9, created_utc=NOW, root_comment_score=10_000)
        (out,) = blend([best], NOW, RANKING)
        assert out.metadata["_final"] <= 0.9 + 1e-9

    def test_worst_case_penalty_is_bounded_by_the_weights(self):
        worst = doc(_score=1.0, created_utc=NOW - 50_000 * DAY, root_comment_score=0)
        (out,) = blend([worst], NOW, RANKING)
        floor = 1 - RANKING["recency_weight"] - RANKING["community_weight"]
        assert out.metadata["_final"] == pytest.approx(floor, abs=1e-6)

    def test_recency_breaks_a_tie(self):
        old = doc(_score=0.80, created_utc=NOW - 3000 * DAY, root_comment_score=10, post_id="a")
        new = doc(_score=0.80, created_utc=NOW, root_comment_score=10, post_id="b")
        assert [d.metadata["post_id"] for d in blend([old, new], NOW, WITH_RECENCY)] == ["b", "a"]

    def test_does_not_invert_a_large_relevance_gap(self):
        # A clearly better but ancient answer must still win.
        strong_old = doc(_score=0.85, created_utc=NOW - 3000 * DAY, root_comment_score=0, post_id="strong")
        weak_new = doc(_score=0.60, created_utc=NOW, root_comment_score=500, post_id="weak")
        assert blend([weak_new, strong_old], NOW, WITH_RECENCY)[0].metadata["post_id"] == "strong"

    def test_missing_score_metadata_does_not_raise(self):
        (out,) = blend([doc()], NOW, RANKING)
        assert out.metadata["_final"] == 0.0

    def test_zero_weights_preserve_relevance_exactly(self):
        cfg = {**RANKING, "recency_weight": 0.0, "community_weight": 0.0}
        (out,) = blend([doc(_score=0.42, created_utc=NOW - 9999 * DAY, root_comment_score=0)], NOW, cfg)
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
        assert [d.metadata["post_id"] for d in blend([ignored, endorsed], NOW, RANKING)] == ["endorsed", "ignored"]

    def test_relevance_still_holds_a_weak_document_down(self):
        # The gate is permissive, so endorsement must not be able to promote
        # something that barely answers the question.
        barely = doc(_score=0.35, root_comment_score=200, post_id="barely")
        solid = doc(_score=0.98, root_comment_score=2, post_id="solid")
        assert [d.metadata["post_id"] for d in blend([barely, solid], NOW, RANKING)] == ["solid", "barely"]

    def test_several_answers_from_one_thread_all_survive(self):
        # Nothing caps per thread: they are different people answering, and
        # keeping them is usually the best available result.
        docs = [doc(_score=0.9, root_comment_score=10 - i, post_id="p") for i in range(6)]
        assert len(blend(docs, NOW, RANKING)) == 6
