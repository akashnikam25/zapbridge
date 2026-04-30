import json
import structlog
from fastapi import Depends, FastAPI, HTTPException, Request
from rq import Retry
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.config import settings
from app.connections import queue, SessionLocal, redis_conn, get_db
from app.webhooks.validator import validate_signature
from app.webhooks.receiver import is_duplicate
from app.workers.processor import process_github_event
from app.auth.oauth import login_redirect, handle_callback, disconnect, get_or_refresh_token
from app.github import fetch_all_issues
from app.models import User

structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ]
)

logger = structlog.get_logger()

app = FastAPI()


@app.get("/auth/login")
def auth_login():
    return login_redirect()


@app.get("/auth/callback")
def auth_callback(code: str, state: str):
    return handle_callback(code, state)


@app.delete("/auth/disconnect")
def auth_disconnect(github_login: str):
    return disconnect(github_login)


@app.post("/webhook")
async def receive_webhook(request: Request):
    body = await request.body()
    sig = request.headers.get("X-Hub-Signature-256", "")

    if not validate_signature(body, sig, settings.GITHUB_WEBHOOK_SECRET):
        raise HTTPException(status_code=401, detail="Invalid signature")

    delivery_id = request.headers.get("X-GitHub-Delivery", "")
    if is_duplicate(delivery_id):
        return {"status": "already_processed"}

    payload = json.loads(body)
    event_type = request.headers.get("X-GitHub-Event", "unknown")

    logger.info("webhook_received", event_type=event_type, delivery_id=delivery_id)

    job = queue.enqueue(
        process_github_event,
        event_type,
        payload,
        job_timeout=120,
        retry=Retry(max=3, interval=[10, 30, 60]),  # backoff: 10s, 30s, 60s
        failure_ttl=86400,  # keep failed jobs 24h for inspection, then auto-clean
    )
    logger.info("job_queued", job_id=job.id)
    return {"status": "queued", "job_id": job.id}


@app.get("/issues")
def list_issues(repo: str, github_login: str):
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(github_login=github_login).first()
        if not user:
            raise HTTPException(404, "User not connected — visit /auth/login first")
        token = get_or_refresh_token(user, db)
    finally:
        db.close()

    issues = fetch_all_issues(token, repo)
    return {"repo": repo, "count": len(issues), "issues": issues}


@app.get("/health")
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    redis_conn.ping()
    return {"status": "ok", "db": "up", "redis": "up"}


@app.get("/admin/failed-jobs")
def list_failed_jobs():
    from rq import Queue
    failed = Queue("failed", connection=redis_conn)
    return [
        {
            "id": j.id,
            "exc": j.exc_info,
            "enqueued_at": str(j.enqueued_at),
        }
        for j in failed.get_jobs()
    ]
