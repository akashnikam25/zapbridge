"""Integration tests — require `docker compose up -d` (real Redis + real Postgres).

Run:
    pytest tests/test_integration.py -v

These tests exercise the full request path using real infrastructure.
Slack and Claude AI calls are patched to avoid external network traffic.
The RQ worker runs synchronously (SimpleWorker) so job execution happens
in-process and patches remain active during worker execution.
"""
import hashlib
import hmac
import json
import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from rq import SimpleWorker

from app.config import settings
from app.connections import queue as rq_queue, redis_conn
from app.main import app

client = TestClient(app)

SAMPLE_PAYLOAD = {
    "action": "opened",
    "pull_request": {
        "html_url": "https://github.com/test/repo/pull/1",
        "title": "Fix critical bug",
    },
    "repository": {"full_name": "test/repo"},
    "sender": {"login": "testuser"},
}


def _sign(body: bytes) -> str:
    return "sha256=" + hmac.new(
        settings.GITHUB_WEBHOOK_SECRET.encode(), body, hashlib.sha256
    ).hexdigest()


@pytest.fixture(autouse=True)
def clean_redis():
    """Flush the RQ queue and idempotency keys before and after each test."""
    rq_queue.empty()
    for key in redis_conn.scan_iter("webhook:*"):
        redis_conn.delete(key)
    yield
    rq_queue.empty()
    for key in redis_conn.scan_iter("webhook:*"):
        redis_conn.delete(key)


def test_webhook_full_pipeline():
    """Valid webhook → job queued → SimpleWorker processes it → Slack notified."""
    body = json.dumps(SAMPLE_PAYLOAD).encode()
    sig = _sign(body)
    delivery_id = str(uuid.uuid4())

    with (
        patch(
            "app.workers.processor._summarize_event",
            return_value="PR opened: Fix critical bug",
        ),
        patch("app.workers.processor.post_to_slack") as mock_slack,
    ):
        resp = client.post(
            "/webhook",
            content=body,
            headers={
                "X-Hub-Signature-256": sig,
                "X-GitHub-Event": "pull_request",
                "X-GitHub-Delivery": delivery_id,
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "queued"

        # SimpleWorker runs without forking — patches stay active during execution.
        worker = SimpleWorker([rq_queue], connection=redis_conn)
        worker.work(burst=True)

        mock_slack.assert_called_once()


def test_webhook_invalid_signature():
    """Invalid HMAC signature → 401."""
    body = json.dumps(SAMPLE_PAYLOAD).encode()
    resp = client.post(
        "/webhook",
        content=body,
        headers={
            "X-Hub-Signature-256": "sha256=badsignature",
            "X-GitHub-Event": "push",
            "X-GitHub-Delivery": str(uuid.uuid4()),
            "Content-Type": "application/json",
        },
    )
    assert resp.status_code == 401


def test_webhook_duplicate_delivery():
    """Same X-GitHub-Delivery sent twice → second returns already_processed."""
    body = json.dumps(SAMPLE_PAYLOAD).encode()
    sig = _sign(body)
    delivery_id = str(uuid.uuid4())

    headers = {
        "X-Hub-Signature-256": sig,
        "X-GitHub-Event": "push",
        "X-GitHub-Delivery": delivery_id,
        "Content-Type": "application/json",
    }

    resp1 = client.post("/webhook", content=body, headers=headers)
    assert resp1.status_code == 200
    assert resp1.json()["status"] == "queued"

    resp2 = client.post("/webhook", content=body, headers=headers)
    assert resp2.status_code == 200
    assert resp2.json() == {"status": "already_processed"}


def test_health_check():
    """Health endpoint returns ok when Redis and Postgres are both reachable."""
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["db"] == "up"
    assert data["redis"] == "up"
