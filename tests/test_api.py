"""FastAPI endpoint tests using TestClient with a mocked OCR worker."""
from __future__ import annotations

import asyncio
import importlib
import io
import os

import pytest
from fastapi.testclient import TestClient


COMMANDE_PAYLOAD = {
    "supplier_name": "BOULANGERIE DURAND",
    "num_cmd": "CMD-COM606-1",
    "num_bl": "BL-1",
    "date_cmd": "2026-05-23",
    "total_ht": 100.0,
    "line_items": [
        {
            "description": "Farine",
            "qty": 4,
            "unit_price": 25.0,
            "total_ht": 100.0,
            "cost_center_label": "BOULANGERIE",
            "cost_center_code": "BOUL",
        }
    ],
    "raw_text": "...",
    "confidence": 0.9,
    "field_confidence": {"num_cmd": 0.95},
    "warnings": [],
}

FACTURE_PAYLOAD = {
    "supplier_name": "ACME SARL",
    "num_fact": "F-1",
    "date_fact": "2026-04-01",
    "total_ht": 50.0,
    "total_ttc": 60.0,
    "tva_rate": 20.0,
    "line_items": [
        {"description": "Item", "qty": 1, "unit_price": 50.0, "total_ht": 50.0}
    ],
    "raw_text": "...",
    "confidence": 0.91,
    "field_confidence": {},
    "warnings": [],
}


@pytest.fixture
def app_module(monkeypatch, tmp_path):
    # Steer module-level Settings at import time so we don't touch /data.
    monkeypatch.setenv("DB_PATH", str(tmp_path / "ocr.db"))
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_API_KEY", "unused")

    import main  # noqa: WPS433 — fresh module per test
    importlib.reload(main)

    # Make process_file deterministic and synchronous. The endpoint dispatches
    # OCR through asyncio.create_task; the test waits below for it.
    def fake_process_file(path, supplier_candidates, doc_type):
        from models import DocumentType
        if doc_type == DocumentType.COMMANDE:
            return main.ocr_worker.parse_commande(COMMANDE_PAYLOAD, supplier_candidates)
        return main.ocr_worker.parse_facture(FACTURE_PAYLOAD, supplier_candidates)

    monkeypatch.setattr(main.ocr_worker, "process_file", fake_process_file)
    return main


def _drain_background_tasks():
    """Force any asyncio.create_task(...) scheduled by the endpoint to run."""
    loop = asyncio.new_event_loop()
    try:
        # Yield control so the task scheduled in the request handler runs.
        loop.run_until_complete(asyncio.sleep(0.05))
    finally:
        loop.close()


def _upload(client, doc_type=None, filename="x.pdf"):
    files = {"file": (filename, b"%PDF-1.4 dummy", "application/pdf")}
    params = {"id_pdv": 5}
    if doc_type is not None:
        params["doc_type"] = doc_type
    return client.post(
        "/upload",
        files=files,
        params=params,
        headers={"x-api-key": "test-key"},
    )


def _wait_done(client, job_id, timeout_s=2.0):
    import time
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        r = client.get(f"/jobs/{job_id}", headers={"x-api-key": "test-key"})
        if r.json()["job"]["status"] == "done":
            return r.json()["job"]
        time.sleep(0.02)
    return r.json()["job"]


def test_upload_default_is_facture(app_module):
    client = TestClient(app_module.app)
    r = _upload(client)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["doc_type"] == "facture"
    job = _wait_done(client, body["job_id"])
    assert job["doc_type"] == "facture"
    assert job["status"] == "done"
    assert job["ocr_result"]["num_fact"] == "F-1"
    assert job["commande_result"] is None


def test_upload_commande_persisted_and_returned(app_module):
    client = TestClient(app_module.app)
    r = _upload(client, doc_type="commande")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["doc_type"] == "commande"

    job = _wait_done(client, body["job_id"])
    assert job["doc_type"] == "commande"
    assert job["status"] == "done"
    assert job["ocr_result"] is None
    cmd = job["commande_result"]
    assert cmd["num_cmd"] == "CMD-COM606-1"
    assert cmd["num_bl"] == "BL-1"
    assert cmd["date_cmd"] == "2026-05-23"
    assert cmd["total_ht"] == 100.0
    assert cmd["line_items"][0]["cost_center_label"] == "BOULANGERIE"


def test_db_persists_doc_type(app_module):
    """The new doc_type column round-trips through SQLite even after restart."""
    client = TestClient(app_module.app)
    body = _upload(client, doc_type="commande").json()
    job = _wait_done(client, body["job_id"])
    assert job["doc_type"] == "commande"

    # Reopen DB from disk to prove persistence (no in-memory cache).
    from db import Db
    fresh = Db(app_module.settings.db_path)
    reloaded = fresh.get_job(body["job_id"])
    assert reloaded is not None
    assert reloaded.doc_type.value == "commande"
    assert reloaded.commande_result is not None
    assert reloaded.commande_result.num_cmd == "CMD-COM606-1"
    assert reloaded.ocr_result is None


def test_unknown_doc_type_rejected(app_module):
    client = TestClient(app_module.app)
    r = _upload(client, doc_type="bordereau")
    # FastAPI returns 422 for enum mismatch on Query.
    assert r.status_code == 422


def test_invalid_api_key_rejected(app_module):
    client = TestClient(app_module.app)
    files = {"file": ("x.pdf", b"%PDF", "application/pdf")}
    r = client.post(
        "/upload",
        files=files,
        params={"id_pdv": 5},
        headers={"x-api-key": "wrong"},
    )
    assert r.status_code == 401


def test_jobs_pending_static_route_not_shadowed(app_module):
    """Regression for COM-606 QA blocker #1: the static /jobs/pending route
    must resolve before /jobs/{job_id}, otherwise "pending" is captured as a
    job_id and the endpoint 404s.
    """
    client = TestClient(app_module.app)

    body = _upload(client, doc_type="commande").json()
    _wait_done(client, body["job_id"])  # ensure at least one done job exists for pdv=5

    r = client.get("/jobs/pending", params={"id_pdv": 5}, headers={"x-api-key": "test-key"})
    assert r.status_code == 200, r.text
    payload = r.json()
    assert "jobs" in payload
    assert any(j["id"] == body["job_id"] for j in payload["jobs"])
    # Second call returns nothing — first call already marked the job fetched.
    r2 = client.get("/jobs/pending", params={"id_pdv": 5}, headers={"x-api-key": "test-key"})
    assert r2.status_code == 200
    assert all(j["id"] != body["job_id"] for j in r2.json()["jobs"])


def test_suppliers_sync_persists_for_pdv(app_module):
    client = TestClient(app_module.app)
    r = client.post(
        "/suppliers/sync",
        params={"id_pdv": 5},
        json={"candidates": [
            {"id_f": 17, "name": "Boulangerie Durand"},
            {"id_f": 23, "name": "Grossiste Martin"},
        ]},
        headers={"x-api-key": "test-key"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body == {"id_pdv": 5, "count": 2}

    # The cache must be scoped per pdv: another pdv sees nothing.
    assert app_module.db.list_supplier_candidates(5)[0].id_f == 17
    assert app_module.db.list_supplier_candidates(999) == []


def test_suppliers_sync_replaces_not_merges(app_module):
    client = TestClient(app_module.app)
    headers = {"x-api-key": "test-key"}

    client.post(
        "/suppliers/sync",
        params={"id_pdv": 5},
        json={"candidates": [{"id_f": 17, "name": "Boulangerie Durand"}]},
        headers=headers,
    )
    # Replace with a different list — old id_f=17 must be gone.
    client.post(
        "/suppliers/sync",
        params={"id_pdv": 5},
        json={"candidates": [{"id_f": 42, "name": "Nouveau Fournisseur"}]},
        headers=headers,
    )
    candidates = app_module.db.list_supplier_candidates(5)
    assert [c.id_f for c in candidates] == [42]


def test_full_flow_supplier_match_after_sync(app_module):
    """COM-606 QA blocker #2: POST /upload?doc_type=commande followed by
    GET /jobs/{job_id} must exercise supplier matching when candidates are
    seeded for the id_pdv. BOULANGERIE DURAND must match id_f=17.
    """
    client = TestClient(app_module.app)

    sync = client.post(
        "/suppliers/sync",
        params={"id_pdv": 5},
        json={"candidates": [
            {"id_f": 17, "name": "Boulangerie Durand"},
            {"id_f": 23, "name": "Grossiste Martin"},
        ]},
        headers={"x-api-key": "test-key"},
    )
    assert sync.status_code == 200

    body = _upload(client, doc_type="commande").json()
    job = _wait_done(client, body["job_id"])
    assert job["status"] == "done"
    cmd = job["commande_result"]
    assert cmd["supplier_match"]["id_f"] == 17
    assert cmd["supplier_match"]["name"] == "Boulangerie Durand"
    assert cmd["supplier_match"]["score"] is not None and cmd["supplier_match"]["score"] > 0.6
    # No "no candidates synced" warning since the cache had entries.
    assert not any("No supplier candidates synced" in w for w in cmd["warnings"])


def test_warning_emitted_when_no_candidates_for_pdv(app_module):
    """COM-606 QA blocker #3 follow-up: when nothing has been synced for the
    pdv but OCR extracted a supplier_name, the result must carry an explicit
    warning rather than a silent all-null supplier_match.
    """
    client = TestClient(app_module.app)
    # Note: NO /suppliers/sync call.
    body = _upload(client, doc_type="commande").json()
    job = _wait_done(client, body["job_id"])
    cmd = job["commande_result"]
    assert cmd["supplier_match"]["id_f"] is None
    assert any("No supplier candidates synced" in w for w in cmd["warnings"])
