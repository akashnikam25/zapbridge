import pytest
from unittest.mock import patch, MagicMock
from fastapi import HTTPException
from app.github import fetch_with_retry


def _mock_resp(status_code, json_data=None, headers=None):
    m = MagicMock()
    m.status_code = status_code
    m.json.return_value = json_data or []
    m.headers = headers or {}
    return m


def test_200_returns_json():
    with patch("httpx.get", return_value=_mock_resp(200, [{"id": 1}])):
        result = fetch_with_retry("http://example.com", {})
    assert result == [{"id": 1}]


def test_401_raises():
    with patch("httpx.get", return_value=_mock_resp(401)):
        with pytest.raises(HTTPException) as exc:
            fetch_with_retry("http://example.com", {})
    assert exc.value.status_code == 401


def test_max_retries_exhausted():
    with patch("httpx.get", return_value=_mock_resp(429)), \
         patch("time.sleep"):
        with pytest.raises(HTTPException) as exc:
            fetch_with_retry("http://example.com", {}, max_retries=2)
    assert exc.value.status_code == 429
