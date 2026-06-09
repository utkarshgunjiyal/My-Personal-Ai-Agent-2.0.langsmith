"""MongoDB connection module."""
import os
from motor.motor_asyncio import AsyncIOMotorClient

_client: AsyncIOMotorClient | None = None
_db = None


def get_db():
    """Return the database handle. Lazy connect on first call."""
    global _client, _db
    if _client is None:
        mongo_url = os.environ["MONGO_URL"]
        db_name = os.environ["DB_NAME"]
        _client = AsyncIOMotorClient(mongo_url)
        _db = _client[db_name]
    return _db


async def init_indexes():
    """Create indexes used by the app."""
    db = get_db()
    await db.users.create_index("email", unique=True)
    await db.users.create_index("user_id", unique=True)
    await db.user_sessions.create_index("session_token", unique=True)
    await db.user_sessions.create_index("expires_at", expireAfterSeconds=0)
    await db.password_reset_tokens.create_index("expires_at", expireAfterSeconds=0)
    await db.login_attempts.create_index("identifier")
    await db.threads.create_index([("user_id", 1), ("updated_at", -1)])
    await db.messages.create_index([("thread_id", 1), ("created_at", 1)])
    await db.semantic_cache.create_index("user_id")
    await db.agent_runs.create_index([("user_id", 1), ("created_at", -1)])
    await db.uploaded_files.create_index([("thread_id", 1), ("created_at", 1)])
    await db.uploaded_files.create_index("file_id", unique=True)
    await db.thread_documents.create_index([("thread_id", 1), ("user_id", 1)])
    await db.thread_documents.create_index("file_id")
    await db.thread_documents.create_index("doc_id", unique=True)
    await db.summaries.create_index("thread_id", unique=True)
