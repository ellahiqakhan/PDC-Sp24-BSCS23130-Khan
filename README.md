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
uvicorn app.main:app --reload --port 8001
```
## Demo Commands (PowerShell)

Invoke-WebRequest -Uri "http://localhost:8001/health"

Invoke-WebRequest -Uri "http://localhost:8001/circuit/force-open" -Method Post

Invoke-WebRequest -Uri "http://localhost:8001/ask" -Method Post -Body '{"prompt":"test"}' -ContentType "application/json"

Invoke-WebRequest -Uri "http://localhost:8001/health"

Invoke-WebRequest -Uri "http://localhost:8001/circuit/reset" -Method Post

---

## Running the Tests

```bash
# Normal run (mocks the LLM)
pytest tests/ -v

# With verbose output and timing
pytest tests/ -v --tb=short
```

---

## Simulating LLM Failure

```bash
LLM_SIMULATE_FAILURE=true uvicorn app.main:app --reload --port 8001
```

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
