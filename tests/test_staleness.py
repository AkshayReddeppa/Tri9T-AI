"""Staleness detection tests — the assignment's hardest module."""
import os
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.config import settings
from app.db import Base, get_db
from app.main import app
from app.versioning.pipeline import ingest_pdf


V1 = "data/raw/ct200_manual.pdf"
V2 = "data/raw/ct200_manual_v2.pdf"


@pytest.fixture
def client(tmp_path, monkeypatch):
    gen = tmp_path / "gen"; gen.mkdir()
    monkeypatch.setattr(settings, "generations_dir", str(gen))
    monkeypatch.setattr(settings, "llm_provider", "fake")
    monkeypatch.setattr(settings, "fake_llm_script", [])

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
        for p in (V1, V2):
            if os.path.exists(p):
                ingest_pdf(s, p, "CardioTrack CT-200")
    finally:
        s.close()

    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _gen_for(client, query: str, version: int = 1) -> dict:
    """Generate against a SPECIFIC version (default v1) so staleness is testable.
    Default is v1 — using latest would pin to v2 and staleness would trivially be fresh."""
    hits = client.get(f"/search?q={query}&version={version}").json()
    assert hits, f"no search hits for {query} in v{version}"
    nid = hits[0]["id"]
    sid = client.post("/selections",
                      json={"name": f"st-{query}-v{version}", "node_ids": [nid]}).json()["id"]
    return client.post(f"/selections/{sid}/generate?force=true").json()


# ---- FRESH: v1 → v2 unchanged section ----

def test_staleness_fresh_unchanged_node(client):
    """Overpressure Protection (4.1) is identical v1↔v2 → fresh."""
    gen = _gen_for(client, "overpressure")  # v1 by default
    st = client.get(f"/generations/{gen['id']}/staleness").json()
    assert st["overall_status"] == "fresh"
    assert st["overall_severity"] == "none"
    assert all(n["status"] == "fresh" for n in st["nodes"])


# ---- STALE + CRITICAL: numeric threshold changed ----

def test_staleness_critical_numeric_change(client):
    """Battery Life: v1 '300 cycles, 15%' -> v2 '250 cycles, 10%' → critical."""
    gen = _gen_for(client, "battery%20life")
    st = client.get(f"/generations/{gen['id']}/staleness").json()
    assert st["overall_status"] == "stale", st
    assert st["overall_severity"] == "critical", st
    node = st["nodes"][0]
    assert node["status"] == "stale"
    assert node["severity"] == "critical"
    assert node["reason"] == "numeric_threshold_changed"
    assert node["snapshot_hash"] != node["current_hash"]


def test_staleness_critical_time_change(client):
    """Error Codes 4.2: v1 'E3 auto-deflate within 2s' -> v2 'within 1.5s', plus E6 added."""
    gen = _gen_for(client, "error%20codes")
    st = client.get(f"/generations/{gen['id']}/staleness").json()
    assert st["overall_status"] == "stale", st
    assert st["overall_severity"] == "critical", st
    assert any(n["reason"] in ("numeric_threshold_changed", "error_code_changed")
               for n in st["nodes"]), st


# ---- Word-level severities ----

def test_severity_minor_wording_only():
    """One-word replacement (no numbers, no safety keywords) → minor."""
    from app.generation.staleness import _severity
    old = "The device displays the result after measurement."
    new = "The device shows the result after measurement."   # ONLY 1 word changed
    sev, ratio, reason = _severity(old, new)
    assert sev == "minor", f"got {sev} (ratio={ratio})"
    assert reason == "wording_change"


def test_severity_critical_when_number_changes():
    """A numeric threshold change must escalate to critical."""
    from app.generation.staleness import _severity
    sev, ratio, reason = _severity(
        "Auto-deflates within 2 seconds, displays E3.",
        "Auto-deflates within 1.5 seconds, displays E3.",
    )
    assert sev == "critical"
    assert reason == "numeric_threshold_changed"


def test_severity_critical_when_new_error_code():
    """Adding E6 to the error list must be critical."""
    from app.generation.staleness import _severity
    sev, _, reason = _severity(
        "Audible alarms limited to the E1-E5 error conditions.",
        "Audible alarms limited to the E1-E6 error conditions.",
    )
    assert sev == "critical", f"got {sev} (reason={reason})"
    assert reason == "error_code_changed"


# ---- Visible in retrieval ----

def test_retrieval_includes_staleness_block(client):
    """GET /generations/{id} must include the staleness report."""
    gen = _gen_for(client, "battery%20life")
    r = client.get(f"/generations/{gen['id']}").json()
    assert "staleness" in r
    assert r["staleness"]["overall_status"] == "stale"
    assert r["staleness"]["overall_severity"] == "critical"


def test_retrieval_list_has_staleness_summary(client):
    gen = _gen_for(client, "battery%20life")
    rows = client.get("/generations").json()
    row = next(r for r in rows if r["id"] == gen["id"])
    assert row["overall_status"] == "stale"
    assert row["overall_severity"] == "critical"


def test_retrieval_by_node_id_includes_staleness(client):
    gen = _gen_for(client, "battery%20life")
    node_id = gen["node_versions"][0]["node_id"]
    rows = client.get(f"/generations?node_id={node_id}").json()
    assert rows
    assert rows[0]["overall_status"] == "stale"


# ---- Removal detection ----

def test_staleness_removed_when_no_current_node(client, monkeypatch):
    """If logical_id no longer exists → removed, critical."""
    gen = _gen_for(client, "overpressure")
    from app.generation import staleness as st_mod
    monkeypatch.setattr(st_mod, "_current_node", lambda db, lid: None)
    st = client.get(f"/generations/{gen['id']}/staleness").json()
    assert st["overall_status"] == "removed"
    assert st["overall_severity"] == "critical"
    assert all(n["status"] == "removed" for n in st["nodes"])


# ---- Multi-node aggregation ----

def test_multi_node_worst_case_wins(client):
    """Mixed fresh+stale selection → overall stale, severity = worst node."""
    # BOTH from v1 so v2 comparison can detect change
    fresh = client.get("/search?q=overpressure&version=1").json()[0]["id"]
    stale = client.get("/search?q=battery%20life&version=1").json()[0]["id"]
    sid = client.post("/selections",
                      json={"name": "mixed", "node_ids": [fresh, stale]}).json()["id"]
    gen = client.post(f"/selections/{sid}/generate?force=true").json()
    st = client.get(f"/generations/{gen['id']}/staleness").json()
    assert st["overall_status"] == "stale", st
    assert st["overall_severity"] == "critical", st
    statuses = {n["status"] for n in st["nodes"]}
    assert statuses == {"fresh", "stale"}, statuses