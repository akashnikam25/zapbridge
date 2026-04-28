# Slice 7: GitHub Issues API (Pagination + Backoff)

**Estimated time:** ~2 hours  
**Depends on:** Slice 6 (needs auth token)  
**Files created:** `app/github.py`  
**Files modified:** `app/main.py`

---

## Goal

Fetch all open issues for a repo, handling pagination and GitHub rate limits gracefully.  
This is the "most complex REST API integration" interview story.

---

## `app/github.py`

```python
import time
import random
import httpx
from fastapi import HTTPException


def fetch_with_retry(url: str, headers: dict, max_retries: int = 5) -> list:
    for attempt in range(max_retries):
        resp = httpx.get(url, headers=headers, timeout=30.0)

        if resp.status_code == 200:
            return resp.json()

        if resp.status_code in (429, 403):
            reset = resp.headers.get("X-RateLimit-Reset")
            if reset:
                wait = max(int(reset) - int(time.time()) + 1, 0)
            else:
                wait = (2 ** attempt) + random.uniform(0, 1)  # jitter
            time.sleep(min(wait, 60))
            continue

        if resp.status_code == 401:
            raise HTTPException(401, "Token invalid or revoked")

        raise HTTPException(resp.status_code, f"GitHub API error: {resp.text[:200]}")

    raise HTTPException(429, "Rate limit exhausted after max retries")


def fetch_all_issues(token: str, repo: str) -> list[dict]:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }
    all_issues, page = [], 1

    while True:
        data = fetch_with_retry(
            f"https://api.github.com/repos/{repo}/issues?state=open&per_page=30&page={page}",
            headers,
        )
        all_issues.extend(data)
        if len(data) < 30:
            break  # Last page — fewer results than page size
        page += 1

    return all_issues
```

---

## Add route to `app/main.py`

```python
from app.github import fetch_all_issues
from app.connections import SessionLocal
from app.models import User
from app.auth.oauth import get_or_refresh_token

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
```

---

## Why jitter on backoff

Exponential backoff without jitter causes a thundering herd: all retrying clients fire at the same moment, hammering the API simultaneously. `random.uniform(0, 1)` spreads them out.

`X-RateLimit-Reset` is better than exponential backoff when available — GitHub tells you exactly when the window resets, so you wait the minimum necessary time instead of guessing.

---

## Production note: blocking sleep in workers

`time.sleep(wait)` blocks the RQ worker process for up to 60 seconds during a rate-limit wait. One worker = one job at a time while sleeping.

**For the demo:** run 2 workers so webhook jobs aren't delayed by a rate-limited issues fetch:
```bash
rq worker zapbridge -w 2
```

**In production:** use separate queues:
```python
webhook_queue = Queue("zapbridge")       # high-priority, fast jobs
issues_queue  = Queue("issues-fetch")   # can wait; separate worker pool
```

---

## Done when

1. `GET /issues?repo=owner/repo&github_login=<your-login>` → returns paginated list of open issues.
2. Trigger rate limiting (or mock it) → server backs off gracefully instead of 429-flooding GitHub.

---

## Interview story

"Pagination: I loop until GitHub returns fewer results than `per_page` — that signals the last page. Rate limiting: I read `X-RateLimit-Reset` from the response header, which tells me exactly when the window resets — this is more precise than pure exponential backoff. When the header isn't present I fall back to exponential backoff with jitter. Jitter prevents thundering herd: without it, all retrying clients fire at the same instant and amplify the rate limit problem."
