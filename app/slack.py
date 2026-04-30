import httpx
import structlog
from app.config import settings

logger = structlog.get_logger()


def post_to_slack(message: str) -> None:
    with httpx.Client(timeout=10.0) as client:
        resp = client.post(settings.SLACK_WEBHOOK_URL, json={"text": message})
    if resp.status_code != 200:
        logger.error("slack_failed", status_code=resp.status_code)
        raise RuntimeError(f"Slack rejected message: {resp.status_code} {resp.text}")
