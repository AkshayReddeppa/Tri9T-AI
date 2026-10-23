"""Selection API tests — including the critical 'survives re-ingest' check."""
import os
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db import Base, get_db
from app.main import app
from app.versioning.pipeline import ingest_pdf


V1 = "data/raw/ct200_manual.pdf"
V2 = "data/raw/ct200_manual_v2.pdf"


@pytest.fixture
def client(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/t.db",
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    S = sessionmaker(bind=engine)

    def _ovr():
        s = S()
        try: yield s
        finally: s.close()

    app.dependency_overrides[get_db] = _ovr
    s = S()
    try:
        if os.path.exists(V1):
            ingest_pdf(s, V1, "CardioTrack CT-200")
    finally:
        s.close()

    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _battery_id(client):
    hits = client.get("/search?q=battery%20life").json()
    return hits[0]["id"]


def test_create_selection(client):
    nid = _battery_id(client)
    r = client.post("/selections", json={"name": "Battery check", "node_ids": [nid]})
    assert r.status_code == 201
    d = r.json()
    assert d["name"] == "Battery check"
    assert len(d["items"]) == 1
    assert d["items"][0]["node_id"] == nid
    assert "300" in d["items"][0]["body"]          # v1 text snapshot


def test_selection_rejects_unknown_node(client):
    r = client.post("/selections", json={"name": "x", "node_ids": ["nope"]})
    assert r.status_code == 400
    assert "not found" in r.json()["detail"]


def test_selection_rejects_empty_node_ids(client):
    r = client.post("/selections", json={"name": "x", "node_ids": []})
    assert r.status_code == 422


def test_selection_rejects_empty_name(client):
    nid = _battery_id(client)
    r = client.post("/selections", json={"name": "", "node_ids": [nid]})
    assert r.status_code == 422


def test_duplicate_node_ids_deduped_and_reported(client):
    nid = _battery_id(client)
    r = client.post("/selections", json={"name": "dup", "node_ids": [nid, nid, nid]})
    assert r.status_code == 201
    d = r.json()
    assert len(d["items"]) == 1
    assert d["deduplicated_count"] == 2


def test_get_selection_and_list(client):
    nid = _battery_id(client)
    sid = client.post("/selections", json={"name": "s", "node_ids": [nid]}).json()["id"]

    r = client.get(f"/selections/{sid}")
    assert r.status_code == 200 and r.json()["id"] == sid

    r = client.get("/selections")
    assert r.status_code == 200
    assert any(x["id"] == sid for x in r.json())


def test_get_selection_404(client):
    assert client.get("/selections/nope").status_code == 404


def test_selection_survives_reingest(client):
    """CRITICAL: after v2 is ingested, an old selection must still resolve to v1 text."""
    nid = _battery_id(client)                       # v1 Battery Life node
    sid = client.post("/selections", json={"name": "pin", "node_ids": [nid]}).json()["id"]

    # Now ingest v2 (Battery Life body changes 300 -> 250 cycles)
    s = next(app.dependency_overrides[get_db]())
    try:
        if os.path.exists(V2):
            ingest_pdf(s, V2, "CardioTrack CT-200")
    finally:
        s.close()

    # Selection must still show v1 text
    r = client.get(f"/selections/{sid}")
    assert r.status_code == 200
    body = r.json()["items"][0]["body"]
    assert "300" in body and "250" not in body, "selection text leaked to v2"


def test_delete_selection(client):
    nid = _battery_id(client)
    sid = client.post("/selections", json={"name": "del", "node_ids": [nid]}).json()["id"]
    assert client.delete(f"/selections/{sid}").status_code == 204
    assert client.get(f"/selections/{sid}").status_code == 404