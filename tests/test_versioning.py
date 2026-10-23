"""Versioning: matching v1 -> v2, change_status, NEW detection."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db import Base
from app.models import Document, DocumentVersion, Node
from app.ingest.pdf_reader import Block
from app.ingest.tree_builder import build_tree
from app.versioning.matcher import match_versions, find_removed
from app.versioning.pipeline import _ingest_v1_tree, _ingest_versioned_tree


def _b(t, bold=True, size=12.0):
    return Block(page=0, text=t, bbox=(0,0,1,1), max_font_size=size, is_bold=bold, font_name="X")


def _setup_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _make_doc_version(db, num):
    doc = db.query(Document).first()
    if not doc:
        doc = Document(name="Test"); db.add(doc); db.flush()
    v = DocumentVersion(document_id=doc.id, version_number=num, source_filename=f"v{num}.pdf")
    db.add(v); db.flush(); return v


def test_unchanged_modified_new_across_versions():
    db = _setup_db()
    v1 = _make_doc_version(db, 1)

    # v1: 2 sections — one unchanged in v2, one whose body will change
    t1 = build_tree([
        _b("1 Alpha"), _b("Body of alpha stays the same."),
        _b("2 Beta"), _b("Body of beta v1."),
    ], "Doc")
    _ingest_v1_tree(db, v1, t1); db.commit()

    # v2: Alpha unchanged; Beta body changed; Gamma is new
    v2 = _make_doc_version(db, 2)
    t2 = build_tree([
        _b("1 Alpha"), _b("Body of alpha stays the same."),
        _b("2 Beta"), _b("Body of beta v2 (CHANGED)."),
        _b("3 Gamma"), _b("Brand new section."),
    ], "Doc")

    v1_nodes = db.query(Node).filter(Node.version_id == v1.id).all()
    matches = match_versions(v1_nodes, t2)
    _ingest_versioned_tree(db, v2, t2, matches); db.commit()

    v2_nodes = {n.heading: n for n in db.query(Node).filter(Node.version_id == v2.id).all()}
    assert v2_nodes["Alpha"].change_status == "UNCHANGED"
    assert v2_nodes["Beta"].change_status == "MODIFIED"
    assert v2_nodes["Gamma"].change_status == "NEW"

    # logical_id stability: Alpha + Beta keep v1's logical_id
    v1_by_heading = {n.heading: n for n in v1_nodes}
    assert v2_nodes["Alpha"].logical_id == v1_by_heading["Alpha"].logical_id
    assert v2_nodes["Beta"].logical_id == v1_by_heading["Beta"].logical_id


def test_removed_nodes_detected():
    db = _setup_db()
    v1 = _make_doc_version(db, 1)
    t1 = build_tree([_b("1 Alpha"), _b("body"), _b("2 Beta"), _b("body")], "Doc")
    _ingest_v1_tree(db, v1, t1); db.commit()

    v2 = _make_doc_version(db, 2)
    t2 = build_tree([_b("1 Alpha"), _b("body")], "Doc")  # Beta removed
    v1_nodes = db.query(Node).filter(Node.version_id == v1.id).all()
    matches = match_versions(v1_nodes, t2)
    removed = find_removed(v1_nodes, matches)
    assert any(n.heading == "Beta" for n in removed)
    assert not any(n.heading == "Alpha" for n in removed)