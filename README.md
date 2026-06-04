# 🧠 AI Decision Engine

> A production-grade, full-stack multi-agent RAG decision engine.
> Four LLM agents debate, a judge scores, a refiner synthesizes — every answer
> is grounded, cached and persisted across server restarts.

[![CI](https://img.shields.io/badge/CI-passing-34C759?style=flat-square)](.github/workflows/ci.yml)
[![Stack](https://img.shields.io/badge/stack-FastAPI%20·%20React%20·%20MongoDB%20·%20LangGraph-007AFF?style=flat-square)](.)
[![License](https://img.shields.io/badge/license-MIT-FFCC00?style=flat-square)](#license)

---

## ✨ Why this project

A single LLM call is fragile: it can hallucinate, miss the latest research, or
choose the wrong interpretation of an ambiguous question. **Decision Engine**
runs *four* agents in parallel, has a *judge* score each candidate answer, and
finally has a *refiner* synthesize a single, evidence-grounded response.

Everything — threads, messages, agent traces, scores, semantic cache — is
persisted in MongoDB. Reload the page, restart the server, restart the cluster:
your conversations resume exactly where you left off.

## 🏗️ Architecture

```
                ┌─────────────────────────────────────────┐
                │  React 18 · Tailwind · Recharts         │
                │   ▸ Chat UI                             │
                │   ▸ Thread sidebar (persistent)         │
                │   ▸ Agent trace panel + score badges    │
                │   ▸ Stats dashboard                     │
                └──────────────────┬──────────────────────┘
                                   │ JSON · cookies
                                   ▼
                ┌─────────────────────────────────────────┐
                │  FastAPI  (uvicorn · /api prefix)       │
                │   ▸ JWT email/password + Emergent Google│
                │   ▸ Brute force protection              │
                │   ▸ CORS for preview/prod origins       │
                └──────────────────┬──────────────────────┘
                                   │
        ┌──────────────────────────┼─────────────────────────────┐
        ▼                          ▼                             ▼
┌─────────────────┐    ┌──────────────────────┐    ┌──────────────────────┐
│  LangGraph      │    │   MongoDB            │    │   Emergent LLM       │
│  workflow       │    │   ▸ users            │    │   (gpt-4.1-mini)     │
│   ▸ check_cache │    │   ▸ user_sessions    │    └──────────────────────┘
│   ▸ fan-out 4   │    │   ▸ threads          │
│      agents     │    │   ▸ messages         │
│   ▸ evaluate    │    │   ▸ agent_runs       │
│   ▸ refine      │    │   ▸ semantic_cache   │
│   ▸ write_cache │    │   ▸ password_reset_  │
└─────────────────┘    │     tokens           │
                       └──────────────────────┘
```

### The four agents

| Color | Agent              | Source                       | Best at                          |
|-------|--------------------|------------------------------|----------------------------------|
| 🔵    | `local_retrieval`  | BM25 + TF-IDF cosine (hybrid) | Anything in the local KB         |
| 🟡    | `general_llm`      | LLM parametric knowledge     | Well-known general topics        |
| 🟢    | `tavily_web`       | Live Tavily web search       | Current events, news             |
| 🔴    | `arxiv_research`   | arXiv abstract search        | Research-grade technical answers |

A **judge** (LLM-as-a-judge) scores each answer 0–10 on correctness,
relevance, clarity and grounding. The highest-scoring answer flows into the
**refiner**, which produces the user-facing final answer.

### Semantic cache

Every refined answer is embedded (TF-IDF) and indexed per user. The next time
a *semantically similar* question is asked (cosine ≥ 0.72), the cached answer
is returned in ~10 ms — bypassing the entire pipeline. Cache hits are visually
indicated in the UI with a glowing cyan badge.

## 📦 Project structure

```
.
├── backend/
│   ├── server.py              # FastAPI app, CORS, startup, /api/health
│   ├── db.py                  # Motor client + index creation
│   ├── auth/
│   │   ├── routes.py          # JWT register/login + Emergent Google
│   │   ├── deps.py            # get_current_user (cookie/header)
│   │   └── security.py        # bcrypt + PyJWT
│   ├── agents/
│   │   ├── graph.py           # LangGraph workflow (cache → 4-agent → judge → refine → write)
│   │   ├── retrieval.py       # Hybrid BM25 + TF-IDF retriever
│   │   ├── cache.py           # MongoDB-backed semantic cache
│   │   ├── external.py        # Tavily + arXiv helpers
│   │   └── llm.py             # emergentintegrations LlmChat wrapper
│   ├── chat/routes.py         # /api/threads, /api/ask
│   └── stats/routes.py        # /api/stats/overview, /api/stats/recent
├── frontend/
│   ├── src/
│   │   ├── pages/             # Landing, Login, Register, AuthCallback, Chat, Dashboard
│   │   ├── components/        # AgentTracePanel
│   │   ├── context/           # AuthContext
│   │   └── lib/api.js         # axios client
│   └── tailwind.config.js     # Swiss/dark theme
├── tests/                     # pytest smoke tests
├── docker-compose.yml         # mongo + backend + frontend
└── .github/workflows/ci.yml   # GitHub Actions CI
```

## 🚀 Quickstart (local)

### Prerequisites

- Python 3.11+
- Node 20+ / yarn
- MongoDB 6+ running locally on `:27017`

### Backend

```bash
cd backend
pip install -r requirements.txt
pip install emergentintegrations --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/
cp ../.env.example .env   # then edit
uvicorn server:app --host 0.0.0.0 --port 8001 --reload
```

### Frontend

```bash
cd frontend
yarn install
yarn start    # http://localhost:3000
```

### Docker (one command)

```bash
docker-compose up --build
# Frontend: http://localhost:3000
# Backend:  http://localhost:8001/docs
```

## 🔑 Environment

`backend/.env`:

| Variable             | Required | Description                                                |
|----------------------|----------|------------------------------------------------------------|
| `MONGO_URL`          | ✅       | MongoDB connection string                                  |
| `DB_NAME`            | ✅       | Mongo database name                                        |
| `EMERGENT_LLM_KEY`   | ✅       | Universal LLM key (OpenAI/Anthropic/Gemini compatible)     |
| `LLM_MODEL`          | ✅       | Default model (e.g. `gpt-4.1-mini`)                        |
| `LLM_PROVIDER`       | ✅       | `openai` / `anthropic` / `gemini`                          |
| `JWT_SECRET`         | ✅       | Long random hex string                                     |
| `ADMIN_EMAIL`        | ✅       | Seeded on first start                                      |
| `ADMIN_PASSWORD`     | ✅       | Seeded on first start                                      |
| `FRONTEND_URL`       | ✅       | Used for CORS                                              |
| `TAVILY_API_KEY`     | ❌       | Enables the live web agent. Skipped if blank.              |

`frontend/.env`:

| Variable                | Description                       |
|-------------------------|-----------------------------------|
| `REACT_APP_BACKEND_URL` | URL where the FastAPI app is served |

## 🔌 API

Interactive Swagger docs at **`/docs`** when the backend is running.

| Method | Path                          | Description                                   |
|-------:|-------------------------------|-----------------------------------------------|
| GET    | `/api/`                       | Service info                                  |
| GET    | `/api/health`                 | Health probe                                  |
| POST   | `/api/auth/register`          | Email + password registration                 |
| POST   | `/api/auth/login`             | Email + password login                        |
| POST   | `/api/auth/logout`            | Clears cookies                                |
| GET    | `/api/auth/me`                | Current authenticated user                    |
| POST   | `/api/auth/refresh`           | Refresh access token                          |
| POST   | `/api/auth/forgot-password`   | Generate reset link (logged to console)       |
| POST   | `/api/auth/reset-password`    | Reset password with token                     |
| POST   | `/api/auth/google/session`    | Exchange Emergent OAuth `session_id` for cookie |
| GET    | `/api/threads`                | List user threads                             |
| POST   | `/api/threads`                | Create empty thread                           |
| GET    | `/api/threads/{id}`           | Get thread + messages                         |
| DELETE | `/api/threads/{id}`           | Delete thread + messages                      |
| POST   | `/api/ask`                    | Ask a question (auto-creates thread if needed)|
| GET    | `/api/stats/overview`         | Aggregated metrics (user, or all if admin)    |
| GET    | `/api/stats/recent`           | Last 20 runs                                  |

## 🎯 Resume bullet points

Use these on your CV — every claim is backed by code in this repo.

- Designed and built a **production-grade multi-agent RAG system** (LangGraph,
  FastAPI, React, MongoDB) with 4 parallel agents, LLM-as-a-judge evaluation,
  answer refinement and a persistent semantic cache.
- Implemented **dual authentication** — JWT (email+password) and Emergent
  Google OAuth — sharing a unified user model; httpOnly cookies, bcrypt,
  brute-force lockout, and password reset tokens with TTL.
- Persistent **per-user state** in MongoDB (threads, messages, agent traces,
  scores, latency, semantic cache) — conversations survive server restarts.
- **Hybrid retrieval** combining BM25 (sparse) and TF-IDF cosine (dense
  substitute) over an in-process knowledge base with min-max score fusion.
- **Async fan-out** of all four agents via `asyncio.gather` for low end-to-end
  latency; LLM-as-a-judge scores each answer 0–10; refiner produces a single
  user-facing answer.
- Built a **command-center dashboard** with per-agent leaderboard, average
  scores, win counts, cache hit rate and weekly query volume.
- Shipped **CI** (GitHub Actions: pytest + frontend build), **Docker
  Compose** (mongo + backend + frontend) and **OpenAPI/Swagger** docs.

## 🧪 Testing

```bash
# Unit tests (no LLM needed)
pytest tests/test_retrieval.py -v

# Smoke tests against a running backend
E2E_BACKEND_URL=http://localhost:8001 pytest tests/test_api.py -v
```

## 🛣️ Roadmap

- [ ] Per-user knowledge base ingestion (upload PDFs / URLs)
- [ ] Streamed token responses over Server-Sent Events
- [ ] Admin view: per-user cost & token tracking
- [ ] Rate limiting middleware

## 📄 License

MIT — see [LICENSE](LICENSE) (add your name).

---

Built with care · LangGraph · FastAPI · MongoDB · React · Tailwind · Recharts
