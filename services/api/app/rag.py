"""The retrieval-augmented generation pipeline behind ``POST /ask``.

One :class:`RetrievalAugmentedGenerator` is built during the FastAPI lifespan and
reused for every request; construction loads an embedding model and optionally a
cross-encoder, so it is far too expensive to do per request.

A question travels through six stages:

1. **Rewrite.** With chat history, the question plus that history becomes one
   standalone query -- this is what resolves "is it hard?" into something
   retrievable. With no history there is nothing to resolve against and the
   step is skipped, saving a round trip on every first question.
2. **Multi-query expansion.** ``MultiQueryRetriever`` asks the LLM for several
   phrasings and unions the documents each one retrieves, which recovers
   passages a single phrasing would miss.
3. **Retrieval.** Each phrasing runs a search against Qdrant through
   :class:`ScoredRetriever`.
4. **Deduplication.** The union is collapsed on the stored point id. This has to
   happen before reranking, or the cross-encoder pays to score the same
   document more than once.
5. **Rerank.** A cross-encoder scores every (query, document) pair properly --
   attending to both texts at once, which a bi-encoder vector search cannot do --
   and drops anything below the configured threshold.
6. **Generate.** The surviving documents are formatted into the answer prompt and
   streamed from the LLM token by token.

Stages 1 and 2 always use the *primary* model even in thinking mode, so thinking
tokens are never spent on query rewriting.

Only the last stage is a LangChain Expression Language (LCEL) chain. Retrieval
used to be one too, which meant the documents it found were consumed inside the
chain and never surfaced -- so the backend could not tell a client which threads
an answer was drawn from, and had to ask the model to reprint the links instead.
Running the retrieval stages explicitly is what makes the documents available to
:meth:`RetrievalAugmentedGenerator.generate`.

The collection name, embedding model and vector geometry are not configured here.
They are contracted with ``services/db`` in ``conf/collection.yaml`` and verified
at startup; see :mod:`app.contract`.
"""

import asyncio
import json
import logging
import math
import os
import time
from collections.abc import AsyncGenerator, Callable

import yaml
from dotenv import load_dotenv
from huggingface_hub import InferenceClient
from langchain_classic.retrievers import MultiQueryRetriever
from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents.base import Document
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.retrievers import BaseRetriever
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
#
# `post_id` groups documents that share a thread, for the per-post cap and for
# collapsing the repeated post body out of the prompt. `created_utc` and `score`
# feed the ranking weights.
REQUIRED_METADATA = ("permalink", "post_id", "created_utc", "score")


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


def deduplicate(docs: list[Document]) -> list[Document]:
    """Collapse documents that are the same stored point, keeping the best score.

    ``MultiQueryRetriever`` unions the results of several phrasings and dedupes
    them with ``[doc for i, doc in enumerate(docs) if doc not in docs[:i]]``,
    which compares whole ``Document`` objects -- **including metadata**. That
    works until something writes per-query state into metadata, which
    :class:`ScoredRetriever` does: it stashes the similarity score under
    ``_score`` before the union happens. Two phrasings that both find the same
    point produce two objects whose scores differ, so they compare unequal and
    both survive. The library's dedup is silently disabled by our own
    annotation.

    ``metadata["_id"]`` is the stored point id, written by ``langchain_qdrant``
    on every document it builds, and is the identity that actually matters.
    Deduping on it also has to decide which copy to keep: the highest ``_score``
    wins, because a document retrieved by several phrasings should be
    represented by its best match, not by whichever phrasing happened to run
    last.

    Documents without an ``_id`` are passed through untouched rather than
    collapsed together -- they have no identity to compare, and treating them as
    one document would be a worse error than keeping a duplicate.

    Args:
        docs: Documents from one or more retrieval calls, in any order.

    Returns:
        The documents, first occurrence order preserved, one per point id.
    """
    # Position by point id rather than searching `out` for the previous copy:
    # list.index compares Documents by value, so it would find whichever earlier
    # element happened to compare equal rather than the one actually being
    # replaced.
    position: dict[str, int] = {}
    out: list[Document] = []
    for doc in docs:
        point_id = doc.metadata.get("_id")
        if point_id is None:
            out.append(doc)
            continue
        index = position.get(point_id)
        if index is None:
            position[point_id] = len(out)
            out.append(doc)
        elif doc.metadata.get("_score", 0.0) > out[index].metadata.get("_score", 0.0):
            # Same point, better score: keep this copy where the first one
            # already sits, so ordering stays stable.
            out[index] = doc
    return out


def describe_sources(docs: list[Document], snippet_chars: int = 200) -> list[dict]:
    """Turn retrieved documents into the citations the stream reports.

    These are the threads retrieval actually selected, which is the whole point:
    the alternative is asking the model to reprint links it was shown and
    parsing them back out of its prose, where it can drop one, invent one, or
    format the list in a way the parser does not expect.

    Documents are stored as a TITLE line, a CONTENT line and then the COMMENT
    TREE, so the title is recoverable without another payload key. Anything that
    does not match that layout falls back to the permalink rather than raising
    -- a citation is not worth failing a request over.

    Several documents can share a post and therefore a permalink, so the list is
    collapsed to one entry per thread, keeping the first (best-ranked).

    Args:
        docs: Documents in final rank order.
        snippet_chars: How much of the discussion to include as a preview.

    Returns:
        One dict per distinct thread, in rank order.
    """
    out: list[dict] = []
    seen: set[str] = set()
    for doc in docs:
        permalink = doc.metadata.get("permalink")
        if not permalink or permalink in seen:
            continue
        seen.add(permalink)

        first_line, _, rest = doc.page_content.partition("\n")
        title = first_line[len("TITLE: ") :].strip() if first_line.startswith("TITLE: ") else ""
        _, _, tree = rest.partition("COMMENT TREE:")
        # Prefer the discussion, fall back to whatever followed the title, and
        # finally to the raw document -- an empty preview is worse than a rough
        # one.
        snippet = " ".join((tree or rest or doc.page_content).split())[:snippet_chars]
        out.append({"permalink": permalink, "title": title or permalink, "snippet": snippet})
    return out


def recency_factor(created_utc: float | None, now: float, grace_days: float, half_life_days: float) -> float:
    """Score how current a thread is, from 1.0 (fresh) down towards 0.0 (ancient).

    Flat at 1.0 for everything inside the grace period, then halving every
    ``half_life_days``. The flat region is the part that matters: a grace period
    changes the *shape* of the curve, whereas a floor -- ``f + (1-f) * decay`` --
    expands to ``wr*f + wr*(1-f)*decay``, whose constant term cancels in a
    ranking and so is only a roundabout way of writing a smaller weight.

    ``created_utc`` is the *submission's* timestamp rather than the comment's,
    which is the right signal anyway: measured across the corpus, 89% of root
    comments are written within a day of the post and 97% within a week, so the
    error is far smaller than the grace period absorbs.

    Args:
        created_utc: POSIX timestamp, or None when the payload did not carry one.
        now: POSIX timestamp for the current time.
        grace_days: Age below which nothing is penalised.
        half_life_days: Days after the grace period to halve the factor.

    Returns:
        A multiplier in ``(0, 1]``.
    """
    # A missing timestamp is an indexing gap, not evidence of staleness, so it
    # is treated as current rather than punished.
    if created_utc is None:
        return 1.0
    # Clamped because a clock skew or a bad payload could otherwise produce a
    # negative age, and 0.5 ** negative exceeds 1 -- which would let this boost
    # a document above its own relevance and break the whole invariant.
    age_days = max(0.0, (now - float(created_utc)) / 86400.0)
    return 0.5 ** (max(0.0, age_days - grace_days) / half_life_days)


def community_factor(score: float | None, reference_score: float) -> float:
    """Score how strongly the community endorsed a thread, on a 0..1 scale.

    Logarithmic because Reddit scores are heavy-tailed -- the corpus median is 8
    and the maximum 697 -- so a linear scale would let a handful of viral
    threads dominate every ranking they appear in.

    Note ``0`` and ``None`` are deliberately different. Zero is a real observed
    value and a genuine signal, so it maps to 0.0; a missing value is an
    indexing gap and maps to the corpus median instead, so an unknown document
    is neither rewarded nor punished. This is why ``metadata.get("score", 0)``
    and ``score or 0`` would both be wrong.

    Args:
        score: The stored score, or None when the payload did not carry one.
        reference_score: The score at which the factor saturates.

    Returns:
        A multiplier in ``[0, 1]``.
    """
    if score is None:
        # log1p(8) / log1p(100), the corpus median expressed on this scale.
        return 0.5
    return min(1.0, math.log1p(max(float(score), 0.0)) / math.log1p(reference_score))


def blend(docs: list[Document], now: float, ranking_cfg: dict) -> list[Document]:
    """Reorder documents by relevance tempered with recency and endorsement.

    The multiplier is ``1 - wr - wc + wr*recency + wc*community``, bounded in
    ``[1-wr-wc, 1]``. That makes it a pure penalty: a document can lose ranking
    weight for being stale or unloved, but nothing can ever score above its own
    relevance. The largest relevance gap it can invert is ``1/(1-wr-wc)`` -- at
    the shipped weights about 18%, which makes this a tie-breaker rather than a
    re-ranker. Anyone raising the weights until the ordering visibly changes is
    breaking retrieval, not tuning it.

    Multiplicative rather than additive because the flip condition then reduces
    to ``relevance_a / relevance_b < multiplier_b / multiplier_a``, which is
    scale-invariant: it behaves the same among documents scoring 0.9 as among
    documents scoring 0.35. An additive form would reorder far more aggressively
    at the low end, which is exactly where the scores mean least.

    This must run *after* the relevance cutoff. Filtering on the blended score
    would make the threshold mean "relevant, conditioned on being recent and
    popular", which is not a number anyone can reason about.

    Args:
        docs: Documents that already cleared the relevance threshold, each
            carrying ``_score``.
        now: POSIX timestamp for the current time.
        ranking_cfg: The ``rag.ranking`` block.

    Returns:
        The same documents, best first, each annotated with ``_final``.
    """
    weight_recency = ranking_cfg["recency_weight"]
    weight_community = ranking_cfg["community_weight"]
    base = 1.0 - weight_recency - weight_community

    for doc in docs:
        recency = recency_factor(
            doc.metadata.get("created_utc"),
            now,
            ranking_cfg["grace_days"],
            ranking_cfg["half_life_days"],
        )
        community = community_factor(doc.metadata.get("score"), ranking_cfg["reference_score"])
        multiplier = base + weight_recency * recency + weight_community * community
        doc.metadata["_recency"] = recency
        doc.metadata["_final"] = doc.metadata.get("_score", 0.0) * multiplier

    return sorted(docs, key=lambda d: d.metadata["_final"], reverse=True)


def diversify(docs: list[Document], top_n: int, max_per_post: int) -> list[Document]:
    """Take the best ``top_n`` documents without letting one thread dominate.

    A document is one comment tree, and a busy post can contribute a dozen of
    them -- a third of the corpus sits on a post with more than one. Several
    answers to the same question are genuinely worth having, so the cap is not
    one; what it prevents is a single thread filling the entire context window
    and making the sources list repeat itself.

    When the cap leaves fewer than ``top_n`` documents, it is *relaxed* and the
    selection retried rather than topped up with leftovers, which keeps the
    invariant "no post contributes more than the cap" true of whatever comes
    back instead of quietly violating it.

    Args:
        docs: Documents, already ordered best first.
        top_n: How many to return.
        max_per_post: Starting cap on documents from any one post.

    Returns:
        At most ``top_n`` documents, order preserved.
    """
    cap = max_per_post
    while cap <= top_n:
        counts: dict[str, int] = {}
        kept: list[Document] = []
        for doc in docs:
            post_id = doc.metadata.get("post_id")
            # An unknown post is never capped: bucketing every such document
            # together would collapse unrelated threads into one.
            if post_id is None or counts.get(post_id, 0) < cap:
                if post_id is not None:
                    counts[post_id] = counts.get(post_id, 0) + 1
                kept.append(doc)
                if len(kept) == top_n:
                    return kept
        if len(kept) == len(docs):
            # Nothing was held back, so relaxing the cap cannot find more.
            return kept
        cap += 1
    return docs[:top_n]


class ScoredRetriever(BaseRetriever):
    """A retriever that keeps the search score alongside each document.

    LangChain's ``BaseRetriever`` interface returns bare documents, discarding
    the scores the vector store computed. Those scores order the candidate pool
    and are the only ranking signal available when the cross-encoder is
    disabled, so this wrapper stashes each one in ``doc.metadata["_score"]``.

    It calls ``similarity_search_with_score`` rather than
    ``similarity_search_with_relevance_scores`` deliberately. The latter maps
    the score through a "relevance" function -- for cosine, ``(score + 1) / 2``
    -- and applies ``score_threshold`` to *that*, client side, after popping it
    out of the kwargs so Qdrant never sees it. Under hybrid retrieval it would
    be normalising a Reciprocal Rank Fusion score as though it were a cosine
    similarity, which is meaningless. This returns whatever the mode actually
    produced, and ``_score_kind`` records which that is so nothing downstream
    compares the two scales by accident.

    Both underscore keys are locally attached, not part of the payload written
    by ``services/db``, and are not in the collection contract.
    """

    vector_store: QdrantVectorStore
    k: int
    score_kind: str
    score_threshold: float | None = None

    def _annotate(self, results: list[tuple[Document, float]]) -> list[Document]:
        """Attach each score, and the scale it is on, to its document."""
        for doc, score in results:
            doc.metadata["_score"] = score
            doc.metadata["_score_kind"] = self.score_kind
        return [doc for doc, _ in results]

    def _get_relevant_documents(self, query: str, *, run_manager: CallbackManagerForRetrieverRun) -> list[Document]:
        """Retrieve documents synchronously, annotating each with its score."""
        return self._annotate(
            self.vector_store.similarity_search_with_score(query, k=self.k, score_threshold=self.score_threshold)
        )

    async def _aget_relevant_documents(
        self, query: str, *, run_manager: CallbackManagerForRetrieverRun
    ) -> list[Document]:
        """Async twin of the above.

        ``langchain_qdrant`` implements no async methods, so this resolves to
        the base class running the sync search in a thread pool. Calling it
        rather than the sync version is still what keeps the event loop free
        during the round trip.
        """
        return self._annotate(
            await self.vector_store.asimilarity_search_with_score(query, k=self.k, score_threshold=self.score_threshold)
        )


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
        self.retrieval_cfg = self.config["rag"]["retrieval"]
        self.rerank_cfg = self.config["rag"]["rerank"]
        self.ranking_cfg = self.config["rag"]["ranking"]

        # The collection name, embedding model and vector geometry are contracted
        # with services/db, not configured per service. Everything is checked
        # before the first query, so a writer/reader mismatch is a startup crash
        # naming the offending value rather than quietly wrong retrieval.
        self.contract = contract_mod.load()
        contract_mod.require_metadata(self.contract, *REQUIRED_METADATA)

        # Before anything expensive loads, so a bad combination is a startup
        # crash naming the fix rather than a pipeline that quietly returns
        # nothing.
        self._validate_config()

        self.embedding = HuggingFaceEmbeddings(model_name=self.contract.model)
        contract_mod.validate_embedding(self.contract, self.embedding)

        self.qdrant_client = QdrantClient(url=os.getenv("QDRANT_URL"), api_key=os.getenv("QDRANT_API_KEY"))
        contract_mod.validate_collection(self.contract, self.qdrant_client)
        logging.info(f"Qdrant collection {self.contract.name!r} matches conf/collection.yaml.")

        # Hybrid reads the BM25 sparse vector services/db has been writing on
        # every point since before anything queried it -- which is exactly why
        # turning it on here is a constructor change and not a re-index.
        #
        # Qdrant fuses the dense and sparse rankings with Reciprocal Rank
        # Fusion, so the score it returns is rank-derived and lands around 0.02,
        # nothing like a cosine similarity. Nothing may threshold on it; see
        # _validate_config.
        mode = self.retrieval_cfg["mode"]
        sparse_kwargs = {}
        if mode == "hybrid":
            from langchain_qdrant import FastEmbedSparse, RetrievalMode

            sparse_kwargs = {
                "sparse_embedding": FastEmbedSparse(model_name=self.contract.sparse_model),
                "sparse_vector_name": self.contract.sparse_vector_name,
                "retrieval_mode": RetrievalMode.HYBRID,
            }
        self.vector_store = QdrantVectorStore(
            collection_name=self.contract.name,
            embedding=self.embedding,
            client=self.qdrant_client,
            vector_name=self.contract.vector_name,
            **sparse_kwargs,
        )
        logging.info(f"Retrieval mode: {mode}")

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
            k=self.retrieval_cfg["k"],
            # Under hybrid this is None, enforced by _validate_config: the fused
            # score is a rank artefact and cannot be thresholded.
            score_threshold=self.retrieval_cfg["score_threshold"],
            score_kind="rrf" if mode == "hybrid" else "cosine",
        )

        # torch and sentence_transformers are imported lazily: together they are
        # the heaviest dependency in the image, and a deployment with the reranker
        # disabled should not pay to import them.
        if self.rerank_cfg["enabled"]:
            import torch
            from sentence_transformers import CrossEncoder

            # Sigmoid squashes the raw logit into 0..1 so `score_threshold` is a
            # probability-like cutoff that means the same thing across models.
            self.cross_encoder = CrossEncoder(self.rerank_cfg["model"], activation_fn=torch.nn.Sigmoid())
            logging.info(f"Cross-encoder reranker loaded: {self.rerank_cfg['model']}")
        else:
            self.cross_encoder = None

        # Retrieval is not a chain. It used to be, and the documents it found
        # were consumed inside the chain and never surfaced -- which is why the
        # backend could not tell the client which threads an answer came from,
        # and had to ask the model to reprint the links instead.
        #
        # Both retrieval-side steps always use the primary model, so thinking
        # tokens are never spent on reformulating a question.
        self._rewrite_chain = self.frame_qn_prompt | self.llm_primary | StrOutputParser()
        self.multiquery = MultiQueryRetriever.from_llm(
            retriever=self.retriever,
            llm=self.llm_primary,
            # Defaults to False, which would keep the rewritten query -- the one
            # built to be self-contained and retrieval-friendly -- from ever
            # reaching the index. Only the LLM's paraphrases of it would.
            include_original=True,
        )

        # One cross-encoder pass at a time. The Spaces run on two vCPUs, and
        # without this every concurrent request starts its own torch inference
        # and they thrash each other; serialising makes p95 better, not worse.
        self._rerank_gate = asyncio.Semaphore(1)

        # Two answer chains differing only in which model writes the answer.
        # This is the only LCEL left, and streaming is the reason it stays.
        self._answer_primary = self.prompt | self.llm_primary | StrOutputParser()
        self._answer_thinking = self.prompt | self.llm_thinking | StrOutputParser()

    def _validate_config(self) -> None:
        """Refuse to start on a configuration that cannot work.

        Every case here is one that would otherwise fail silently -- returning
        no documents, or filtering nothing at all -- rather than raising. A
        pipeline that answers "I don't have that information" to every question
        looks like a content problem, not a configuration one, and that is an
        expensive thing to debug.

        Raises:
            ValueError: With a message naming what to change.
        """
        rag_cfg = self.config["rag"]

        # The old shape. search_kwargs gets its own message because one of the
        # keys it carried was not merely renamed -- it never did anything.
        if "search_kwargs" in rag_cfg:
            raise ValueError(
                "conf/config.yaml: rag.search_kwargs was replaced by rag.retrieval. Its `k` is now "
                "rag.retrieval.k, and its `score_threshold` is now rag.rerank.score_threshold. Note that "
                "the old retrieval threshold never filtered anything: langchain_core pops score_threshold "
                "and applies it to the NORMALISED score (cosine + 1) / 2, so the configured 0.3 only "
                "excluded documents below a cosine similarity of -0.4. The cross-encoder cutoff was "
                "always the only real filter, which is why it is the only threshold left."
            )
        if "reranker" in rag_cfg:
            raise ValueError(
                "conf/config.yaml: rag.reranker was renamed to rag.rerank, which also now carries the "
                "relevance cutoff (score_threshold), the candidate ceiling (max_candidates), how many "
                "documents reach the prompt (top_n) and the per-post cap (max_per_post)."
            )

        mode = self.retrieval_cfg["mode"]
        if mode not in ("dense", "hybrid"):
            raise ValueError(f"conf/config.yaml: rag.retrieval.mode must be 'dense' or 'hybrid', not {mode!r}.")

        if mode == "hybrid":
            if self.retrieval_cfg["score_threshold"] is not None:
                raise ValueError(
                    "conf/config.yaml: rag.retrieval.score_threshold must be null when mode is hybrid. "
                    "Qdrant applies it to the Reciprocal Rank Fusion score, which is around 0.02, so any "
                    "value chosen for a cosine similarity discards every document and every answer becomes "
                    "'I don't have that information'. Filter with rag.rerank.score_threshold instead."
                )
            if not self.contract.sparse_vector_name:
                raise ValueError(
                    "conf/config.yaml: rag.retrieval.mode is hybrid, but conf/collection.yaml declares no "
                    "sparse vector, so there is no lexical index to fuse with. Use mode: dense."
                )
            if not self.rerank_cfg["enabled"]:
                raise ValueError(
                    "conf/config.yaml: rag.retrieval.mode is hybrid with rag.rerank.enabled false, which "
                    "leaves nothing filtering relevance at all -- the fused score is a rank artefact, not a "
                    "similarity, so it cannot be thresholded. Enable the reranker or use mode: dense."
                )

    async def search_query_for(self, question: str, chat_history: list) -> str:
        """Decide what string retrieval should actually search for.

        With chat history, the question may be elliptical -- "is it hard?" means
        nothing on its own -- so it is rewritten into a standalone query against
        the history. That rewrite is an LLM round trip.

        With no history there is nothing to resolve against, so the rewrite is
        skipped and the question is searched verbatim. The prompt's other job,
        expanding PESU abbreviations, is deliberately not worth a round trip
        here: the rewrite expands *alongside* the original rather than replacing
        it, so the abbreviation still reaches BM25 either way, and measurement
        shows lexical matching on those tokens is where hybrid retrieval earns
        its keep (see ``scripts/eval_retrieval.py``).

        Args:
            question: The user's question, as asked.
            chat_history: Prior turns, already alternating human/AI.

        Returns:
            The query to retrieve with.
        """
        if not chat_history:
            return question
        return await self._rewrite_chain.ainvoke({"input": question, "chat_history": chat_history})

    async def retrieve(self, question: str, chat_history: list) -> tuple[str, list[Document]]:
        """Find the documents that should answer a question.

        The stages are separate and ordered deliberately:

        1. **Rewrite** into a standalone query, when there is history to resolve.
        2. **Expand** into several phrasings and union what each retrieves.
        3. **Deduplicate** on the stored point id. This must come before
           reranking, or the cross-encoder pays to score the same point twice.
        4. **Truncate** the candidate pool, bounding time-to-first-token.
        5. **Rerank** against the search query -- not the original question. For
           a follow-up the original may be contentless, and scoring "is it
           hard?" against a comment tree produces noise. This is also where the
           relevance cutoff is applied, and it is the only filter.
        6. **Blend** in recency and endorsement. Strictly after the cutoff, so
           these only reorder documents that already answer the question.
        7. **Diversify**, so one thread cannot fill the whole context window.

        Args:
            question: The user's question, as asked.
            chat_history: Prior turns, already alternating human/AI.

        Returns:
            ``(search_query, documents)``. The query is returned because the
            caller needs to know what was actually searched for.
        """
        search_query = await self.search_query_for(question, chat_history)
        docs = deduplicate(await self.multiquery.ainvoke(search_query))

        # Bound what reaches the cross-encoder. Every pair is CPU-bound torch
        # inference paid before the first token, and the multi-query step
        # decides how many phrasings to invent, so without a ceiling the
        # time-to-first-token is set by the LLM's verbosity.
        docs.sort(key=lambda d: d.metadata.get("_score", 0.0), reverse=True)
        docs = docs[: self.rerank_cfg["max_candidates"]]

        docs = await self.rerank(search_query, docs)
        docs = blend(docs, time.time(), self.ranking_cfg)
        docs = diversify(docs, self.rerank_cfg["top_n"], self.rerank_cfg["max_per_post"])
        return search_query, docs

    def format_docs(self, docs: list[Document]) -> str:
        """Flatten retrieved documents into the ``{context}`` block of the answer prompt.

        Documents from the same post are grouped under one heading. Each is
        stored as a TITLE line, a CONTENT line and then the COMMENT TREE, where
        the first two are the submission's and identical across every comment
        tree on that post. Corpus-wide that prefix is 54% of a median document,
        so repeating it per document is pure waste.

        In practice the saving here is small -- 0 to 2% on real queries --
        because :func:`diversify` runs first and usually leaves at most one
        document per post, so there is rarely a prefix left to collapse. The
        two overlap, and diversity gets there first. This still matters when a
        post genuinely contributes several comment trees, and would matter much
        more if ``max_per_post`` were raised.

        Each group is prefixed with the thread's permalink, which is what the
        answer cites. `permalink` rather than `url` because for a link post
        `url` is the external article, not the discussion the answer came from.

        Order matters -- the model weights earlier context more heavily -- so
        documents arrive best-first and that order is preserved, with the
        caveat that grouping pulls a lower-ranked document up next to its
        higher-ranked sibling. That is acceptable because the two are the same
        thread and equally attributable.

        Args:
            docs: Documents surviving retrieval, reranking and diversification,
                already ordered best first.

        Returns:
            The documents as one blank-line-separated string.
        """
        blocks: list[list[str]] = []
        index_of: dict[str, int] = {}
        for doc in docs:
            post_id = doc.metadata.get("post_id")
            head, separator, tree = doc.page_content.partition("COMMENT TREE:")
            # A document that does not carry the expected layout is emitted
            # whole rather than dropped or mangled.
            if not separator:
                blocks.append([f"{doc.metadata['permalink']}\n{doc.page_content}"])
                continue
            seen = index_of.get(post_id) if post_id is not None else None
            if seen is None:
                if post_id is not None:
                    index_of[post_id] = len(blocks)
                blocks.append([f"{doc.metadata['permalink']}\n{head.rstrip()}", f"{separator}{tree}"])
            else:
                blocks[seen].append(f"{separator}{tree}")
        return "\n\n".join("\n".join(block) for block in blocks)

    async def rerank(self, query: str, docs: list[Document]) -> list[Document]:
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

        The model call is a synchronous, CPU-bound torch inference. It runs in a
        worker thread rather than inline, because inline it would block the
        event loop for every other request streaming at the same time, and
        behind a semaphore, because two vCPUs cannot usefully run several torch
        inferences at once.

        Args:
            query: What retrieval actually searched for -- the rewritten query
                when there was history, not necessarily the user's wording.
            docs: Documents to score.

        Returns:
            The documents that cleared the threshold, best first.
        """
        if self.cross_encoder is None or not docs:
            return docs

        # The cross-encoder's own sigmoid scale, and the only relevance filter
        # in the pipeline. Deliberately not shared with retrieval, which under
        # hybrid has no thresholdable score at all.
        threshold = self.rerank_cfg["score_threshold"]
        pairs = [[query, doc.page_content] for doc in docs]
        async with self._rerank_gate:
            scores = await asyncio.to_thread(self.cross_encoder.predict, pairs)

        reranked = []
        for doc, score in zip(docs, scores):
            if float(score) >= threshold:
                doc.metadata["_score"] = float(score)
                reranked.append(doc)

        reranked.sort(key=lambda d: d.metadata["_score"], reverse=True)
        logging.debug(f"Reranker: {len(docs)} → {len(reranked)} docs above threshold {threshold}")
        return reranked

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

        answer_chain = self._answer_thinking if thinking else self._answer_primary

        logging.info(f"Using {'thinking' if thinking else 'primary'} LLM for query: {query}")

        # Streaming state. `pending` buffers characters that might be a partial
        # </think> tag; see _process_thinking_chunk.
        thinking_done = False
        pending = ""
        token_count = 0

        try:
            # Retrieval runs to completion before the answer starts streaming.
            # It always did -- the chain could not stream a token before it had
            # its context either -- but now the documents are in hand here,
            # which is what lets the stream report its own sources.
            search_query, docs = await self.retrieve(query, chat_history)
            logging.info(f"Retrieved {len(docs)} documents for {search_query!r}")

            # Before the first token, so a client can render citations while the
            # answer is still being written. Emitted even when empty, so the UI
            # can distinguish "no sources" from "sources not sent yet".
            yield json.dumps({"type": "sources", "sources": describe_sources(docs)}) + "\n"

            async for chunk in answer_chain.astream(
                {
                    "question": query,
                    "context": self.format_docs(docs),
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
