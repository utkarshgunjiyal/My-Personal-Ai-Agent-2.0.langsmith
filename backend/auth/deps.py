"""Auth dependency – resolves current user from JWT or Emergent session cookie."""
from datetime import datetime, timezone

import jwt
from fastapi import HTTPException, Request

from auth.security import decode_token
from db import get_db


async def get_current_user(request: Request) -> dict:
    """Resolve current user. Supports both JWT (email/password) and Emergent Google session."""
    db = get_db()

    # 1. Try Emergent session_token (cookie or Authorization header)
    session_token = request.cookies.get("session_token")
    if not session_token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer ") and len(auth_header) > 50:
            # Long-ish tokens that aren't JWT structure go through session lookup
            candidate = auth_header[7:]
            if candidate.count(".") != 2:
                session_token = candidate

    if session_token:
        session = await db.user_sessions.find_one(
            {"session_token": session_token}, {"_id": 0}
        )
        if session:
            expires_at = session.get("expires_at")
            if isinstance(expires_at, str):
                expires_at = datetime.fromisoformat(expires_at)
            if expires_at and expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if not expires_at or expires_at >= datetime.now(timezone.utc):
                user = await db.users.find_one(
                    {"user_id": session["user_id"]}, {"_id": 0, "password_hash": 0}
                )
                if user:
                    return user

    # 2. Try JWT access_token
    token = request.cookies.get("access_token")
    if not token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            raise HTTPException(status_code=401, detail="Invalid token type")
        user = await db.users.find_one(
            {"user_id": payload["sub"]}, {"_id": 0, "password_hash": 0}
        )
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        return user
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


async def get_current_user_or_none(request: Request):
    try:
        return await get_current_user(request)
    except HTTPException:
        return None
