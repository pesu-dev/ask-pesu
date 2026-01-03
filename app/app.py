"""FastAPI application for AskPESU backend APIs."""

import argparse
import datetime
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytz
import torch
import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from google.api_core.exceptions import ResourceExhausted

from app.docs import ask_docs, health_docs, index_docs, quota_docs
from app.models import AskRequestModel, AskResponseModel, HealthResponseModel, QuotaResponseModel
from app.quota import QuotaState
from app.rag import RetrievalAugmentedGenerator


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Lifespan event handler for startup and shutdown events."""
    # Startup
    logging.info("AskPESU API startup")

    # Initialize the RAG engine
    global rag
    config_path = getattr(app.state, "config_path", "conf/config.yaml")
    rag = RetrievalAugmentedGenerator(config_path)
    logging.info("RAG pipeline initialized...")

    yield
    # Shutdown
    logging.info("AskPESU API shutdown.")


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
            "name": "Monitoring",
            "description": "Health checks and other monitoring endpoints.",
        },
    ],
)

origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize globals
DIST_DIR = "frontend/out"  # Directory for static files (built from frontend)
IST = pytz.timezone("Asia/Kolkata")  # Indian Standard Time timezone
rag: RetrievalAugmentedGenerator | None = None  # Global variable to hold the RAG instance

# Global state to track if 'thinking' mode is enabled
THINKING_STATE = QuotaState(name="thinking", cooldown_hours=24)
# Global state to track if primary LLM is enabled
PRIMARY_STATE = QuotaState(name="primary", cooldown_hours=24)

# Mount static files
app.mount("/static", StaticFiles(directory=DIST_DIR), name="static")


def get_quota_status() -> dict:
    """Return quota availability for both LLMs."""
    THINKING_STATE.refresh()
    PRIMARY_STATE.refresh()
    return {
        "thinking": THINKING_STATE.status(),
        "primary": PRIMARY_STATE.status(),
    }


@app.exception_handler(ResourceExhausted)
async def resource_exhausted_exception_handler(_request: Request, exc: ResourceExhausted) -> JSONResponse:
    """Handler for resource exhausted exceptions."""
    logging.warning(f"Quota exceeded: {exc}")
    return JSONResponse(
        status_code=429,
        content={
            "status": False,
            "message": str(exc),
            "quota": get_quota_status(),
            "timestamp": datetime.datetime.now(IST).isoformat(),
        },
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


@app.get(
    "/",
    response_class=FileResponse,
    tags=["Generation"],
    responses=index_docs.response_examples,
)
async def index() -> FileResponse:
    """Serve the main entrypoint (index.html) from the built static files."""
    return FileResponse(f"{DIST_DIR}/index.html")


@app.post(
    "/ask",
    response_model=AskResponseModel,
    response_class=JSONResponse,
    openapi_extra=ask_docs.request_examples,
    responses=ask_docs.response_examples,
    tags=["Generation"],
)
async def ask(payload: AskRequestModel) -> JSONResponse:
    """Endpoint to handle question-answering requests.

    Automatically manages LLM quota with cooldowns.
    May raise 429 if 'thinking' or 'primary' mode is temporarily unavailable.
    """
    global THINKING_STATE, PRIMARY_STATE
    logging.debug(f"Received /ask question: {payload.query}")
    logging.debug(f"Thinking mode: {payload.thinking}")
    current_time = datetime.datetime.now(IST)

    # Re-enable thinking mode and primary LLM if cooldown period has expired
    THINKING_STATE.refresh()
    PRIMARY_STATE.refresh()

    # Check if thinking mode is requested and enabled
    if payload.thinking and not THINKING_STATE.enabled:
        logging.warning("Thinking mode was requested but currently unavailable due to quota limits.")
        raise ResourceExhausted(
            "Thinking mode is temporarily unavailable due to quota limits. "
            "Please try again later, or disable 'thinking' mode if enabled."
        )

    # Check if primary LLM is requested and enabled
    if not payload.thinking and not PRIMARY_STATE.enabled:
        logging.warning("Primary LLM is currently unavailable due to quota limits.")
        raise ResourceExhausted("Primary LLM is temporarily unavailable due to quota limits. Please try again later.")

    # Attempt to generate the answer
    start_time = time.perf_counter()
    try:
        answer = await rag.generate(query=payload.query, thinking=payload.thinking, history=payload.history)
    except ResourceExhausted:
        llm_state = THINKING_STATE if payload.thinking else PRIMARY_STATE
        llm_state.disable()
        raise

    latency = round(time.perf_counter() - start_time, 3)
    response = AskResponseModel(
        status=True,
        message="Answer generated successfully.",
        answer=answer,
        timestamp=current_time,
        latency=latency,
    )
    return JSONResponse(status_code=200, content=response.model_dump(mode="json", exclude_none=True))


@app.get(
    "/health",
    response_model=HealthResponseModel,
    response_class=JSONResponse,
    openapi_extra=health_docs.request_examples,
    responses=health_docs.response_examples,
    tags=["Monitoring"],
)
async def health() -> JSONResponse:
    """Health check endpoint."""
    logging.debug("Health check requested.")
    response = HealthResponseModel(
        status=True,
        message="ok",
        timestamp=datetime.datetime.now(IST),
    )
    return JSONResponse(status_code=200, content=response.model_dump(mode="json", exclude_none=True))


@app.get(
    "/quota",
    response_model=QuotaResponseModel,
    response_class=JSONResponse,
    openapi_extra=quota_docs.request_examples,
    responses=quota_docs.response_examples,
    tags=["Monitoring"],
)
async def quota() -> JSONResponse:
    """Quota status endpoint."""
    logging.debug("Quota status requested.")
    response = QuotaResponseModel(
        status=True,
        quota=get_quota_status(),
        timestamp=datetime.datetime.now(IST),
    )
    return JSONResponse(status_code=200, content=response.model_dump(mode="json", exclude_none=True))


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

    # Store config path in app state for lifespan handler
    app.state.config_path = args.config

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
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    logging.info(f"Using device: {device}")
    if device.type == "cuda":
        logging.info(f"CUDA version: {torch.version.cuda}")
        logging.info(f"Number of GPUs: {torch.cuda.device_count()}")
        for i in range(torch.cuda.device_count()):
            logging.info(f"GPU {i} name: {torch.cuda.get_device_name(i)}")
            logging.info(f"\tGPU {i} memory: {torch.cuda.get_device_properties(i).total_memory / 1024**3:.2f} GB")
            logging.info(f"\tGPU {i} memory allocated: {torch.cuda.memory_allocated(i) / 1024**3:.2f} GB")
            logging.info(f"\tGPU {i} memory reserved: {torch.cuda.memory_reserved(i) / 1024**3:.2f} GB")
        torch.set_float32_matmul_precision("high")
    else:
        logging.info("Running without GPU acceleration")
    main()
