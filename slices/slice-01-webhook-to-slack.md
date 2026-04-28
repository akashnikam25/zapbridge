# Slice 1: Webhook → Slack (No security yet)

**Estimated time:** ~2 hours  
**Depends on:** Slice 0  
**Files created:** `app/config.py`, `app/connections.py`, `app/slack.py`, `app/main.py`

---

## Goal

Receive any GitHub POST, parse the event type, post a message to Slack.  
No signature validation, no queue, no database. Proves the integration works.

---

## Step 1 — `app/config.py` (write first — everything else imports it)

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    SLACK_WEBHOOK_URL: str
    DATABASE_URL: str = "postgresql://localhost/zapbridge"
    REDIS_URL: str = "redis://localhost:6379"
    GITHUB_CLIENT_ID: str
    GITHUB_CLIENT_SECRET: str
    FERNET_KEY: str
    ANTHROPIC_API_KEY: str
    GITHUB_WEBHOOK_SECRET: str

    model_config = {"env_file": ".env"}

settings = Settings()
```

**Interview story:** "pydantic-settings reads from `.env` and validates at startup. If `FERNET_KEY` is missing you get a clear error before the server starts — not a cryptic AttributeError when the first request hits."

---

## Step 2 — `app/connections.py` (write second — all slices import from here)

```python
# app/connections.py — single source of truth for Redis, RQ, and DB connections
from redis import Redis
from rq import Queue
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.config import settings

redis_conn = Redis.from_url(settings.REDIS_URL)
queue = Queue("zapbridge", connection=redis_conn)

engine = create_engine(settings.DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

---

## Step 3 — `app/slack.py`

```python
import httpx
from app.config import settings

# Sync function — works in both the FastAPI endpoint (Slice 1) and the RQ worker (Slice 4+).
# Blocks the event loop for ~100ms in Slice 1, invisible at demo scale.
def post_to_slack(message: str) -> None:
    with httpx.Client(timeout=10.0) as client:
        resp = client.post(settings.SLACK_WEBHOOK_URL, json={"text": message})
    if resp.status_code != 200:
        raise RuntimeError(f"Slack rejected message: {resp.status_code} {resp.text}")
```

---

## Step 4 — `app/main.py`

```python
from fastapi import FastAPI, Request
from app.slack import post_to_slack

app = FastAPI()

@app.post("/webhook")
async def receive_webhook(request: Request):
    payload = await request.json()
    event_type = request.headers.get("X-GitHub-Event", "unknown")
    message = f"GitHub event: {event_type} — {payload.get('action', '')}"
    post_to_slack(message)
    return {"status": "ok"}
```

---

## Run it

```bash
uvicorn app.main:app --reload
```

---

## Done when

Open a PR on the GitHub repo (or trigger any event) → a Slack message appears.

---

## Interview story

"I started with the simplest possible pipeline — receive a POST, parse the event type, post to Slack. No security, no queue. Proves the integration works end-to-end before adding complexity. Every subsequent slice adds one production pattern to this working baseline."
