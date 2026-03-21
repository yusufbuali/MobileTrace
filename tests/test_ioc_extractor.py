"""Unit tests for app.ioc_extractor — regex patterns and deduplication."""
import pytest
from app.ioc_extractor import extract_iocs, _normalise_phone


# ── Phone ────────────────────────────────────────────────────────────────────

def test_phone_e164():
    msgs = [{"id": "1", "body": "Call me at +97312345678", "platform": "sms",
              "thread_id": "t1", "timestamp": "2024-01-01T00:00:00"}]
    result = extract_iocs(msgs, [])
    phones = [i for i in result["iocs"] if i["type"] == "phone"]
    assert len(phones) == 1
    assert "+97312345678" in phones[0]["value"]


def test_phone_deduplication():
    body = "+97312345678"
    msgs = [
        {"id": "1", "body": body, "platform": "sms", "thread_id": "t1", "timestamp": "2024-01-01"},
        {"id": "2", "body": body, "platform": "whatsapp", "thread_id": "t2", "timestamp": "2024-01-02"},
    ]
    result = extract_iocs(msgs, [])
    phones = [i for i in result["iocs"] if i["type"] == "phone"]
    assert len(phones) == 1
    assert phones[0]["occurrences"] == 2


def test_phone_normalise():
    assert _normalise_phone("+973 1234 5678") == "+97312345678"
    assert _normalise_phone("+973-1234-5678") == "+97312345678"


# ── Email ────────────────────────────────────────────────────────────────────

def test_email_extracted():
    msgs = [{"id": "1", "body": "Send to suspect@gmail.com please",
              "platform": "telegram", "thread_id": "t1", "timestamp": "2024-01-01"}]
    result = extract_iocs(msgs, [])
    emails = [i for i in result["iocs"] if i["type"] == "email"]
    assert len(emails) == 1
    assert emails[0]["value"] == "suspect@gmail.com"


# ── URL ──────────────────────────────────────────────────────────────────────

def test_url_https():
    msgs = [{"id": "1", "body": "Check https://example.com/path?x=1",
              "platform": "whatsapp", "thread_id": "t1", "timestamp": "2024-01-01"}]
    result = extract_iocs(msgs, [])
    urls = [i for i in result["iocs"] if i["type"] == "url"]
    assert len(urls) == 1
    assert "example.com" in urls[0]["value"]


def test_url_http():
    msgs = [{"id": "1", "body": "go to http://shady.ru",
              "platform": "sms", "thread_id": "t1", "timestamp": "2024-01-01"}]
    result = extract_iocs(msgs, [])
    urls = [i for i in result["iocs"] if i["type"] == "url"]
    assert any("shady.ru" in u["value"] for u in urls)


# ── Crypto ───────────────────────────────────────────────────────────────────

def test_btc_address():
    msgs = [{"id": "1", "body": "Send to 1A1zP1eP5QGefi2DMPTfTL5SLmv7Divf",
              "platform": "telegram", "thread_id": "t1", "timestamp": "2024-01-01"}]
    result = extract_iocs(msgs, [])
    crypto = [i for i in result["iocs"] if i["type"] == "crypto"]
    assert len(crypto) == 1
    assert crypto[0]["value"] == "1A1zP1eP5QGefi2DMPTfTL5SLmv7Divf"


def test_eth_address():
    msgs = [{"id": "1", "body": "ETH wallet: 0xde0B295669a9FD93d5F28D9Ec85E40f4cb697BAe",
              "platform": "whatsapp", "thread_id": "t1", "timestamp": "2024-01-01"}]
    result = extract_iocs(msgs, [])
    crypto = [i for i in result["iocs"] if i["type"] == "crypto"]
    assert len(crypto) == 1


# ── IP ───────────────────────────────────────────────────────────────────────

def test_public_ip_extracted():
    msgs = [{"id": "1", "body": "Server at 185.220.101.5",
              "platform": "sms", "thread_id": "t1", "timestamp": "2024-01-01"}]
    result = extract_iocs(msgs, [])
    ips = [i for i in result["iocs"] if i["type"] == "ip"]
    assert len(ips) == 1
    assert ips[0]["value"] == "185.220.101.5"


def test_private_ip_excluded():
    msgs = [{"id": "1", "body": "LAN at 192.168.1.1 and 10.0.0.1",
              "platform": "sms", "thread_id": "t1", "timestamp": "2024-01-01"}]
    result = extract_iocs(msgs, [])
    ips = [i for i in result["iocs"] if i["type"] == "ip"]
    assert len(ips) == 0


# ── Coords ───────────────────────────────────────────────────────────────────

def test_coords_extracted():
    msgs = [{"id": "1", "body": "Meet at 26.2285, 50.5860",
              "platform": "whatsapp", "thread_id": "t1", "timestamp": "2024-01-01"}]
    result = extract_iocs(msgs, [])
    coords = [i for i in result["iocs"] if i["type"] == "coords"]
    assert len(coords) == 1


# ── Summary ──────────────────────────────────────────────────────────────────

def test_summary_by_type():
    msgs = [
        {"id": "1", "body": "+97312345678 and suspect@evil.com",
         "platform": "sms", "thread_id": "t1", "timestamp": "2024-01-01"},
    ]
    result = extract_iocs(msgs, [])
    assert result["summary"]["total"] >= 2
    assert result["summary"]["by_type"]["phone"] >= 1
    assert result["summary"]["by_type"]["email"] >= 1


# ── Contact sources ───────────────────────────────────────────────────────────

def test_contacts_scanned():
    contacts = [{"phone": "+97312345678", "email": "dealer@evil.com"}]
    result = extract_iocs([], contacts)
    phones = [i for i in result["iocs"] if i["type"] == "phone"]
    emails = [i for i in result["iocs"] if i["type"] == "email"]
    assert len(phones) == 1
    assert len(emails) == 1


# ── Source snippets ───────────────────────────────────────────────────────────

def test_sources_capped_at_5():
    msgs = [
        {"id": str(i), "body": "+97312345678", "platform": "sms",
         "thread_id": "t1", "timestamp": f"2024-01-0{i+1}"}
        for i in range(8)
    ]
    result = extract_iocs(msgs, [])
    phones = [i for i in result["iocs"] if i["type"] == "phone"]
    assert phones[0]["occurrences"] == 8
    assert len(phones[0]["sources"]) <= 5


# ── Empty input ───────────────────────────────────────────────────────────────

def test_empty_input():
    result = extract_iocs([], [])
    assert result["iocs"] == []
    assert result["summary"]["total"] == 0
