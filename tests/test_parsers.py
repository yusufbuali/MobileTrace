"""Tests for parser base class and ParsedCase dataclass."""
from app.parsers.base import ParsedCase, BaseParser


# --- Telegram UTF-8 string extractor ---

def test_extract_utf8_strings_ascii():
    from app.parsers.android_parser import _extract_utf8_strings
    result = _extract_utf8_strings(b"\x00\x01Hello World\x00\x02", min_len=4)
    assert any("Hello World" in s for s in result)


def test_extract_utf8_strings_arabic():
    from app.parsers.android_parser import _extract_utf8_strings
    # Arabic "مرحبا" (Marhaba) encoded as UTF-8
    arabic = "مرحبا بالعالم"
    blob = b"\x00\x01" + arabic.encode("utf-8") + b"\x00\x02"
    result = _extract_utf8_strings(blob, min_len=4)
    joined = " ".join(result)
    assert "مرحبا" in joined


def test_extract_utf8_strings_cyrillic():
    from app.parsers.android_parser import _extract_utf8_strings
    cyrillic = "Привет мир"
    blob = b"\xff\xfe" + cyrillic.encode("utf-8") + b"\x00\x00"
    result = _extract_utf8_strings(blob, min_len=4)
    joined = " ".join(result)
    assert "Привет" in joined


def test_extract_utf8_strings_filters_short():
    from app.parsers.android_parser import _extract_utf8_strings
    blob = b"\x00hi\x00" + b"long enough text" + b"\x00"
    result = _extract_utf8_strings(blob, min_len=6)
    assert not any(s == "hi" for s in result)
    assert any("long enough" in s for s in result)


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


# --- Task 10: XRY parser ---
from app.parsers.xry_parser import XryParser


def test_xry_can_handle_xrep_folder(tmp_path):
    d = tmp_path / "xry_export"
    d.mkdir()
    (d / "report.xrep").write_text("<xml/>")
    assert XryParser().can_handle(d)


def test_xry_can_handle_xrep_zip(tmp_path):
    z = tmp_path / "export.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("report.xrep", "<xml/>")
    assert XryParser().can_handle(z)


def test_xry_parses_device_info_from_xrep(tmp_path):
    xrep = tmp_path / "report.xrep"
    xrep.write_text("""<?xml version="1.0"?>
    <XRY>
      <DeviceInfo>
        <DeviceName>iPhone 14 Pro</DeviceName>
        <IMEI>999888777666555</IMEI>
        <OS>iOS 16.1</OS>
      </DeviceInfo>
    </XRY>""")
    dest = tmp_path / "out"
    dest.mkdir()
    result = XryParser().parse(tmp_path, dest)
    assert result.format == "xry"
    assert "iPhone" in result.device_info.get("model", "")


# --- Task 11: Oxygen parser ---
import sqlite3
from app.parsers.oxygen_parser import OxygenParser


def make_oxygen_db(path: Path) -> Path:
    """Create a minimal Oxygen Forensics SQLite DB for testing."""
    ofb = path / "device.ofb"
    conn = sqlite3.connect(ofb)
    conn.executescript("""
        CREATE TABLE DeviceInfo (field TEXT, value TEXT);
        INSERT INTO DeviceInfo VALUES ('DeviceName', 'Samsung Galaxy S22');
        INSERT INTO DeviceInfo VALUES ('IMEI', '111222333444555');
        INSERT INTO DeviceInfo VALUES ('OS', 'Android 13');

        CREATE TABLE messages (
            id INTEGER PRIMARY KEY, address TEXT, body TEXT,
            date INTEGER, type INTEGER
        );
        INSERT INTO messages VALUES (1, '+9731234567', 'Test SMS', 1700000000000, 1);

        CREATE TABLE calls (
            id INTEGER PRIMARY KEY, number TEXT, duration INTEGER,
            date INTEGER, call_type INTEGER
        );
        INSERT INTO calls VALUES (1, '+9731234567', 120, 1700000000000, 1);

        CREATE TABLE contacts (
            id INTEGER PRIMARY KEY, display_name TEXT,
            phone_number TEXT, email TEXT
        );
        INSERT INTO contacts VALUES (1, 'Alice', '+9731234567', 'alice@example.com');
    """)
    conn.commit()
    conn.close()
    return ofb


def test_oxygen_can_handle_ofb(tmp_path):
    ofb = make_oxygen_db(tmp_path)
    assert OxygenParser().can_handle(ofb)


def test_oxygen_parses_device_info(tmp_path):
    ofb = make_oxygen_db(tmp_path)
    result = OxygenParser().parse(ofb, tmp_path / "out")
    assert "Samsung" in result.device_info.get("model", "")
    assert result.device_info.get("platform") == "android"


def test_oxygen_parses_messages(tmp_path):
    ofb = make_oxygen_db(tmp_path)
    result = OxygenParser().parse(ofb, tmp_path / "out")
    assert len(result.messages) == 1
    assert result.messages[0]["body"] == "Test SMS"
    assert result.messages[0]["platform"] == "sms"


def test_oxygen_parses_contacts(tmp_path):
    ofb = make_oxygen_db(tmp_path)
    result = OxygenParser().parse(ofb, tmp_path / "out")
    assert len(result.contacts) == 1
    assert result.contacts[0]["name"] == "Alice"


def test_oxygen_parses_calls(tmp_path):
    ofb = make_oxygen_db(tmp_path)
    result = OxygenParser().parse(ofb, tmp_path / "out")
    assert len(result.call_logs) == 1
    assert result.call_logs[0]["duration_s"] == 120


# --- Symlink path traversal guard ---
from app.parsers.folder_parser import FolderParser


def test_scan_folder_skips_symlink_escape(tmp_path):
    """scan_folder must not return paths that escape the evidence root via symlink."""
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()

    # Real archive file sitting outside the evidence root
    outside_archive = tmp_path / "secret.zip"
    outside_archive.write_bytes(b"PK\x03\x04")

    # Symlink inside evidence_dir → points outside
    link = evidence_dir / "escape.zip"
    try:
        link.symlink_to(outside_archive)
    except (OSError, NotImplementedError):
        import pytest
        pytest.skip("Symlink creation not supported on this platform")

    result = FolderParser.scan_folder(evidence_dir)

    archive_paths = {a["path"] for a in result["archives"]}
    assert str(link) not in archive_paths
    assert str(outside_archive) not in archive_paths
