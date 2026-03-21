"""Tests for GET /api/cases/<id>/timeline (A1)."""
import uuid

def _insert_case(db, title="TL Test"):
    cid = str(uuid.uuid4())
    db.execute("INSERT INTO cases (id, title) VALUES (?,?)", (cid, title))
    db.commit()
    return cid

def _insert_msg(db, cid, platform, ts, body="hi", direction="incoming"):
    db.execute(
        "INSERT INTO messages (case_id, platform, direction, sender, recipient,"
        " body, timestamp, thread_id, raw_json) VALUES (?,?,?,?,?,?,?,?,?)",
        (cid, platform, direction, "Alice", None, body, ts, "t1", "{}"),
    )
    db.commit()

def _insert_call(db, cid, ts, platform="sms", direction="incoming"):
    db.execute(
        "INSERT INTO call_logs (case_id, number, direction, duration_s, timestamp, platform)"
        " VALUES (?,?,?,?,?,?)",
        (cid, "+15559999", direction, 120, ts, platform),
    )
    db.commit()

def test_timeline_empty_case(client, app):
    with app.app_context():
        from app.database import get_db
        cid = _insert_case(get_db())
    resp = client.get(f"/api/cases/{cid}/timeline")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["items"] == []
    assert data["next_cursor"] is None

def test_timeline_merges_and_sorts(client, app):
    with app.app_context():
        from app.database import get_db
        db = get_db()
        cid = _insert_case(db)
        _insert_msg(db, cid, "sms",      "2021-03-14T09:00:00")
        _insert_msg(db, cid, "whatsapp", "2021-03-14T10:00:00")
        _insert_call(db, cid,             "2021-03-14T11:00:00", platform="phone")
    resp = client.get(f"/api/cases/{cid}/timeline")
    items = resp.get_json()["items"]
    assert len(items) == 3
    timestamps = [i["timestamp"] for i in items]
    assert timestamps == sorted(timestamps)
    assert any(i["type"] == "message" for i in items)
    assert any(i["type"] == "call" for i in items)

def test_timeline_platform_filter_excludes(client, app):
    """platform=sms filter must exclude whatsapp messages."""
    with app.app_context():
        from app.database import get_db
        db = get_db()
        cid = _insert_case(db)
        _insert_msg(db, cid, "sms",      "2021-01-01T09:00:00")
        _insert_msg(db, cid, "whatsapp", "2021-01-01T10:00:00")
    resp = client.get(f"/api/cases/{cid}/timeline?platforms=sms")
    items = resp.get_json()["items"]
    assert all(i["platform"] == "sms" for i in items)
    assert len(items) == 1

def test_timeline_limit_capped_at_500(client, app):
    with app.app_context():
        from app.database import get_db
        db = get_db()
        cid = _insert_case(db)
        _insert_msg(db, cid, "sms", "2021-01-01T09:00:00")
    resp = client.get(f"/api/cases/{cid}/timeline?limit=9999")
    assert resp.status_code == 200  # no crash
    assert len(resp.get_json()["items"]) <= 500

def test_timeline_pagination_no_duplicates(client, app):
    """Two pages must together equal all items with no duplicates, even with tie timestamps."""
    with app.app_context():
        from app.database import get_db
        db = get_db()
        cid = _insert_case(db)
        # 5 messages at identical timestamp — stresses tie-breaking
        for i in range(5):
            _insert_msg(db, cid, "sms", "2021-01-01T12:00:00", body=f"msg{i}")
    resp1 = client.get(f"/api/cases/{cid}/timeline?limit=3")
    data1 = resp1.get_json()
    assert len(data1["items"]) == 3
    assert data1["next_cursor"] is not None

    nc = data1["next_cursor"]
    resp2 = client.get(
        f"/api/cases/{cid}/timeline?limit=3"
        f"&cursor_ts={nc['ts']}&cursor_key={nc['key']}"
    )
    data2 = resp2.get_json()
    assert len(data2["items"]) == 2

    # Use row_key (namespaced) for dedup — numeric id can overlap across tables
    all_keys = [i["row_key"] for i in data1["items"]] + [i["row_key"] for i in data2["items"]]
    assert len(all_keys) == len(set(all_keys)), "Duplicate items across pages"
