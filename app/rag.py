"""Retrieval-Augmented Generation (RAG) pipeline implementation using LangChain and Qdrant."""

import os

import yaml
from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from langchain.retrievers.multi_query import MultiQueryRetriever
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_core.documents.base import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough
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
        self.llm = init_chat_model(
            model=self.config["rag"]["llm"],
            model_provider="google_genai",
            google_api_key=os.getenv("GEMINI_API_KEY"),
        )

        # Initialize retriever
        self.retriever = MultiQueryRetriever.from_llm(
            retriever=self.vector_store.as_retriever(search_kwargs=self.config["rag"]["search_kwargs"]),
            llm=self.llm,
        )

        # Initialize the prompt template
        self.prompt = ChatPromptTemplate.from_messages(
            [
                ("system", self.config["rag"]["system_prompt"]),
                ("human", "Question: {question}\nContext: {context}\nAnswer:"),
            ]
        )

        # Initialize the RAG chain
        self.rag_chain = (
            {
                "context": self.retriever | self.format_docs,
                "question": RunnablePassthrough(),
            }
            | self.prompt
            | self.llm
            | StrOutputParser()
        )

    @staticmethod
    def format_docs(docs: list[Document]) -> str:
        """Format the retrieved documents into a single string."""
        return "\n\n".join(f"{doc.metatata['url']}\n{doc.page_content}" for doc in docs)

    async def generate(self, query: str) -> str:
        """Generate a response for the given query using the RAG chain."""
        return await self.rag_chain.ainvoke(query)
