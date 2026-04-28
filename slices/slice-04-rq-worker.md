# Slice 4: RQ Worker + Async Processing

**Estimated time:** ~2 hours  
**Depends on:** Slices 2 + 3  
**Files created:** `app/workers/processor.py`  
**Files modified:** `app/main.py`

---

## Goal

Return HTTP 200 immediately after validation + idempotency check, then process the event asynchronously in a worker. This is the core architectural pattern for Zapier's business.

---

## `app/workers/processor.py`

```python
from app.slack import post_to_slack

def format_message(event_type: str, payload: dict) -> str:
    repo = payload.get("repository", {}).get("full_name", "")
    action = payload.get("action", "")
    return f"*[{repo}]* GitHub `{event_type}` event — action: `{action}`"

def process_github_event(event_type: str, payload: dict) -> None:
    # RQ workers are synchronous — post_to_slack is sync, which is correct here.
    message = format_message(event_type, payload)  # replaced by Claude in Slice 5
    post_to_slack(message)
```

---

## Inline flow comment for `app/webhooks/receiver.py`

Paste this block comment at the top of the function body in the final file:

```python
# Pipeline:
#   POST /webhook
#     │
#     ├─ validate_signature()  → 401 if invalid
#     ├─ is_duplicate()        → {"status":"already_processed"} if seen
#     └─ queue.enqueue()       → {"status":"queued"} ← HTTP 200 returned here
#                                 ↓ async boundary
#                              RQ worker: _summarize_event() → post_to_slack()
```

---

## Update `app/main.py`

```python
import json
from fastapi import FastAPI, Request, HTTPException
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
```

---

## Run the worker

In a separate terminal:

```bash
rq worker zapbridge
```

---

## retry=Retry explained

`Retry(max=3, interval=[10, 30, 60])` means:
- First retry: 10 seconds after failure
- Second retry: 30 seconds after failure
- Third retry: 60 seconds after failure
- After 3 failures: job moves to the `failed` queue (dead letter)

`failure_ttl=86400` keeps failed jobs for 24 hours so you can inspect them, then Redis auto-cleans.

---

## Done when

1. Kill the worker (`Ctrl+C`).
2. Trigger a GitHub event → `{"status": "queued", "job_id": "..."}` — request still returns 200.
3. Start the worker again → Slack message arrives as the queue drains.

---

## Interview story

"The webhook receiver must return 200 within 10 seconds or GitHub considers it failed and retries. If Claude takes 3 seconds, or Slack is slow, you'd fail that deadline from the endpoint. So the receiver does ONE thing: validate the signature, check idempotency, enqueue. The worker does the heavy lifting. Classic producer-consumer. The Retry config gives us 3 attempts with exponential backoff before a job lands in the dead letter queue."
