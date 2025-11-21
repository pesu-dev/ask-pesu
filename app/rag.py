"""Retrieval-Augmented Generation (RAG) pipeline implementation using LangChain and Qdrant."""

import os

import yaml
from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from langchain.retrievers.multi_query import MultiQueryRetriever
from langchain_core.documents.base import Document
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough, RunnableSerializable
from langchain_huggingface.embeddings import HuggingFaceEmbeddings
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient

load_dotenv()


class RetrievalAugmentedGenerator:
    """A class that encapsulates the Retrieval-Augmented Generation (RAG) pipeline."""

    def __init__(self, config_path: str = "conf/config.yaml") -> None:
        """Initialize the RAG pipeline with configuration from a YAML file.

        Args:
            config_path (str): Path to the configuration YAML file.
        """
        # Load configuration from YAML file
        with open(config_path) as file:
            self.config = yaml.safe_load(file)

        # Initialize embeddings
        self.embedding = HuggingFaceEmbeddings(model_name=self.config["rag"]["embedding"])

        # Initialize Qdrant client and vector store
        self.qdrant_client = QdrantClient(url=os.getenv("QDRANT_URL"), api_key=os.getenv("QDRANT_API_KEY"))
        self.vector_store = QdrantVectorStore(
            collection_name=self.config["rag"]["qdrant_collection"],
            embedding=self.embedding,
            client=self.qdrant_client,
        )

        # Initialize LLM
        self.llm_primary = init_chat_model(
            model=self.config["rag"]["llm"]["primary"],
            model_provider="google_genai",
            google_api_key=os.getenv("GEMINI_API_KEY"),
        )
        # Initialize secondary LLM if specified
        self.llm_thinking = None
        if self.config["rag"]["llm"].get("thinking"):
            self.llm_thinking = init_chat_model(
                model=self.config["rag"]["llm"]["thinking"],
                model_provider="google_genai",
                google_api_key=os.getenv("GEMINI_API_KEY"),
            )

        # Initialize the prompt template
        self.prompt = ChatPromptTemplate.from_messages(
            [
                ("system", self.config["rag"]["system_prompt"]),
                ("human", "Question: {question}\nContext: {context}\nAnswer:"),
            ]
        )

        self.frame_qn_prompt = ChatPromptTemplate.from_messages([
            ("system",
            "You are a question rewriting assistant. Your job is to rewrite the user's "
            "question into an independent, self-contained question.\n\n"

            "Rewrite rules:\n"
            "1. ONLY use the chat history if the user's question is ambiguous or refers to previous context "
            "(e.g., pronouns like 'he', 'she', 'it', 'they', 'that').\n"
            "2. If the question is clear on its own, return it EXACTLY as it is.\n"
            "3. When resolving a follow-up question, ALWAYS prioritize the most recent topic in the chat history. "
            "Do NOT pull context from older, unrelated parts of the conversation.\n"
            "4. If the question could refer to multiple topics, choose the MOST RECENT plausible topic.\n"
            "5. Do NOT invent or assume connections between unrelated topics.\n"
            "6. Do NOT answer the question — only rewrite it.\n\n"

            "Chat History:\n{chat_history}"
            ),
            ("human", "{input}")
        ])

        # Build the RAG chains
        self.retriever = self.vector_store.as_retriever(search_kwargs=self.config["rag"]["search_kwargs"])
        self.rag_chain_primary = self._build_chain(self.llm_primary)
        self.rag_chain_thinking = self._build_chain(self.llm_thinking) if self.llm_thinking else None

    def _build_chain(self, llm: BaseChatModel) -> RunnableSerializable[str, str]:
        """Build the RAG chain using the specified LLM.

        Args:
            llm: The language model to use in the RAG chain.

        Returns:
            RunnableSerializable: The constructed RAG chain.
        """
        # Initialize multiquery retriever
        multiquery_retriever = MultiQueryRetriever.from_llm(
            retriever=self.retriever,
            llm=llm,
        )


        history_aware_retriever = (
            {
                "input": RunnablePassthrough(),
                "chat_history": RunnablePassthrough()
            }
            | self.frame_qn_prompt
            | llm
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
        """Format the retrieved documents into a single string."""
        return "\n\n".join(f"{doc.metadata['url']}\n{doc.page_content}" for doc in docs)

    async def generate(self, query: str, thinking: bool, history: list) -> str:
        """Generate a response for the given query using the RAG chain.

        Args:
            query (str): The input query.
            thinking (bool): Flag to indicate if the model should 'think' before answering.
            history (list): The entire chat history until the current query

        Returns:
            str: The generated response.
        """
        chat_history = []

        for convo in history:
            if query != convo.query:
                chat_history.append(HumanMessage(convo.query))
                chat_history.append(AIMessage(convo.answer))

        rag_chain = (
            self.rag_chain_thinking if thinking and self.rag_chain_thinking is not None else self.rag_chain_primary
        )

        return await rag_chain.ainvoke(
            {
            "input": query,
            "question":query,
            "chat_history": chat_history
            }
        )
