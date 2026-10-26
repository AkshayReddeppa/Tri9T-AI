"""Generation tests — validation, retry, idempotency, malformed handling."""
import os, pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.config import settings
from app.db import Base, get_db
from app.main import app
from app.versioning.pipeline import ingest_pdf


V1 = "data/raw/ct200_manual.pdf"


@pytest.fixture
def client(tmp_path, monkeypatch):
    # isolate JSON store
    gen_dir = tmp_path / "generations"
    gen_dir.mkdir()
    monkeypatch.setattr(settings, "generations_dir", str(gen_dir))
    # fake provider by default
    monkeypatch.setattr(settings, "llm_provider", "fake")
    monkeypatch.setattr(settings, "fake_llm_script", [])
    monkeypatch.setattr(settings, "llm_max_attempts", 3)

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


def _sel(client):
    nid = client.get("/search?q=overpressure").json()[0]["id"]
    return client.post("/selections",
                       json={"name": "QA", "node_ids": [nid]}).json()["id"]


def test_generate_valid(client):
    sid = _sel(client)
    r = client.post(f"/selections/{sid}/generate")
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["status"] == "VALID"
    assert len(d["parsed"]["test_cases"]) >= 3
    assert d["node_versions"][0]["content_hash"]
    assert d["attempts"][0]["status"] == "VALID"


def test_generate_404_selection(client):
    assert client.post("/selections/nope/generate").status_code == 404


def test_generate_recovers_after_malformed(client, monkeypatch):
    monkeypatch.setattr(settings, "fake_llm_script",
                        ["this is not json", "OK"])
    sid = _sel(client)
    d = client.post(f"/selections/{sid}/generate").json()
    assert d["status"] == "VALID"
    assert d["attempts"][0]["status"] == "INVALID"
    assert d["attempts"][1]["status"] == "VALID"


def test_generate_all_malformed_stored_honestly(client, monkeypatch):
    monkeypatch.setattr(settings, "fake_llm_script",
                        ["bad", "still bad", "always bad"])
    sid = _sel(client)
    d = client.post(f"/selections/{sid}/generate").json()
    assert d["status"] == "MALFORMED"
    assert d["parsed"] is None
    assert d["raw_response"] == "always bad"   # last attempt preserved
    assert len(d["attempts"]) == 3


def test_generate_llm_exception(client, monkeypatch):
    monkeypatch.setattr(settings, "fake_llm_script", ["RAISE", "RAISE", "OK"])
    sid = _sel(client)
    d = client.post(f"/selections/{sid}/generate").json()
    assert d["status"] == "VALID"
    assert d["attempts"][0]["status"] == "LLM_ERROR"
    assert d["attempts"][1]["status"] == "LLM_ERROR"
    assert d["attempts"][2]["status"] == "VALID"


def test_idempotency_same_selection_returns_cached(client):
    sid = _sel(client)
    first = client.post(f"/selections/{sid}/generate").json()
    second = client.post(f"/selections/{sid}/generate").json()
    assert first["id"] == second["id"]
    assert second["cache_hit"] is True


def test_force_bypasses_cache(client):
    sid = _sel(client)
    first = client.post(f"/selections/{sid}/generate").json()
    second = client.post(f"/selections/{sid}/generate?force=true").json()
    assert first["id"] != second["id"]
    assert second["cache_hit"] is False


def test_idempotency_across_identical_selections(client):
    """Two different selection IDs with identical content -> cached on 2nd call."""
    nid = client.get("/search?q=overpressure").json()[0]["id"]
    s1 = client.post("/selections", json={"name": "A", "node_ids": [nid]}).json()["id"]
    s2 = client.post("/selections", json={"name": "B", "node_ids": [nid]}).json()["id"]
    first = client.post(f"/selections/{s1}/generate").json()
    second = client.post(f"/selections/{s2}/generate").json()
    assert second["cache_hit"] is True
    assert second["id"] == first["id"]


def test_retrieval_by_selection(client):
    sid = _sel(client)
    gid = client.post(f"/selections/{sid}/generate").json()["id"]
    r = client.get(f"/generations?selection_id={sid}").json()
    assert any(g["id"] == gid for g in r)
    r2 = client.get(f"/generations/{gid}").json()
    assert r2["id"] == gid and r2["parsed"]


def test_retrieval_by_node(client):
    hits = client.get("/search?q=overpressure").json()
    nid = hits[0]["id"]
    sid = client.post("/selections", json={"name": "N", "node_ids": [nid]}).json()["id"]
    gid = client.post(f"/selections/{sid}/generate").json()["id"]
    r = client.get(f"/generations?node_id={nid}").json()
    assert any(g["id"] == gid for g in r)


def test_retrieval_404(client):
    assert client.get("/generations/nope").status_code == 404

def test_permanent_llm_error_does_not_retry(client, monkeypatch):
    """401 must fail fast, not burn 3 attempts."""
    from app.llm.base import LLMError
    calls = {"n": 0}

    class FailingClient:
        def generate(self, system, user, temperature=0.2):
            calls["n"] += 1
            raise LLMError("groq request failed: Client error '401 Unauthorized'")

    monkeypatch.setattr("app.generation.service.get_llm_client", lambda: FailingClient())
    sid = _sel(client)
    d = client.post(f"/selections/{sid}/generate").json()
    assert d["status"] == "MALFORMED"
    assert calls["n"] == 1                       # only 1 attempt
    assert d["attempts"][0]["fatal"] is True


def test_llm_unicode_spaces_are_sanitized(client, monkeypatch):
    """LLMs sometimes emit U+202F around units. Stored output must be ASCII-clean."""
    from app.generation import service

    def _tc(i):
        return (
            f'{{"title":"Verify {299+i}\\u202fmmHg threshold {i}",'
            f'"steps":["Inflate to {300+i}\\u202fmmHg"],'
            f'"expected_result":"Valve opens within 2\\u202fseconds {i}",'
            f'"priority":"critical",'
            f'"source_section":"4.1"}}'
        )

    dirty_json = '{"test_cases":[' + ",".join(_tc(i) for i in range(3)) + ']}'

    class DirtyClient:
        def generate(self, *a, **kw): return dirty_json

    monkeypatch.setattr(service, "get_llm_client", lambda: DirtyClient())

    nid = client.get("/search?q=overpressure").json()[0]["id"]
    sid = client.post("/selections",
                      json={"name": "uni", "node_ids": [nid]}).json()["id"]
    gen = client.post(f"/selections/{sid}/generate?force=true").json()

    assert gen["status"] == "VALID", f"got: {gen.get('attempts')}"
    for tc in gen["parsed"]["test_cases"]:
        assert "\u202f" not in tc["title"]
        assert "\u202f" not in tc["expected_result"]
        assert "mmHg" in tc["title"]