# OAuth state machine:
#   GET /auth/login
#     └─ uuid state → SET oauth_state:{uuid} 1 EX 600 → redirect to GitHub
#
#   GET /auth/callback?code=...&state={uuid}
#     ├─ GETDEL oauth_state:{uuid}
#     │     └─ nil → 400 CSRF rejected
#     ├─ POST github.com/login/oauth/access_token → access_token
#     ├─ encrypt(access_token) via Fernet
#     └─ UPSERT users → {"status": "connected"}
#
#   DELETE /auth/disconnect
#     ├─ decrypt(access_token_enc)
#     ├─ DELETE github.com/applications/{id}/token  (revoke)
#     └─ DELETE users row

import uuid
import httpx
from fastapi import HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.dialects.postgresql import insert
from app.config import settings
from app.connections import redis_conn, SessionLocal
from app.models import User
from app.auth.tokens import encrypt, decrypt

CSRF_STATE_TTL = 600  # 10 minutes


def store_oauth_state(state: str) -> None:
    redis_conn.set(f"oauth_state:{state}", 1, ex=CSRF_STATE_TTL)


def consume_oauth_state(state: str) -> bool:
    # GETDEL: atomic get-and-delete — verifies AND invalidates in one operation.
    # Prevents replay attacks: a valid state can only be consumed once.
    return redis_conn.getdel(f"oauth_state:{state}") is not None


def login_redirect() -> RedirectResponse:
    state = str(uuid.uuid4())
    store_oauth_state(state)
    url = (
        f"https://github.com/login/oauth/authorize"
        f"?client_id={settings.GITHUB_CLIENT_ID}"
        f"&scope=repo,read:user"
        f"&state={state}"
    )
    return RedirectResponse(url)


def handle_callback(code: str, state: str) -> dict:
    if not consume_oauth_state(state):
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")

    resp = httpx.post(
        "https://github.com/login/oauth/access_token",
        data={
            "client_id": settings.GITHUB_CLIENT_ID,
            "client_secret": settings.GITHUB_CLIENT_SECRET,
            "code": code,
        },
        headers={"Accept": "application/json"},
        timeout=15.0,
    )
    resp.raise_for_status()
    token_data = resp.json()
    access_token = token_data["access_token"]

    # Get GitHub user info
    user_resp = httpx.get(
        "https://api.github.com/user",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=10.0,
    )
    user_resp.raise_for_status()
    github_user = user_resp.json()

    db = SessionLocal()
    try:
        stmt = insert(User).values(
            github_id=github_user["id"],
            github_login=github_user["login"],
            access_token_enc=encrypt(access_token),
        ).on_conflict_do_update(
            index_elements=["github_id"],
            set_={
                "access_token_enc": encrypt(access_token),
                "github_login": github_user["login"],
                # Clear provider-specific fields on reconnect so stale values don't linger.
                # GitHub never sets these, but a future provider swap would leave garbage here.
                "refresh_token_enc": None,
                "token_expires_at": None,
            },
        )
        db.execute(stmt)
        db.commit()
    finally:
        db.close()

    return {"status": "connected", "login": github_user["login"]}


def disconnect(github_login: str) -> dict:
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(github_login=github_login).first()
        if not user:
            raise HTTPException(404, "User not found")

        access_token = decrypt(user.access_token_enc)

        # Revoke the token at GitHub
        httpx.delete(
            f"https://api.github.com/applications/{settings.GITHUB_CLIENT_ID}/token",
            auth=(settings.GITHUB_CLIENT_ID, settings.GITHUB_CLIENT_SECRET),
            json={"access_token": access_token},
            timeout=10.0,
        )

        db.delete(user)
        db.commit()
    finally:
        db.close()

    return {"status": "disconnected"}


def get_or_refresh_token(user: User, db) -> str:
    # NOTE: GitHub tokens never expire — the refresh branch only applies to providers
    # that issue short-lived tokens (Google: 1h, Salesforce: 2h, Slack: varies).
    if user.token_expires_at is None:
        return decrypt(user.access_token_enc)

    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    # token_expires_at must be stored as timezone-aware; make it aware if it isn't (migration safety)
    expires_at = user.token_expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at - now > timedelta(minutes=5):
        return decrypt(user.access_token_enc)

    # Token within 5 minutes of expiry — refresh it
    refresh_token = decrypt(user.refresh_token_enc)
    resp = httpx.post(
        "https://github.com/login/oauth/access_token",
        data={
            "client_id": settings.GITHUB_CLIENT_ID,
            "client_secret": settings.GITHUB_CLIENT_SECRET,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
        headers={"Accept": "application/json"},
        timeout=15.0,
    )
    resp.raise_for_status()
    new_data = resp.json()

    user.access_token_enc = encrypt(new_data["access_token"])
    if "refresh_token" in new_data:
        user.refresh_token_enc = encrypt(new_data["refresh_token"])
    db.commit()

    return new_data["access_token"]
