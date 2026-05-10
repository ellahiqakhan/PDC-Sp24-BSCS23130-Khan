"""
Circuit Breaker Pattern Implementation
--------------------------------------
Implements the Circuit Breaker pattern to protect the application from
cascading failures when an external service (e.g., LLM API) is unavailable.

States:
  CLOSED   -> Normal operation. Requests pass through.
  OPEN     -> Failure threshold exceeded. Requests are short-circuited immediately.
  HALF_OPEN -> After cooldown, one probe request is allowed through to test recovery.
"""

import time
import threading
import logging
from enum import Enum
from typing import Callable, Any

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    CLOSED = "CLOSED"        # Healthy: all requests go through
    OPEN = "OPEN"            # Failing: all requests blocked, fallback used
    HALF_OPEN = "HALF_OPEN"  # Testing: one request allowed to probe recovery


class CircuitBreakerOpenException(Exception):
    """Raised when a call is attempted while the circuit breaker is OPEN."""
    pass


class CircuitBreaker:
    """
    Thread-safe Circuit Breaker.

    Args:
        failure_threshold (int):   Number of consecutive failures before opening.
        recovery_timeout (float):  Seconds to wait before transitioning to HALF_OPEN.
        expected_exception (type): The exception type that counts as a failure.
    """

    def __init__(
        self,
        failure_threshold: int = 3,
        recovery_timeout: float = 30.0,
        expected_exception: type = Exception,
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exception = expected_exception

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time: float = 0.0
        self._lock = threading.Lock()  # Ensures thread-safe state transitions

    # ------------------------------------------------------------------
    # Public properties
    # ------------------------------------------------------------------

    @property
    def state(self) -> CircuitState:
        """Return current state, auto-transitioning OPEN -> HALF_OPEN if ready."""
        with self._lock:
            if (
                self._state == CircuitState.OPEN
                and time.monotonic() - self._last_failure_time >= self.recovery_timeout
            ):
                logger.info("Circuit transitioning OPEN -> HALF_OPEN (probe allowed).")
                self._state = CircuitState.HALF_OPEN
            return self._state

    @property
    def failure_count(self) -> int:
        return self._failure_count

    # ------------------------------------------------------------------
    # Core call method
    # ------------------------------------------------------------------

    def call(self, func: Callable, *args, fallback: Callable = None, **kwargs) -> Any:
        """
        Execute `func` through the circuit breaker.

        If the circuit is OPEN, either invoke `fallback` (if provided) or raise
        CircuitBreakerOpenException.

        Args:
            func:     The function to protect (e.g., an LLM API call).
            *args:    Positional arguments forwarded to `func`.
            fallback: Optional callable invoked when the circuit is open.
            **kwargs: Keyword arguments forwarded to `func`.

        Returns:
            Result of `func`, or result of `fallback` if the circuit is open.
        """
        current_state = self.state  # triggers OPEN -> HALF_OPEN transition if due

        if current_state == CircuitState.OPEN:
            logger.warning("Circuit OPEN — request short-circuited.")
            if fallback:
                return fallback(*args, **kwargs)
            raise CircuitBreakerOpenException(
                "Circuit breaker is OPEN. Service unavailable."
            )

        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except self.expected_exception as exc:
            self._on_failure()
            logger.error("Circuit breaker recorded failure: %s", exc)
            if fallback:
                return fallback(*args, **kwargs)
            raise

    # ------------------------------------------------------------------
    # Internal state-transition helpers
    # ------------------------------------------------------------------

    def _on_success(self) -> None:
        """Reset breaker on a successful call."""
        with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                logger.info("Probe succeeded — circuit CLOSED.")
            self._state = CircuitState.CLOSED
            self._failure_count = 0

    def _on_failure(self) -> None:
        """Increment failure count; open the circuit if threshold is reached."""
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.monotonic()

            if self._state == CircuitState.HALF_OPEN:
                # Probe failed — stay OPEN and reset cooldown
                logger.warning("Probe failed — circuit back to OPEN.")
                self._state = CircuitState.OPEN

            elif self._failure_count >= self.failure_threshold:
                logger.warning(
                    "Failure threshold (%d) reached — circuit OPEN.",
                    self.failure_threshold,
                )
                self._state = CircuitState.OPEN

    # ------------------------------------------------------------------
    # Manual controls (useful for testing / admin endpoints)
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Force-reset the circuit breaker to CLOSED state."""
        with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._last_failure_time = 0.0
        logger.info("Circuit breaker manually reset to CLOSED.")

    def force_open(self) -> None:
        """Force the circuit to OPEN (useful in tests to simulate failure)."""
        with self._lock:
            self._state = CircuitState.OPEN
            self._last_failure_time = time.monotonic()
        logger.info("Circuit breaker manually forced OPEN.")

    def get_status(self) -> dict:
        """Return a JSON-serialisable status snapshot."""
        return {
            "state": self.state.value,
            "failure_count": self._failure_count,
            "failure_threshold": self.failure_threshold,
            "recovery_timeout_seconds": self.recovery_timeout,
            "seconds_since_last_failure": round(
                time.monotonic() - self._last_failure_time, 2
            )
            if self._last_failure_time
            else None,
        }
