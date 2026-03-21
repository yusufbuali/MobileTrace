"""Tests for report generation, graph endpoint, and RTL support."""
import pytest
from app import create_app
from app.database import init_db, close_db, get_db


@pytest.fixture
def client(tmp_path):
    app = create_app(testing=True)
    db_path = str(tmp_path / "test.db")
    app.config["MT_CONFIG"]["server"]["database_path"] = db_path
    app.config["MT_CONFIG"]["server"]["cases_dir"] = str(tmp_path / "cases")
    init_db(db_path)
    with app.test_client() as c:
        yield c
    close_db()


@pytest.fixture
def populated_case(client):
    r = client.post("/api/cases", json={"title": "Report Test Case", "officer": "Smith"})
    case_id = r.get_json()["id"]
    db = get_db()
    db.execute(
        "INSERT INTO messages (case_id, platform, direction, sender, recipient, body, timestamp, thread_id, raw_json) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (case_id, "sms", "incoming", "+9731234567", "device",
         "Hello", "2026-01-01T10:00:00+00:00", "+9731234567", "{}"),
    )
    db.execute(
        "INSERT INTO contacts (case_id, name, phone, email, source_app, raw_json) VALUES (?,?,?,?,?,?)",
        (case_id, "Ali", "+9731234567", "", "android_contacts", "{}"),
    )
    db.execute(
        "INSERT INTO call_logs (case_id, number, direction, duration_s, timestamp, platform) VALUES (?,?,?,?,?,?)",
        (case_id, "+9731234567", "incoming", 60, "2026-01-01T11:00:00+00:00", "phone"),
    )
    db.execute(
        "INSERT INTO analysis_results (case_id, artifact_key, result, provider) VALUES (?,?,?,?)",
        (case_id, "sms", "**LOW** — nothing suspicious.", "claude"),
    )
    db.commit()
    return case_id


# ── Report HTML ───────────────────────────────────────────────────────────────

def test_report_returns_html(client, populated_case):
    resp = client.get(f"/api/cases/{populated_case}/report")
    assert resp.status_code == 200
    assert "text/html" in resp.content_type


def test_report_contains_case_title(client, populated_case):
    resp = client.get(f"/api/cases/{populated_case}/report")
    assert b"Report Test Case" in resp.data


def test_report_contains_messages(client, populated_case):
    resp = client.get(f"/api/cases/{populated_case}/report")
    assert b"Hello" in resp.data


def test_report_contains_analysis(client, populated_case):
    resp = client.get(f"/api/cases/{populated_case}/report")
    assert b"LOW" in resp.data


def test_report_not_found(client):
    resp = client.get("/api/cases/nonexistent/report")
    assert resp.status_code == 404


# ── Graph ─────────────────────────────────────────────────────────────────────

def test_graph_returns_nodes_and_edges(client, populated_case):
    resp = client.get(f"/api/cases/{populated_case}/graph")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "nodes" in data
    assert "edges" in data


def test_graph_not_found(client):
    resp = client.get("/api/cases/nonexistent/graph")
    assert resp.status_code == 404


def test_graph_has_contact_node(client, populated_case):
    resp = client.get(f"/api/cases/{populated_case}/graph")
    nodes = resp.get_json()["nodes"]
    phones = [n["id"] for n in nodes]
    assert "+9731234567" in phones


# ── Count endpoints ───────────────────────────────────────────────────────────

def test_messages_count(client, populated_case):
    resp = client.get(f"/api/cases/{populated_case}/messages/count")
    assert resp.status_code == 200
    assert resp.get_json()["count"] == 1


def test_contacts_count(client, populated_case):
    resp = client.get(f"/api/cases/{populated_case}/contacts/count")
    assert resp.get_json()["count"] == 1


def test_calls_count(client, populated_case):
    resp = client.get(f"/api/cases/{populated_case}/calls/count")
    assert resp.get_json()["count"] == 1


# ── RTL support ───────────────────────────────────────────────────────────────

def test_rtl_detection_arabic():
    from app.rtl_support import is_rtl_text
    assert is_rtl_text("مرحبا بالعالم") is True


def test_rtl_detection_english():
    from app.rtl_support import is_rtl_text
    assert is_rtl_text("Hello world") is False


def test_augment_report_context_arabic_title():
    from app.rtl_support import augment_report_context
    ctx = augment_report_context({}, case_name="قضية المشتبه به")
    assert ctx["is_rtl"] is True
    assert ctx["text_direction"] == "rtl"
    assert "direction: rtl" in ctx["rtl_css"]


def test_augment_report_context_english_title():
    from app.rtl_support import augment_report_context
    ctx = augment_report_context({}, case_name="Drug Investigation")
    assert ctx["is_rtl"] is False
    assert ctx["rtl_css"] == ""


def test_report_rtl_arabic_case(client):
    """Report with Arabic title should include dir=rtl."""
    r = client.post("/api/cases", json={"title": "قضية اختبار", "officer": "X"})
    case_id = r.get_json()["id"]
    resp = client.get(f"/api/cases/{case_id}/report")
    assert resp.status_code == 200
    assert b'dir="rtl"' in resp.data


def test_report_includes_annotated_evidence_section(client):
    """Report shows Annotated Evidence section when annotations exist."""
    from app.database import get_db
    # Create case
    r = client.post("/api/cases", json={"title": "Ann Report Test", "officer": "Det"})
    case_id = r.get_json()["id"]
    # Seed a message
    db = get_db()
    db.execute(
        "INSERT INTO messages (case_id, platform, direction, sender, recipient, body, timestamp) "
        "VALUES (?,?,?,?,?,?,?)",
        (case_id, "whatsapp", "incoming", "Alice", "device", "Key evidence here", "2024-01-01T10:00:00"),
    )
    db.commit()
    msg_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    # Add annotation via API
    client.post(f"/api/cases/{case_id}/annotations",
                json={"message_id": msg_id, "tag": "KEY_EVIDENCE", "note": "Critical"})
    # Get report
    r2 = client.get(f"/api/cases/{case_id}/report")
    assert r2.status_code == 200
    html = r2.data.decode()
    assert "Annotated Evidence" in html
    assert "KEY EVIDENCE" in html or "KEY_EVIDENCE" in html
    assert "Critical" in html


def test_build_report_context_returns_dict(populated_case, client):
    """_build_report_context returns a dict with expected top-level keys."""
    from app.routes.reports import _build_report_context
    from app.database import get_db
    case_id = populated_case  # fixture returns case_id string
    with client.application.app_context():
        db = get_db()
        ctx = _build_report_context(db, case_id)
    for key in ("case", "messages", "contacts", "calls", "analysis",
                "evidence_files", "executive_summary", "conversation_excerpts",
                "stats", "generated_at"):
        assert key in ctx, f"missing key: {key}"
