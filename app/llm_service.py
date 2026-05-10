"""
LLM Service Layer
-----------------
Wraps all external LLM API calls.  Every request is routed through the
Circuit Breaker so that a slow or dead LLM endpoint can never block the
entire FastAPI server.

Key behaviours:
  • Real call  : sends a POST to the configured LLM_API_URL with a timeout.
  • Fallback   : if the circuit is OPEN (or the real call keeps failing) the
                 service returns a graceful degraded response immediately,
                 rather than hanging.
  • Simulation : set LLM_SIMULATE_FAILURE=true in the environment to make
                 every real call raise a timeout — used by the test suite.
"""

import os
import time
import logging
import httpx

from app.circuit_breaker import CircuitBreaker, CircuitBreakerOpenException

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level Circuit Breaker instance (shared across all requests)
# ---------------------------------------------------------------------------
# Opens after 3 consecutive failures; probes again after 30 s.
llm_circuit_breaker = CircuitBreaker(
    failure_threshold=3,
    recovery_timeout=30.0,
    expected_exception=Exception,
)

# ---------------------------------------------------------------------------
# Configuration (override via environment variables)
# ---------------------------------------------------------------------------
LLM_API_URL: str = os.getenv(
    "LLM_API_URL", "https://api.openai.com/v1/chat/completions"
)
LLM_API_KEY: str = os.getenv("LLM_API_KEY", "sk-placeholder")
LLM_TIMEOUT: float = float(os.getenv("LLM_TIMEOUT_SECONDS", "10"))

# Set to "true" to simulate a permanently failing / timing-out LLM endpoint
SIMULATE_FAILURE: bool = os.getenv("LLM_SIMULATE_FAILURE", "false").lower() == "true"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _call_llm_api(prompt: str) -> dict:
    """
    Make the actual HTTP request to the LLM API.

    Raises:
        httpx.TimeoutException  – if the server takes longer than LLM_TIMEOUT s.
        httpx.HTTPStatusError   – on 4xx / 5xx responses.
        RuntimeError            – when SIMULATE_FAILURE is enabled (for tests).
    """
    if SIMULATE_FAILURE:
        logger.warning("[SIMULATION] Simulating LLM API timeout …")
        time.sleep(2)  # brief pause so the test feels realistic
        raise httpx.TimeoutException("Simulated LLM timeout after 60 s")

    headers = {
        "Authorization": f"Bearer {LLM_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "gpt-3.5-turbo",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 200,
    }

    with httpx.Client(timeout=LLM_TIMEOUT) as client:
        response = client.post(LLM_API_URL, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()

    return {
        "response": data["choices"][0]["message"]["content"],
        "source": "llm_api",
        "circuit_state": llm_circuit_breaker.state.value,
    }


def _fallback_response(prompt: str) -> dict:
    """
    Graceful degraded response returned when the circuit is OPEN.

    Instead of hanging or returning a 500 error, users get a polite message
    explaining the service is temporarily unavailable.
    """
    logger.info("LLM fallback triggered for prompt: %.60s…", prompt)
    return {
        "response": (
            "The AI assistant is temporarily unavailable due to high load or "
            "a downstream outage. Please try again in a moment. "
            "Your request has been noted."
        ),
        "source": "fallback",
        "circuit_state": llm_circuit_breaker.state.value,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def query_llm(prompt: str) -> dict:
    """
    Submit a prompt to the LLM, protected by the Circuit Breaker.

    Returns a dict with keys:
      - response      : the text answer (real or fallback)
      - source        : "llm_api" | "fallback"
      - circuit_state : current state of the breaker ("CLOSED" | "OPEN" | "HALF_OPEN")
    """
    return llm_circuit_breaker.call(
        _call_llm_api,
        prompt,
        fallback=_fallback_response,
    )


def get_circuit_status() -> dict:
    """Return the current circuit breaker status (for the health endpoint)."""
    return llm_circuit_breaker.get_status()
