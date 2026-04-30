import json
import pytest
from unittest.mock import MagicMock, patch
from app.workers.processor import _summarize_event, build_prompt


def test_build_prompt_contains_repo_and_action():
    payload = {"repository": {"full_name": "user/repo"}, "action": "opened"}
    prompt = build_prompt("pull_request", payload)
    assert "user/repo" in prompt
    assert "opened" in prompt


def test_summarize_event_valid():
    mock_client = MagicMock()
    mock_client.messages.create.return_value.content = [
        MagicMock(text="PR opened by Alice: adds login feature.")
    ]
    with patch("app.workers.processor.anthropic_client", mock_client):
        result = _summarize_event("pull_request", {})
    assert len(result) >= 10


def test_summarize_event_too_short():
    mock_client = MagicMock()
    mock_client.messages.create.return_value.content = [MagicMock(text="ok")]
    with patch("app.workers.processor.anthropic_client", mock_client):
        with pytest.raises(ValueError, match="unusable summary"):
            _summarize_event("pull_request", {})


def test_build_prompt_truncates_long_payload():
    long_payload = {"data": "x" * 3000}
    prompt = build_prompt("push", long_payload)
    raw = json.dumps(long_payload)
    assert raw[:2000] in prompt
    assert raw[2000:] not in prompt
