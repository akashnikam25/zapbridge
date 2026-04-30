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
        all_issues.extend([i for i in data if "pull_request" not in i])
        if len(data) < 30:
            break  # Last page — fewer results than page size
        page += 1

    return all_issues
