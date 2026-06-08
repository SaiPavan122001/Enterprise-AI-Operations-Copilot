# Enterprise AI Operations Copilot

An AI-powered Operations Copilot that performs automated Root Cause Analysis (RCA) across incidents, deployments, and application logs using Retrieval-Augmented Generation (RAG), Multi-Agent AI, LangGraph workflows, Qdrant Vector Search, Gemini, and Langfuse observability.

---

## Overview

Enterprise operations teams spend significant time investigating production incidents, deployment failures, and service outages.

This project automates the investigation process by combining:

* Semantic Search (RAG)
* Multi-Agent Analysis
* LangGraph Workflow Orchestration
* Gemini AI Reasoning
* Vector Database Retrieval
* LLM Observability

The system retrieves relevant operational data, correlates incidents with deployments and logs, and generates structured RCA reports.

---

## Key Features

### AI-Powered Root Cause Analysis

Generate structured RCA reports including:

* Root Cause
* Supporting Evidence
* Resolution Recommendations
* Risk Assessment
* Preventive Actions

---

### Multi-Agent Architecture

Specialized agents investigate different operational domains:

* Incident Agent
* Deployment Agent
* Log Analysis Agent
* Gemini RCA Agent

Each agent contributes context to the final investigation.

---

### Retrieval-Augmented Generation (RAG)

Uses:

* Sentence Transformers
* Vector Embeddings
* Qdrant Vector Database

to retrieve semantically relevant operational records.

---

### LangGraph Workflow

Coordinates investigation steps:

1. Incident Analysis
2. Deployment Analysis
3. Log Analysis
4. RCA Generation

---

### Langfuse Observability

Tracks:

* RCA requests
* LLM interactions
* Prompt usage
* Investigation traces

---

### Modern React Frontend

Features:

* ChatGPT/Gemini-style interface
* Light & Dark Theme
* Real-time RCA generation
* Conversation view
* Loading states

---

## System Architecture

```text
User
│
▼
React Frontend
│
▼
FastAPI Backend
│
▼
LangGraph Workflow
│
├─────────────► Incident Agent
│
├─────────────► Deployment Agent
│
├─────────────► Log Agent
│
▼
Qdrant Vector Search
│
▼
Relevant Operational Context
│
▼
Gemini RCA Agent
│
▼
Langfuse Observability
│
▼
Root Cause Analysis Report
```

---

## Tech Stack

### Frontend

* React
* Vite
* JavaScript
* CSS

### Backend

* FastAPI
* Python

### AI & RAG

* Gemini 2.5 Flash
* LangGraph
* SentenceTransformers
* Qdrant

### Observability

* Langfuse

### Data

* Incidents Dataset
* Deployments Dataset
* Application Logs

---

## Project Structure

```text
enterprise-ai-copilot/

backend/
│
├── agents/
│   ├── incident_agent.py
│   ├── deployment_agent.py
│   ├── log_agent.py
│   └── gemini_rca_agent.py
│
├── workflows/
│   └── rca_graph.py
│
├── vector_store/
│   ├── qdrant_client.py
│   ├── search_service.py
│   └── load_enterprise_data.py
│
├── observability/
│   └── langfuse_client.py
│
├── api/
│   └── routes.py
│
└── app.py

frontend/
│
├── src/
├── App.jsx
└── main.jsx
```

---

## API Endpoints

### Health Check

```http
GET /health
```

### Search

```http
POST /search
```

### Investigate

```http
POST /investigate
```

Example:

```text
Why is payroll failing?
```

```text
What deployment caused the outage?
```

```text
Which logs indicate the root cause?
```

---

## Running the Project

### Backend

```bash
cd backend

uvicorn app:app
```

Backend URL:

```text
http://127.0.0.1:8000
```

Swagger:

```text
http://127.0.0.1:8000/docs
```

---

### Frontend

```bash
cd frontend

npm install

npm run dev
```

Frontend:

```text
http://localhost:5173
```

---

## Future Enhancements

* Full Agentic AI Architecture
* Tool Calling with Gemini
* Conversation Memory
* Multi-turn Investigations
* MCP Integration
* Kubernetes Deployment
* Dockerized Infrastructure
* Authentication & Role-Based Access
* Real-time Incident Monitoring

---

## Resume Highlights

* Built an Enterprise AI Operations Copilot using FastAPI, React, LangGraph, Gemini, and Qdrant.
* Implemented Retrieval-Augmented Generation (RAG) with vector search for operational investigations.
* Designed a Multi-Agent AI workflow for incident, deployment, and log analysis.
* Integrated Gemini AI for automated Root Cause Analysis generation.
* Added observability and tracing using Langfuse.
* Developed a conversational frontend for real-time operational investigations.

---

## License

MIT License
