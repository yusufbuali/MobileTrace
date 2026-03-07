"""Tests for parser base class and ParsedCase dataclass."""
from app.parsers.base import ParsedCase, BaseParser


def test_parsed_case_defaults():
    pc = ParsedCase(format="ufdr")
    assert pc.contacts == []
    assert pc.messages == []
    assert pc.call_logs == []
    assert pc.warnings == []
    assert pc.device_info == {}


def test_parsed_case_message_normalization():
    pc = ParsedCase(format="xry")
    pc.messages.append({
        "platform": "sms",
        "direction": "incoming",
        "sender": "+1234567890",
        "recipient": "device",
        "body": "Hello",
        "timestamp": "2026-01-01T10:00:00",
    })
    assert len(pc.messages) == 1
    assert pc.messages[0]["platform"] == "sms"
