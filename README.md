Ellahiqa Khan - BSCS23130

# PDC Assignment 2 — Building Resilient Distributed Systems

**Course:** Parallel and Distributed Computing (PDC)  
**Problem Solved:** Problem 3 — Fault Tolerance via Circuit Breaker Pattern

---

## Project Structure

```
PDC-Sp24-BSCS23130-Khan/
├── app/
│   ├── __init__.py
│   ├── main.py             # FastAPI app + X-Student-ID middleware
│   ├── circuit_breaker.py  # Circuit Breaker implementation (CLOSED/OPEN/HALF_OPEN)
│   └── llm_service.py      # LLM API wrapper using the circuit breaker
├── tests/
│   ├── __init__.py
│   └── test_llm_failure.py # Test suite (before/after failure simulation)
├── requirements.txt
└── README.md
```

---

## Setup & Installation

```bash
# 1. Clone the repository
git clone https://github.com/<your-username>/PDC-Sp24-BSCS23130-Khan.git
cd PDC-Sp24-BSCS23130-Khan

# 2. Create and activate a virtual environment
python -m venv venv
source venv/bin/activate        # macOS/Linux
# venv\Scripts\activate         # Windows

# 3. Install dependencies
pip install -r requirements.txt
```

---

## Running the Server

```bash
uvicorn app.main:app --reload
```

The API will be available at `http://127.0.0.1:8000`.  
Interactive docs: `http://127.0.0.1:8000/docs`

---

## Running the Tests

```bash
# Normal run (mocks the LLM)
pytest tests/ -v

# With verbose output and timing
pytest tests/ -v --tb=short
```

---

## Simulating LLM Failure (for demo)

```bash
# Start server with LLM failure simulation enabled
LLM_SIMULATE_FAILURE=true uvicorn app.main:app --reload
```

With this flag set, every call to the real LLM endpoint is replaced by a
simulated timeout. The circuit breaker will trip after 3 attempts and all
subsequent requests will receive an instant fallback response.

---

## Key API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Root health check |
| `POST` | `/ask` | Submit prompt to LLM (circuit-breaker protected) |
| `GET` | `/health` | Service health + circuit state |
| `GET` | `/circuit/status` | Detailed circuit breaker status |
| `POST` | `/circuit/reset` | Force circuit to CLOSED |
| `POST` | `/circuit/force-open` | Force circuit to OPEN (demo use) |

---

## Verifying the X-Student-ID Header

```bash
# Using curl
curl -I http://127.0.0.1:8000/
# Look for: x-student-id: BSCS23130

# Using curl with a POST
curl -s -D - -X POST http://127.0.0.1:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"prompt": "hello"}' | grep -i "x-student-id"

# Expected output:
# x-student-id: BSCS23130
```

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_API_URL` | OpenAI endpoint | URL of the LLM API |
| `LLM_API_KEY` | `sk-placeholder` | LLM API key |
| `LLM_TIMEOUT_SECONDS` | `10` | Seconds before an LLM call times out |
| `LLM_SIMULATE_FAILURE` | `false` | Set `true` to simulate LLM timeout |
