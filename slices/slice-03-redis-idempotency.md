# Slice 3: Redis Idempotency (SETNX)

**Estimated time:** ~1 hour  
**Depends on:** Slice 2  
**Files created:** `app/webhooks/receiver.py`  
**Files modified:** `app/main.py`

---

## Goal

Detect and reject duplicate webhook deliveries.  
GitHub retries any webhook that doesn't respond within 10 seconds or gets a non-2xx response. Without idempotency, a temporary outage causes every event to be processed twice.

---

## `app/webhooks/receiver.py`

```python
from app.connections import redis_conn

IDEMPOTENCY_TTL = 86400  # 24 hours

def is_duplicate(delivery_id: str) -> bool:
    key = f"webhook:{delivery_id}"
    # SET NX EX is fully atomic: set-if-not-exists + expiry in one round-trip.
    # SETNX + EXPIRE is NOT atomic — if the process dies between them, the key
    # has no TTL and that delivery ID is locked out forever (memory leak + permanent block).
    already_seen = not redis_conn.set(key, 1, nx=True, ex=IDEMPOTENCY_TTL)
    return already_seen
```

---

## Update `app/main.py`

```python
from fastapi import FastAPI, Request, HTTPException
from app.config import settings
from app.slack import post_to_slack
from app.webhooks.validator import validate_signature
from app.webhooks.receiver import is_duplicate

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

    import json
    payload = json.loads(body)
    event_type = request.headers.get("X-GitHub-Event", "unknown")
    message = f"GitHub event: {event_type} — {payload.get('action', '')}"
    post_to_slack(message)
    return {"status": "ok"}
```

---

## Why atomic SET NX EX (not SETNX + EXPIRE)

`SETNX` sets the key. `EXPIRE` sets the TTL. If your process dies between those two commands, the key exists forever with no TTL — that delivery ID is permanently blocked and the memory leaks.

`SET key 1 NX EX 86400` does both in a single round-trip. Atomic by definition.

---

## Done when

In the GitHub webhook settings, find a recent delivery and click "Redeliver".  
The second delivery should return `{"status": "already_processed"}`.

---

## Interview story

"GitHub retries webhooks if your server doesn't respond within 10 seconds or returns non-2xx — e.g., during a temporary outage. Without idempotency, every event gets processed twice. I use `SET key 1 NX EX 86400` — one atomic Redis command. NX means 'only set if not exists', EX sets the TTL in the same operation. The older pattern (`SETNX` + `EXPIRE`) isn't crash-safe: if your process dies between those two commands, the key has no TTL and that delivery ID is blocked forever. The atomic form eliminates that entire failure mode."
