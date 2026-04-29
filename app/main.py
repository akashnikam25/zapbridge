from fastapi import FastAPI, Request
from app.slack import post_to_slack

app = FastAPI()


def _extract_url(event_type: str, payload: dict) -> str | None:
    """Pick the most relevant html_url for the event so Slack can link to it."""
    if event_type == "pull_request":
        return payload.get("pull_request", {}).get("html_url")
    if event_type == "issues":
        return payload.get("issue", {}).get("html_url")
    if event_type == "issue_comment":
        return payload.get("comment", {}).get("html_url")
    if event_type == "push":
        return payload.get("compare")
    if event_type == "release":
        return payload.get("release", {}).get("html_url")
    # Fallback: repo URL is present on almost every event
    return payload.get("repository", {}).get("html_url")


@app.post("/webhook")
async def receive_webhook(request: Request):
    payload = await request.json()
    event_type = request.headers.get("X-GitHub-Event", "unknown")
    action = payload.get("action", "")
    url = _extract_url(event_type, payload)

    label = f"GitHub event: {event_type} — {action}".rstrip(" —")
    # Slack mrkdwn link syntax: <url|label>
    message = f"<{url}|{label}>" if url else label

    post_to_slack(message)
    return {"status": "ok"}
