"""FastAPI application for AskPESU backend APIs."""

import argparse
import datetime
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytz
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.docs import ask_docs, health_docs
from app.models import RequestModel, ResponseModel
from app.rag import RetrievalAugmentedGenerator


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Lifespan event handler for startup and shutdown events."""
    # Startup
    logging.info("askPESU API startup")
    yield
    # Shutdown
    logging.info("askPESU API shutdown.")


app = FastAPI(
    title="askPESU API",
    description="Backend APIs for AskPESU, a question-answering chatbot for PES University.",
    version="0.1.0",
    docs_url="/docs",
    lifespan=lifespan,
    openapi_tags=[
        {
            "name": "Generation",
            "description": "Operations related to generating responses from the chatbot.",
        },
        {
            "name": "Documentation",
            "description": "Render the README and other developer-facing docs.",
        },
        {
            "name": "Monitoring",
            "description": "Health checks and other monitoring endpoints.",
        },
    ],
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(_request: Request, _exc: Exception) -> JSONResponse:
    """Handler for unhandled exceptions."""
    logging.exception("Unhandled exception occurred.")
    return JSONResponse(
        status_code=500,
        content={
            "status": False,
            "message": "Internal Server Error. Please try again later.",
            "timestamp": datetime.datetime.now(IST).isoformat(),
        },
    )


@app.post(
    "/ask",
    response_model=ResponseModel,
    response_class=JSONResponse,
    openapi_extra=ask_docs.request_examples,
    responses=ask_docs.response_examples,
    tags=["Generation"],
)
async def ask(payload: RequestModel) -> JSONResponse:
    """Endpoint to handle question-answering requests."""
    logging.debug(f"Received /ask question: {payload.query}")
    start_time = time.perf_counter()
    answer = await rag.generate(query=payload.query)
    latency = time.perf_counter() - start_time
    response = ResponseModel(
        status=True,
        message="Answer generated successfully.",
        answer=answer,
        timestamp=datetime.datetime.now(IST),
        latency=latency,
    )
    return JSONResponse(status_code=200, content=response.model_dump(exclude_none=True))


@app.get(
    "/health",
    response_class=JSONResponse,
    responses=health_docs.response_examples,
    tags=["Monitoring"],
)
async def health() -> JSONResponse:
    """Health check endpoint."""
    logging.debug("Health check requested.")
    return JSONResponse(
        status_code=200,
        content={
            "status": True,
            "message": "ok",
            "timestamp": datetime.datetime.now(IST).isoformat(),
        },
    )


def main() -> None:
    """Main function to run the FastAPI application with command line arguments."""
    # Set up argument parser for command line arguments
    parser = argparse.ArgumentParser(
        description="Run the FastAPI application for askPESU backend.",
    )
    parser.add_argument(
        "--host",
        type=str,
        default="0.0.0.0",
        help="Host to run the FastAPI application on. Default is 0.0.0.0",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=7860,
        help="Port to run the FastAPI application on. Default is 7860",
    )
    parser.add_argument(
        "--config",
        type=str,
        default="conf/config.yaml",
        help="Path to the configuration YAML file. Default is conf/config.yaml",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Run the application in debug mode with detailed logging.",
    )
    args = parser.parse_args()

    # Initialize the RAG engine
    global rag
    rag = RetrievalAugmentedGenerator(args.config)
    logging.info("RAG pipeline initialized...")

    # Set up logging configuration
    logging_level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=logging_level,
        format="%(asctime)s - %(levelname)s - %(filename)s:%(funcName)s:%(lineno)d - %(message)s",
        filemode="w",
    )

    # Run the app
    uvicorn.run("app.app:app", host=args.host, port=args.port, reload=args.debug)


if __name__ == "__main__":
    IST = pytz.timezone("Asia/Kolkata")  # Indian Standard Time timezone
    rag: RetrievalAugmentedGenerator | None = None  # Global variable to hold the RAG instance
    main()
