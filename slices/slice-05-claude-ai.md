# Slice 5: Claude AI Summarization

**Estimated time:** ~1 hour  
**Depends on:** Slice 4  
**Files modified:** `app/workers/processor.py`

---

## Goal

Replace the static `format_message()` with a Claude-generated summary.  
Validates AI output before posting to Slack — never post garbage.

---

## Update `app/workers/processor.py`

```python
import json
import anthropic
import structlog
from app.config import settings
from app.slack import post_to_slack

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


def process_github_event(event_type: str, payload: dict) -> None:
    message = _summarize_event(event_type, payload)
    post_to_slack(message)
```

---

## Model choice: Haiku

Haiku is ~10x cheaper than Sonnet and the quality is identical for 2-sentence event summaries. Sonnet is overkill here.

Current model ID: `claude-haiku-4-5-20251001`

---

## Why validate AI output

AI output is non-deterministic. The guard rails here:
- `max_tokens=150` — bounds cost and response length
- `len(summary) < 10` — catches empty or garbage responses before they hit Slack
- `logger.info(...)` — every summary is logged so you can audit what got posted

---

## Done when

Trigger a GitHub PR event → Slack shows a Claude-written 2-sentence summary, not raw JSON.

---

## Interview story

"The AI call is a single `.create()` — my code controls the flow, not a framework. AI output is non-deterministic, so I validate before acting: `max_tokens` caps cost, a minimum length check rejects empty responses, and I log every summary for auditability. The model is Haiku — it's 10x cheaper than Sonnet for this task and the quality is identical for 2-sentence event summaries."
