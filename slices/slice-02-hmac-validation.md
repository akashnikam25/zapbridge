# Slice 2: HMAC-SHA256 Signature Validation

**Estimated time:** ~1 hour  
**Depends on:** Slice 1  
**Files created:** `app/webhooks/validator.py`  
**Files modified:** `app/main.py`

---

## Goal

Reject any POST that doesn't carry a valid GitHub signature.  
This prevents an attacker from spoofing webhook events to your endpoint.

---

## `app/webhooks/validator.py`

```python
import hmac
import hashlib

def validate_signature(payload: bytes, signature_header: str, secret: str) -> bool:
    if not signature_header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(
        secret.encode(), payload, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header)  # Timing-safe
```

---

## Update `app/main.py`

```python
from fastapi import FastAPI, Request, HTTPException
from app.config import settings
from app.slack import post_to_slack
from app.webhooks.validator import validate_signature

app = FastAPI()

@app.post("/webhook")
async def receive_webhook(request: Request):
    body = await request.body()
    sig = request.headers.get("X-Hub-Signature-256", "")

    if not validate_signature(body, sig, settings.GITHUB_WEBHOOK_SECRET):
        raise HTTPException(status_code=401, detail="Invalid signature")

    payload = await request.json()  # safe to parse after validation
    event_type = request.headers.get("X-GitHub-Event", "unknown")
    message = f"GitHub event: {event_type} — {payload.get('action', '')}"
    post_to_slack(message)
    return {"status": "ok"}
```

> Note: call `request.body()` before `request.json()` — once you consume the body as JSON you can't re-read it as bytes.

---

## Why `compare_digest`

A naive `==` short-circuits on the first mismatching byte. An attacker can measure how long your server takes to reject different payloads and reconstruct the valid signature bit by bit (timing attack). `hmac.compare_digest` always takes the same time regardless of where the mismatch is.

---

## Done when

1. Remove the webhook secret from your `.env` (or send a POST with the wrong secret) → 401.
2. Restore the correct secret → accepted.

---

## Interview story

"GitHub signs every webhook with HMAC-SHA256 using the secret you register. I compute the expected signature server-side and compare with `hmac.compare_digest` — not `==`. The difference is timing-safety: `==` short-circuits, leaking information byte by byte. `compare_digest` runs in constant time."
