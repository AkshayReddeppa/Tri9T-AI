"""Browse API tests — run against an in-memory DB seeded with v1+v2 PDFs (if present)."""
import os
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db import Base, get_db
from app.main import app
from app.versioning.pipeline import ingest_pdf


@pytest.fixture
def client(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path}/test.db",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine)

    def _override():
        s = TestSession()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = _override

    s = TestSession()
    try:
        for p in ("data/raw/ct200_manual.pdf", "data/raw/ct200_manual_v2.pdf"):
            if os.path.exists(p):
                ingest_pdf(s, p, "CardioTrack CT-200")
    finally:
        s.close()

    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_sections_default_latest(client):
    r = client.get("/sections")
    assert r.status_code == 200
    d = r.json()
    assert d["version_number"] == 2
    assert d["document_title"].startswith("CardioTrack CT-200")
    assert any("Device Overview" in s["heading"] for s in d["sections"])


def test_sections_v1(client):
    r = client.get("/sections?version=1")
    assert r.status_code == 200
    assert r.json()["version_number"] == 1


def test_sections_bad_version(client):
    assert client.get("/sections?version=abc").status_code == 400
    assert client.get("/sections?version=99").status_code == 404


def test_get_node_with_children(client):
    sections = client.get("/sections").json()["sections"]
    target = next(s for s in sections if "Device Overview" in s["heading"])
    r = client.get(f"/nodes/{target['id']}")
    assert r.status_code == 200
    d = r.json()
    assert d["content_hash"]
    assert isinstance(d["children"], list)


def test_get_node_404(client):
    assert client.get("/nodes/nope").status_code == 404


def test_search_hits_heading_and_body(client):
    r = client.get("/search?q=overpressure")
    assert r.status_code == 200
    hits = r.json()
    assert hits
    assert any("overpressure" in (h["heading"] + h["snippet"]).lower() for h in hits)


def test_search_empty_422(client):
    assert client.get("/search?q=").status_code == 422


def test_diff_modified_node(client):
    hits = client.get("/search?q=battery%20life").json()
    assert hits
    d = client.get(f"/nodes/{hits[0]['id']}/diff").json()
    assert d["changed"] is True
    assert len(d["versions"]) >= 2
    assert d["hunks"], "expected non-empty diff hunks for MODIFIED node"


def test_diff_unchanged_node(client):
    hits = client.get("/search?q=Intended%20Use").json()
    target = next(h for h in hits if h["heading"] == "Intended Use")
    d = client.get(f"/nodes/{target['id']}/diff").json()
    assert d["changed"] is False
    assert d["hunks"] == []