"""FastAPI entrypoint for the AI Decision Engine."""
from dotenv import load_dotenv

load_dotenv()

import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from auth.routes import router as auth_router, seed_admin
from chat.routes import router as chat_router
from chat.stream import router as chat_stream_router
from db import get_db, init_indexes
from stats.routes import router as stats_router
from uploads.routes import router as uploads_router

# ----- Logging -----
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s :: %(message)s",
)
log = logging.getLogger("decision-engine")

app = FastAPI(
    title="AI Decision Engine API",
    description=(
        "Multi-agent RAG decision engine. LangGraph workflow, hybrid retrieval, "
        "LLM-as-judge evaluation, answer refinement, "
        "MongoDB persistence, JWT authentication."
    ),
    version="2.0.0",
)

# ----- CORS -----
# FRONTEND_URL must be set to the deployed frontend origin in production.
frontend_url = os.environ.get("FRONTEND_URL", "http://localhost:3000")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[frontend_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ----- Routers -----
app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(chat_stream_router)
app.include_router(stats_router)
app.include_router(uploads_router)


# ----- Lifecycle -----
@app.on_event("startup")
async def on_startup():
    # Touch DB so motor verifies it's reachable
    db = get_db()
    await db.command("ping")
    await init_indexes()
    await seed_admin()
    log.info("AI Decision Engine ready (DB=%s).", os.environ["DB_NAME"])


# ----- Public ----- (kept under /api so it's reachable via ingress)
@app.get("/api/")
def root():
    return {
        "service": "AI Decision Engine",
        "status": "ok",
        "version": "2.0.0",
        "docs": "/docs",
    }


@app.get("/api/health")
async def health():
    db = get_db()
    try:
        await db.command("ping")
        return {"status": "healthy"}
    except Exception as e:
        return {"status": "degraded", "error": str(e)}
