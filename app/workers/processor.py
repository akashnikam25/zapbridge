import json
import anthropic
import structlog
from app.config import settings
from app.slack import post_to_slack

# Worker pipeline:
#   process_github_event(event_type, payload)
#     │
#     ├─ _summarize_event()
#     │     ├─ anthropic.messages.create()   timeout=30s
#     │     ├─ len(summary) < 10 → ValueError → retry → DLQ after 3 failures
#     │     └─ logger.info("claude_summary_generated")
#     └─ post_to_slack(message)
#           ├─ 200 → done
#           └─ non-200 → RuntimeError → retry → DLQ

logger = structlog.get_logger()
anthropic_client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)


def build_prompt(event_type: str, payload: dict) -> str:
    repo = payload.get("repository", {}).get("full_name", "unknown/repo")
    sender = payload.get("sender", {}).get("login", "unknown")
    # Truncate payload to avoid token waste — first 2000 chars covers all useful fields
    return f"""Summarize this GitHub {event_type} event for a Slack notification.
Be specific: what changed, who changed it, why it matters.
Max 2 sentences. No filler.

Repository: {repo}
Sender: {sender}
Event: {json.dumps(payload)[:2000]}"""


def _summarize_event(event_type: str, payload: dict) -> str:
    response = anthropic_client.messages.create(
        model="claude-haiku-4-5-20251001",  # Fast + cheap for 2-sentence summaries
        max_tokens=150,
        messages=[{"role": "user", "content": build_prompt(event_type, payload)}],
        timeout=30.0,  # Fail fast — don't let Anthropic slowness block the worker for 120s
    )
    summary = response.content[0].text.strip()

    if len(summary) < 10:
        raise ValueError(f"Claude returned unusable summary: {summary!r}")

    logger.info("claude_summary_generated", length=len(summary))
    return summary


def _extract_url(payload: dict) -> str | None:
    return (
        payload.get("pull_request", {}).get("html_url")
        or payload.get("issue", {}).get("html_url")
        or payload.get("release", {}).get("html_url")
        or payload.get("compare")  # push events
        or payload.get("repository", {}).get("html_url")
    )


def process_github_event(event_type: str, payload: dict) -> None:
    summary = _summarize_event(event_type, payload)
    url = _extract_url(payload)
    message = f"{summary}\n<{url}>" if url else summary
    post_to_slack(message)
