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
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from google.api_core.exceptions import ResourceExhausted

from app.docs import ask_docs, health_docs, index_docs
from app.models import RequestModel, ResponseModel
from app.rag import RetrievalAugmentedGenerator


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Lifespan event handler for startup and shutdown events."""
    # Startup
    logging.info("askPESU API startup")

    # Initialize the RAG engine
    global rag
    config_path = getattr(app.state, "config_path", "conf/config.yaml")
    rag = RetrievalAugmentedGenerator(config_path)
    logging.info("RAG pipeline initialized...")

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
            "name": "Monitoring",
            "description": "Health checks and other monitoring endpoints.",
        },
    ],
)

# Initialize globals
DIST_DIR = "/out"  # Directory for static files (built from frontend)
IST = pytz.timezone("Asia/Kolkata")  # Indian Standard Time timezone
rag: RetrievalAugmentedGenerator | None = None  # Global variable to hold the RAG instance
THINKING_ENABLED = True  # Global flag to indicate if 'thinking' mode is enabled
THINKING_DISABLED_UNTIL: datetime.datetime | None = (
    None  # Global variable to hold the timestamp until which 'thinking' mode is disabled
)
THINKING_DISABLED_COOLDOWN_HOURS = 24  # Number of hours to disable 'thinking' mode after quota exhaustion

# Mount static files
app.mount("/static", StaticFiles(directory=DIST_DIR), name="static")


@app.exception_handler(ResourceExhausted)
async def resource_exhausted_exception_handler(_request: Request, exc: ResourceExhausted) -> JSONResponse:
    """Handler for resource exhausted exceptions."""
    global THINKING_ENABLED, THINKING_DISABLED_UNTIL
    logging.exception(f"Quota exceeded: {exc}")
    prefix = (
        "Quota exceeded."
        if THINKING_ENABLED
        else f"Thinking mode disabled until {THINKING_DISABLED_UNTIL.strftime('%Y-%m-%d %H:%M:%S %Z')} "
        f"due to quota limits."
    )
    return JSONResponse(
        status_code=429,
        content={
            "status": False,
            "message": f"{prefix}. Please try again later, or disable 'thinking' mode if enabled.",
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
    response_model=ResponseModel,
    response_class=JSONResponse,
    openapi_extra=ask_docs.request_examples,
    responses=ask_docs.response_examples,
    tags=["Generation"],
)
async def ask(payload: RequestModel) -> JSONResponse:
    """Endpoint to handle question-answering requests."""
    global THINKING_ENABLED, THINKING_DISABLED_UNTIL, THINKING_DISABLED_COOLDOWN_HOURS
    logging.debug(f"Received /ask question: {payload.query}")
    logging.debug(f"Thinking mode: {payload.thinking}")
    current_time = datetime.datetime.now(IST)

    # Re-enable thinking mode if cooldown period has expired
    if not THINKING_ENABLED and THINKING_DISABLED_UNTIL and current_time >= THINKING_DISABLED_UNTIL:
        THINKING_ENABLED = True
        THINKING_DISABLED_UNTIL = None
        logging.info("Thinking mode cooldown expired, re-enabling thinking mode")

    # Check if thinking mode is requested and enabled
    if payload.thinking and not THINKING_ENABLED:
        logging.warning("Thinking mode was requested but currently disabled due to quota limits.")
        raise ResourceExhausted(
            "Thinking mode temporarily disabled due to quota limits. "
            "Please try again later, or disable 'thinking' mode if enabled."
        )

    # Attempt to generate the answer
    start_time = time.perf_counter()
    try:
        answer = await rag.generate(query=payload.query, thinking=payload.thinking)
    except ResourceExhausted as e:
        llm_used = "primary" if not payload.thinking else "thinking"
        # Disable thinking mode for the next THINKING_DISABLED_COOLDOWN_HOURS hours if quota exceeded
        THINKING_ENABLED = False
        THINKING_DISABLED_UNTIL = current_time + datetime.timedelta(hours=THINKING_DISABLED_COOLDOWN_HOURS)
        logging.exception(
            f"Quota exceeded on llm:{llm_used}: {e}. Thinking mode disabled until {THINKING_DISABLED_UNTIL}"
        )
        raise

    latency = round(time.perf_counter() - start_time, 3)
    response = ResponseModel(
        status=True,
        message="Answer generated successfully.",
        answer=answer,
        timestamp=current_time,
        latency=latency,
    )
    return JSONResponse(status_code=200, content=response.model_dump(mode="json", exclude_none=True))


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
