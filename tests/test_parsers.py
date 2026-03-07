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


# --- Task 9: UFDR parser ---
import zipfile
from pathlib import Path
from app.parsers.ufdr_parser import UfdrParser


def test_ufdr_can_handle(tmp_path):
    f = tmp_path / "test.ufdr"
    f.write_bytes(b"PK")  # ZIP magic
    assert UfdrParser().can_handle(f)


def test_ufdr_cannot_handle_non_ufdr(tmp_path):
    f = tmp_path / "test.zip"
    f.write_bytes(b"PK")
    assert not UfdrParser().can_handle(f)


def make_mock_ufdr(path: Path) -> Path:
    """Create a minimal valid UFDR ZIP for testing."""
    ufdr = path / "test.ufdr"
    with zipfile.ZipFile(ufdr, "w") as zf:
        metadata = """<?xml version="1.0"?>
        <project>
          <model>Samsung Galaxy S21</model>
          <imei>123456789012345</imei>
          <platform>Android 12</platform>
        </project>"""
        zf.writestr("Metadata.xml", metadata)
    return ufdr


def test_ufdr_parses_device_info(tmp_path):
    ufdr = make_mock_ufdr(tmp_path)
    dest = tmp_path / "out"
    dest.mkdir()
    result = UfdrParser().parse(ufdr, dest)
    assert result.format == "ufdr"
    assert "Samsung" in result.device_info.get("model", "")
