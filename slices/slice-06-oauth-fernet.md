# Slice 6: GitHub OAuth + Fernet Token Encryption

**Estimated time:** ~3 hours  
**Depends on:** Slice 1 (config + connections)  
**Files created:** `app/auth/tokens.py`, `app/auth/oauth.py`, `app/models.py`  
**Files modified:** `app/main.py`, `app/connections.py`

---

## Goal

Full GitHub OAuth flow: login → exchange code → encrypt tokens → store in DB → disconnect (revoke + delete).  
Tokens are encrypted at rest with Fernet. CSRF state lives in Redis, not in-memory.

---

## `app/models.py`

```python
from datetime import datetime
from sqlalchemy import String, Text, DateTime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    github_id: Mapped[int] = mapped_column(unique=True)
    github_login: Mapped[str] = mapped_column(String(255))
    access_token_enc: Mapped[str] = mapped_column(Text)           # Fernet-encrypted
    refresh_token_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
```

Create the table (one-time):
```bash
python -c "from app.connections import engine; from app.models import Base; Base.metadata.create_all(engine)"
```

---

## `app/auth/tokens.py`

```python
from cryptography.fernet import Fernet
from app.config import settings

_fernet = Fernet(settings.FERNET_KEY.encode())

def encrypt(token: str) -> str:
    return _fernet.encrypt(token.encode()).decode()

def decrypt(encrypted: str) -> str:
    return _fernet.decrypt(encrypted.encode()).decode()
```

---

## `app/auth/oauth.py`

```python
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
            set_={"access_token_enc": encrypt(access_token), "github_login": github_user["login"]},
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

    from datetime import datetime, timedelta
    if user.token_expires_at - datetime.utcnow() > timedelta(minutes=5):
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
```

---

## Add routes to `app/main.py`

```python
from app.auth.oauth import login_redirect, handle_callback, disconnect

@app.get("/auth/login")
def auth_login():
    return login_redirect()

@app.get("/auth/callback")
def auth_callback(code: str, state: str):
    return handle_callback(code, state)

@app.delete("/auth/disconnect")
def auth_disconnect(github_login: str):
    return disconnect(github_login)
```

---

## Why Fernet

Fernet is AES-128-CBC with HMAC-SHA256. The key lives only in an env var — not in the DB, not in code. If someone dumps the database, they get ciphertext. If they also get the key (env var breach), rotate the key and re-encrypt.

## Why Redis CSRF state (not in-memory)

An in-memory dict fails with multiple workers (each has its own dict) and on any process restart. Redis is already in the stack — one `SET` on login, one atomic `GETDEL` on callback. GETDEL verifies AND invalidates in one operation, preventing replay attacks.

## Why implement token refresh if GitHub tokens don't expire

GitHub OAuth tokens don't expire. The refresh function is implemented as a demonstration of the pattern that applies to every real-world OAuth provider: Google (1h expiry), Salesforce (2h), Slack (varies). If asked in the interview, lead with: "GitHub tokens don't expire — I know this. I implemented the refresh pattern anyway because..."

---

## Done when

1. `GET /auth/login` → redirects to GitHub → authorize → callback stores encrypted token in DB.
2. `DELETE /auth/disconnect?github_login=<your-login>` → token revoked at GitHub, row deleted from DB.
