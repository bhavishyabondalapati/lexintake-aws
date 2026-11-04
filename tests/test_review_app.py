"""The review app's routes with a fake backend (no AWS)."""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "review_app"))

from backend import ReviewError, _public  # noqa: E402
from main import create_app, safe_filename  # noqa: E402

DOC = "3f2b8c1e-0000-4000-8000-000000000001"


class FakeBackend:
    max_upload_bytes = 5 * 1024 * 1024

    def __init__(self):
        self.slots = 2
        self.docs = {
            DOC: {
                "doc_id": DOC, "status": "pending_review", "created_at": "2026-11-03T10:00:00+00:00",
                "doc_type": "nda", "confidence": "0.6", "risk": "medium", "reasons": ["low_field_confidence:mutual"],
                "score_key": "results/x/score.json", "s3_key": f"uploads/{DOC}/a.pdf",
            }
        }
        self.decisions = []
        self.presigned = []

    def reserve_upload(self):
        if self.slots == 0:
            return False
        self.slots -= 1
        return True

    def presign_upload(self, doc_id, filename):
        self.presigned.append((doc_id, filename))
        return {"url": "https://bucket.s3.us-east-2.amazonaws.com/", "fields": {"key": f"uploads/{doc_id}/{filename}"}}

    def pending_reviews(self):
        return [d for d in self.docs.values() if d["status"] == "pending_review"]

    def get_document(self, doc_id):
        return self.docs.get(doc_id)

    def get_score(self, key):
        return {
            "reasons": [{"code": "low_field_confidence", "field": "mutual", "detail": "0.60 < 0.8"}],
            "playbook": [{"label": "Term > 24 months", "outcome": "pass", "reason": "6 vs limit 24"}],
            "checks": [{
                "name": "counterparty", "value": "<script>alert(1)</script>", "status": "verified",
                "confidence": 0.9, "quote": "<b>Dalton</b> Foods LLC", "page": 1,
            }],
        }

    def pdf_url(self, key):
        return "https://example.invalid/pdf"

    def approve(self, doc_id):
        self._decide("approve", doc_id)

    def reject(self, doc_id):
        self._decide("reject", doc_id)

    def _decide(self, what, doc_id):
        if self.docs[doc_id]["status"] != "pending_review":
            raise ReviewError("not waiting")
        self.docs[doc_id]["status"] = "approved" if what == "approve" else "rejected"
        self.decisions.append((what, doc_id))


@pytest.fixture
def backend():
    return FakeBackend()


@pytest.fixture
def client(backend):
    return TestClient(create_app(backend), follow_redirects=False)


def test_index_lists_pending_reviews(client):
    page = client.get("/").text
    assert DOC in page and "Waiting for review (1)" in page


def test_presign_returns_a_form_for_a_clean_pdf_name(client, backend):
    r = client.post("/api/presign", json={"filename": "../../my contract (final).PDF", "size": 1000})
    assert r.status_code == 200
    doc_id, name = backend.presigned[0]
    assert name == "my_contract_final_.PDF"
    assert r.json()["fields"]["key"] == f"uploads/{doc_id}/{name}"


@pytest.mark.parametrize("body", [
    {"filename": "notes.txt", "size": 10},
    {"filename": ".pdf", "size": 10},
    {"filename": "a.pdf", "size": 0},
    {"filename": "a.pdf", "size": 5 * 1024 * 1024 + 1},
    {"filename": "a.pdf", "size": "big"},
])
def test_presign_rejects_bad_files_without_using_a_daily_slot(client, backend, body):
    assert client.post("/api/presign", json=body).status_code == 400
    assert backend.slots == 2 and backend.presigned == []


def test_daily_limit_blocks_the_third_upload(client):
    ok = {"filename": "a.pdf", "size": 100}
    assert client.post("/api/presign", json=ok).status_code == 200
    assert client.post("/api/presign", json=ok).status_code == 200
    r = client.post("/api/presign", json=ok)
    assert r.status_code == 429 and "daily" in r.json()["error"]


def test_approve_and_reject_call_the_backend_and_redirect(client, backend):
    r = client.post(f"/doc/{DOC}/approve")
    assert r.status_code == 303 and backend.decisions == [("approve", DOC)]
    backend.docs[DOC]["status"] = "pending_review"
    client.post(f"/doc/{DOC}/reject")
    assert backend.decisions[-1] == ("reject", DOC)


def test_deciding_twice_shows_a_message_instead_of_failing(client):
    client.post(f"/doc/{DOC}/approve")
    r = client.post(f"/doc/{DOC}/approve")
    assert r.status_code == 303 and r.headers["location"].endswith("error=not_waiting")
    assert "not waiting for review any more" in client.get(r.headers["location"]).text


def test_bad_ids_and_decisions_are_404(client):
    assert client.post(f"/doc/{DOC}/delete").status_code == 404
    assert client.post("/doc/not-a-uuid/approve").status_code == 404
    assert client.get("/doc/not-a-uuid").status_code == 404


def test_document_text_from_the_pdf_is_escaped(client):
    page = client.get(f"/doc/{DOC}").text
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;" in page and "&lt;b&gt;Dalton" in page


def test_unknown_error_keys_are_not_echoed(client):
    assert "<i>x</i>" not in client.get(f"/doc/{DOC}?error=<i>x</i>").text


def test_task_token_never_reaches_the_templates():
    item = _public({"doc_id": "d", "task_token": "SECRET", "reasons": '["a:b"]'})
    assert "task_token" not in item and item["reasons"] == ["a:b"]


def test_safe_filename():
    assert safe_filename("C:\\docs\\Deal NDA.pdf") == "Deal_NDA.pdf"
    assert safe_filename("x.exe") is None
