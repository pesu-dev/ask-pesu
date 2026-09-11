"""The retrieval-augmented generation pipeline behind ``POST /ask``.

One :class:`RetrievalAugmentedGenerator` is built during the FastAPI lifespan and
reused for every request; construction loads an embedding model and optionally a
cross-encoder, so it is far too expensive to do per request.

A question travels through seven stages:

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
   and drops anything below the configured threshold. This is the only stage
   that filters, and it filters rather than orders: its scores separate the
   surviving documents by only a few percent.
6. **Rank.** Upvotes on the answer decide the order of what survived. Strictly
   after the cutoff, so it reorders only documents that already answer the
   question. The sort is stable, so documents with equal upvotes keep the
   relevance order they arrived in. The best ``top_n`` go on.
7. **Generate.** The surviving documents are formatted into the answer prompt and
   streamed from the LLM token by token, after the threads they came from have
   been reported as a ``sources`` event.

Stages 1 and 2 always use the *primary* model even in thinking mode, so thinking
tokens are never spent on query rewriting.

Only the last stage is a LangChain Expression Language (LCEL) chain, because
streaming is what LCEL is for here. The retrieval stages run explicitly instead:
expressed as a chain they emit only the answer text, and the documents they
found stay inside it, which leaves the backend unable to tell a client which
threads an answer was drawn from except by asking the model to reprint the
links. Running them explicitly is what makes the documents available to
:meth:`RetrievalAugmentedGenerator.generate`.

The collection name, embedding model and vector geometry are not configured here.
They are contracted with ``services/db`` in ``conf/collection.yaml`` and verified
at startup; see :mod:`app.contract`.
"""

import asyncio
import datetime
import json
import logging
import math
import os
import re
from collections.abc import AsyncGenerator, Callable

import yaml
from dotenv import load_dotenv
from huggingface_hub import InferenceClient, whoami
from langchain_classic.retrievers import MultiQueryRetriever
from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents.base import Document
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder, PromptTemplate
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

# Where a thinking-mode stream has got to. Three states rather than a "done"
# flag, because "not done" conflated two very different situations: inside a
# reasoning block, and not yet knowing whether there is one. Treating the
# second as the first is what made a model that emits no <think> at all --
# a different repo_id, or a provider that moves reasoning into its own field
# -- render its entire answer as reasoning.
PHASE_START = "start"  # nothing decided yet; the opening tag may still arrive
PHASE_THINKING = "thinking"  # inside the block, waiting for </think>
PHASE_ANSWER = "answer"  # past it, or there never was one: all answer now

# Payload keys read out of retrieved documents. Checked against the contract at
# startup so removing one from conf/collection.yaml fails here rather than as a
# KeyError on the first query.
#
# `permalink`, not `url`: for a self post the two agree, but for a link post
# `url` is the external article being discussed rather than the discussion
# itself. Answers are synthesised from the comment thread, so citing `url` there
# would send the reader to a page that does not contain what was cited.
#
# `post_id` groups documents that share a post, so the repeated post title and
# body is emitted once rather than per document. `root_comment_score` is the
# ranking signal.
REQUIRED_METADATA = ("permalink", "post_id", "root_comment_score")


# The two ways the provider refuses us for want of budget rather than for a bad
# request. 429 is a rate limit and clears on its own; 402 means the account's
# included inference credits are spent and clears when they renew, which is a
# very different wait -- see :func:`credits_reset_at`.
_REFUSAL_STATUSES = (402, 429)


def _quota_refusal(error: BaseException) -> int | None:
    """Classify a failure as the provider refusing us on budget, or not.

    ``huggingface_hub`` raises ``HfHubHTTPError`` with the response attached, so
    the status code is available and exact; the string matching is only a
    fallback for anything that loses it. Getting this wrong in one direction
    costs an unnecessary cooldown, and in the other means hammering a provider
    that is already refusing us -- and, worse, showing the user a raw HTTP error
    with a billing URL in it.

    A 402 is why the status code is checked first rather than the message: it
    reads "You have depleted your monthly included credits", which contains none
    of the words matched below.

    Args:
        error: The exception raised during generation.

    Returns:
        The refusing status code, or None if this was some other failure.
    """
    status = getattr(getattr(error, "response", None), "status_code", None)
    if status in _REFUSAL_STATUSES:
        return status
    text = str(error).lower()
    for marker, code in (
        ("too many requests", 429),
        ("rate limit", 429),
        ("429", 429),
        ("payment required", 402),
        ("credits", 402),
        ("402", 402),
        ("quota", 429),
    ):
        if marker in text:
            return code
    return None


def credits_reset_at() -> datetime.datetime | None:
    """Ask Hugging Face when this account's included credits renew.

    ``whoami`` reports ``periodEnd``, a POSIX timestamp, which is the only
    authoritative answer to "when will this work again" after a 402. There is no
    endpoint that reports a remaining balance, and inference responses carry no
    quota headers at all, so this cannot be checked in advance -- only after
    being refused.

    Returns:
        When the credits renew, or None if the lookup fails for any reason. The
        caller then falls back to its default cooldown; this runs inside error
        handling and must not raise.
    """
    try:
        period_end = whoami(token=os.getenv("HF_TOKEN")).get("periodEnd")
        if period_end is None:
            return None
        return datetime.datetime.fromtimestamp(float(period_end), datetime.UTC)
    except Exception as error:
        logging.warning(f"Could not read the credit reset time from Hugging Face: {error}")
        return None


# Two or more characters of capitals and digits: how the corpus writes the tokens
# the lexical half of retrieval matches on -- CSE, RR, SGPA, PESSAT, T1, AIML.
# A pattern rather than a list, so there is no vocabulary to keep in step with
# the rewrite prompt's.
ACRONYM = re.compile(r"\b[A-Z][A-Z0-9]+\b")


def preserve_acronyms(rewritten: str, question: str, fallback: str = "") -> str:
    """Put back any acronym the rewrite expanded away instead of keeping.

    The rewrite prompt is told to expand an abbreviation *alongside* the
    original -- "CSE (Computer Science Engineering)" -- because BM25 matches the
    literal token and the threads themselves say CSE. It obeys that for
    abbreviations in the question and drops it for ones it resolves out of the
    chat history: "is it hard?" against a conversation about CSE at RR comes
    back as "Computer Science Engineering at the Ring Road campus", with both
    tokens gone. That costs the whole of hybrid retrieval's advantage on the
    request, since every alternative phrasing is written from the rewritten
    query and inherits the loss.

    ``fallback`` is consulted only when the question carries no acronym of its
    own. A question that names one has already said what it is about, and
    reaching into the previous turn then drags the topic the user just left back
    into the query -- "what about ECE?" would be searched for CSE as well.

    Appended rather than substituted, because where they belong in the sentence
    is not knowable from the text. The query is only ever embedded, matched and
    handed to the reranker, never shown to anyone, so trailing tokens cost
    nothing but the space they take.

    Args:
        rewritten: What the rewrite returned.
        question: The user's question, as asked.
        fallback: The turn being resolved against, used only when ``question``
            has no acronym.

    Returns:
        The rewritten query, with any lost acronym appended.
    """
    wanted = ACRONYM.findall(question) or ACRONYM.findall(fallback)
    present = set(ACRONYM.findall(rewritten))
    missing: list[str] = []
    for token in wanted:
        if token not in present and token not in missing:
            missing.append(token)
    return f"{rewritten} {' '.join(missing)}" if missing else rewritten


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


def _created_utc(doc: Document) -> float | None:
    """The thread's timestamp, or None when it is missing or not a number.

    This is the SUBMISSION's time, not the root comment's. It tracks the age of
    the discussion closely -- root comments arrive within a day of the post
    about nine times in ten -- but it is not the answer's own date, so do not
    present it as one.

    Qdrant round-trips payloads through JSON, so a value that was written as a
    string comes back as one; anything not already a number is dropped rather
    than coerced, since a citation is not worth failing a request over.

    Non-finite and non-positive values are dropped too. A NaN would reach the
    stream as the bare token ``NaN``, which ``json.dumps`` emits happily and
    ``JSON.parse`` rejects -- one bad payload would break the client mid-answer.
    """
    value = doc.metadata.get("created_utc")
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    value = float(value)
    return value if math.isfinite(value) and value > 0 else None


def _thread_month(doc: Document) -> str:
    """The thread's month and year for the context block, or "" if unknown.

    Month rather than a full date: the model is being told roughly how old an
    answer is so it can say so, and a precise day would invite it to quote one.
    """
    created = _created_utc(doc)
    if created is None:
        return ""
    try:
        return datetime.datetime.fromtimestamp(created, tz=datetime.UTC).strftime("%B %Y")
    except (OverflowError, OSError, ValueError):
        return ""


def _heading(doc: Document) -> str:
    """The line a thread's block in the context is prefixed with.

    Empty when the document carries no permalink, in which case the block is
    still emitted -- losing a citation beats losing the answer.
    """
    permalink = doc.metadata.get("permalink")
    if not permalink:
        return ""
    month = _thread_month(doc)
    return f"{permalink} (posted {month})\n" if month else f"{permalink}\n"


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
    collapsed to one entry per post, keeping the first (best-ranked).

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
        out.append(
            {
                "permalink": permalink,
                "title": title or permalink,
                "snippet": snippet,
                "created_utc": _created_utc(doc),
            }
        )
    return out


def rank(docs: list[Document]) -> list[Document]:
    """Order documents by how the community received the answer.

    Upvotes on the ROOT COMMENT, not on the post. The post's score is identical
    across every document from one post and so ranks none of them, and it cannot
    go negative, which makes a rejected answer indistinguishable from an unrated
    one. The comment's score does both.

    Sorted directly on the raw count, with no normalisation and no scale
    constant. A bounded 0..1 factor would only be needed to *multiply*
    endorsement with relevance; ordering needs no such thing, because sorting is
    invariant to monotonic transforms -- ranking by ``log(score)/log(25)`` gives
    exactly the ranking of ``score``. Removing the multiplication removes the
    constant, and with it the only value in the configuration that was derived
    from a snapshot of the corpus and would drift as it grew.

    **The sort is stable, and that is load-bearing.** Documents arrive in
    cross-encoder order, and most answers carry very few upvotes, so ties are
    the common case -- and a tie keeps the relevance order it came in with. The
    effect is "upvotes where they differ, relevance where they do not", without
    either being expressed as a weight.

    A missing score sorts as zero: neither endorsed nor rejected, so it sits
    above genuinely downvoted answers and below genuinely upvoted ones.

    Args:
        docs: Documents that already cleared the relevance cutoff, in
            cross-encoder order.

    Returns:
        The same documents, best first.
    """

    def upvotes(doc: Document) -> float:
        score = doc.metadata.get("root_comment_score")
        return float(score) if isinstance(score, int | float) and not isinstance(score, bool) else 0.0

    return sorted(docs, key=upvotes, reverse=True)


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
    produced.

    Note the scale therefore depends on the mode: a cosine similarity under
    ``dense``, a Reciprocal Rank Fusion score under ``hybrid`` -- which is
    derived from rank position rather than similarity, and lives on a far
    smaller scale. Nothing compares scores across modes, and nothing may
    threshold the fused one.

    ``_score`` is locally attached, not part of the payload written by
    ``services/db``, and is not in the collection contract.
    """

    vector_store: QdrantVectorStore
    k: int
    score_threshold: float | None = None

    def _annotate(self, results: list[tuple[Document, float]]) -> list[Document]:
        """Attach each score to its document."""
        for doc, score in results:
            doc.metadata["_score"] = score
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
        self.sources_cfg = self.config["rag"]["sources"]
        self.history_cfg = self.config["rag"]["history"]

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
        # Fusion, so the score it returns is derived from rank position rather
        # than similarity and is nothing like a cosine. Nothing may threshold on
        # it; see _validate_config.
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

        # Answer prompt: system rules (answer only from context, do not
        # reprint the sources, refuse off-topic questions), then the recent
        # conversation, then the human turn carrying {question} and the
        # retrieved {context}.
        #
        # The history is there so a follow-up can be understood -- "what about
        # ECE?" says nothing on its own. It is also a second and far more
        # convenient source of facts than the context, because it holds this
        # model's own previous answers, so the system prompt carries a rule
        # forbidding answering from it. The two are a pair; neither works alone.
        #
        # The retrieved context sits in the final turn, after the history, so
        # what the answer must be drawn from is what the model read last.
        self.prompt = ChatPromptTemplate.from_messages(
            [
                ("system", self.config["rag"]["prompts"]["system_prompt"]),
                MessagesPlaceholder("chat_history"),
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

        # Retrieval is assembled from parts rather than composed into a chain,
        # so `retrieve` can hand the documents back to the caller. A chain would
        # consume them internally and yield only text, leaving nothing to report
        # as the answer's sources.
        #
        # Both retrieval-side steps always use the primary model, so thinking
        # tokens are never spent on reformulating a question.
        self._rewrite_chain = self.frame_qn_prompt | self.llm_primary | StrOutputParser()
        self.multiquery = MultiQueryRetriever.from_llm(
            retriever=self.retriever,
            llm=self.llm_primary,
            prompt=self._multi_query_prompt(),
            # Defaults to False, which would keep the rewritten query -- the one
            # built to be self-contained and retrieval-friendly -- from ever
            # reaching the index. Only the LLM's paraphrases of it would.
            include_original=True,
        )

        # Cross-encoder passes allowed at once. Serialised by default because a
        # cpu-basic Space has two vCPUs, and concurrent torch inferences thrash
        # rather than overlap.
        self._rerank_gate = asyncio.Semaphore(self.rerank_cfg["concurrency"])

        # Two answer chains differing only in which model writes the answer.
        # This is the only LCEL left, and streaming is the reason it stays.
        self._answer_primary = self.prompt | self.llm_primary | StrOutputParser()
        self._answer_thinking = self.prompt | self.llm_thinking | StrOutputParser()

    def _multi_query_prompt(self) -> PromptTemplate:
        """Build the prompt that writes the alternative phrasings.

        Supplied rather than left to the library, whose default prompt hardcodes
        "3 different versions" in its wording -- so the count cannot be
        configured without replacing the prompt outright.

        ``{count}`` is substituted here rather than declared as an input
        variable, because it is fixed for the life of the process and the
        retriever only ever passes ``{question}``.

        Returns:
            A prompt template taking ``question``.
        """
        template = self.config["rag"]["prompts"]["multi_query_prompt"]
        return PromptTemplate(
            input_variables=["question"],
            template=template.replace("{count}", str(self.retrieval_cfg["query_expansions"])),
        )

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

        # Blocks that this file no longer reads. Each is refused rather than
        # ignored, because a stale block is set by somebody who expects it to do
        # something, and silently doing nothing is the worst answer available.
        for stale, guidance in (
            (
                "search_kwargs",
                "its `k` is now rag.retrieval.k and its `score_threshold` is now rag.rerank.score_threshold",
            ),
            ("reranker", "it is now rag.rerank, which also carries score_threshold and top_n"),
            ("ranking", "ranking is a sort on the answer's upvotes and takes no weights; remove the block"),
        ):
            if stale in rag_cfg:
                raise ValueError(f"conf/config.yaml: rag.{stale} is not read -- {guidance}.")

        answer_turns = self.history_cfg["answer_turns"]
        if not isinstance(answer_turns, int) or isinstance(answer_turns, bool) or answer_turns < 0:
            raise ValueError(
                f"conf/config.yaml: rag.history.answer_turns must be a non-negative integer, not "
                f"{answer_turns!r}. It slices the conversation from the end, so a negative value "
                f"drops the OLDEST turns and keeps every other one -- the prompt would then grow "
                f"with the conversation, which is the one thing this setting exists to stop."
            )

        mode = self.retrieval_cfg["mode"]
        if mode not in ("dense", "hybrid"):
            raise ValueError(f"conf/config.yaml: rag.retrieval.mode must be 'dense' or 'hybrid', not {mode!r}.")

        if mode == "hybrid":
            if self.retrieval_cfg["score_threshold"] is not None:
                raise ValueError(
                    "conf/config.yaml: rag.retrieval.score_threshold must be null when mode is hybrid. "
                    "Qdrant applies it to the fused score, which is derived from rank position rather "
                    "than similarity and lives on a far smaller scale, so a value chosen for a cosine "
                    "similarity discards every document and every answer becomes 'I don't have that "
                    "information'. Filter with rag.rerank.score_threshold instead."
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
        skipped and the question is searched verbatim -- which also keeps its
        abbreviations, and lexical matching on those tokens is where hybrid
        retrieval earns its keep.

        What comes back is passed through :func:`preserve_acronyms`, because the
        rewrite drops those tokens when it resolves them out of the history.

        Args:
            question: The user's question, as asked.
            chat_history: Prior turns, already alternating human/AI.

        Returns:
            The query to retrieve with.
        """
        if not chat_history:
            return question
        rewritten = await self._rewrite_chain.ainvoke({"input": question, "chat_history": chat_history})
        # The turn being resolved against, which is where an elliptical question
        # gets its subject. The most recent one only: the rewrite prompt is told
        # to prefer the most recent topic, so reaching further back would put
        # tokens from an abandoned one into the query.
        recent = next((m.content for m in reversed(chat_history) if isinstance(m, HumanMessage)), "")
        return preserve_acronyms(rewritten, question, recent)

    async def retrieve(self, question: str, chat_history: list) -> tuple[str, list[Document]]:
        """Find the documents that should answer a question.

        The stages are separate and ordered deliberately:

        1. **Rewrite** into a standalone query, when there is history to resolve.
        2. **Expand** into several phrasings and union what each retrieves.
        3. **Deduplicate** on the stored point id. This must come before
           reranking, or the cross-encoder pays to score the same point twice.
        4. **Rerank** against the search query -- not the original question. For
           a follow-up the original may be contentless, and scoring "is it
           hard?" against a comment tree produces noise. This is also where the
           relevance cutoff is applied, and it is the only place anything is
           discarded for being a poor answer.
        5. **Rank** by upvotes on the answer. Strictly after the cutoff, so
           this only reorders documents that already answer the question.

        Args:
            question: The user's question, as asked.
            chat_history: Prior turns, already alternating human/AI.

        Returns:
            ``(search_query, documents)``. The query is returned because the
            caller needs to know what was actually searched for.
        """
        search_query = await self.search_query_for(question, chat_history)
        docs = deduplicate(await self.multiquery.ainvoke(search_query))

        docs = await self.rerank(search_query, docs)
        docs = rank(docs)
        return search_query, docs[: self.rerank_cfg["top_n"]]

    def format_docs(self, docs: list[Document]) -> str:
        """Flatten retrieved documents into the ``{context}`` block of the answer prompt.

        Documents from the same post are grouped under one heading. Each is
        stored as a TITLE line, a CONTENT line and then the COMMENT TREE, where
        the first two are the submission's and identical across every comment
        tree on that post -- often a large share of the document, so repeating
        it once per answer is waste.

        Nothing caps how many documents one post contributes, so this is what
        keeps several answers from the same post affordable: they share one
        heading and the post body is written once rather than per answer.

        Each group is prefixed with the thread's permalink, which is what the
        answer cites. `permalink` rather than `url` because for a link post
        `url` is the external article, not the discussion the answer came from.
        A document that somehow carries no permalink is still emitted, without
        the heading: :func:`describe_sources` takes the same view, and losing a
        citation is a far smaller failure than losing the answer.

        Order matters -- the model weights earlier context more heavily -- so
        documents arrive best-first and that order is preserved, with the
        caveat that grouping pulls a lower-ranked document up next to its
        higher-ranked sibling. That is acceptable because the two are the same
        thread and equally attributable.

        Args:
            docs: Documents surviving retrieval and reranking, already
                ordered best first.

        Returns:
            The documents as one blank-line-separated string.
        """
        blocks: list[list[str]] = []
        index_of: dict[str, int] = {}
        for doc in docs:
            post_id = doc.metadata.get("post_id")
            heading = _heading(doc)
            head, separator, tree = doc.page_content.partition("COMMENT TREE:")
            # A document that does not carry the expected layout is emitted
            # whole rather than dropped or mangled.
            if not separator:
                blocks.append([f"{heading}{doc.page_content}"])
                continue
            seen = index_of.get(post_id) if post_id is not None else None
            if seen is None:
                if post_id is not None:
                    index_of[post_id] = len(blocks)
                blocks.append([f"{heading}{head.rstrip()}", f"{separator}{tree}"])
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

    def _process_thinking_chunk(self, chunk: str, pending: str, phase: str) -> tuple[str, str, list[dict]]:
        """Split one streamed chunk into reasoning (``step``) and answer (``token``) events.

        A thinking model emits ``<think>reasoning</think>answer``, but the stream
        arrives in arbitrary chunks, so either tag can be split across a chunk
        boundary -- ``"...</thi"`` then ``"nk>..."``. Emitting eagerly would leak
        a fragment of the closing tag into the visible reasoning and then fail to
        recognise the tag at all.

        The fix is a small buffer: hold back the last ``len("</think>") - 1``
        characters, which is the longest prefix of the tag that could still be
        completed by the next chunk, and emit everything before it. Once the tag
        is seen the buffer is no longer needed and later chunks pass straight
        through as answer tokens.

        The opening tag is decided the same way. Until enough has arrived to tell
        whether the stream opens with ``<think>``, nothing is emitted; a stream
        that turns out not to open with it is answer text from the first
        character, not reasoning.

        Args:
            chunk: Newly received text.
            pending: Characters withheld from previous chunks.
            phase: Where the stream has got to; one of the ``PHASE_*`` values.

        Returns:
            ``(pending, phase, events)`` -- the updated buffer, the updated
            phase, and the events to emit for this chunk.
        """
        if phase == PHASE_ANSWER:
            return pending, phase, [{"type": "token", "content": chunk}]

        pending += chunk

        if phase == PHASE_START:
            # Leading whitespace before the tag is not reasoning, and dropping it
            # from an answer costs nothing either.
            opening = pending.lstrip()
            if opening.startswith(THINK_START):
                pending = opening[len(THINK_START) :]
                phase = PHASE_THINKING
            elif THINK_START.startswith(opening[: len(THINK_START)]):
                # Still short of the tag, and still consistent with it.
                return pending, phase, []
            else:
                return "", PHASE_ANSWER, [{"type": "token", "content": opening}]

        events: list[dict] = []
        if THINK_END in pending:
            index = pending.index(THINK_END)
            step_part = pending[:index]
            token_part = pending[index + len(THINK_END) :]
            pending = ""
            phase = PHASE_ANSWER

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

        return pending, phase, events

    def _flush_pending(self, pending: str, phase: str) -> list[dict]:
        """Emit whatever is left once the stream ends.

        Reaching here still in ``PHASE_THINKING`` means the model never closed
        its ``<think>`` block, which in practice means ``max_new_tokens`` ran out
        while it was still reasoning. There is no answer in that case: what the
        buffer holds is the tail of the reasoning, at most a few characters, and
        emitting it as the answer produced a reply like "nothing" -- which reads
        as a real answer and is worse than admitting the failure. It goes out as
        reasoning, and the stream reports an error.
        """
        if phase == PHASE_THINKING:
            logging.warning("</think> never arrived; the answer budget ran out during reasoning.")
            events: list[dict] = [{"type": "step", "content": pending}] if pending else []
            events.append(
                {
                    "type": "error",
                    "content": (
                        "The model spent its whole answer budget on reasoning and never began the "
                        "answer. Ask again, or use normal mode."
                    ),
                }
            )
            return events
        return [{"type": "token", "content": pending}] if pending else []

    async def generate(
        self,
        query: str,
        thinking: bool,
        history: list,
        on_quota_exceeded: Callable[[datetime.datetime | None], None] | None = None,
    ) -> AsyncGenerator[str, None]:
        """Run the pipeline and yield newline-delimited JSON events.

        Each yielded string is one complete JSON object plus a newline, so the
        client can parse incrementally without buffering the whole response:

        - ``{"type": "sources", "sources": [...]}`` the threads retrieval
          selected, sent once, before the first token
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
            on_quota_exceeded: Called if the provider refused us on budget,
                with the time the refusal is expected to lift (or None to let
                the caller pick). Lets the caller start a cooldown without this
                module knowing about quota state.

        Yields:
            NDJSON lines, each terminated by a newline.
        """
        logging.info(f"Received query: {query} with thinking={thinking} and history of length {len(history)}")

        # Conversations live only in the browser, so the client replays history
        # on every request. Skip any turn whose query equals the current one:
        # clients may include the in-flight question, and feeding it back as
        # already-answered confuses the rewrite step.
        turns = [(HumanMessage(convo.query), AIMessage(convo.answer)) for convo in history if query != convo.query]
        chat_history = [message for turn in turns for message in turn]

        # What the ANSWER prompt sees, which is not what retrieval sees, in two
        # ways.
        #
        # Only whole turns. The client sends a turn with an empty answer when
        # one was aborted or failed, deliberately, because the question still
        # says what the user was asking about. Rendered into the rewrite
        # prompt's text that is harmless, but here it would become a real empty
        # assistant message in the chat completion, which providers variously
        # reject or answer strangely.
        #
        # And only the last few. The rewrite step keeps the whole conversation,
        # because the thing a follow-up refers to can be several turns back; the
        # answer only has to know what is being asked now, and every turn it
        # carries is a full previous answer sitting alongside the retrieved
        # documents. `history` itself has no ceiling, so without this the prompt
        # grows with the conversation and nothing stops it.
        answer_turns = self.history_cfg["answer_turns"]
        complete = [turn for turn in turns if turn[0].content.strip() and turn[1].content.strip()]
        recent_history = [message for turn in complete[-answer_turns:] for message in turn] if answer_turns else []

        answer_chain = self._answer_thinking if thinking else self._answer_primary

        logging.info(f"Using {'thinking' if thinking else 'primary'} LLM for query: {query}")

        # Streaming state. `pending` buffers characters that might be a partial
        # <think> or </think> tag; see _process_thinking_chunk.
        phase = PHASE_START
        pending = ""
        token_count = 0

        try:
            # Retrieval runs to completion before the answer starts
            # streaming, which is unavoidable -- nothing can be generated
            # without context. Holding the documents here rather than inside a
            # chain is what lets the stream report its own sources.
            search_query, docs = await self.retrieve(query, chat_history)
            logging.info(f"Retrieved {len(docs)} documents for {search_query!r}")

            # Before the first token, so a client can render citations while the
            # answer is still being written. Emitted even when empty, so the UI
            # can distinguish "no sources" from "sources not sent yet".
            sources = describe_sources(docs, self.sources_cfg["snippet_chars"])
            yield json.dumps({"type": "sources", "sources": sources}) + "\n"

            async for chunk in answer_chain.astream(
                {
                    "question": query,
                    "context": self.format_docs(docs),
                    "chat_history": recent_history,
                }
            ):
                token_count += 1

                # Normal mode has no reasoning to separate, so chunks pass
                # straight through as answer tokens.
                if not thinking:
                    yield json.dumps({"type": "token", "content": chunk}) + "\n"
                    continue

                pending, phase, events = self._process_thinking_chunk(chunk, pending, phase)
                for event in events:
                    yield json.dumps(event) + "\n"

            # Not guarded on `pending`: a reasoning block that never closed has
            # an error to report whether or not anything is still buffered.
            for event in self._flush_pending(pending, phase):
                yield json.dumps(event) + "\n"
            logging.info(f"Stream complete. Total chunks: {token_count}")
        except Exception as e:
            logging.error(f"Error in generate(): {str(e)}", exc_info=True)
            refusal = _quota_refusal(e)
            if on_quota_exceeded is not None and refusal is not None:
                # Tell the caller to start a cooldown so subsequent requests are
                # rejected up front instead of failing mid-stream. A 402 waits
                # for the billing period to roll over, which is knowable exactly
                # and is usually much longer than a rate-limit cooldown.
                on_quota_exceeded(credits_reset_at() if refusal == 402 else None)
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
