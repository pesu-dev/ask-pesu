"""A chat model served by a local ollama, used in place of Hugging Face Inference.

Every LLM call the pipeline makes -- question rewriting, multi-query expansion,
the answer itself -- goes through an inference provider, and stops working when
the account's included credits run out. Both configured models are open weights
published for ollama, so the same pipeline can run against a copy on localhost.

``LLM_MODE=ollama`` is what switches to it; see :func:`local_config`. Only the
LLM moves -- embeddings, Qdrant, the reranker and the prompts are untouched.

It talks to ollama's native ``/api/chat`` rather than its OpenAI-compatible
endpoint because of where reasoning arrives: ollama puts a thinking model's
reasoning in its own ``thinking`` field, while
:meth:`RetrievalAugmentedGenerator._process_thinking_chunk` expects it inline in
``<think>`` tags the way Hugging Face sends it. The translation is here, so
nothing downstream can tell the two apart.
"""

import json
import logging
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx
from langchain_core.callbacks import AsyncCallbackManagerForLLMRun, CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult

# app.rag imports this module from inside its constructor rather than at the
# top, so this import is of a module that has finished loading.
from app.rag import THINK_END, THINK_START

# Environment variables rather than config values, so that a deployed Space --
# which shares conf/config.yaml with every other environment -- cannot be
# pointed at a localhost that is not there.
MODE_VAR = "LLM_MODE"
MODE_HF = "hf"
MODE_OLLAMA = "ollama"

BASE_URL_VAR = "OLLAMA_BASE_URL"
PRIMARY_MODEL_VAR = "OLLAMA_PRIMARY_MODEL"
THINKING_MODEL_VAR = "OLLAMA_THINKING_MODEL"
NUM_CTX_VAR = "OLLAMA_NUM_CTX"

# Tokens of context the models are loaded with, which has to hold the system
# prompt, the retrieved threads and the answer budget together -- ollama's own
# default does not, and it refuses a prompt longer than the window. Lower it if
# the model does not then fit in VRAM; the overflow runs on the CPU, slower.
DEFAULT_NUM_CTX = 16384

_ROLES = {"system": "system", "human": "user", "ai": "assistant"}


@dataclass(frozen=True)
class LocalConfig:
    """Where the local models are, and which ones to use.

    Attributes:
        base_url: The ollama server, without a trailing slash.
        primary: The ollama tag standing in for ``rag.llm.primary``.
        thinking: The ollama tag standing in for ``rag.llm.thinking``.
        num_ctx: Context window the models are loaded with.
    """

    base_url: str
    primary: str
    thinking: str
    num_ctx: int


def local_config() -> LocalConfig | None:
    """Read the ollama settings, if that is the mode the environment asks for.

    ``LLM_MODE`` is read case-insensitively and defaults to ``hf``, so an
    environment that says nothing about it gets Hugging Face Inference.

    Returns:
        The settings, or None under ``hf``, where the pipeline builds Hugging
        Face endpoints as normal and nothing else here is read.

    Raises:
        ValueError: If ``LLM_MODE`` is neither mode, or if ``OLLAMA_NUM_CTX`` is
            not a positive integer.
        KeyError: If ``ollama`` is asked for without the server and both models
            being named. There is no fallback to Hugging Face, which would spend
            the credits the run asked not to use.
    """
    mode = os.getenv(MODE_VAR, MODE_HF).strip().lower()
    if mode == MODE_HF:
        return None
    if mode != MODE_OLLAMA:
        raise ValueError(f"{MODE_VAR} must be {MODE_HF!r} or {MODE_OLLAMA!r}, not {mode!r}.")

    # ollama replaces a window it cannot use with one of its own and reports
    # that size in its errors, which would name a number nobody set.
    num_ctx = os.getenv(NUM_CTX_VAR, "").strip()
    if num_ctx and not (num_ctx.isdigit() and int(num_ctx) > 0):
        raise ValueError(f"{NUM_CTX_VAR} must be a positive integer, not {num_ctx!r}.")

    return LocalConfig(
        base_url=os.environ[BASE_URL_VAR].rstrip("/"),
        primary=os.environ[PRIMARY_MODEL_VAR],
        thinking=os.environ[THINKING_MODEL_VAR],
        num_ctx=int(num_ctx) if num_ctx else DEFAULT_NUM_CTX,
    )


def require_models(config: LocalConfig) -> None:
    """Check that the server is up and has both models, before anything uses it.

    A missing model is otherwise a 404 in the middle of the first answer, long
    after startup reported success.

    Args:
        config: The settings to check.

    Raises:
        RuntimeError: If the server cannot be reached, or does not have a model.
    """
    try:
        response = httpx.get(f"{config.base_url}/api/tags", timeout=30)
        response.raise_for_status()
    except httpx.HTTPError as error:
        raise RuntimeError(f"{BASE_URL_VAR} is {config.base_url}, which is not answering: {error}") from error

    # /api/tags always reports a tag, so a bare name means the "latest" one.
    installed = {model["name"] for model in response.json().get("models", [])}
    wanted = [name if ":" in name else f"{name}:latest" for name in (config.primary, config.thinking)]
    missing = [name for name in wanted if name not in installed]
    if missing:
        raise RuntimeError(f"{config.base_url} does not have {', '.join(missing)}. Run: ollama pull {missing[0]}")
    logging.info(f"Local inference: {config.primary} and {config.thinking} at {config.base_url}.")


def _raise_for_status(status_code: int, body: str) -> None:
    """Report an ollama error with what ollama said, not just the status line.

    httpx's own error carries the status and the URL and nothing else, while the
    reason is in the body -- and the one that matters here is a prompt longer
    than the context window, which names both sizes. ollama nests that message
    inside a JSON string inside a JSON object; anything that does not unpack is
    reported as it arrived.

    Args:
        status_code: The HTTP status ollama returned.
        body: The whole response body.

    Raises:
        RuntimeError: If the status is an error.
    """
    if status_code < 400:
        return
    detail = body.strip()
    try:
        inner = json.loads(json.loads(detail)["error"])
        detail = inner["error"]["message"]
    except (KeyError, TypeError, ValueError):
        pass
    raise RuntimeError(f"ollama returned {status_code}: {detail}")


class OllamaChat(BaseChatModel):
    """One of the two configured models, answered by a local ollama.

    Sampling is configured from the same block of config.yaml as the Hugging
    Face model this stands in for, so the two differ in their weights rather
    than in how those weights are used.

    Attributes:
        base_url: The ollama server, without a trailing slash.
        model: The ollama tag to generate with.
        temperature: Sampling temperature, from the model's config block.
        num_predict: Tokens one response may produce, from ``max_new_tokens``.
        num_ctx: Context window to load the model with.
        timeout: Seconds to wait on the server, from the model's config block.
    """

    base_url: str
    model: str
    temperature: float
    num_predict: int
    num_ctx: int
    timeout: float

    @property
    def _llm_type(self) -> str:
        return "ollama"

    def _body(self, messages: list[BaseMessage], stream: bool) -> dict[str, Any]:
        """Build the ``/api/chat`` request for one generation.

        Args:
            messages: The prompt, already rendered by the chain.
            stream: Whether to ask for token-by-token delivery.

        Returns:
            The JSON body to post.
        """
        return {
            "model": self.model,
            "messages": [{"role": _ROLES[message.type], "content": str(message.text)} for message in messages],
            "stream": stream,
            "options": {
                "temperature": self.temperature,
                "num_predict": self.num_predict,
                "num_ctx": self.num_ctx,
            },
        }

    @staticmethod
    def _as_text(message: dict[str, Any], reasoning_open: bool) -> tuple[str, bool]:
        """Render one ollama message as the inline text the pipeline parses.

        ollama returns a thinking model's reasoning in ``thinking``, separately
        from the answer in ``content``, and sends all of the reasoning before
        any of the answer. The pipeline reads ``<think>reasoning</think>answer``,
        so one opening and one closing tag are added back around it here.

        The closing tag is written when the answer begins, and a response that
        reasons without ever answering is left unclosed on purpose: that is
        exactly what a Hugging Face stream that runs out of budget mid-thought
        looks like, and the pipeline already reports it.

        Args:
            message: The ``message`` object from a response or a stream chunk.
            reasoning_open: Whether ``<think>`` has already been written.

        Returns:
            ``(text, reasoning_open)`` -- what to emit, and the updated state.
        """
        reasoning = message.get("thinking") or ""
        content = message.get("content") or ""

        text = ""
        if reasoning:
            if not reasoning_open:
                text, reasoning_open = THINK_START, True
            text += reasoning
        if content:
            if reasoning_open:
                text += THINK_END
                reasoning_open = False
            text += content
        return text, reasoning_open

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: object,
    ) -> ChatResult:
        """Generate a whole response in one call.

        This is what the retrieval-side calls reach -- question rewriting,
        multi-query expansion, the conversation title -- none of which stream.

        Args:
            messages: The prompt, already rendered by the chain.
            stop: Unused; ollama's stop sequences are not needed here.
            run_manager: Unused callback manager.
            **kwargs: Unused.

        Returns:
            The response as a single generation.
        """
        response = httpx.post(
            f"{self.base_url}/api/chat", json=self._body(messages, stream=False), timeout=self.timeout
        )
        _raise_for_status(response.status_code, response.text)
        text, _ = self._as_text(response.json()["message"], reasoning_open=False)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(text))])

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: object,
    ) -> AsyncIterator[ChatGenerationChunk]:
        """Stream a response, which is how the answer reaches the user.

        ollama sends one JSON object per line, each carrying the text generated
        since the last, and a final one that carries none.

        Args:
            messages: The prompt, already rendered by the chain.
            stop: Unused.
            run_manager: Unused callback manager.
            **kwargs: Unused.

        Yields:
            One chunk per piece of text ollama sends.
        """
        reasoning_open = False
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream(
                "POST", f"{self.base_url}/api/chat", json=self._body(messages, stream=True)
            ) as response:
                if response.is_error:
                    # Nothing has been read yet, and the reason is in the body.
                    await response.aread()
                    _raise_for_status(response.status_code, response.text)

                async for line in response.aiter_lines():
                    if not line:
                        continue
                    message = json.loads(line).get("message") or {}
                    text, reasoning_open = self._as_text(message, reasoning_open)
                    if text:
                        yield ChatGenerationChunk(message=AIMessageChunk(text))
