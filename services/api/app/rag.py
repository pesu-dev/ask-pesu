"""Retrieval-Augmented Generation (RAG) pipeline implementation using LangChain and Qdrant."""

import json
import logging
import os
from collections.abc import AsyncGenerator
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

from app.contract import CollectionContract

load_dotenv()

THINK_START = "<think>"
THINK_END = "</think>"

# Payload keys read out of retrieved documents. Checked against the contract at
# startup so removing one from conf/collection.yaml fails here rather than as a
# KeyError on the first query.
REQUIRED_METADATA = ("url",)


class ScoredRetriever(BaseRetriever):
    """Thin wrapper around QdrantVectorStore that attaches relevance scores to doc.metadata['_score']."""

    vector_store: QdrantVectorStore
    search_kwargs: dict

    def _get_relevant_documents(self, query: str, *, run_manager: CallbackManagerForRetrieverRun) -> list[Document]:
        results = self.vector_store.similarity_search_with_relevance_scores(query, **self.search_kwargs)
        for doc, score in results:
            doc.metadata["_score"] = score
        return [doc for doc, _ in results]

    async def _aget_relevant_documents(
        self, query: str, *, run_manager: CallbackManagerForRetrieverRun
    ) -> list[Document]:
        results = await self.vector_store.asimilarity_search_with_relevance_scores(query, **self.search_kwargs)
        for doc, score in results:
            doc.metadata["_score"] = score
        return [doc for doc, _ in results]


class RetrievalAugmentedGenerator:
    """A class that encapsulates the Retrieval-Augmented Generation (RAG) pipeline."""

    def __init__(self, config_path: str = "conf/config.yaml") -> None:
        """Initialize the RAG pipeline components."""
        InferenceClient(api_key=os.environ["HF_TOKEN"])

        with open(config_path) as file:
            self.config = yaml.safe_load(file)

        # The collection name, embedding model and vector geometry are contracted
        # with services/db, not configured per service. Everything is checked
        # before the first query, so a writer/reader mismatch is a startup crash
        # naming the offending value rather than quietly wrong retrieval.
        self.contract = CollectionContract.load()
        self.contract.require_metadata(*REQUIRED_METADATA)

        self.embedding = HuggingFaceEmbeddings(model_name=self.contract.model)
        self.contract.validate_embedding(self.embedding)

        self.qdrant_client = QdrantClient(url=os.getenv("QDRANT_URL"), api_key=os.getenv("QDRANT_API_KEY"))
        self.contract.validate_collection(self.qdrant_client)
        logging.info(f"Qdrant collection {self.contract.name!r} matches conf/collection.yaml.")

        self.vector_store = QdrantVectorStore(
            collection_name=self.contract.name,
            embedding=self.embedding,
            client=self.qdrant_client,
            vector_name=self.contract.vector_name,
        )

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

        self.prompt = ChatPromptTemplate.from_messages(
            [
                ("system", self.config["rag"]["prompts"]["system_prompt"]),
                ("human", self.config["rag"]["prompts"]["answer_prompt"]),
            ]
        )

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

        reranker_cfg = self.config["rag"].get("reranker", {})
        if reranker_cfg.get("enabled", False):
            import torch
            from sentence_transformers import CrossEncoder

            self.cross_encoder = CrossEncoder(reranker_cfg["model"], activation_fn=torch.nn.Sigmoid())
            logging.info(f"Cross-encoder reranker loaded: {reranker_cfg['model']}")
        else:
            self.cross_encoder = None

        self.rag_chain_primary = self._build_chain(self.llm_primary)
        self.rag_chain_thinking = self._build_chain(self.llm_thinking) if self.llm_thinking else None

    def _build_chain(self, llm: BaseChatModel) -> RunnableSerializable[str, str]:
        # Always use llm_primary for retrieval steps — never burn thinking-model
        # tokens on question rewriting or multi-query expansion.
        multiquery_retriever = MultiQueryRetriever.from_llm(
            retriever=self.retriever,
            llm=self.llm_primary,
        )

        history_aware_retriever = (
            {"input": itemgetter("input"), "chat_history": itemgetter("chat_history")}
            | self.frame_qn_prompt
            | self.llm_primary
            | StrOutputParser()
            | multiquery_retriever
        )

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
        """Format retrieved documents into a string for prompt input."""
        if self.cross_encoder is None:
            docs = sorted(docs, key=lambda d: d.metadata.get("_score", 0.0), reverse=True)
        return "\n\n".join(f"{doc.metadata['url']}\n{doc.page_content}" for doc in docs)

    def _rerank(self, inputs: dict) -> dict:
        """Re-rank retrieved docs with the cross-encoder and filter by sigmoid threshold."""
        if self.cross_encoder is None:
            return inputs

        query = inputs["input"]
        docs = inputs["docs"]
        if not docs:
            return inputs

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
        """Process a single chunk in thinking mode.

        Returns:
            (updated_pending, updated_thinking_done, list of events to emit)
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
            safe_end = max(0, len(pending) - len(THINK_END) + 1)
            if safe_end > 0:
                events.append({"type": "step", "content": pending[:safe_end]})
                pending = pending[safe_end:]

        return pending, thinking_done, events

    def _flush_pending(self, pending: str, thinking_done: bool) -> dict:
        """Flush the remaining buffer after the stream ends."""
        if not thinking_done:
            logging.warning("</think> never detected in thinking mode — emitting buffer as answer.")
        return {"type": "token", "content": pending}

    async def generate(self, query: str, thinking: bool, history: list) -> AsyncGenerator[str, None]:
        """Generate an answer to the query using the RAG pipeline."""
        logging.info(f"Received query: {query} with thinking={thinking} and history of length {len(history)}")

        chat_history = []
        for convo in history:
            if query != convo.query:
                chat_history.append(HumanMessage(convo.query))
                chat_history.append(AIMessage(convo.answer))

        rag_chain = (
            self.rag_chain_thinking if thinking and self.rag_chain_thinking is not None else self.rag_chain_primary
        )

        logging.info(f"Using {'thinking' if thinking else 'primary'} LLM for query: {query}")

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
            yield json.dumps({"type": "error", "content": str(e)}) + "\n"

        yield json.dumps({"type": "done"}) + "\n"

    async def shorten_query(self, query: str) -> str:
        """Shorten a query to max 8 words."""
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
