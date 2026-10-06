"""Tests for student-facing language cleanup in the RAG API."""

import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from langchain_core.documents import Document

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.rag import DetoxifyToxicityScorer, describe_sources, source_snippet  # noqa: E402


class FakeToxicityScorer:
    """Test scorer keyed by exact candidate text."""

    def __init__(self, scores: dict[str, float]) -> None:
        """Remember deterministic scores for candidate snippets."""
        self._scores = scores

    def scores(self, texts: list[str]) -> list[float]:
        """Return configured toxicity scores for each candidate."""
        return [self._scores[text] for text in texts]


class SourceSnippetLanguageTests(unittest.TestCase):
    """Source previews should keep criticism while dropping abusive wording."""

    def test_below_threshold_text_is_preserved_without_word_masking(self) -> None:
        """Only the classifier score decides whether a passage is masked."""
        text = "The hostel is terrible and the food is shit."
        scorer = FakeToxicityScorer({text: 0.89})

        self.assertEqual(source_snippet(text, 120, scorer, 0.9), text)

    def test_source_snippet_uses_toxicity_score_to_pick_cleaner_passage(self) -> None:
        """A high-toxicity passage loses to ordinary criticism."""
        toxic = "AuthorA: Everyone involved deserves personal harassment."
        critical = "AuthorB: The hostel is terrible, the food is bad, and the Wi-Fi drops often."
        scorer = FakeToxicityScorer({toxic: 0.95, critical: 0.12})

        snippet = source_snippet(f"{toxic}\n\n{critical}", 120, scorer, toxicity_threshold=0.9)

        self.assertEqual(snippet, critical)

    def test_source_snippet_masks_at_or_above_threshold(self) -> None:
        """The whole passage is masked, including exactly at the threshold."""
        text = "AuthorA: Everyone involved deserves personal harassment."
        for score in (0.9, 0.95):
            with self.subTest(score=score):
                scorer = FakeToxicityScorer({text: score})
                self.assertEqual(source_snippet(text, 120, scorer, 0.9), "[masked]")

    def test_snippet_character_limit(self) -> None:
        """Both clean text and masked previews respect the requested length."""
        text = "The hostel is terrible."
        for score, expected in ((0.1, "The"), (0.95, "[ma")):
            with self.subTest(score=score):
                self.assertEqual(source_snippet(text, 3, FakeToxicityScorer({text: score}), 0.9), expected)
        scorer = Mock()
        self.assertEqual(source_snippet(text, 0, scorer, 0.9), "")
        scorer.scores.assert_not_called()

    def test_describe_sources_masks_raw_thread_text(self) -> None:
        """Source events prefer lower-scoring criticism without changing the raw document."""
        doc = Document(
            page_content=(
                "TITLE: Hostel review\n"
                "CONTENT: \n"
                "COMMENT TREE: AuthorA: The hostel is shit.\n"
                "AuthorB: The hostel is terrible, but the campus is convenient."
            ),
            metadata={"permalink": "https://reddit.com/r/PESU/comments/example", "created_utc": 1715000000.0},
        )

        scorer = FakeToxicityScorer(
            {
                "AuthorA: The hostel is shit.": 0.95,
                "AuthorB: The hostel is terrible, but the campus is convenient.": 0.12,
            }
        )
        [source] = describe_sources([doc], snippet_chars=200, scorer=scorer, toxicity_threshold=0.9)

        self.assertNotIn("shit", source["snippet"].lower())
        self.assertIn("hostel is terrible", source["snippet"])
        self.assertIn("The hostel is shit.", doc.page_content)

    def test_source_scoring_failure_propagates(self) -> None:
        """An inference failure cannot produce an unscored source preview."""
        doc = Document(page_content="A discussion", metadata={"permalink": "https://reddit.com/example"})
        scorer = Mock()
        scorer.scores.side_effect = RuntimeError("inference failed")
        with self.assertRaisesRegex(RuntimeError, "inference failed"):
            describe_sources([doc], 200, scorer, 0.9)


class DetoxifyScorerTests(unittest.TestCase):
    """Detoxify failures must never be treated as zero toxicity."""

    def test_model_loading_failure_propagates(self) -> None:
        """A missing model fails the call, including subsequent attempts."""
        scorer = DetoxifyToxicityScorer("original", 0.9)
        with patch("detoxify.Detoxify", side_effect=RuntimeError("model unavailable")):
            for _ in range(2):
                with self.assertRaisesRegex(RuntimeError, "model unavailable"):
                    scorer.scores(["Some criticism"])

    def test_inference_failure_propagates(self) -> None:
        """An inference exception is not swallowed by the wrapper."""
        scorer = DetoxifyToxicityScorer("original", 0.9)
        with patch("detoxify.Detoxify") as factory:
            factory.return_value.predict.side_effect = RuntimeError("inference failed")
            with self.assertRaisesRegex(RuntimeError, "inference failed"):
                scorer.scores(["Some criticism"])

    def test_scores_and_model_reuse(self) -> None:
        """Batched toxicity scores are returned and the loaded model is reused."""
        scorer = DetoxifyToxicityScorer("original", 0.9)
        with patch("detoxify.Detoxify") as factory:
            factory.return_value.predict.return_value = {"toxicity": [0.1, 0.95]}
            for _ in range(2):
                self.assertEqual(scorer.scores(["Criticism", "Abuse"]), [0.1, 0.95])
            factory.assert_called_once_with("original", device="cpu")

    def test_invalid_predictions_raise(self) -> None:
        """Missing, incomplete, or invalid scores cannot pass as clean text."""
        cases = [
            ({"insult": [0.5]}, KeyError),
            ({"toxicity": []}, ValueError),
            ({"toxicity": [float("nan")]}, ValueError),
            ({"toxicity": [float("inf")]}, ValueError),
            ({"toxicity": [-0.1]}, ValueError),
            ({"toxicity": [1.1]}, ValueError),
        ]
        for result, error_type in cases:
            with self.subTest(result=result), patch("detoxify.Detoxify") as factory:
                factory.return_value.predict.return_value = result
                with self.assertRaises(error_type):
                    DetoxifyToxicityScorer("original", 0.9).scores(["Some criticism"])


if __name__ == "__main__":
    unittest.main()
