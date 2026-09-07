"""HTTP surface of askPESU: routes, lifespan, and static file serving.

This one process serves both the API and the compiled React frontend from the
same origin, which is why production needs no CORS configuration and the client
can use relative URLs.

Routes:

- ``GET  /``             the SPA entrypoint
- ``POST /ask``          question answering, streamed as NDJSON
- ``POST /rewriteQuery`` condense a question into a conversation title
- ``GET  /health``       liveness
- ``GET  /quota``        per-model cooldown state

The expensive machinery -- embedding model, reranker, Qdrant client -- is built
once in :func:`lifespan` and shared by every request.
"""

import argparse
import asyncio
import datetime
import json
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytz
import torch
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app.docs import ask_docs, health_docs, index_docs, quota_docs
from app.models import AskRequestModel, HealthResponseModel, QuotaResponseModel, ShortenQueryModel
from app.quota import QuotaExceededError, QuotaState
from app.rag import RetrievalAugmentedGenerator

load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Build the RAG pipeline before the server accepts traffic.

    Everything expensive or fallible happens here rather than per request:
    loading the embedding model and reranker, connecting to Qdrant, and checking
    the collection contract. Anything raised aborts startup, so a deployment
    pointed at a missing or mismatched collection never binds a port -- which is
    what we want, because the alternative is answering from the wrong data.
    """
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


# CORS is a development-only convenience. In production FastAPI serves the built
# frontend from this same origin, and `npm run dev` proxies /ask, /health, /quota
# and /rewriteQuery to this server (see frontend/vite.config.ts), so neither path
# makes a cross-origin request. These entries only matter if you point a frontend
# on another origin at this API.
origins = [
    "http://localhost:8080",  # the port vite.config.ts serves on
    "http://127.0.0.1:8080",
    "http://localhost:5173",  # vite's own default, if the port is overridden
    "http://127.0.0.1:5173",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Where the Dockerfile's frontend build stage leaves the compiled SPA. Relative
# to the working directory, which is /app in the image.
DIST_DIR = "frontend/dist"
# All user-facing timestamps are Indian Standard Time; the audience is one campus.
IST = pytz.timezone("Asia/Kolkata")
# Populated by the lifespan handler. None only before startup completes.
rag: RetrievalAugmentedGenerator | None = None

# Cooldowns are tracked per model, so exhausting the thinking model's quota does
# not take normal mode down with it. This lives in process memory: a restart
# clears it, and multiple replicas would not share it.
THINKING_STATE = QuotaState(name="thinking", cooldown_hours=24)
PRIMARY_STATE = QuotaState(name="primary", cooldown_hours=24)

# Hashed asset bundles are served directly. Everything else falls through to the
# routes below, so client-side routing still works. This mount fails loudly at
# import if the frontend was never built -- the clearest signal that a deploy
# shipped without its dist/ directory.
app.mount(
    "/assets",
    StaticFiles(directory=f"{DIST_DIR}/assets"),
    name="assets",
)


async def test_stream() -> AsyncIterator[str]:
    """Replay a canned answer in the real NDJSON format, for ``ENV=test``.

    Lets the frontend be developed against realistic streaming -- including
    thinking steps, markdown, LaTeX and a Sources list -- without a Qdrant
    instance, an HF token, or spending inference quota.
    """
    # Step 1
    yield json.dumps({"type": "step", "content": "Searching documents...\n"}) + "\n"
    await asyncio.sleep(0.02)

    # Step 2
    yield json.dumps({"type": "step", "content": "Ranking sources...\n"}) + "\n"

    await asyncio.sleep(0.02)
    # Step 3
    yield json.dumps({"type": "step", "content": "Generating answer...\n"}) + "\n"
    await asyncio.sleep(0.02)

    tokens = [
        "### How SGPA is Calculated\n\n",
        "SGPA is the **weighted average** of the grades obtained in all courses during a semester, ",
        "where the weights are the **credits** assigned to each course.\n\n",
        "#### Formula\n\n",
        "$$\\text{SGPA} = ",
        "\\frac{\\sum (\\text{Grade Points} \\times \\text{Credits})}{\\text{Total Credits}}$$\n\n",
        "#### Step-by-step\n\n",
        "1. **Determine the final grade** for each course.\n",
        "2. **Convert the grade into grade points**.\n",
        "3. **Multiply** the grade points by the course credits.\n",
        "4. **Add** the products for all courses.\n",
        "5. **Divide** by the total credits in the semester.\n\n",
        "#### Example\n\n",
        "- Course 1: 4 credits, grade **A** = 9 points\n",
        "- Course 2: 2 credits, grade **S** = 10 points\n\n",
        "So the SGPA is **(4 x 9 + 2 x 10) / 6 = 9.33**.\n\n",
        "**Sources**\n\n",
        "- https://www.reddit.com/r/PESU/\n",
    ]
    for t in tokens:
        yield json.dumps({"type": "token", "content": t}) + "\n"
        await asyncio.sleep(0.1)

    yield json.dumps({"type": "done"}) + "\n"


def get_quota_status() -> dict:
    """Return quota availability for both LLMs."""
    THINKING_STATE.refresh()
    PRIMARY_STATE.refresh()
    return {
        "thinking": THINKING_STATE.status(),
        "primary": PRIMARY_STATE.status(),
    }


@app.exception_handler(QuotaExceededError)
async def quota_exceeded_exception_handler(_request: Request, exc: QuotaExceededError) -> JSONResponse:
    """Turn a quota cooldown into a 429 carrying the full quota snapshot.

    The snapshot lets the client tell the user *when* to come back, and whether
    the other mode is still usable, without a follow-up call to /quota.
    """
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
    """Return a generic 500 for anything unhandled.

    The exception is logged in full but deliberately not returned: tracebacks can
    carry connection strings and prompt content. Note this cannot catch failures
    inside a response that has already started streaming.
    """
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
    """Serve the compiled single-page app.

    Only the root path is served here; hashed bundles come from the /assets
    mount. The SPA handles its own routing once loaded.
    """
    return FileResponse(f"{DIST_DIR}/index.html")


@app.post(
    "/rewriteQuery",
    response_model=ShortenQueryModel,
    tags=["Generation"],
)
async def rewrite_query(payload: AskRequestModel) -> ShortenQueryModel:
    """Condense a question into a short title for the conversation sidebar.

    Only ``query`` is read; ``thinking`` and ``history`` are ignored. The request
    model is shared with /ask so the client can post the same object it already
    has, without a second schema.
    """
    return ShortenQueryModel(query=await rag.shorten_query(payload.query))


@app.post(
    "/ask",
    # No response_model: the body is a newline-delimited JSON stream, which
    # FastAPI cannot validate against a model. The shape is documented through
    # `responses` instead -- see app/docs/ask.py. response_class keeps FastAPI
    # from advertising a default application/json body it never returns.
    response_class=StreamingResponse,
    openapi_extra=ask_docs.request_examples,
    responses=ask_docs.response_examples,
    tags=["Generation"],
)
async def ask(payload: AskRequestModel) -> StreamingResponse:
    """Answer a question, streaming the result as newline-delimited JSON.

    Returns as soon as the first token is ready rather than waiting for the whole
    answer, so the UI can render progressively.

    Quota is checked *before* streaming starts, because that is the only point at
    which a 429 can still be sent -- once the response has begun the status line
    is committed, and failures can only be reported as an `error` event.

    Raises:
        QuotaExceededError: If the requested model is in cooldown. The handler
            turns this into a 429 carrying the current quota snapshot.
    """
    global THINKING_STATE, PRIMARY_STATE
    logging.debug(f"Received /ask question: {payload.query}")
    logging.debug(f"Thinking mode: {payload.thinking}")
    # current_time = datetime.datetime.now(IST)

    # Re-enable thinking mode and primary LLM if cooldown period has expired
    THINKING_STATE.refresh()
    PRIMARY_STATE.refresh()

    # Check if thinking mode is requested and enabled
    if payload.thinking and not THINKING_STATE.enabled:
        logging.warning("Thinking mode was requested but currently unavailable due to quota limits.")
        raise QuotaExceededError(
            "Thinking mode is temporarily unavailable due to quota limits. "
            "Please try again later, or disable 'thinking' mode if enabled."
        )

    # Check if primary LLM is requested and enabled
    if not payload.thinking and not PRIMARY_STATE.enabled:
        logging.warning("Primary LLM is currently unavailable due to quota limits.")
        raise QuotaExceededError("Primary LLM is temporarily unavailable due to quota limits. Please try again later.")

    if os.getenv("ENV") == "test":
        return StreamingResponse(test_stream(), media_type="text/plain")

    # A quota failure surfaces mid-stream, so the pipeline calls back here to
    # start the cooldown; without this the state machine could never trip and
    # /quota would always report available.
    state = THINKING_STATE if payload.thinking else PRIMARY_STATE
    return StreamingResponse(
        rag.generate(
            query=payload.query,
            thinking=payload.thinking,
            history=payload.history,
            on_quota_exceeded=state.disable,
        ),
        # text/plain rather than application/x-ndjson: intermediaries are more
        # likely to stream it through unbuffered, and the client splits on
        # newlines regardless of the declared type.
        media_type="text/plain",
        status_code=200,
    )


@app.get(
    "/health",
    response_model=HealthResponseModel,
    response_class=JSONResponse,
    openapi_extra=health_docs.request_examples,
    responses=health_docs.response_examples,
    tags=["Monitoring"],
)
async def health() -> JSONResponse:
    """Report that the process is up.

    Liveness only. It does not probe Qdrant or the inference provider, because
    the contract check at startup means the process would not be running at all
    if the collection were wrong.
    """
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
    """Report per-model cooldown state so the UI can disable a mode before it is used.

    Refreshes first, so a cooldown that has expired is reported as available
    rather than waiting for the next request to clear it.
    """
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
