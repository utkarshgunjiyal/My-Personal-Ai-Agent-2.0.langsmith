# AI Decision Engine API

A FastAPI-based multi-agent RAG decision engine using LangGraph, hybrid retrieval, LLM evaluation, answer refinement, and semantic caching.

## Features

- FastAPI backend with Swagger docs
- LangGraph workflow orchestration
- Hybrid retrieval using FAISS + BM25
- Semantic cache using embeddings
- Multiple answer-generation agents:
  - Local retrieval agent
  - General LLM agent
  - Tavily web-search agent
  - arXiv research agent
- LLM-as-a-judge evaluation
- Final answer refinement
- Thread-based LangGraph checkpointing with `MemorySaver`

## Project Structure

```text
.
├── main.py              # FastAPI API layer
├── graph.py             # LangGraph workflow
├── retrieval.py         # Hybrid retriever: FAISS + BM25
├── cache.py             # Semantic cache
├── external_agents.py   # Tavily and arXiv helper functions
├── requirements.txt     # Python dependencies
├── .env.example         # Environment variable template
├── Dockerfile           # Docker deployment file
└── README.md
```

## Setup Locally

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Create a `.env` file:

```bash
cp .env.example .env
```

Add your keys:

```env
OPENROUTER_API_KEY=your_openrouter_api_key_here
TAVILY_API_KEY=your_tavily_api_key_here
```

## Run Locally

```bash
uvicorn main:api --reload
```

Open Swagger docs:

```text
http://127.0.0.1:8000/docs
```

## Main Endpoint

### POST `/ask`

Request body:

```json
{
  "question": "What is RAG?",
  "thread_id": "user-1"
}
```

Example response:

```json
{
  "question": "What is RAG?",
  "answer": "RAG stands for Retrieval-Augmented Generation...",
  "scores": [9.0, 8.0, 7.5, 8.5],
  "cache_hit": false,
  "cache_similarity": 0.0,
  "thread_id": "user-1",
  "request_id": "generated-request-id"
}
```

## Other Endpoints

```text
GET /              # API status
GET /health        # Health check
GET /history       # API-level in-memory request history
DELETE /history    # Clear API-level request history
```

## Docker Run

```bash
docker build -t ai-decision-engine .
docker run -p 8000:8000 --env-file .env ai-decision-engine
```

Then open:

```text
http://localhost:8000/docs
```

## Deployment Notes

Use this start command on most platforms:

```bash
uvicorn main:api --host 0.0.0.0 --port 8000
```

For platforms like Render/Railway, add environment variables from `.env.example` in the dashboard.

## Important Note About Memory

`MemorySaver` stores LangGraph checkpoints for a given `thread_id`, but this project does not use `add_messages`, so it does not automatically append full conversational chat history. The semantic cache is responsible for reusing similar previous answers.
