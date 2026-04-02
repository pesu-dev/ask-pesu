"""Retrieval-Augmented Generation (RAG) pipeline implementation using LangChain and Qdrant."""

import json
import logging
import os
from collections.abc import AsyncGenerator

import yaml
from dotenv import load_dotenv
from huggingface_hub import InferenceClient
from langchain_classic.retrievers import MultiQueryRetriever
from langchain_core.documents.base import Document
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough, RunnableSerializable
from langchain_huggingface import ChatHuggingFace, HuggingFaceEndpoint
from langchain_huggingface.embeddings import HuggingFaceEmbeddings
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient

load_dotenv()

THINK_END = "</think>"


class RetrievalAugmentedGenerator:
    """A class that encapsulates the Retrieval-Augmented Generation (RAG) pipeline."""

    def __init__(self, config_path: str = "conf/config.yaml") -> None:
        """Initialize the RAG pipeline components."""
        InferenceClient(api_key=os.environ["HF_TOKEN"])

        with open(config_path) as file:
            self.config = yaml.safe_load(file)

        self.embedding = HuggingFaceEmbeddings(model_name=self.config["rag"]["embedding"])

        self.qdrant_client = QdrantClient(url=os.getenv("QDRANT_URL"), api_key=os.getenv("QDRANT_API_KEY"))
        self.vector_store = QdrantVectorStore(
            collection_name=self.config["rag"]["qdrant_collection"],
            embedding=self.embedding,
            client=self.qdrant_client,
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

        self.retriever = self.vector_store.as_retriever(search_kwargs=self.config["rag"]["search_kwargs"])
        self.rag_chain_primary = self._build_chain(self.llm_primary)
        self.rag_chain_thinking = self._build_chain(self.llm_thinking) if self.llm_thinking else None

    def _build_chain(self, llm: BaseChatModel) -> RunnableSerializable[str, str]:
        # Always use llm_primary for retrieval steps — never burn thinking-model
        # tokens on question rewriting or multi-query expansion.
        multiquery_retriever = MultiQueryRetriever.from_llm(
            retriever=self.retriever,
            llm=self.llm_primary,  # <-- always primary, not `llm`
        )

        history_aware_retriever = (
            {"input": RunnablePassthrough(), "chat_history": RunnablePassthrough()}
            | self.frame_qn_prompt
            | self.llm_primary
            | StrOutputParser()
            | multiquery_retriever
        )

        return (
            {
                "context": history_aware_retriever | self.format_docs,
                "question": RunnablePassthrough(),
            }
            | self.prompt
            | llm
            | StrOutputParser()
        )

    @staticmethod
    def format_docs(docs: list[Document]) -> str:
        """Format retrieved documents into a string for prompt input."""
        return "\n\n".join(f"{doc.metadata['url']}\n{doc.page_content}" for doc in docs)

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
        print(result)
        return " ".join(result.split()[:8])
