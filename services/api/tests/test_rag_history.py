"""Offline checks for the history sent to the rewrite model."""

import unittest

from app.rag import rewrite_transcript
from langchain_core.messages import AIMessage, HumanMessage


class RewriteTranscriptTests(unittest.TestCase):
    """Keep the rewrite input readable and bounded without touching answer history."""

    def test_formats_messages_without_langchain_repr_metadata(self) -> None:
        """Render role labels and preserve newlines instead of message reprs."""
        transcript = rewrite_transcript(
            [HumanMessage("Tell me about CSE at RR"), AIMessage("It is a long answer\nwith details.")],
            max_turns=8,
            max_answer_chars=2000,
        )

        self.assertEqual(transcript, "User: Tell me about CSE at RR\nAssistant: It is a long answer\nwith details.")
        self.assertNotIn("HumanMessage(", transcript)
        self.assertNotIn("additional_kwargs", transcript)

    def test_keeps_recent_turns_and_bounds_assistant_text(self) -> None:
        """Drop stale turns and cap long assistant answers."""
        transcript = rewrite_transcript(
            [
                HumanMessage("old question"),
                AIMessage("old answer"),
                HumanMessage("latest question"),
                AIMessage("abcdefghij"),
            ],
            max_turns=1,
            max_answer_chars=4,
        )

        self.assertEqual(transcript, "User: latest question\nAssistant: abcd")
        self.assertNotIn("old question", transcript)


if __name__ == "__main__":
    unittest.main()
