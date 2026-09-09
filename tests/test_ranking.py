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

from app.rag import deduplicate, describe_sources, rank
from langchain_core.documents.base import Document


def doc(**metadata: object) -> Document:
    """Build a document carrying only the metadata a test cares about."""
    return Document(page_content=metadata.pop("text", "body"), metadata=dict(metadata))


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


class TestRank:
    """Upvotes on the answer order the documents; ties keep relevance order."""

    def test_orders_by_upvotes(self):
        docs = [doc(post_id="low", root_comment_score=2), doc(post_id="high", root_comment_score=40)]
        assert [d.metadata["post_id"] for d in rank(docs)] == ["high", "low"]

    def test_a_downvoted_answer_sinks(self):
        # The post's score cannot go negative, which is why the comment's is used.
        docs = [doc(post_id="rejected", root_comment_score=-20), doc(post_id="unrated", root_comment_score=0)]
        assert [d.metadata["post_id"] for d in rank(docs)] == ["unrated", "rejected"]

    def test_ties_keep_the_relevance_order_they_arrived_in(self):
        # Two thirds of the corpus sits at three upvotes or fewer, so this is
        # the common case, and it is the whole reason the sort must be stable.
        docs = [doc(post_id=str(i), root_comment_score=1) for i in range(5)]
        assert [d.metadata["post_id"] for d in rank(docs)] == ["0", "1", "2", "3", "4"]

    def test_a_missing_score_is_neither_endorsed_nor_rejected(self):
        docs = [
            doc(post_id="unknown"),
            doc(post_id="down", root_comment_score=-5),
            doc(post_id="up", root_comment_score=5),
        ]
        assert [d.metadata["post_id"] for d in rank(docs)] == ["up", "unknown", "down"]

    def test_a_boolean_is_not_a_score(self):
        # metadata is JSON round-tripped, so guard against True sorting as 1.
        (out,) = rank([doc(post_id="x", root_comment_score=True)])
        assert out.metadata["post_id"] == "x"

    def test_no_documents(self):
        assert rank([]) == []
