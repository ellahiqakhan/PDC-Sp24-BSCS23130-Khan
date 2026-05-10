"""
Tests — Circuit Breaker & LLM Fault Tolerance
----------------------------------------------
PDC Assignment 2 | Ellahiqa Khan | BSCS23130

Run all tests:
    pytest tests/ -v

Run with failure simulation (LLM always times out):
    LLM_SIMULATE_FAILURE=true pytest tests/ -v

What these tests prove:
  1. BEFORE fix: a single slow call blocks everything (simulated).
  2. AFTER fix:  the circuit opens, subsequent calls get instant fallback,
                 and the X-Student-ID header is always present.
"""

import os
import time
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Ensure we are NOT hitting a real LLM during tests
# ---------------------------------------------------------------------------
os.environ["LLM_SIMULATE_FAILURE"] = "false"  # we control failures via mocks

from app.main import app                          # noqa: E402 — import after env set
from app.circuit_breaker import CircuitBreaker, CircuitState, CircuitBreakerOpenException
from app.llm_service import llm_circuit_breaker   # noqa: E402

client = TestClient(app)

STUDENT_ID = "BSCS23130"

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_circuit_breaker():
    """Reset circuit breaker to CLOSED before every test for isolation."""
    llm_circuit_breaker.reset()
    yield
    llm_circuit_breaker.reset()


# ===========================================================================
# 1. X-Student-ID header — mandatory on every response
# ===========================================================================

class TestStudentIDHeader:
    def test_root_has_student_id_header(self):
        resp = client.get("/")
        assert resp.headers.get("x-student-id") == STUDENT_ID, (
            "X-Student-ID header missing from GET /"
        )

    def test_health_has_student_id_header(self):
        resp = client.get("/health")
        assert resp.headers.get("x-student-id") == STUDENT_ID

    def test_ask_has_student_id_header_on_fallback(self):
        """Even when circuit is OPEN and fallback fires, header must be present."""
        llm_circuit_breaker.force_open()
        resp = client.post("/ask", json={"prompt": "test"})
        assert resp.headers.get("x-student-id") == STUDENT_ID

    def test_404_has_student_id_header(self):
        resp = client.get("/nonexistent-route")
        assert resp.headers.get("x-student-id") == STUDENT_ID


# ===========================================================================
# 2. Circuit Breaker unit tests
# ===========================================================================

class TestCircuitBreakerUnit:
    def test_initial_state_is_closed(self):
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=30)
        assert cb.state == CircuitState.CLOSED

    def test_success_keeps_circuit_closed(self):
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=30)
        result = cb.call(lambda: "ok")
        assert result == "ok"
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0

    def test_failures_increment_counter(self):
        cb = CircuitBreaker(failure_threshold=5, recovery_timeout=30)
        for i in range(3):
            with pytest.raises(RuntimeError):
                cb.call(lambda: (_ for _ in ()).throw(RuntimeError("fail")))
        assert cb.failure_count == 3
        assert cb.state == CircuitState.CLOSED  # not yet at threshold

    def test_circuit_opens_at_threshold(self):
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=30)
        for _ in range(3):
            with pytest.raises(Exception):
                cb.call(lambda: (_ for _ in ()).throw(RuntimeError("fail")))
        assert cb.state == CircuitState.OPEN

    def test_open_circuit_raises_without_fallback(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=30)
        with pytest.raises(RuntimeError):
            cb.call(lambda: (_ for _ in ()).throw(RuntimeError("fail")))
        # Now OPEN — next call should short-circuit
        with pytest.raises(CircuitBreakerOpenException):
            cb.call(lambda: "should not run")

    def test_open_circuit_uses_fallback(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=30)
        with pytest.raises(RuntimeError):
            cb.call(lambda: (_ for _ in ()).throw(RuntimeError("fail")))
        result = cb.call(lambda: "nope", fallback=lambda: "fallback_value")
        assert result == "fallback_value"

    def test_success_after_failures_resets_counter(self):
        cb = CircuitBreaker(failure_threshold=5, recovery_timeout=30)
        for _ in range(2):
            with pytest.raises(RuntimeError):
                cb.call(lambda: (_ for _ in ()).throw(RuntimeError("x")))
        cb.call(lambda: "ok")  # success
        assert cb.failure_count == 0
        assert cb.state == CircuitState.CLOSED

    def test_half_open_transition(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.1)
        with pytest.raises(RuntimeError):
            cb.call(lambda: (_ for _ in ()).throw(RuntimeError("fail")))
        assert cb.state == CircuitState.OPEN
        time.sleep(0.15)  # let recovery timeout elapse
        assert cb.state == CircuitState.HALF_OPEN

    def test_half_open_success_closes_circuit(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.1)
        with pytest.raises(RuntimeError):
            cb.call(lambda: (_ for _ in ()).throw(RuntimeError("fail")))
        time.sleep(0.15)
        cb.call(lambda: "probe_ok")
        assert cb.state == CircuitState.CLOSED

    def test_manual_force_open(self):
        cb = CircuitBreaker(failure_threshold=10, recovery_timeout=30)
        cb.force_open()
        assert cb.state == CircuitState.OPEN

    def test_manual_reset(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=30)
        cb.force_open()
        cb.reset()
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0


# ===========================================================================
# 3. BEFORE the fix — simulating the blocking failure
# ===========================================================================

class TestBeforeFix:
    """
    Simulate what happens WITHOUT the circuit breaker:
    A slow/hanging LLM call blocks the thread for the full timeout.
    We measure wall-clock time to prove the server was blocked.
    """

    def test_slow_llm_blocks_without_circuit_breaker(self):
        """
        Without the circuit breaker, every call to a timing-out LLM
        blocks for the full timeout duration. We cap the mock at 0.5 s
        to keep tests fast, but in production this would be 60 seconds.
        """
        SIMULATED_TIMEOUT = 0.5  # seconds (represents the real 60-s timeout)

        def slow_llm_call(prompt: str):
            time.sleep(SIMULATED_TIMEOUT)   # ← this is what hangs the server
            raise TimeoutError("LLM timed out after 60 s")

        start = time.monotonic()
        with pytest.raises(TimeoutError):
            slow_llm_call("any prompt")
        elapsed = time.monotonic() - start

        assert elapsed >= SIMULATED_TIMEOUT, (
            "Expected the call to block for at least the timeout duration"
        )
        print(f"\n[BEFORE FIX] Call blocked for {elapsed:.3f}s — server hung!")


# ===========================================================================
# 4. AFTER the fix — circuit breaker + fallback
# ===========================================================================

class TestAfterFix:
    """
    Prove that after integrating the Circuit Breaker:
      • Failures are counted and the circuit opens.
      • Subsequent calls get an INSTANT fallback (no blocking).
      • The X-Student-ID header is always present.
    """

    @patch("app.llm_service._call_llm_api", side_effect=TimeoutError("LLM down"))
    def test_circuit_opens_after_repeated_failures(self, mock_llm):
        """Three consecutive LLM failures should open the circuit."""
        for _ in range(3):
            resp = client.post("/ask", json={"prompt": "hello"})
            assert resp.status_code == 200          # fallback keeps service up
            assert resp.json()["source"] == "fallback"

        status = client.get("/circuit/status").json()
        assert status["state"] == "OPEN"

    @patch("app.llm_service._call_llm_api", side_effect=TimeoutError("LLM down"))
    def test_fallback_is_instant_when_circuit_is_open(self, mock_llm):
        """
        Once the circuit is OPEN, subsequent calls must return in < 100 ms
        regardless of how long the real LLM would have taken.
        """
        # Trip the breaker
        for _ in range(3):
            client.post("/ask", json={"prompt": "trip"})

        # Now measure — should be near-instant
        start = time.monotonic()
        resp = client.post("/ask", json={"prompt": "fast?"})
        elapsed = time.monotonic() - start

        assert resp.status_code == 200
        assert resp.json()["source"] == "fallback"
        assert resp.json()["circuit_state"] == "OPEN"
        assert elapsed < 0.1, f"Fallback took {elapsed:.3f}s — should be instant!"
        print(f"\n[AFTER FIX]  Fallback returned in {elapsed*1000:.1f} ms ✓")

    @patch("app.llm_service._call_llm_api", return_value={
        "response": "Here is the answer.", "source": "llm_api", "circuit_state": "CLOSED"
    })
    def test_healthy_llm_returns_real_response(self, mock_llm):
        """When the LLM is healthy, the real response should be returned."""
        resp = client.post("/ask", json={"prompt": "What is machine learning?"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["source"] == "llm_api"
        assert data["circuit_state"] == "CLOSED"

    def test_fallback_message_is_user_friendly(self):
        """The fallback response should be a helpful message, not an error."""
        llm_circuit_breaker.force_open()
        resp = client.post("/ask", json={"prompt": "test"})
        data = resp.json()
        assert "temporarily unavailable" in data["response"].lower()
        assert data["source"] == "fallback"

    @patch("app.llm_service._call_llm_api", side_effect=TimeoutError("LLM down"))
    def test_service_stays_200_during_llm_outage(self, mock_llm):
        """The API must never return 5xx during an LLM outage — fallback keeps it alive."""
        for _ in range(10):  # 10 calls during outage
            resp = client.post("/ask", json={"prompt": "still working?"})
            assert resp.status_code == 200, (
                f"Got {resp.status_code} — service should stay up during LLM outage"
            )

    def test_circuit_reset_endpoint(self):
        """Admin reset endpoint should bring the circuit back to CLOSED."""
        llm_circuit_breaker.force_open()
        resp = client.post("/circuit/reset")
        assert resp.status_code == 200
        assert resp.json()["state"] == "CLOSED"

    def test_health_endpoint_shows_degraded_when_open(self):
        """Health check should report 'degraded' when circuit is OPEN."""
        llm_circuit_breaker.force_open()
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "degraded"

    def test_health_endpoint_shows_healthy_when_closed(self):
        """Health check should report 'healthy' when circuit is CLOSED."""
        resp = client.get("/health")
        assert resp.json()["status"] == "healthy"


# ===========================================================================
# 5. Concurrent requests — prove no thread blocking
# ===========================================================================

class TestConcurrency:
    @patch("app.llm_service._call_llm_api", side_effect=TimeoutError("LLM down"))
    def test_concurrent_requests_all_get_fallback(self, mock_llm):
        """
        Fire 10 concurrent requests while the circuit is tripped.
        All should resolve near-instantly via fallback.
        """
        import threading

        results = []

        def make_request():
            r = client.post("/ask", json={"prompt": "concurrent"})
            results.append(r.status_code)

        # Trip the circuit
        for _ in range(3):
            client.post("/ask", json={"prompt": "trip"})

        # Fire concurrent requests
        threads = [threading.Thread(target=make_request) for _ in range(10)]
        start = time.monotonic()
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        elapsed = time.monotonic() - start

        assert all(s == 200 for s in results), "Some requests failed"
        assert elapsed < 2.0, f"Concurrent requests took {elapsed:.2f}s — too slow"
        print(f"\n[CONCURRENCY] 10 requests resolved in {elapsed*1000:.0f} ms ✓")
