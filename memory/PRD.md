# PRD — AI Decision Engine

## Original problem statement
> "well this is the repo and in this I have not connected it to databases and it's not a good project I want to make it better and a bit at production level, make it good project so it can be used in my resume to give me jobs"

## Vision
Turn a single-file FastAPI multi-agent RAG demo into a full-stack, resume-grade product that recruiters and engineers can run, read and remember.

## User personas
1. **Resume reader (recruiter / hiring manager)** — quickly glances at the landing page and README, looks for sophistication signals (multi-agent, persistence, auth).
2. **Reviewing engineer** — clones the repo, reads code, looks for clean architecture, tests, CI, docker.
3. **End user** — signs up, asks questions, expects threads to persist, expects fast answers, sees agent reasoning.

## Core requirements (static)
- Multi-agent RAG: local retrieval, general LLM, web search, arXiv research
- LLM-as-judge evaluation + refinement
- Persistent semantic cache (per user, MongoDB-backed)
- JWT email/password + Emergent Google OAuth (unified user model)
- Threads persisted (resume across server restarts) — primary user requirement
- Stats / admin dashboard
- Production polish: Dockerfile, docker-compose, CI, README with architecture diagram

## Architecture (high-level)
React (Tailwind, Phosphor, Recharts) → FastAPI `/api` → LangGraph workflow → MongoDB + Emergent LLM (gpt-4.1-mini).

## What's been implemented (2026-06-04)
- [x] Backend: FastAPI app with `/api` prefix, CORS, JWT auth, Google OAuth, brute force lockout, password reset, indexes, admin seed
- [x] LangGraph workflow with concurrent agent fan-out, judge & refiner
- [x] **Streaming `/api/ask/stream` endpoint (SSE)** — emits `cache_check`, `agent_start/complete`, `judge_scores`, `refine_token`, `done` events; UI displays a live agent-status panel and streams refined tokens in real time
- [x] **Deployed to production** at https://career-showcase-511.emergent.host
- [x] **README showcase**: 5 polished screenshots committed to `docs/screenshots/` + Playwright capture script at `scripts/capture_screenshots.py` to regenerate them anytime
- [x] Hybrid retriever (BM25 + TF-IDF cosine, min-max fused)
- [x] Persistent semantic cache (per-user, hydrates from MongoDB)
- [x] Chat routes: list/create/get/delete threads, /ask
- [x] Stats routes: overview + recent
- [x] Frontend: Landing, Login, Register, AuthCallback, Chat, Dashboard
- [x] Agent trace panel with color-coded scores, "Best" badge, expandable context
- [x] Cache hit badge with similarity %
- [x] Recharts dashboard with avg scores per agent + leaderboard
- [x] Dockerfile (backend), Dockerfile (frontend nginx), docker-compose, CI workflow
- [x] Comprehensive README with architecture diagram + resume bullets
- [x] Smoke tests (auth, threads/stats require auth) + unit tests for retrieval
- [x] **DONE 2026-06-05**: File upload + multimodal RAG (PDF / TXT / images) — `/api/uploads` (POST/GET/DELETE), pypdf text extraction, OpenAI gpt-4o vision OCR/description for images, TF-IDF retrieval over per-thread chunks, paperclip + attachment-chips UI in chat composer, `uploads_used` SSE event, judge / refiner / cache made upload-aware
- [x] **DONE 2026-06-09 — AI Mentor 2.0 upgrade**:
  - OCR for scanned + mixed PDFs via Tesseract (`pytesseract` + `pdf2image`) with per-page strategy (text first, OCR fallback on <30 chars)
  - **Hybrid retrieval** on per-thread documents: BM25 (`rank_bm25`) + dense FAISS embeddings (fastembed `BAAI/bge-small-en-v1.5`, 384-d, ONNX, no PyTorch) merged via Reciprocal Rank Fusion (k=60)
  - **Persistent FAISS indices** on disk (`/app/data/faiss/<thread_id>.{index,ids.json}`) with auto-rebuild from MongoDB chunks if files are missing — users never have to re-upload
  - **5th agent `thread_files`** activated only when the thread has uploads — purple in trace panel + live pipeline, hard-override picks it as best when grounded in any uploaded chunk token / filename
  - **Conversation memory**: rolling LLM summary regenerated every 10 messages (with delta-since-last counter so boundaries aren't skipped through cache hits) + short-term last-5 messages composed into every agent prompt; uniform `memory_loaded` SSE event on cache-hit and engine paths
  - **Document summarize endpoint** `POST /api/uploads/{file_id}/summarize` returns structured markdown (TL;DR / Key points / Entities / Open questions)
  - **Frontend**: drag-and-drop overlay, paste-image-from-clipboard handler, per-chip Summarize button + modal, microphone STT via browser Web Speech API, per-assistant-message Read-aloud via Web Speech TTS, dynamic 5-column LivePipeline when uploads exist
  - **New SSE events** `memory_loaded`, `summary_updated` for full observability

## Backlog (P0/P1/P2)
- [x] **DONE 2026-06-04**: SSE/streaming responses for the `/ask` flow with live agent state + token streaming
- [x] **DONE 2026-06-05**: User file uploads (PDFs, text files, images) grounded into RAG retrieval per thread — the ChatGPT-style attachment flow
- [x] **DONE 2026-06-09**: Drag-and-drop + paste-image upload; OCR; FAISS; conversation memory; per-doc summary; voice (browser STT/TTS)
- P2: Token & cost tracking per user
- P2: Rate-limiting middleware (slowapi)
- P2: Email delivery for password reset (currently logged to console)
- P2: Production cost calculator visualization
- P2: Cross-encoder reranker (e.g. bge-reranker-base) to replace RRF for higher precision retrieval
- P2: Per-thread `upload_count` denormalized to thread doc to skip the per-request count_documents() call
- [x] **DONE 2026-06-22 — LangSmith Level-1 tracing**: `@traceable` on `call_llm` / `stream_llm` (async-generator with `reduce_fn` aggregator) / `_run_one_agent` / `_score_trace`. Each `/api/ask/stream` is wrapped as a single root `ask_stream` trace via `tracing.trace_root` (graceful no-op when `LANGSMITH_TRACING` is unset). Judge scores (per-agent + `judge_best_score`) are pushed to LangSmith Feedback API; root run metadata carries `user_id`, `thread_id`, `best_agent`, `has_uploads`, `upload_count`. Project: `ai-mentor-prod`.

## Test credentials
See `/app/memory/test_credentials.md`.
