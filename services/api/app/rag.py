"""The retrieval-augmented generation pipeline behind ``POST /ask``.

One :class:`RetrievalAugmentedGenerator` is built during the FastAPI lifespan and
reused for every request; construction loads an embedding model and optionally a
cross-encoder, so it is far too expensive to do per request.

A question travels through five stages, all wired together with LangChain
Expression Language (LCEL) in :meth:`RetrievalAugmentedGenerator._build_chain`:

1. **Rewrite.** The question plus chat history becomes one standalone,
   retrieval-friendly query. This is what resolves "is it hard?" into "is the
   Data Structures course at PES University hard?", and expands PESU
   abbreviations (RR, EC, CSE, SGPA...) using the prompt in ``conf/config.yaml``.
2. **Multi-query expansion.** ``MultiQueryRetriever`` asks the LLM for several
   phrasings of that query and unions the documents each one retrieves, which
   recovers passages a single phrasing would miss.
3. **Dense retrieval.** Each phrasing runs a vector search against Qdrant
   through :class:`ScoredRetriever`.
4. **Rerank.** A cross-encoder scores every (query, document) pair properly --
   attending to both texts at once, which a bi-encoder vector search cannot do --
   and drops anything below the configured threshold.
5. **Generate.** The surviving documents are formatted into the answer prompt and
   streamed from the LLM token by token.

Stages 1 and 2 always use the *primary* model even in thinking mode, so thinking
tokens are never spent on query rewriting.

The collection name, embedding model and vector geometry are not configured here.
They are contracted with ``services/db`` in ``conf/collection.yaml`` and verified
at startup; see :mod:`app.contract`.
"""

import json
import logging
import os
from collections.abc import AsyncGenerator, Callable
from operator import itemgetter

import yaml
from dotenv import load_dotenv
from huggingface_hub import InferenceClient
from langchain_classic.retrievers import MultiQueryRetriever
from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents.base import Document
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.retrievers import BaseRetriever
from langchain_core.runnables import RunnableLambda, RunnablePassthrough, RunnableSerializable
from langchain_huggingface import ChatHuggingFace, HuggingFaceEndpoint
from langchain_huggingface.embeddings import HuggingFaceEmbeddings
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient

from app import contract as contract_mod

load_dotenv()

# Thinking models wrap their reasoning in these tags. The backend strips them
# and re-emits the reasoning as `step` events so the UI can show it separately
# from the answer.
THINK_START = "<think>"
THINK_END = "</think>"

# Payload keys read out of retrieved documents. Checked against the contract at
# startup so removing one from conf/collection.yaml fails here rather than as a
# KeyError on the first query.
#
# `permalink`, not `url`: for a self post the two agree, but for a link post
# `url` is the external article being discussed rather than the discussion
# itself. Answers are synthesised from the comment thread, so citing `url` there
# would send the reader to a page that does not contain what was cited.
REQUIRED_METADATA = ("permalink",)


def _is_quota_error(error: BaseException) -> bool:
    """Guess whether a failure was the provider refusing us on quota or rate limit.

    The Hugging Face Inference client surfaces these as an HTTP error, so prefer
    the status code and fall back to the message. It is a heuristic: guessing
    wrong only costs an unnecessary cooldown, whereas not detecting a real 429
    means hammering a provider that is already refusing us.
    """
    status = getattr(getattr(error, "response", None), "status_code", None)
    if status == 429:
        return True
    text = str(error).lower()
    return any(marker in text for marker in ("429", "too many requests", "quota", "rate limit"))


class ScoredRetriever(BaseRetriever):
    """A retriever that keeps the similarity score alongside each document.

    LangChain's ``BaseRetriever`` interface returns bare documents, discarding
    the scores the vector store computed. Those scores are the only ranking
    signal available when the cross-encoder is disabled, so this wrapper stashes
    each one in ``doc.metadata["_score"]``.

    The underscore prefix marks it as locally attached rather than part of the
    payload written by ``services/db`` -- it is not in the collection contract.
    """

    vector_store: QdrantVectorStore
    search_kwargs: dict

    def _get_relevant_documents(self, query: str, *, run_manager: CallbackManagerForRetrieverRun) -> list[Document]:
        """Retrieve documents synchronously, annotating each with its score."""
        results = self.vector_store.similarity_search_with_relevance_scores(query, **self.search_kwargs)
        for doc, score in results:
            doc.metadata["_score"] = score
        return [doc for doc, _ in results]

    async def _aget_relevant_documents(
        self, query: str, *, run_manager: CallbackManagerForRetrieverRun
    ) -> list[Document]:
        """Async twin of the above.

        ``BaseRetriever`` supplies a default that runs the sync version in a
        thread pool, but the whole request path is async, so implementing this
        properly keeps the event loop free during the network round trip.
        """
        results = await self.vector_store.asimilarity_search_with_relevance_scores(query, **self.search_kwargs)
        for doc, score in results:
            doc.metadata["_score"] = score
        return [doc for doc, _ in results]


class RetrievalAugmentedGenerator:
    """Owns the whole question-answering pipeline: models, retriever and chains.

    Built once during the FastAPI lifespan. Constructing it downloads and loads
    the embedding model and (when enabled) the cross-encoder, so it must not be
    built per request.
    """

    def __init__(self, config_path: str = "conf/config.yaml") -> None:
        """Load config, verify the collection contract, and assemble both chains.

        Deliberately fails fast. Every external assumption -- the token, the
        embedding model, the live collection's geometry -- is checked here, so a
        misconfigured deployment refuses to start rather than serving wrong
        answers. Anything raised propagates out of the lifespan and the server
        never binds.

        Args:
            config_path: Path to the runtime config. Values that are contracted
                with ``services/db`` are NOT read from here; see
                ``conf/collection.yaml``.
        """
        # Constructed purely to assert HF_TOKEN is present and well-formed: this
        # subscript raises KeyError immediately, rather than every generation
        # failing later with an opaque authentication error. The client itself is
        # unused -- LangChain builds its own from the same token.
        InferenceClient(api_key=os.environ["HF_TOKEN"])

        with open(config_path) as file:
            self.config = yaml.safe_load(file)

        # The collection name, embedding model and vector geometry are contracted
        # with services/db, not configured per service. Everything is checked
        # before the first query, so a writer/reader mismatch is a startup crash
        # naming the offending value rather than quietly wrong retrieval.
        self.contract = contract_mod.load()
        contract_mod.require_metadata(self.contract, *REQUIRED_METADATA)

        self.embedding = HuggingFaceEmbeddings(model_name=self.contract.model)
        contract_mod.validate_embedding(self.contract, self.embedding)

        self.qdrant_client = QdrantClient(url=os.getenv("QDRANT_URL"), api_key=os.getenv("QDRANT_API_KEY"))
        contract_mod.validate_collection(self.contract, self.qdrant_client)
        logging.info(f"Qdrant collection {self.contract.name!r} matches conf/collection.yaml.")

        # Dense retrieval only, even though every point also carries the BM25
        # sparse vector services/db writes. Reading hybrid is a change to this
        # constructor rather than a re-index -- which is the whole reason the
        # sparse vector is written now -- but it is not a free switch: Qdrant
        # fuses the two rankings with Reciprocal Rank Fusion, whose output is a
        # rank-derived score on a different scale from cosine similarity, so
        # `score_threshold` would silently stop meaning anything and the
        # reranker cutoff would need re-deriving.
        self.vector_store = QdrantVectorStore(
            collection_name=self.contract.name,
            embedding=self.embedding,
            client=self.qdrant_client,
            vector_name=self.contract.vector_name,
        )

        # Two chat models, both streaming. `provider` routes the call through a
        # third-party inference provider (nscale) rather than HF's own hardware.
        # Primary LLM — used for normal mode AND question rewriting in all modes
        self.llm_primary = ChatHuggingFace(
            llm=HuggingFaceEndpoint(
                repo_id=self.config["rag"]["llm"]["primary"]["repo_id"],
                provider=self.config["rag"]["llm"]["primary"]["provider"],
                huggingfacehub_api_token=os.getenv("HF_TOKEN"),
                temperature=self.config["rag"]["llm"]["primary"]["temperature"],
                max_new_tokens=self.config["rag"]["llm"]["primary"]["max_new_tokens"],
                timeout=self.config["rag"]["llm"]["primary"]["timeout"],
                streaming=True,
            ),
        )

        # Thinking LLM — ONLY used for final answer generation in thinking mode
        self.llm_thinking = ChatHuggingFace(
            llm=HuggingFaceEndpoint(
                repo_id=self.config["rag"]["llm"]["thinking"]["repo_id"],
                provider=self.config["rag"]["llm"]["thinking"]["provider"],
                huggingfacehub_api_token=os.getenv("HF_TOKEN"),
                temperature=self.config["rag"]["llm"]["thinking"]["temperature"],
                max_new_tokens=self.config["rag"]["llm"]["thinking"]["max_new_tokens"],
                timeout=self.config["rag"]["llm"]["thinking"]["timeout"],
                streaming=True,
            )
        )

        # Answer prompt: system rules (cite sources, refuse off-topic questions)
        # plus the human turn carrying {question} and the retrieved {context}.
        self.prompt = ChatPromptTemplate.from_messages(
            [
                ("system", self.config["rag"]["prompts"]["system_prompt"]),
                ("human", self.config["rag"]["prompts"]["answer_prompt"]),
            ]
        )

        # Rewrite prompt: turns a possibly-elliptical follow-up plus history into
        # one standalone query. {input} is the raw question.
        self.frame_qn_prompt = ChatPromptTemplate.from_messages(
            [
                ("system", self.config["rag"]["prompts"]["rewrite_prompt"]),
                ("human", "{input}"),
            ]
        )

        self.retriever = ScoredRetriever(
            vector_store=self.vector_store,
            search_kwargs=self.config["rag"]["search_kwargs"],
        )

        # torch and sentence_transformers are imported lazily: together they are
        # the heaviest dependency in the image, and a deployment with the reranker
        # disabled should not pay to import them.
        reranker_cfg = self.config["rag"].get("reranker", {})
        if reranker_cfg.get("enabled", False):
            import torch
            from sentence_transformers import CrossEncoder

            # Sigmoid squashes the raw logit into 0..1 so `score_threshold` is a
            # probability-like cutoff that means the same thing across models.
            self.cross_encoder = CrossEncoder(reranker_cfg["model"], activation_fn=torch.nn.Sigmoid())
            logging.info(f"Cross-encoder reranker loaded: {reranker_cfg['model']}")
        else:
            self.cross_encoder = None

        # Two chains differing only in which model writes the final answer; both
        # retrieve with the primary model.
        self.rag_chain_primary = self._build_chain(self.llm_primary)
        self.rag_chain_thinking = self._build_chain(self.llm_thinking)

    def _build_chain(self, llm: BaseChatModel) -> RunnableSerializable[str, str]:
        """Compose the LCEL chain that turns a question into a stream of answer text.

        Args:
            llm: The model that writes the final answer. Retrieval always uses
                the primary model regardless of this argument.

        Returns:
            A runnable taking ``{"input", "question", "chat_history"}`` and
            streaming answer strings.
        """
        # Always use llm_primary for retrieval steps — never burn thinking-model
        # tokens on question rewriting or multi-query expansion.
        multiquery_retriever = MultiQueryRetriever.from_llm(
            retriever=self.retriever,
            llm=self.llm_primary,
        )

        # Rewrite, then retrieve: the dict pulls the two fields the rewrite prompt
        # needs, the LLM rewrites, StrOutputParser unwraps the message into a
        # plain string, and that string is what the retriever searches with.
        history_aware_retriever = (
            {"input": itemgetter("input"), "chat_history": itemgetter("chat_history")}
            | self.frame_qn_prompt
            | self.llm_primary
            | StrOutputParser()
            | multiquery_retriever
        )

        # `assign` runs the retriever and adds its output under "docs" while
        # keeping the original input keys, so "input" survives for the reranker
        # (which needs the query) and for the answer prompt further down.
        return (
            RunnablePassthrough.assign(docs=history_aware_retriever)
            | RunnableLambda(self._rerank)
            | {
                "context": itemgetter("docs") | RunnableLambda(self.format_docs),
                "question": itemgetter("input"),
            }
            | self.prompt
            | llm
            | StrOutputParser()
        )

    def format_docs(self, docs: list[Document]) -> str:
        """Flatten retrieved documents into the ``{context}`` block of the answer prompt.

        Each document is prefixed with its Reddit permalink because the system
        prompt instructs the model to end its answer with a Sources list, and the
        link has to be visible in the context for the model to cite it. The
        permalink always addresses the thread the answer came from, which `url`
        does not for link posts.

        Order matters -- the model weights earlier context more heavily -- so the
        best document goes first.

        Args:
            docs: Documents surviving retrieval and reranking.

        Returns:
            The documents as one blank-line-separated string.
        """
        # When the reranker ran it already sorted by cross-encoder score. Without
        # it the documents arrive in retriever order, which for a multi-query
        # union is not globally sorted, so sort by the stashed vector score.
        if self.cross_encoder is None:
            docs = sorted(docs, key=lambda d: d.metadata.get("_score", 0.0), reverse=True)
        return "\n\n".join(f"{doc.metadata['permalink']}\n{doc.page_content}" for doc in docs)

    def _rerank(self, inputs: dict) -> dict:
        """Re-score documents against the query and drop the weak ones.

        Vector search compares two embeddings computed independently, so it can
        rank a document highly for being broadly on-topic. A cross-encoder reads
        the query and the document together and is far better at judging whether
        this passage actually answers this question -- but it is too slow to run
        over the whole collection, which is why it only re-scores what retrieval
        already shortlisted.

        Note this is a *filter*: if nothing clears the threshold the answer prompt
        gets no context, and the system prompt makes the model say it does not
        have that information. That is the intended behaviour -- an admission
        beats an answer invented from weak context.

        Args:
            inputs: Chain state carrying at least ``"input"`` and ``"docs"``.

        Returns:
            The same dict with ``"docs"`` filtered and sorted best-first.
        """
        if self.cross_encoder is None:
            return inputs

        query = inputs["input"]
        docs = inputs["docs"]
        if not docs:
            return inputs

        # Reuses the vector-search threshold deliberately: one number to tune,
        # and the sigmoid puts cross-encoder scores on a comparable 0..1 scale.
        threshold = self.config["rag"]["search_kwargs"]["score_threshold"]
        pairs = [[query, doc.page_content] for doc in docs]
        scores = self.cross_encoder.predict(pairs)

        reranked = []
        for doc, score in zip(docs, scores):
            if float(score) >= threshold:
                doc.metadata["_score"] = float(score)
                reranked.append(doc)

        reranked.sort(key=lambda d: d.metadata["_score"], reverse=True)
        logging.debug(f"Reranker: {len(docs)} → {len(reranked)} docs above threshold {threshold}")
        inputs["docs"] = reranked
        return inputs

    def _process_thinking_chunk(self, chunk: str, pending: str, thinking_done: bool) -> tuple[str, bool, list[dict]]:
        """Split one streamed chunk into reasoning (``step``) and answer (``token``) events.

        A thinking model emits ``<think>reasoning</think>answer``, but the stream
        arrives in arbitrary chunks, so ``</think>`` can be split across a chunk
        boundary -- ``"...</thi"`` then ``"nk>..."``. Emitting eagerly would leak
        a fragment of the closing tag into the visible reasoning and then fail to
        recognise the tag at all.

        The fix is a small buffer: hold back the last ``len("</think>") - 1``
        characters, which is the longest prefix of the tag that could still be
        completed by the next chunk, and emit everything before it. Once the tag
        is seen the buffer is no longer needed and later chunks pass straight
        through as answer tokens.

        Args:
            chunk: Newly received text.
            pending: Characters withheld from previous chunks.
            thinking_done: Whether ``</think>`` has already been seen.

        Returns:
            ``(pending, thinking_done, events)`` -- the updated buffer, the
            updated flag, and the events to emit for this chunk.
        """
        events = []

        if thinking_done:
            events.append({"type": "token", "content": chunk})
            return pending, thinking_done, events

        pending += chunk

        # Strip the opening <think> tag if it appears at the start of the stream
        if pending.startswith(THINK_START):
            pending = pending[len(THINK_START) :]

        if THINK_END in pending:
            idx = pending.index(THINK_END)
            step_part = pending[:idx]
            token_part = pending[idx + len(THINK_END) :]
            pending = ""
            thinking_done = True

            if step_part:
                events.append({"type": "step", "content": step_part})
            if token_part:
                events.append({"type": "token", "content": token_part})
        else:
            # No closing tag yet. Everything except a possible partial tag at the
            # end is safe to emit; a partial can be at most len(tag) - 1 chars.
            safe_end = max(0, len(pending) - len(THINK_END) + 1)
            if safe_end > 0:
                events.append({"type": "step", "content": pending[:safe_end]})
                pending = pending[safe_end:]

        return pending, thinking_done, events

    def _flush_pending(self, pending: str, thinking_done: bool) -> dict:
        """Emit whatever is left in the buffer once the stream ends.

        Reaching here with ``thinking_done`` false means the model never closed
        its ``<think>`` block -- truncated by ``max_new_tokens``, or it simply did
        not follow the format. The buffer is emitted as answer text rather than
        discarded, so the user sees something instead of an empty reply.
        """
        if not thinking_done:
            logging.warning("</think> never detected in thinking mode — emitting buffer as answer.")
        return {"type": "token", "content": pending}

    async def generate(
        self,
        query: str,
        thinking: bool,
        history: list,
        on_quota_exceeded: Callable[[], None] | None = None,
    ) -> AsyncGenerator[str, None]:
        """Run the pipeline and yield newline-delimited JSON events.

        Each yielded string is one complete JSON object plus a newline, so the
        client can parse incrementally without buffering the whole response:

        - ``{"type": "step", "content": ...}``  reasoning, thinking mode only
        - ``{"type": "token", "content": ...}`` a piece of the answer
        - ``{"type": "error", "content": ...}`` generation failed
        - ``{"type": "done"}``                  always last

        This generator never raises. HTTP status and headers are already sent by
        the time it runs, so a failure cannot become a 500 -- it is reported as an
        ``error`` event instead, and ``done`` still follows so clients waiting for
        it do not hang.

        Args:
            query: The user's question.
            thinking: Use the thinking model for the answer.
            history: Prior ``{query, answer}`` turns from the client.
            on_quota_exceeded: Called if the failure looks like a provider quota
                or rate-limit refusal. Lets the caller start a cooldown without
                this module knowing about quota state.

        Yields:
            NDJSON lines, each terminated by a newline.
        """
        logging.info(f"Received query: {query} with thinking={thinking} and history of length {len(history)}")

        # Conversations live only in the browser, so the client replays history
        # on every request. Skip any turn whose query equals the current one:
        # clients may include the in-flight question, and feeding it back as
        # already-answered confuses the rewrite step.
        chat_history = []
        for convo in history:
            if query != convo.query:
                chat_history.append(HumanMessage(convo.query))
                chat_history.append(AIMessage(convo.answer))

        rag_chain = self.rag_chain_thinking if thinking else self.rag_chain_primary

        logging.info(f"Using {'thinking' if thinking else 'primary'} LLM for query: {query}")

        # Streaming state. `pending` buffers characters that might be a partial
        # </think> tag; see _process_thinking_chunk.
        thinking_done = False
        pending = ""
        token_count = 0

        try:
            async for chunk in rag_chain.astream(
                {
                    "input": query,
                    "question": query,
                    "chat_history": chat_history,
                }
            ):
                token_count += 1

                # Normal mode has no reasoning to separate, so chunks pass
                # straight through as answer tokens.
                if not thinking:
                    yield json.dumps({"type": "token", "content": chunk}) + "\n"
                    continue

                pending, thinking_done, events = self._process_thinking_chunk(chunk, pending, thinking_done)
                for event in events:
                    yield json.dumps(event) + "\n"

            if pending:
                yield json.dumps(self._flush_pending(pending, thinking_done)) + "\n"
            logging.info(f"Stream complete. Total chunks: {token_count}")
        except Exception as e:
            logging.error(f"Error in generate(): {str(e)}", exc_info=True)
            if on_quota_exceeded is not None and _is_quota_error(e):
                # Tell the caller to start a cooldown so subsequent requests are
                # rejected up front instead of failing mid-stream.
                on_quota_exceeded()
            yield json.dumps({"type": "error", "content": str(e)}) + "\n"

        # Emitted on every path, success or failure, so the client always has a
        # definite end of stream.
        yield json.dumps({"type": "done"}) + "\n"

    async def shorten_query(self, query: str) -> str:
        """Condense a question into a short title for a conversation in the sidebar.

        Not part of the RAG pipeline -- no retrieval, just one small LLM call.
        Always uses the primary model.

        Args:
            query: The user's original question.

        Returns:
            At most eight words. The prompt asks for that, and the slice enforces
            it, since the model may add a preamble or ignore the limit.
        """
        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "Rewrite the user's query into at most 8 important words."
                    "Keep the core meaning. Remove filler words."
                    "Return ONLY the shortened query.",
                ),
                ("human", "{query}"),
            ]
        )

        chain = prompt | self.llm_primary | StrOutputParser()

        result = await chain.ainvoke({"query": query})
        return " ".join(result.split()[:8])
