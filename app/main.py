import json
from fastapi import FastAPI, HTTPException, Request
from rq import Retry
from app.config import settings
from app.connections import queue
from app.webhooks.validator import validate_signature
from app.webhooks.receiver import is_duplicate
from app.workers.processor import process_github_event

app = FastAPI()


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

    job = queue.enqueue(
        process_github_event,
        event_type,
        payload,
        job_timeout=120,
        retry=Retry(max=3, interval=[10, 30, 60]),  # backoff: 10s, 30s, 60s
        failure_ttl=86400,  # keep failed jobs 24h for inspection, then auto-clean
    )
    return {"status": "queued", "job_id": job.id}
