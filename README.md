# Enterprise AI Operations Copilot

An AI-powered Operations Copilot that performs automated Root Cause Analysis (RCA) across incidents, deployments, and application logs using Retrieval-Augmented Generation (RAG), Multi-Agent AI, LangGraph workflows, Qdrant Vector Search, Gemini, and Langfuse observability.

---

## Architecture

```text
User
│
▼
React Frontend (Vite)
│  POST /investigate[/stream]  { "question": "..." }   ← VITE_API_URL
│  (SSE stream of real workflow stage completions)
▼
FastAPI Backend
│
▼
LangGraph Investigation Workflow
  question_analysis → incident_retrieval → deployment_correlation
  → log_retrieval → runbook_retrieval → evidence_aggregation
  → evidence_validation → rca_generation
│
├─ Incident Agent   → Qdrant vector search, relevance-score filtered
├─ Deployment Agent → correlates via incident.deployment_id (service fallback)
├─ Log Agent        → structured log entries, ERROR/WARN prioritised
├─ Runbook Agent    → retrieves matching runbook as GUIDANCE (not evidence)
├─ Evidence Layer   → structured EvidenceBundle (models/evidence.py)
├─ Evidence Validation → incident/deployment/log/runbook checks → strength
│                        (HIGH | MEDIUM | LOW | INSUFFICIENT) — authoritative
▼
Gemini RCA (grounded structured prompt; confidence clamped by evidence layer)
│
▼
Structured JSON response
{ status, investigation: { summary, impact, root_cause, confidence,
  contributing_factors, recommended_remediation, preventive_actions,
  observed_evidence, timeline, evidence, validation }, report (markdown fallback) }
│
▼
React RCA card: evidence labels (OBSERVED EVIDENCE / RUNBOOK GUIDANCE /
AI ANALYSIS / RECOMMENDATION), timeline, collapsible evidence panels, feedback
```

Supporting systems: Qdrant (semantic retrieval), Langfuse (one trace per
investigation with per-stage spans; optional), localStorage (investigation
history + feedback — no fake backend persistence).

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React 19, Vite, plain CSS, react-markdown |
| Backend | Python 3.12, FastAPI, Pydantic, uvicorn |
| Workflow | LangGraph |
| LLM | Google Gemini 2.5 Flash (`google-genai`) |
| Embeddings | SentenceTransformers `BAAI/bge-small-en-v1.5` |
| Vector DB | Qdrant (embedded local mode) |
| Observability | Langfuse (optional) |

---

## Project Structure

```text
backend/
├── app.py                  # FastAPI app, CORS, error handlers, lifespan
├── config.py               # All environment-driven settings
├── api/routes.py           # Pydantic models + endpoints
├── agents/
│   ├── incident_agent.py   # Vector search
│   ├── deployment_agent.py # deployment_id correlation
│   ├── log_agent.py        # Log retrieval
│   ├── runbook_agent.py    # Runbook matching
│   └── gemini_rca_agent.py # Grounded RCA generation + fallback
├── workflows/rca_graph.py  # LangGraph investigation workflow
├── vector_store/           # Qdrant client, setup, seed script
├── utils/                  # Data cache, rate limiter
├── observability/          # Langfuse (optional, defensive init)
├── data/                   # incidents.json, deployments.json, logs.txt, runbooks/
├── tests/                  # pytest suite (external services mocked)
└── requirements.txt

frontend/
├── src/
│   ├── App.jsx             # Layout, state, investigation flow
│   ├── components/         # Header, Sidebar, RCAReport, EvidencePanel, …
│   └── services/api.js     # Backend client (VITE_API_URL)
└── .env.example
```

---

## Setup

### 1. Backend

```bash
cd backend
python -m venv venv
venv\Scripts\activate            # Windows  (source venv/bin/activate on macOS/Linux)
pip install -r requirements.txt
```

Create `backend/.env` (see `.env.example`):

```env
GEMINI_API_KEY=your_gemini_api_key
LANGFUSE_PUBLIC_KEY=...
LANGFUSE_SECRET_KEY=...
LANGFUSE_HOST=https://cloud.langfuse.com
CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
```

### 2. Initialize the vector database (one command)

```bash
cd backend
python -m scripts.seed
```

Validates the data, creates the Qdrant collection (with payload indexes),
embeds all 20 incidents with deterministic point IDs, upserts, and verifies
the record count. Safe to re-run.

### 3. Run the backend

```bash
cd backend
uvicorn app:app --reload
# http://127.0.0.1:8000 — Swagger: http://127.0.0.1:8000/docs
```

### 4. Frontend

```bash
cd frontend
npm install
copy .env.example .env           # sets VITE_API_URL=http://127.0.0.1:8000
npm run dev
# http://localhost:5173
```

---

## Environment Variables

### Backend (`backend/.env`)

| Variable | Required | Description |
|---|---|---|
| `GEMINI_API_KEY` | yes | Google Gemini API key |
| `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` / `LANGFUSE_HOST` | no | Langfuse observability (app runs fine without) |
| `CORS_ORIGINS` | no | Comma-separated allowed origins (default: localhost:5173) |
| `GEMINI_MODEL`, `GEMINI_TIMEOUT_MS`, `GEMINI_MAX_RETRIES` | no | LLM tuning |
| `MIN_RELEVANCE_SCORE` | no | Incident retrieval relevance threshold (default 0.30) |
| `LOG_LEVEL` | no | Python logging level (default INFO) |
| `QDRANT_PATH`, `QDRANT_COLLECTION` | no | Vector store location/collection |
| `INVESTIGATE_RATE_LIMIT`, `INVESTIGATE_RATE_WINDOW_SECONDS` | no | Per-IP rate limit on `/investigate` |

### Frontend (`frontend/.env`)

| Variable | Description |
|---|---|
| `VITE_API_URL` | Backend base URL, e.g. `http://127.0.0.1:8000` |

---

## API Endpoints

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/health` | — | `{ status, qdrant, gemini_configured }` |
| POST | `/search` | `{ "query": "...", "limit": 5 }` | `{ status, results }` |
| POST | `/investigate` | `{ "question": "..." }` | `{ status, investigation, report, message }` |
| POST | `/investigate/stream` | `{ "question": "..." }` | SSE: real stage-completion events, then `investigation_completed` with the full payload |

The `investigation` object contains structured RCA data (summary, impact,
root cause, confidence, contributing factors, remediation, preventive
actions, observed evidence, timeline, full evidence bundle and the evidence
validation verdict). `report` is the same RCA as markdown for fallback
rendering. Errors always return `{ "status": "error", "message": ... }` —
internal exceptions are logged, never exposed.

---

## Running Tests

```bash
cd backend
python -m pytest tests/ -v
```

Tests mock Qdrant/Gemini/LangGraph — **no API credits are consumed**.

---

## Production Considerations

- Set `CORS_ORIGINS` to your real frontend domain (wildcards are not used).
- Add authentication in front of `/investigate` before exposing it publicly (rate limiting alone does not prevent abuse).
- Replace the embedded local Qdrant with a Qdrant server (`QDRANT_URL`) for multi-instance deployments.
- Run behind a process manager (e.g. `uvicorn` under systemd/Docker) with `LOG_LEVEL=INFO`.
- Langfuse keys are optional; all observability calls fail soft.

---

## Future Production Evolution (documented, not implemented)

Persistence is currently file-based + localStorage by design. When real
multi-user persistence is needed:

- **PostgreSQL/Supabase** → `users`, `investigations`, `messages`, `feedback`,
  persistent RCA history (replacing localStorage history/feedback).
- **Qdrant** (server mode) → semantic retrieval over incidents, runbooks and
  future knowledge articles.
- **Authentication** → required before any public deployment.
- **MCP integration** → `backend/mcp_server/server.py` already exposes real
  tools (`search_incidents_tool`, `get_deployment`, `search_logs`,
  `get_runbook`) for future agent integrations.

---

## License

MIT License
