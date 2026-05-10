import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.llm_service import query_llm, get_circuit_status, llm_circuit_breaker

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# App lifecycle
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("StudySync API starting up …")
    yield
    logger.info("StudySync API shutting down.")


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="StudySync API",
    description="PDC Assignment 2 — Circuit Breaker Pattern Demo",
    version="1.0.0",
    lifespan=lifespan,
)

# Allow requests from the React frontend during local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# CUSTOM MIDDLEWARE — X-Student-ID header (MANDATORY per assignment rules)
# ---------------------------------------------------------------------------

@app.middleware("http")
async def add_student_id_header(request: Request, call_next):
    """
    Inject 'X-Student-ID: BSCS23130' into EVERY outgoing response.

    This middleware satisfies the strict submission requirement:
      "Every single API response returns X-Student-ID: [Your-Actual-Student-ID]"
    """
    response = await call_next(request)
    response.headers["X-Student-ID"] = "BSCS23130"
    return response


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class PromptRequest(BaseModel):
    prompt: str

    model_config = {"json_schema_extra": {"example": {"prompt": "Explain binary search."}}}


class LLMResponse(BaseModel):
    response: str
    source: str           # "llm_api" or "fallback"
    circuit_state: str    # "CLOSED", "OPEN", or "HALF_OPEN"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/", tags=["Root"])
async def root():
    """Service liveness check."""
    return {"message": "StudySync API is running.", "student_id": "BSCS23130"}


@app.post("/ask", response_model=LLMResponse, tags=["LLM"])
async def ask_llm(body: PromptRequest):
    """
    Submit a prompt to the LLM.

    The request is routed through the Circuit Breaker:
      - If the LLM is healthy (CLOSED), the real API is called.
      - If the LLM keeps failing (OPEN), the fallback response is returned
        immediately — no blocking, no 60-second hang.
    """
    logger.info("Received prompt: %.80s…", body.prompt)
    result = query_llm(body.prompt)
    return LLMResponse(**result)


@app.get("/health", tags=["Monitoring"])
async def health_check():
    """
    Return service health, including the circuit breaker's current state.
    Useful for dashboards and the demo video.
    """
    cb_status = get_circuit_status()
    overall = "degraded" if cb_status["state"] != "CLOSED" else "healthy"
    return {
        "status": overall,
        "circuit_breaker": cb_status,
        "student_id": "BSCS23130",
    }


# ---------------------------------------------------------------------------
# Admin / Demo endpoints — circuit breaker controls
# ---------------------------------------------------------------------------

@app.post("/circuit/reset", tags=["Admin"])
async def reset_circuit():
    """Force the circuit breaker back to CLOSED (use after fixing the LLM)."""
    llm_circuit_breaker.reset()
    return {"message": "Circuit breaker reset to CLOSED.", "state": llm_circuit_breaker.state.value}


@app.post("/circuit/force-open", tags=["Admin"])
async def force_open_circuit():
    """
    Manually open the circuit breaker.
    Used in the demo to simulate 'LLM is down' without waiting for 3 failures.
    """
    llm_circuit_breaker.force_open()
    return {"message": "Circuit breaker forced OPEN.", "state": llm_circuit_breaker.state.value}


@app.get("/circuit/status", tags=["Admin"])
async def circuit_status():
    """Detailed circuit breaker snapshot."""
    return llm_circuit_breaker.get_status()


# ---------------------------------------------------------------------------
# Global exception handler — ensures X-Student-ID header even on errors
# ---------------------------------------------------------------------------

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled exception: %s", exc, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error.", "student_id": "BSCS23130"},
        headers={"X-Student-ID": "BSCS23130"},
    )
