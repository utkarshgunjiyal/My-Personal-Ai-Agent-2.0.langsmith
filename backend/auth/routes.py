"""Auth routes - JWT email/password authentication."""
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field

from auth.deps import get_current_user
from auth.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from db import get_db

router = APIRouter(prefix="/api/auth", tags=["auth"])

MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 15


# --------- Schemas ---------
class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6, max_length=128)
    name: str = Field(min_length=1, max_length=80)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class ForgotPasswordIn(BaseModel):
    email: EmailStr


class ResetPasswordIn(BaseModel):
    token: str
    new_password: str = Field(min_length=6, max_length=128)


# --------- Cookie helpers ---------
def _set_jwt_cookies(response: Response, access: str, refresh: str):
    response.set_cookie(
        key="access_token",
        value=access,
        httponly=True,
        secure=True,
        samesite="none",
        max_age=60 * 60 * 24,
        path="/",
    )
    response.set_cookie(
        key="refresh_token",
        value=refresh,
        httponly=True,
        secure=True,
        samesite="none",
        max_age=60 * 60 * 24 * 7,
        path="/",
    )


def _clear_cookies(response: Response):
    for name in ("access_token", "refresh_token"):
        response.delete_cookie(name, path="/")


def _sanitize_user(user: dict) -> dict:
    user.pop("password_hash", None)
    user.pop("_id", None)
    return user


# --------- Brute force helpers ---------
async def _check_lockout(db, identifier: str):
    rec = await db.login_attempts.find_one({"identifier": identifier})
    if not rec:
        return
    if rec.get("locked_until"):
        locked_until = rec["locked_until"]
        if locked_until.tzinfo is None:
            locked_until = locked_until.replace(tzinfo=timezone.utc)
        if locked_until > datetime.now(timezone.utc):
            raise HTTPException(
                status_code=429,
                detail="Too many failed attempts. Try again in a few minutes.",
            )


async def _register_failed_attempt(db, identifier: str):
    rec = await db.login_attempts.find_one({"identifier": identifier})
    failed = (rec.get("failed", 0) if rec else 0) + 1
    update = {"failed": failed, "updated_at": datetime.now(timezone.utc)}
    if failed >= MAX_FAILED_ATTEMPTS:
        update["locked_until"] = datetime.now(timezone.utc) + timedelta(
            minutes=LOCKOUT_MINUTES
        )
        update["failed"] = 0
    await db.login_attempts.update_one(
        {"identifier": identifier}, {"$set": update}, upsert=True
    )


async def _clear_failed_attempts(db, identifier: str):
    await db.login_attempts.delete_one({"identifier": identifier})


# --------- Routes ---------
@router.post("/register")
async def register(body: RegisterIn, request: Request, response: Response):
    db = get_db()
    email = body.email.lower().strip()
    existing = await db.users.find_one({"email": email})
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    user_id = f"user_{uuid.uuid4().hex[:12]}"
    doc = {
        "user_id": user_id,
        "email": email,
        "name": body.name.strip(),
        "password_hash": hash_password(body.password),
        "role": "user",
        "auth_provider": "password",
        "picture": None,
        "created_at": datetime.now(timezone.utc),
    }
    await db.users.insert_one(doc)
    access = create_access_token(user_id, email)
    refresh = create_refresh_token(user_id)
    _set_jwt_cookies(response, access, refresh)
    user = await db.users.find_one(
        {"user_id": user_id}, {"_id": 0, "password_hash": 0}
    )
    return user


@router.post("/login")
async def login(body: LoginIn, request: Request, response: Response):
    db = get_db()
    email = body.email.lower().strip()
    ip = request.client.host if request.client else "unknown"
    identifier = f"{ip}:{email}"
    await _check_lockout(db, identifier)

    user = await db.users.find_one({"email": email})
    if not user or not user.get("password_hash"):
        await _register_failed_attempt(db, identifier)
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not verify_password(body.password, user["password_hash"]):
        await _register_failed_attempt(db, identifier)
        raise HTTPException(status_code=401, detail="Invalid email or password")

    await _clear_failed_attempts(db, identifier)
    access = create_access_token(user["user_id"], email)
    refresh = create_refresh_token(user["user_id"])
    _set_jwt_cookies(response, access, refresh)
    return _sanitize_user(user)


@router.post("/logout")
async def logout(response: Response):
    _clear_cookies(response)
    return {"ok": True}


@router.get("/me")
async def me(user=Depends(get_current_user)):
    return user


@router.post("/refresh")
async def refresh_token(request: Request, response: Response):
    token = request.cookies.get("refresh_token")
    if not token:
        raise HTTPException(status_code=401, detail="No refresh token")
    try:
        payload = decode_token(token)
        if payload.get("type") != "refresh":
            raise HTTPException(status_code=401, detail="Invalid token type")
        db = get_db()
        user = await db.users.find_one({"user_id": payload["sub"]})
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        access = create_access_token(user["user_id"], user["email"])
        new_refresh = create_refresh_token(user["user_id"])
        _set_jwt_cookies(response, access, new_refresh)
        return {"ok": True}
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid refresh token")


@router.post("/forgot-password")
async def forgot_password(body: ForgotPasswordIn):
    db = get_db()
    user = await db.users.find_one({"email": body.email.lower().strip()})
    # Always 200 to avoid user enumeration
    if user:
        token = secrets.token_urlsafe(32)
        await db.password_reset_tokens.insert_one(
            {
                "token": token,
                "user_id": user["user_id"],
                "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
                "used": False,
            }
        )
        # In a real product you'd email this. For demo: print to logs.
        print(f"[PASSWORD RESET] link: /reset-password?token={token}")
    return {"ok": True}


@router.post("/reset-password")
async def reset_password(body: ResetPasswordIn):
    db = get_db()
    rec = await db.password_reset_tokens.find_one({"token": body.token, "used": False})
    if not rec:
        raise HTTPException(status_code=400, detail="Invalid or expired token")
    expires_at = rec["expires_at"]
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Token expired")
    await db.users.update_one(
        {"user_id": rec["user_id"]},
        {"$set": {"password_hash": hash_password(body.new_password)}},
    )
    await db.password_reset_tokens.update_one(
        {"token": body.token}, {"$set": {"used": True}}
    )
    return {"ok": True}


# --------- Admin seed ---------
async def seed_admin():
    """Seed an admin user from ADMIN_EMAIL/ADMIN_PASSWORD. No-op if either is unset,
    so a missing .env entry can't silently create a known-password admin account."""
    admin_email = os.environ.get("ADMIN_EMAIL")
    admin_password = os.environ.get("ADMIN_PASSWORD")
    if not admin_email or not admin_password:
        return
    admin_email = admin_email.lower()

    db = get_db()
    existing = await db.users.find_one({"email": admin_email})
    if existing is None:
        user_id = f"user_{uuid.uuid4().hex[:12]}"
        await db.users.insert_one(
            {
                "user_id": user_id,
                "email": admin_email,
                "name": "Admin",
                "password_hash": hash_password(admin_password),
                "role": "admin",
                "auth_provider": "password",
                "picture": None,
                "created_at": datetime.now(timezone.utc),
            }
        )
    elif existing.get("password_hash") and not verify_password(
        admin_password, existing["password_hash"]
    ):
        await db.users.update_one(
            {"email": admin_email},
            {"$set": {"password_hash": hash_password(admin_password)}},
        )
