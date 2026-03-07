"""Smoke tests for Flask app factory."""
import pytest
from app import create_app


def test_app_creates_without_error():
    app = create_app(testing=True)
    assert app is not None


def test_app_has_test_client():
    app = create_app(testing=True)
    client = app.test_client()
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "ok"
