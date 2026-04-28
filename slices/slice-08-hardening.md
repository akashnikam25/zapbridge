# Slice 8: Production Hardening

**Estimated time:** ~2 hours  
**Depends on:** All previous slices  
**Files modified:** `app/main.py`, `app/workers/processor.py`, `app/webhooks/receiver.py`

---

## Goal

Add health check, structured logging, and dead letter queue visibility.  
Each takes ~10 minutes and makes the system look and feel production-grade.

---

## 1. Health endpoint (~10 minutes)

Add to `app/main.py`:

```python
from sqlalchemy import text
from fastapi import Depends
from sqlalchemy.orm import Session
from app.connections import redis_conn, get_db

@app.get("/health")
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))   # verify DB reachable
    redis_conn.ping()              # verify Redis reachable
    return {"status": "ok", "db": "up", "redis": "up"}
```

**Why it checks DB and Redis (not just process health):** If Redis goes down, jobs stop queuing. If DB goes down, tokens can't be fetched. A health check that only checks "is the process alive?" would pass while both of those are broken. Load balancers and monitoring use this endpoint to know whether to send traffic.

---

## 2. Structured JSON logging (~10 minutes)

Add to any file that makes key decisions:

```python
import structlog
logger = structlog.get_logger()
```

Log the important events:

```python
# app/webhooks/receiver.py
logger.info("webhook_received", event_type=event_type, delivery_id=delivery_id)
logger.info("job_queued", job_id=job.id)

# app/workers/processor.py
logger.info("claude_summary_generated", length=len(summary))
logger.error("slack_failed", status_code=resp.status_code)
```

**Why structlog over `print()`:** Structured logs are machine-parseable. When you search logs in production (Datadog, CloudWatch, Splunk), you query fields — `event_type=pull_request AND delivery_id=abc` — not grep through strings. Every log line is a dict.

---

## 3. Dead letter queue endpoint (~10 minutes)

Add to `app/main.py`:

```python
@app.get("/admin/failed-jobs")
def list_failed_jobs():
    from rq import Queue
    from app.connections import redis_conn  # reuse shared connection
    failed = Queue("failed", connection=redis_conn)
    return [
        {
            "id": j.id,
            "exc": j.exc_info,
            "enqueued_at": str(j.enqueued_at),
        }
        for j in failed.get_jobs()
    ]
```

**Why:** After 3 retry attempts, RQ moves a job to the `failed` queue. Without this endpoint you'd have to `rq info` in the terminal to know what died. This gives you visibility in the browser — and a story about observability in the interview.

---

## structlog configuration (optional — makes logs prettier in dev)

Add to `app/main.py` before `app = FastAPI()`:

```python
import structlog
structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ]
)
```

---

## Done when

1. `GET /health` → `{"status": "ok", "db": "up", "redis": "up"}`
2. Kill Redis → `GET /health` raises 500 (not 200).
3. Trigger a job that fails 3 times → `GET /admin/failed-jobs` shows it.
4. Webhook events log structured JSON lines to the terminal.

---

## Interview story

"A health endpoint lets the load balancer know the instance is ready. I check DB and Redis — not just process health. If either is down, the system can't function, so they should both fail the health check. Structured logging means every event is a queryable JSON record — when you're debugging at 2am you want to grep by `delivery_id`, not scan raw strings. The failed-jobs endpoint gives me dead letter queue visibility without having to SSH anywhere."
