import httpx
from app.config import settings


def post_to_slack(message: str) -> None:
    with httpx.Client(timeout=10.0) as client:
        resp = client.post(settings.SLACK_WEBHOOK_URL, json={"text": message})
    if resp.status_code != 200:
        raise RuntimeError(f"Slack rejected message: {resp.status_code} {resp.text}")
