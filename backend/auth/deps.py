"""Auth dependency – resolves current user from a JWT access token."""
import jwt
from fastapi import HTTPException, Request

from auth.security import decode_token
from db import get_db


async def get_current_user(request: Request) -> dict:
    """Resolve current user from the JWT access token (cookie or Authorization header)."""
    db = get_db()

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
